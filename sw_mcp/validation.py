"""Public MCP input contract. Expected refusals never fall back to defaults."""
import json
import math
from jsonschema import Draft202012Validator

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.types import CallToolResult, TextContent
from sw_mcp.errors import operational_error


def packed(data, error=False):
    return CallToolResult(content=[TextContent(type='text', text=json.dumps(data, ensure_ascii=False))], structured_content=data, is_error=error)


def refuse(code, message, diagnostics=None, next_action=None):
    error = operational_error(code, message, 'not_required',
                              {'cad_dispatched': False, 'job_created': False, **(diagnostics or {})}, job_created=False)
    error['assertion'] = 'not_applicable'
    error['next_action'].update({'instruction': '核对工具声明与参数后显式重新调用；未自动重试。', **(next_action or {})})
    if error['next_action']['options']:
        error['next_action']['options_status'] = 'explicit_user_selection_required'
    elif error['next_action'].get('tool'):
        error['next_action']['options_status'] = 'tool_identified_arguments_require_user_input'
    return packed({'ok': False, 'error': error}, True)


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
        arguments = {} if arguments is None else arguments
        if not isinstance(arguments, dict):
            return refuse('INVALID_ARGUMENT', 'arguments 必须是 JSON 对象。', {'tool': name, 'field': '/', 'expected_type': 'object', 'received_type': type(arguments).__name__})
        unknown = sorted(set(arguments) - set(accepted))
        if unknown:
            return refuse('UNKNOWN_ARGUMENT', '存在未声明的参数键：' + ', '.join(unknown) + '；未按默认值执行，也未自动改名。',
                          {'tool': name, 'unknown_keys': unknown, 'accepted_keys': accepted})
        # Validate the advertised schema against raw JSON before Pydantic can
        # coerce true or "1.0" into a numerical solve parameter.
        errors = sorted(Draft202012Validator(tool.input_schema).iter_errors(arguments), key=lambda e: str(list(e.path)))
        for key, value in arguments.items():
            if type(value) is float and not math.isfinite(value):
                return refuse('INVALID_ARGUMENT', '数值参数必须有限。', {'tool': name, 'field': key, 'expected_type': 'finite number', 'received_type': 'nonfinite_number', 'accepted_keys': accepted})
        if errors:
            issue = errors[0]
            field = '.'.join(map(str, issue.path)) or '/'
            schema = issue.schema
            kind = ('null' if issue.instance is None else 'boolean' if isinstance(issue.instance, bool) else
                    'string' if isinstance(issue.instance, str) else 'number' if isinstance(issue.instance, (int, float)) else
                    'object' if isinstance(issue.instance, dict) else 'array' if isinstance(issue.instance, list) else 'unknown')
            diag = {'tool': name, 'field': field, 'expected_type': schema.get('type'), 'received_type': kind,
                    'constraint': issue.validator, 'accepted_keys': accepted, 'nullable_keys': [], 'error_count': len(errors)}
            if issue.validator == 'required':
                diag['missing_keys'] = sorted(set(schema.get('required', [])) - set(arguments))
            if 'enum' in schema: diag['accepted_values'] = schema['enum']
            if 'const' in schema: diag['accepted_values'] = [schema['const']]
            label = ', '.join(diag['missing_keys']) if issue.validator == 'required' else field
            return refuse('INVALID_ARGUMENT', '参数不符合工具声明：' + label + '；请按字段类型、必填项和允许值填写。', diag)
        try:
            return await super().call_tool(name, arguments, context)
        except UnexpectedToolError:
            # Preserve the SDK's redaction for unexpected application failures.
            raise
        except ToolError as error:
            cause = error
            while cause is not None and not isinstance(cause, InputRefusal):
                cause = cause.__cause__
            return refuse(cause.code if cause else 'INVALID_ARGUMENT', str(cause) if cause else '参数未通过工具校验；请核对 tools/list 的声明。', {'tool': name, 'accepted_keys': accepted})
