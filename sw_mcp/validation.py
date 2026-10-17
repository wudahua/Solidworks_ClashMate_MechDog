"""Public MCP input contract. Expected refusals never fall back to defaults."""
import json

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.types import CallToolResult, TextContent


def packed(data, error=False):
    return CallToolResult(content=[TextContent(type='text', text=json.dumps(data, ensure_ascii=False))], structured_content=data, is_error=error)


def refuse(code, message, diagnostics=None, next_action=None):
    return packed({'ok': False, 'error': {
        'code': code, 'message': message, 'assertion': 'not_applicable',
        'restoration_status': 'not_required', 'document_context_restoration_status': 'not_required',
        'diagnostics': {'cad_dispatched': False, 'job_created': False, **(diagnostics or {})},
        'next_action': {'automatic_retry': False, 'instruction': '核对工具声明与参数后显式重新调用；未自动重试。', **(next_action or {})},
    }}, True)


class InputRefusal(ToolError):
    """Expected input error; direct callers retain ToolError compatibility."""
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class StrictMCPServer(MCPServer):
    async def list_tools(self):
        tools = await super().list_tools()
        for tool in tools:
            tool.input_schema = {**tool.input_schema, 'additionalProperties': False}
        return tools

    async def call_tool(self, name, arguments, context=None):
        # Use public schemas and inspect raw arguments before SDK model parsing
        # can drop extra keys. Advertising a closed schema alone is insufficient.
        tool = next((tool for tool in await self.list_tools() if tool.name == name), None)
        if tool is None:
            return refuse('UNKNOWN_TOOL', '工具未登记，请重新读取tools/list。', {'tool': name})
        accepted = sorted(tool.input_schema.get('properties', {}))
        unknown = sorted(set(arguments) - set(accepted))
        if unknown:
            return refuse('UNKNOWN_ARGUMENT', '存在未声明的参数键：' + ', '.join(unknown) + '；未按默认值执行，也未自动改名。',
                          {'tool': name, 'unknown_keys': unknown, 'accepted_keys': accepted})
        try:
            return await super().call_tool(name, arguments, context)
        except UnexpectedToolError:
            # Preserve the SDK's redaction for unexpected application failures.
            raise
        except ToolError as error:
            cause = error
            while cause is not None and not isinstance(cause, InputRefusal):
                cause = cause.__cause__
            return refuse(cause.code if cause else 'INVALID_ARGUMENT', str(cause or error), {'tool': name, 'accepted_keys': accepted})
