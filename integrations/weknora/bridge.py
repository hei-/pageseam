"""
WeKnora ↔ PageSeam 转接服务：用 MinerU 的旧版接口（/file_parse）把 PageSeam 接成 WeKnora 的解析引擎。

WeKnora 的 mineru 引擎先请求 GET /v1/health：404 时走旧版同步接口 POST /file_parse（multipart，文件字段 files；
连通性检测请求 GET /docs），
期望返回 {"results": {<文件名去扩展名>: {"md_content", "images", "content_list"}}}。
本服务收到文件后提交给 PageSeam（POST /v1/jobs，outputs=markdown），轮询到完成，取回 Markdown 原样返回：
扫描页 OCR、HTML 表格、跨页表格合并、去页眉页脚都由 PageSeam 完成；WeKnora 照常分块、嵌入、建索引。

content_list 按 PageSeam 的 <!-- page N --> 标记拆成段落，WeKnora 据此生成原文位置（PDF 页码）。
只在 WeKnora 的内部网络里提供服务（不映射宿主机端口），PageSeam 的 API Key 只在这里。
只用标准库，挂载进 python:3.12-slim 运行。

环境变量：
  PAGESEAM_URL        PageSeam 地址，如 http://pageseam:8000
  PAGESEAM_API_KEY    PageSeam 的 API Key
  BRIDGE_TIMEOUT      单个文件最长等待秒数，默认 950（WeKnora 等 MinerU 默认 1000 秒）
"""

import html
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGESEAM_URL = os.environ.get("PAGESEAM_URL", "").rstrip("/")
PAGESEAM_API_KEY = os.environ.get("PAGESEAM_API_KEY", "")
TIMEOUT = float(os.environ.get("BRIDGE_TIMEOUT", "950"))
# MinerU 的 parse_method → PageSeam 的 ocr
OCR_MODE = {"auto": "auto", "ocr": "force", "txt": "off"}
PAGE_MARK = re.compile(r"^<!-- page (\d+) -->\s*$", re.M)
COMMENT_LINE = re.compile(r"^\s*<!--.*?-->\s*$", re.M)
TAG = re.compile(r"<[^>]+>")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("parser-bridge")


class BridgeError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def call(method: str, path: str, body: bytes | None = None, content_type: str | None = None, timeout: float = 60) -> bytes:
    headers = {"Authorization": f"Bearer {PAGESEAM_API_KEY}", "Accept-Language": "zh-CN"}  # 和本服务的提示语言一致
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(PAGESEAM_URL + path, data=body, headers=headers, method=method)
    try:
        # 地址来自部署者配置的 PAGESEAM_URL，不是用户输入
        with urllib.request.urlopen(req, timeout=timeout) as r:  # nosec B310
            return r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        try:
            detail = json.loads(detail).get("detail", detail)
        except ValueError:
            pass
        raise BridgeError(e.code, f"PageSeam {method} {path} 返回 {e.code}：{detail}") from e
    except urllib.error.URLError as e:
        raise BridgeError(502, f"无法连接 PageSeam {PAGESEAM_URL}：{e.reason}") from e


def multipart(fields: dict[str, str], file_field: str, filename: str, data: bytes) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    safe = filename.replace('"', "")
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{safe}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n".encode() + data + b"\r\n"
    )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def parse_document(filename: str, data: bytes, parse_method: str) -> str:
    """提交给 PageSeam 并等到完成，返回 Markdown。队列满（429）时等一会儿重试。"""
    body, ctype = multipart({"outputs": "markdown", "ocr": OCR_MODE.get(parse_method, "auto")}, "file", filename, data)
    deadline = time.monotonic() + TIMEOUT
    while True:
        try:
            job = json.loads(call("POST", "/v1/jobs", body, ctype))
            break
        except BridgeError as e:
            if e.status != 429 or time.monotonic() > deadline:
                raise
            time.sleep(10)
    job_id = job["job_id"]
    log.info("submitted %s → job %s", filename, job_id)
    delay = 1.0
    while job["status"] in ("queued", "running"):
        if time.monotonic() > deadline:
            raise BridgeError(504, f"PageSeam 任务 {job_id} 超过 {TIMEOUT:.0f} 秒未完成")
        time.sleep(delay)
        delay = min(delay * 1.5, 10)
        job = json.loads(call("GET", f"/v1/jobs/{job_id}"))
    try:
        if job["status"] != "succeeded":
            raise BridgeError(422, f"PageSeam 解析失败：{job.get('error') or job['status']}")
        markdown = call("GET", f"/v1/jobs/{job_id}/files/markdown", timeout=120).decode("utf-8")
    finally:
        try:  # 结果已经取回，删掉 PageSeam 上的任务文件
            call("DELETE", f"/v1/jobs/{job_id}")
        except BridgeError:
            pass
    s = job.get("summary") or {}
    log.info("job %s done: %s pages, %d chars, summary=%s", job_id, job.get("page_count"), len(markdown),
             json.dumps({k: s[k] for k in list(s)[:6]}, ensure_ascii=False))
    return markdown


def content_list(markdown: str) -> list[dict]:
    """按 <!-- page N --> 把 Markdown 拆成带页码的段落，供 WeKnora 生成原文位置。

    WeKnora 对齐时只比较字母和数字，所以段落原样给出即可；但要去掉 <!-- table pages a-b --> 这类注释行
    （它紧贴在跨页表格上方，整块跳过会把表格一起丢掉），HTML 表格先去标签、还原 &lt; 等转义，
    否则转义里的字母会让整张表对不上。跨页表格放在起始页，整张表都记为起始页。
    """
    items = []
    marks = list(PAGE_MARK.finditer(markdown))
    for i, m in enumerate(marks):
        page = int(m.group(1))
        end = marks[i + 1].start() if i + 1 < len(marks) else len(markdown)
        for block in re.split(r"\n\s*\n", markdown[m.end():end]):
            block = COMMENT_LINE.sub("", block).strip()
            if not block:
                continue
            if "<table" in block:
                block = html.unescape(TAG.sub(" ", block))
            items.append({"type": "text", "text": block, "page_idx": page - 1})
    return items


class Handler(BaseHTTPRequestHandler):
    server_version = "parser-bridge/1"

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._json(200, {"status": "ok"})
        elif self.path == "/docs":  # WeKnora 对旧版 MinerU 的连通性检测请求 /docs，状态码小于 400 即为可用
            body = "parser-bridge: MinerU legacy /file_parse → PageSeam".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:  # 包括 /v1/health：返回 404，让 WeKnora 选旧版 /file_parse 协议
            self._json(404, {"detail": "Not Found"})

    def do_POST(self):  # noqa: N802
        if self.path != "/file_parse":
            self._json(404, {"detail": "Not Found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            msg = BytesParser(policy=policy.HTTP).parsebytes(
                f"Content-Type: {self.headers.get('Content-Type')}\r\n\r\n".encode() + raw
            )
            fields, upload = {}, None
            for part in msg.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if name == "files" and part.get_filename():
                    upload = (part.get_filename(), part.get_payload(decode=True) or b"")
                elif name:
                    fields[name] = part.get_content().strip()
            if not upload or not upload[1]:
                raise BridgeError(400, "没有收到文件（multipart 字段 files）")
            filename, data = upload
            started = time.monotonic()
            markdown = parse_document(filename, data, fields.get("parse_method", "auto"))
            stem = os.path.splitext(os.path.basename(filename))[0] or "document"
            log.info("file_parse %s ok in %.1fs", filename, time.monotonic() - started)
            self._json(200, {"backend": "pageseam", "results": {stem: {
                "md_content": markdown, "images": {}, "content_list": content_list(markdown),
            }}})
        except BridgeError as e:
            log.warning("file_parse failed: %s", e)
            self._json(e.status, {"detail": str(e)})
        except Exception as e:  # noqa: BLE001 — 任何异常都以 500 返回给 WeKnora，而不是断开连接
            log.exception("file_parse error")
            self._json(500, {"detail": f"parser-bridge 内部错误：{e}"})

    def log_message(self, fmt, *args):  # 只记录非健康检查的请求
        if "/health" not in (args[0] if args else ""):
            log.info("%s %s", self.address_string(), fmt % args)


if __name__ == "__main__":
    if not PAGESEAM_URL or not PAGESEAM_API_KEY:
        raise SystemExit("缺少 PAGESEAM_URL 或 PAGESEAM_API_KEY")
    log.info("parser-bridge listening on :8080 → %s", PAGESEAM_URL)
    # 在容器里运行，只接入 WeKnora 的内部网络，需要监听容器的所有网卡
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()  # nosec B104
