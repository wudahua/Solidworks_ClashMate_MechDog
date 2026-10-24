"""Attach the public MCP tools to their single persistent owner."""
import asyncio,os
from pathlib import Path
from mcp.types import CallToolResult
from sw_mcp.validation import refuse,packed
from sw_mcp.errors import operational_error
from .owner_transport import OwnerClient
from . import core


def transport_refusal(error):
    if error.code in {'TASK_OWNER_REQUEST_UNCONFIRMED','OWNER_OPERATION_OUTCOME_UNCONFIRMED'}:
        value=operational_error(error.code,str(error),'unknown',
            {**(error.diagnostics or {}),'cad_dispatched':None,'job_created':None},job_created=None)
        value['next_action'].update(tool='get_mechanism_task',arguments={},instruction='AI读取既有任务、宿主受理/响应及诊断，不重新提交写入。')
        return packed({'ok':False,'error':value},True)
    return refuse(error.code,str(error),error.diagnostics,
        {'tool':'get_mechanism_task','arguments':{},'instruction':'AI读取既有任务和诊断；未知状态不重试写入或重启绕过。'})


def attach(mcp,root):
    work=Path(os.environ.get('SW_MCP_TASK_WORK',str(root/'runs/dialogue')))
    runtime=Path(os.environ.get('SW_MCP_TASK_RUNTIME',str(root/'runs/cm')))
    client=OwnerClient(root,work,runtime)
    async def dispatch(name,arguments):
        try:
            if name=='get_mechanism_task' and arguments.get('collect_evidence'):
                return packed({'ok':True,'result':await asyncio.to_thread(client.evidence,arguments.get('task_id',''))})
            value=await asyncio.to_thread(client.call,'tool',name,arguments)
            return CallToolResult.model_validate(value)
        except core.StopBatch as error:
            return transport_refusal(error)
    mcp.tool_dispatcher=dispatch
    return client
