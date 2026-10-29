"""Attach the public MCP tools to their single persistent owner."""
import asyncio,os
from pathlib import Path
from mcp.types import CallToolResult
from sw_mcp.validation import packed
from sw_mcp.task_errors import task_failure
from .owner_transport import OwnerClient
from . import core


def transport_refusal(error):
    return packed({'ok':False,'error':task_failure(error.code,str(error),error.diagnostics)},True)


def attach(mcp,root):
    work=Path(os.environ.get('SW_MCP_TASK_WORK',str(root/'runs/dialogue')))
    runtime=Path(os.environ.get('SW_MCP_TASK_RUNTIME',str(root/'runs/cm')))
    client=OwnerClient(root,work,runtime)
    async def dispatch(name,arguments):
        try:
            if name=='get_mechanism_task' and arguments.get('collect_evidence') and not arguments.get('draft_cursor'):
                return packed({'ok':True,'result':await asyncio.to_thread(client.evidence,arguments.get('task_id',''))})
            value=await asyncio.to_thread(client.call,'tool',name,arguments)
            return CallToolResult.model_validate(value)
        except core.StopBatch as error:
            return transport_refusal(error)
    mcp.tool_dispatcher=dispatch
    return client
