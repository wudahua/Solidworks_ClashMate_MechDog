"""Development-only hosted owner with CAD doubles. Never used by product entry points."""
import argparse,sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from sw_mcp.conversation import core
from sw_mcp.conversation.conversation_owner import serve
from sw_mcp.conversation.formal_engine import FormalEngine
from sw_mcp.bridge import Bridge
from sw_mcp.jobs import Jobs
from test_conversation_tasks import FakeSession

class Session(FakeSession):
    def apply(self,confirmed):
        super().apply(confirmed)
        core.write(self.folder/'fixture-apply-count.json',{'calls':self.applied,'real_CAD':False})

def factory(project,work,runtime):
    import motion_server
    # Isolated fixture lease, not the public installation/CAD lease.
    motion_server.bridge=Bridge(project);motion_server.jobs=Jobs(motion_server.bridge,project)
    engine=FormalEngine(project,work,runtime);engine.tasks.session_factory=Session
    return engine

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--work',type=Path);p.add_argument('--generation');a=p.parse_args()
    verdict={'scope_verification':{'scope_acceptance_passed':True},'passed':False,
        'baseline':{'run_id':'fixture-before'},'after':{'run_id':'fixture-after'},'mechanical_card':{'card_id':'fixture'}}
    with patch('sw_mcp.conversation.concentric_card.create',return_value={'card_id':'fixture'}), \
         patch('sw_mcp.conversation.mate_motion.baseline'), \
         patch('sw_mcp.conversation.mate_motion.verify',return_value=verdict), \
         patch('sw_mcp.conversation.startup_gate.require_idle'):
        serve(a.work,a.generation,engine_factory=factory,idle_s=30)
