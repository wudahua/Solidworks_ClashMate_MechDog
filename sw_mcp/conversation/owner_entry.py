"""Console-free broker entry; emit lifecycle evidence before importing the CAD task engine."""
import argparse
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path


def main():
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path,required=True);p.add_argument('--generation',required=True)
    args=p.parse_args()
    if not re.fullmatch('[a-f0-9]{32}',args.generation):raise ValueError('INVALID_GENERATION')
    folder=args.work/'ipc'/args.generation
    if not folder.is_dir() or any(x.is_symlink() or getattr(x,'is_junction',lambda:False)() for x in [folder,*folder.parents]):
        raise ValueError('INVALID_OWNER_FOLDER')
    with (folder/'owner.log').open('a',encoding='utf8',buffering=1) as log:
        sys.stdout=log;sys.stderr=log
        def event(stage,**kw):
            with (folder/'lifecycle.jsonl').open('a',encoding='utf8') as f:
                f.write(json.dumps({'stage':stage,'at':time.time(),'pid':os.getpid(),**kw},ensure_ascii=False)+'\n')
        event('entry_started',python=sys.executable)
        try:
            sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
            from sw_mcp.conversation.conversation_owner import serve
            from sw_mcp.conversation.formal_engine import FormalEngine
            serve(args.work,args.generation,engine_factory=FormalEngine)
        except BaseException as error:
            event('entry_failed',error=type(error).__name__,message=str(error));traceback.print_exc();raise
        else:event('entry_returned')


if __name__=='__main__':main()
