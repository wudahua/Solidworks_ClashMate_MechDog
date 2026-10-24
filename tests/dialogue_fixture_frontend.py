"""No-CAD fixture root; same public schemas and hosted frontend implementation."""
import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import motion_server
from sw_mcp.conversation.frontend import attach
attach(motion_server.mcp,Path(os.environ['SW_MCP_TEST_PROJECT']))
motion_server.mcp.run(transport='stdio')
