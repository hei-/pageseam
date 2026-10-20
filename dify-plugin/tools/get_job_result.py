from collections.abc import Generator
from typing import Any

from dify_plugin.entities.tool import ToolInvokeMessage

from utils.client import DocParserError
# 以模块属性引用基类：SDK 要求每个工具文件的命名空间中只有一个 Tool 子类
from utils import tool_base


class GetJobResultTool(tool_base.DocParserTool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        job_id = (tool_parameters.get("job_id") or "").strip()
        if not job_id:
            raise DocParserError("缺少 job_id")
        client = self._client()
        job = client.wait(client.get(job_id), self._wait_seconds(tool_parameters))
        yield from self._emit(job, ["markdown", "docx", "pdf"])
