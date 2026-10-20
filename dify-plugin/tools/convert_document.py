from collections.abc import Generator
from typing import Any

from dify_plugin.entities.tool import ToolInvokeMessage

# 以模块属性引用基类：SDK 要求每个工具文件的命名空间中只有一个 Tool 子类
from utils import tool_base

FORMATS = {"both": ["docx", "pdf"], "docx": ["docx"], "pdf": ["pdf"]}


class ConvertDocumentTool(tool_base.DocParserTool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        kinds = FORMATS.get(tool_parameters.get("output_format") or "both", FORMATS["both"])
        job = self._submit_and_wait(tool_parameters, kinds)
        if job["status"] == "succeeded":
            summary = job.get("summary") or {}
            yield self.create_text_message(
                f"已转换 {job.get('page_count')} 页，其中 {summary.get('ocr_pages', 0)} 页做了 OCR，"
                f"用时 {(job.get('timings') or {}).get('total', 0):.0f} 秒。"
            )
        yield from self._emit(job, kinds)
