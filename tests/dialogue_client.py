"""Developer harness: actual MCP stdio requests, exact JSONL evidence, no browser."""
import json,os,queue,subprocess,sys,threading,time
from pathlib import Path
from sw_mcp.conversation.task_engine import HERE,core

class Client:
    def __init__(self,project,work,runtime,folder,entry=None):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True);self.pending={};self.counter=0
        self.error=(self.folder/'server.stderr.log').open('wb')
        env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONUNBUFFERED='1')
        env.pop('SW_MCP_PROCESS_ID',None);env.pop('SW_MCP_FAULT_TESTS',None)
        env.update(SW_MCP_TASK_WORK=str(work),SW_MCP_TASK_RUNTIME=str(runtime))
        if entry:env['SW_MCP_TEST_PROJECT']=str(project)
        self.process=subprocess.Popen([sys.executable,'-X','utf8',str(entry or HERE.parents[1]/'motion_server.py')],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.error,env=env,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        def read():
            try:
                for raw in self.process.stdout:
                    with (self.folder/'server_to_client.jsonl').open('ab') as f:f.write(raw)
                    value=json.loads(raw)
                    if value.get('id') in self.pending:self.pending[value['id']].put(value)
            finally:
                for q in list(self.pending.values()):q.put({'error':{'message':'MCP_EOF'}})
        self.reader=threading.Thread(target=read,daemon=True);self.reader.start()
        self.hello=self.rpc('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'ClashMate-conversation-native-acceptance','version':'0.1'}})
        self.send({'jsonrpc':'2.0','method':'notifications/initialized'})
        core.write(self.folder/'handshake.json',self.hello)
    def send(self,v):
        raw=(json.dumps(v,ensure_ascii=False)+'\n').encode('utf-8')
        with (self.folder/'client_to_server.jsonl').open('ab') as f:f.write(raw)
        self.process.stdin.write(raw);self.process.stdin.flush()
    def rpc(self,method,params):
        self.counter+=1;identifier=self.counter;q=queue.Queue();self.pending[identifier]=q
        try:
            self.send({'jsonrpc':'2.0','id':identifier,'method':method,'params':params})
            value=q.get(timeout=720)
            if 'error' in value:raise RuntimeError(value['error'])
            return value['result']
        finally:self.pending.pop(identifier,None)
    def tool(self,name,**arguments):
        result=self.rpc('tools/call',{'name':name,'arguments':arguments})
        value=result.get('structuredContent')
        if value is None:value=json.loads(next(c['text'] for c in result['content'] if c.get('type')=='text'))
        if 'ok' not in value:return value
        if not value.get('ok'):raise core.StopBatch(value['error']['code'],value['error']['message'],value['error'])
        return value['result']
    def wait(self,task_id,maximum_s=650):
        deadline=time.monotonic()+maximum_s;previous=None
        while time.monotonic()<deadline:
            state=self.tool('get_mechanism_task',task_id=task_id)
            mark=(state['phase'],state.get('native_stage'))
            if mark!=previous:print(json.dumps({'task_id':task_id,'phase':mark,'message':state.get('message')},ensure_ascii=False),flush=True);previous=mark
            if not state['busy']:return state
            time.sleep(1)
        raise core.StopBatch('ACCEPTANCE_WAIT_EXPIRED','仅停止等待，未结束任务或原生进程。')
    def close(self):
        self.process.stdin.close()
        try:self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:return False
        self.reader.join(timeout=2);self.process.stdout.close();self.error.close();return self.process.returncode==0

