"""文档解析服务的 HTTP 客户端：提交任务、轮询结果、下载文件、删除任务。"""

import time
from dataclasses import dataclass
from typing import Any

import httpx

from utils.i18n import ACCEPT_LANGUAGE, DEFAULT_LANGUAGE, language, t

POLL_START_SECONDS = 2.0
POLL_MAX_SECONDS = 10.0
MAX_POLL_ERRORS = 3  # 轮询时网络错误连续出现这么多次才放弃
MAX_BUSY_RETRIES = 5  # 服务排队已满（429）时的重试次数


class DocParserError(Exception):
    pass


@dataclass
class DocParserClient:
    base_url: str
    api_key: str
    lang: str = DEFAULT_LANGUAGE

    @classmethod
    def from_credentials(cls, credentials: dict[str, Any]) -> "DocParserClient":
        base_url = (credentials.get("base_url") or "").strip().rstrip("/")
        api_key = (credentials.get("api_key") or "").strip()
        lang = language(credentials)
        if not base_url.startswith(("http://", "https://")):
            raise DocParserError(t("bad_base_url", lang))
        if not api_key:
            raise DocParserError(t("missing_api_key", lang))
        return cls(base_url, api_key, lang)

    def _request(self, method: str, path: str, timeout: float = 30, **kwargs) -> httpx.Response:
        try:
            response = httpx.request(
                method,
                self.base_url + path,
                # 服务端的报错和判定报告用插件同一种语言
                headers={"Authorization": f"Bearer {self.api_key}", "Accept-Language": ACCEPT_LANGUAGE[self.lang]},
                timeout=timeout,
                **kwargs,
            )
        except httpx.TimeoutException as e:
            raise DocParserNetworkError(t("timeout", self.lang, error=e)) from e
        except httpx.HTTPError as e:
            raise DocParserNetworkError(t("unreachable", self.lang, url=self.base_url, error=e)) from e
        if response.status_code == 401:
            raise DocParserError(t("invalid_api_key", self.lang))
        if response.status_code == 429:
            raise DocParserBusy(response.headers.get("Retry-After", "30"))
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail")
            except ValueError:
                detail = response.text[:200]
            raise DocParserError(t("http_error", self.lang, status=response.status_code, detail=detail))
        return response

    def info(self) -> dict:
        return self._request("GET", "/v1/info").json()

    def submit(self, filename: str, data: bytes, options: dict[str, str]) -> dict:
        for attempt in range(MAX_BUSY_RETRIES + 1):
            try:
                return self._request(
                    "POST",
                    "/v1/jobs",
                    timeout=120,
                    files={"file": (filename, data)},
                    data=options,
                ).json()
            except DocParserBusy as e:
                if attempt == MAX_BUSY_RETRIES:
                    raise DocParserError(t("queue_full", self.lang)) from e
                time.sleep(min(float(e.retry_after or 30), 60))
        raise AssertionError("unreachable")

    def get(self, job_id: str) -> dict:
        return self._request("GET", f"/v1/jobs/{job_id}").json()

    def wait(self, job: dict, timeout: float) -> dict:
        """轮询直到任务结束或超时；超时返回最后一次的状态（仍是 queued / running）。"""
        deadline = time.monotonic() + timeout
        interval, errors = POLL_START_SECONDS, 0
        while job["status"] in ("queued", "running"):
            if time.monotonic() + interval > deadline:
                return job
            time.sleep(interval)
            interval = min(interval * 1.5, POLL_MAX_SECONDS)
            try:
                job = self.get(job["job_id"])
                errors = 0
            except DocParserNetworkError:
                errors += 1
                if errors >= MAX_POLL_ERRORS:
                    raise
        if job["status"] == "failed":
            raise DocParserError(t("job_failed", self.lang, error=job.get("error")))
        return job

    def download(self, job_id: str, kind: str) -> bytes:
        return self._request("GET", f"/v1/jobs/{job_id}/files/{kind}", timeout=120).content

    def delete(self, job_id: str) -> None:
        try:
            self._request("DELETE", f"/v1/jobs/{job_id}")
        except DocParserError:
            pass  # 删除失败不影响结果，服务端到期也会自动清理


class DocParserNetworkError(DocParserError):
    pass


class DocParserBusy(DocParserError):
    def __init__(self, retry_after: str):
        super().__init__("busy")
        self.retry_after = retry_after
