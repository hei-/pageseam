"""三个工具共用的逻辑：读取参数、提交并等待任务、输出结果。"""

import os
from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from utils.client import DocParserClient, DocParserError

DEFAULT_WAIT_SECONDS = 540  # 插件单次调用上限是 600 秒，留出下载结果的时间
SUPPORTED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp",
    # Office 文档：服务端先用 LibreOffice 转成 PDF
    ".doc", ".docx", ".docm", ".dot", ".dotx", ".rtf", ".odt", ".wps", ".ppt", ".pptx", ".odp", ".dps",
}
MIME_TYPES = {
    "markdown": "text/markdown",
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
SUFFIXES = {"markdown": ".md", "pdf": "_ocr.pdf", "docx": ".docx"}


class DocParserTool(Tool):
    def _client(self) -> DocParserClient:
        return DocParserClient.from_credentials(self.runtime.credentials)

    @staticmethod
    def _wait_seconds(params: dict[str, Any]) -> float:
        try:
            value = float(params.get("wait_seconds") or DEFAULT_WAIT_SECONDS)
        except (TypeError, ValueError):
            value = DEFAULT_WAIT_SECONDS
        return min(max(value, 0), DEFAULT_WAIT_SECONDS)

    def _submit_and_wait(self, params: dict[str, Any], outputs: list[str]) -> dict:
        file = params.get("file")
        if not file:
            raise DocParserError("缺少文件")
        filename = file.filename or "document.pdf"
        extension = os.path.splitext(filename)[1].lower()
        if extension not in SUPPORTED_EXTENSIONS:
            raise DocParserError(f"不支持 {extension or '无扩展名'} 文件，支持：{', '.join(sorted(SUPPORTED_EXTENSIONS))}")

        client = self._client()
        job = client.submit(
            filename,
            file.blob,
            {
                "outputs": ",".join(outputs),
                "ocr": params.get("ocr") or "auto",
                "ocr_pages": (params.get("ocr_pages") or "").strip(),
                "pages": (params.get("pages") or "").strip(),
                "word_images": params.get("word_images") or "replace",
                "word_tables": params.get("word_tables") or "keep",
            },
        )
        return client.wait(job, self._wait_seconds(params))

    def _emit(self, job: dict, kinds: list[str]) -> Generator[ToolInvokeMessage, None, None]:
        """输出任务结果；任务未完成时输出 job_id，之后用「查询任务结果」工具获取。"""
        yield self.create_variable_message("job_id", job["job_id"])
        yield self.create_variable_message("status", job["status"])
        if job["status"] != "succeeded":
            progress = job.get("progress") or {}
            detail = f"，{progress.get('stage')} {progress.get('done')}/{progress.get('total')}" if progress else ""
            yield self.create_text_message(
                f"文档仍在处理中（{job['status']}{detail}）。请稍后用「查询任务结果」工具，传入 job_id={job['job_id']} 获取结果。"
            )
            return

        client = self._client()
        summary = job.get("summary") or {}
        yield self.create_variable_message("page_count", job.get("page_count") or 0)
        yield self.create_variable_message("ocr_pages", summary.get("ocr_pages") or 0)

        stem = os.path.splitext(job.get("filename") or "document")[0]
        for kind in kinds:
            if kind not in job.get("files", {}):
                continue
            data = client.download(job["job_id"], kind)
            if kind == "markdown":
                yield self.create_text_message(data.decode("utf-8"))
            else:
                yield self.create_blob_message(
                    blob=data, meta={"filename": stem + SUFFIXES[kind], "mime_type": MIME_TYPES[kind]}
                )
        yield self.create_json_message(
            {
                "job_id": job["job_id"],
                "page_count": job.get("page_count"),
                "summary": summary,
                "pages": job.get("pages"),
                "timings": job.get("timings"),
            }
        )
        # 结果已经取回，立即删除服务端文件
        client.delete(job["job_id"])
