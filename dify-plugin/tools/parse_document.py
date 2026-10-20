import re
from collections.abc import Generator
from typing import Any

from dify_plugin.entities.tool import ToolInvokeMessage

# 以模块属性引用基类：SDK 要求每个工具文件的命名空间中只有一个 Tool 子类
from utils import chunking, tool_base

PAGE_MARKER = re.compile(r"^<!-- page \d+ -->\n+", re.MULTILINE)


class ParseDocumentTool(tool_base.DocParserTool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        job = self._submit_and_wait(tool_parameters, ["markdown"])
        keep_markers = tool_parameters.get("page_markers") not in (False, "false", "False", 0)
        max_chars, table_max_chars = chunking.limits(tool_parameters)
        # 没有传这个参数（None）时默认标注文档名
        file = tool_parameters.get("file")
        with_name = tool_parameters.get("chunk_doc_name") not in (False, "false", "False", 0)
        doc_name = chunking.doc_label(getattr(file, "filename", None)) if with_name else ""
        for message in self._emit(job, ["markdown"]):
            if message.type == ToolInvokeMessage.MessageType.TEXT and job["status"] == "succeeded":
                markdown = message.message.text
                # 知识流水线可直接把 chunks 接到知识库节点，不需要再经过通用分块器
                chunks = chunking.chunk_markdown(markdown, max_chars, table_max_chars, doc_name)
                yield self.create_variable_message("chunks", chunks)
                if not keep_markers:
                    message.message.text = PAGE_MARKER.sub("", markdown)
            yield message
