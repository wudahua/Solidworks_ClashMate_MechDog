"""Owned native run -> verify -> default history acceptance, with negative tamper control."""
import sys
import asyncio
import json
from pathlib import Path
from unittest.mock import patch
import v042a7_performance_native as previous

code = previous.matrix.CS
needle = 'r["completed"]=true;save();return 0;'
extra = r'''var originalRun=D(r["run"]);string originalId=(string)originalRun["run_id"];bool bindingRejected=false;try{r["native_current_binding_summary"]=cad.UserRunSummary(originalId);}catch(CadFault fault){if(fault.Code!="MODEL_REVISION_CHANGED")throw;bindingRejected=true;}r["original_native_binding_rejected_if_stale"]=bindingRejected;string latestId=(string)D(r["verify"])["run_id"];cad.UserRunSummary(latestId);string ownedPath=(string)D(r["import"])["path"];cad.ProbeTestCloseOwnedModel(id);var exactBytes=File.ReadAllBytes(ownedPath);try{using(var stream=new FileStream(ownedPath,FileMode.Append,FileAccess.Write,FileShare.ReadWrite))stream.WriteByte(0);bool blocked=false;try{cad.UserRunSummary(latestId);}catch(CadFault fault){blocked=fault.Code=="MODEL_REVISION_CHANGED";}r["external_byte_change_rejected"]=blocked;if(!blocked)throw new Exception("HISTORY_FILE_IDENTITY_GATE_WEAKENED");}finally{File.WriteAllBytes(ownedPath,exactBytes);}cad.UserRunSummary(latestId);r["completed"]=true;save();return 0;'''

assert needle in code
previous.matrix.CS = code.replace(needle, extra).replace('class ProbeAcceptance {', 'public partial class Cad {public void ProbeTestCloseOwnedModel(string id){CloseUserDocuments(GetUserModel(id).Files);}}\nclass ProbeAcceptance {').replace('var exactBytes=File.ReadAllBytes(ownedPath);', 'cad.ProbeTestCloseOwnedModel(id);var exactBytes=File.ReadAllBytes(ownedPath);')
if '--baseline' in sys.argv:
    sys.argv.remove('--baseline')
    previous.matrix.CS = code
if '--visible' in sys.argv:
    sys.argv.remove('--visible')
    previous.matrix.CS = previous.matrix.CS.replace('cad=new Cad(a[0]);', 'cad=new Cad(a[0]);cad.Sw.Visible=true;')
if __name__ == '__main__':
    report = previous.main()
    if report:
        folder = Path(report['directory'])
        native = json.loads((folder/'native.json').read_text(encoding='utf-8-sig'))
        if 'external_byte_change_rejected' in native:
            sys.path.insert(0, str(previous.ROOT))
            import motion_server as server
            from sw_mcp.artifacts import Artifacts
            original_id = native['run']['run_id']
            cid = next(key for key, name in native['run']['component_instances'].items() if 'Part6' in name)
            checks = []
            with patch.object(server, 'artifacts', Artifacts(folder)), patch.object(server.bridge, 'request', side_effect=AssertionError('Public history must not dispatch CAD')):
                for tool, args in [('get_motion_summary', {'run_id':original_id}), ('export_motion_curve', {'run_id':original_id, 'component_id':cid, 'quantity':'angular_velocity'})]:
                    response = asyncio.run(server.mcp.call_tool(tool, args))
                    assert not response.is_error, response.content
                    value = response.structured_content['result']
                    assert value['artifact_integrity'] == 'verified' and value['current_model_validity'] == 'not_checked_offline'
                    assert value['historical_data'] and not value['physical_validation_claim']
                    checks.append({'tool':tool,'result':value})
            (folder/'default-history-public.json').write_text(json.dumps({'all_passed':True,'cad_dispatched':False,'after_real_native_run_and_verify':True,'checks':checks},ensure_ascii=False,indent=2),encoding='utf-8')
            print('PUBLIC_DEFAULT_HISTORY_PASS', str(folder), flush=True)
