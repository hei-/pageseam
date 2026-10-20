from typing import Any

from dify_plugin import ToolProvider
from dify_plugin.errors.tool import ToolProviderCredentialValidationError

from utils.client import DocParserClient, DocParserError


class DocParserProvider(ToolProvider):
    def _validate_credentials(self, credentials: dict[str, Any]) -> None:
        try:
            DocParserClient.from_credentials(credentials).info()
        except DocParserError as e:
            raise ToolProviderCredentialValidationError(str(e)) from e
