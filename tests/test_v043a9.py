"""Host identity, real no-CAD scheduler roundtrip and old-install upgrade regression."""
import asyncio,hashlib,json,os,subprocess,sys,time,unittest,uuid,zipfile
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
from sw_mcp.conversation import core,host_scheduler
from sw_mcp.conversation.owner_transport import OwnerClient
from sw_mcp.conversation.frontend import transport_refusal,attach
from sw_mcp.validation import StrictMCPServer
from sw_mcp.errors import operational_error,NATIVE_ACTION_CLASSES
from scripts import upgrade as upgrader
from scripts.verify_release import validate_manifest,ReleasePathPolicyError
from test_alpha5 import contents

ROOT=Path(__file__).resolve().parents[1]
def folder():
    p=ROOT/'runs/host-contract-tests'/uuid.uuid4().hex[:8];p.mkdir(parents=True);return p

@unittest.skipUnless(os.name=='nt','Windows principal/Scheduler contract')
class PrincipalAndSchedulerTests(unittest.TestCase):
    def test_normalized_principal_fallback_and_strict_negative_cases_in_PS51(self):
        p=folder();helper=ROOT/'sw_mcp/conversation/host_contract.ps1'
        script=p/'cases.ps1'
        script.write_text(". '"+str(helper).replace("'","''")+"'\n"+r'''
$ErrorActionPreference='Stop'
$good='S-1-5-21-1-2-3-500';$other='S-1-5-21-1-2-3-501'
function Xml($id){return '<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task"><Principals><Principal id="p"><UserId>'+$id+'</UserId></Principal></Principals></Task>'}
$fail={param($n) throw 'simulated account lookup failure'}
$local={param($n) if($n -ieq 'HOST\Administrator'){return $good};throw 'isolated name fails'}
$different={param($n) if($n -like 'HOST\*'){return $good};return $other}
$wrong={param($n) return $other}
$rows=@()
$rows+=Resolve-HostPrincipal 'Administrator' (Xml $good) $good $fail 'HOST'
$rows+=Resolve-HostPrincipal $good '' $good $fail 'HOST'
$rows+=Resolve-HostPrincipal 'Administrator' (Xml $other) $good $fail 'HOST'
$rows+=Resolve-HostPrincipal 'Administrator' (Xml 'Administrator') $good $local 'HOST'
$rows+=Resolve-HostPrincipal 'host\administrator' '' $good $local 'HOST'
$rows+=Resolve-HostPrincipal 'Administrator' '' $good $different 'HOST'
$rows+=Resolve-HostPrincipal 'Administrator' '' $good $fail 'HOST'
$rows+=Resolve-HostPrincipal 'Administrator' '' $good $wrong 'HOST'
$rows+=Resolve-HostPrincipal 'Administrator' '<!DOCTYPE Task [<!ENTITY x "bad">]><Task/>' $good $fail 'HOST'
$rows+=Resolve-HostPrincipal $other (Xml $good) $good $fail 'HOST'
$rows | ConvertTo-Json -Depth 10
''',encoding='utf8',newline='\n')
        run=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)],capture_output=True,timeout=25)
        self.assertEqual(run.returncode,0,run.stderr.decode('utf8',errors='replace'))
        rows=json.loads(run.stdout)
        self.assertEqual([r['status'] for r in rows],['verified','verified','mismatch','verified','verified','unverifiable','unverifiable','mismatch','unverifiable','mismatch'])
        self.assertEqual(rows[0]['source'],'definition_xml_sid');self.assertFalse(rows[0]['attempts'])
        self.assertEqual(rows[3]['resolved_sid'],rows[3]['expected_sid'])
        core.write(p/'result.json',{'no_CAD':True,'principal_cases':rows})

    def make_spec(self):
        p=folder();entry=p/'no_CAD_probe.py'
        entry.write_text("import argparse,json,os\nfrom pathlib import Path\np=argparse.ArgumentParser();p.add_argument('--work');p.add_argument('--generation');a=p.parse_args()\nPath(a.work,'probe.json').write_text(json.dumps({'generation':a.generation,'pid':os.getpid(),'CAD_calls':0}),encoding='utf8')\n",encoding='utf8',newline='\n')
        return p,host_scheduler.spec_for(p,entry=entry,testing=True)

    def test_real_register_query_idempotent_and_collision_refusal_without_CAD(self):
        p,spec=self.make_spec()
        try:
            first=host_scheduler.control(spec,'register');query=host_scheduler.control(spec,'query')
            again=host_scheduler.control(spec,'register')
            self.assertTrue(first['created']);self.assertFalse(again['created'])
            for value in (first,query,again):
                self.assertTrue(value['contract']['ok']);self.assertEqual(value['contract']['principal']['resolved_sid'],value['interactive_user_sid'])
                self.assertFalse(value['launch_attempted']);self.assertEqual(value['running_instances'],0)
            with self.assertRaises(core.StopBatch) as e:host_scheduler.control({**spec,'marker':'unrelated-marker'},'query')
            self.assertEqual(e.exception.code,'HOST_TASK_COLLISION')
            self.assertIn('description',e.exception.diagnostics['contract']['failed_checks'])
            core.write(p/'roundtrip.json',{'first':first,'query':query,'again':again,'CAD_calls':0})
        finally:host_scheduler.control(spec,'unregister')

    def test_real_interactive_register_run_query_and_exit_without_CAD(self):
        import ctypes
        session=ctypes.c_uint();self.assertTrue(ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(),ctypes.byref(session)))
        if session.value==0:self.skipTest('Session 0 CI cannot run interactive RunEx; register/query and pure contracts remain covered')
        p,spec=self.make_spec();generation=uuid.uuid4().hex
        try:
            host_scheduler.control(spec,'register');started=host_scheduler.control(spec,'run',generation)
            self.assertTrue(started['launch_confirmed'])
            deadline=time.monotonic()+20
            while not (p/'probe.json').exists() and time.monotonic()<deadline:time.sleep(.1)
            proof=core.read(p/'probe.json');self.assertEqual(proof['generation'],generation);self.assertEqual(proof['CAD_calls'],0)
            for _ in range(20):
                state=host_scheduler.control(spec,'query')
                if not state['running_instances']:break
                time.sleep(.1)
            self.assertEqual(state['running_instances'],0);self.assertEqual(state['last_task_result'],0)
            core.write(p/'run-result.json',{'run':started,'final_query':state,'proof':proof})
        finally:host_scheduler.control(spec,'unregister')

    def test_real_public_stdio_refusals_and_reconnect_without_CAD(self):
        import ctypes
        from dialogue_client import Client
        from sw_mcp.conversation.process_identity import same_process
        session=ctypes.c_uint();ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(),ctypes.byref(session))
        if session.value==0:self.skipTest('Session 0 cannot start the real interactive owner; pure and register/query tests still run')
        p=folder();work=p/'work';runtime=ROOT/'runs/hr';client=None;started=False
        mate={'model_id':'m','entity_a':'a','entity_b':'b','mate_type':'parallel'}
        cases=[('import_assembly',{'path':'relative.SLDASM'},'INVALID_ASSEMBLY_PATH'),
               ('import_assembly',{'path':str(p/'bad.SLDPRT')},'INVALID_ASSEMBLY_TYPE'),
               ('import_assembly',{'path':str(p/'missing.SLDASM')},'ASSEMBLY_FILE_UNAVAILABLE'),
               ('preview_mate',{**mate,'distance_mm':1},'INVALID_MATE_PARAMETERS'),
               ('preview_mate',{**mate,'maximum_translation_mm':10001},'INVALID_POSE_BUDGET'),
               ('reset_study_time',{'model_id':'m','study':'s','reset_output_fps':30},'INVALID_RESET_OPTIONS'),
               ('reset_study_time',{'model_id':'m','study':'s','create_new_model':True},'INVALID_RESET_OPTIONS'),
               ('preflight_motion',{'model_id':'m','checkpoint_id':'cp'},'CHECKPOINT_ID_MISUSED'),
               ('replay_motion_frame',{'run_id':'r','frame':0,'saved_image_only':True,'use_input_snapshot':True},'INCOMPATIBLE_REPLAY_OPTIONS'),
               ('apply_mate',{'plan_id':'p','confirmed':False},'CONFIRMATION_REQUIRED')]
        try:
            client=Client(ROOT,work,runtime,p/'stdio1')
            self.assertEqual(len(client.rpc('tools/list',{})['tools']),30)
            value=client.tool('get_mechanism_task');self.assertIsNone(value['active_task']);started=True
            owner=core.read(work/'owner.json');rows=[]
            for name,args,code in cases:
                result=client.rpc('tools/call',{'name':name,'arguments':args})['structuredContent']
                self.assertFalse(result['ok']);self.assertEqual(result['error']['code'],code)
                self.assertFalse(result['error']['diagnostics']['cad_dispatched'])
                rows.append({'tool':name,'expected':code,'actual':result['error']['code']})
            self.assertTrue(client.close());client=None
            client=Client(ROOT,work,runtime,p/'stdio2');self.assertIsNone(client.tool('get_mechanism_task')['active_task'])
            self.assertEqual(core.read(work/'owner.json')['identity'],owner['identity'])
            evidence=client.tool('get_mechanism_task',collect_evidence=True)
            core.write(p/'public-contract-result.json',{'cases':rows,'tools':30,'same_owner':True,'CAD_calls':0,'evidence':evidence})
        finally:
            if client:client.close()
            if started:
                OwnerClient(ROOT,work,runtime).call('shutdown_idle');identity=core.read(work/'owner.json')['identity']
                deadline=time.monotonic()+15
                while same_process(identity)['status']=='same' and time.monotonic()<deadline:time.sleep(.1)
                self.assertNotEqual(same_process(identity)['status'],'same')
                spec=host_scheduler.spec_for(work)
                for _ in range(20):
                    if not host_scheduler.control(spec,'query')['running_instances']:break
                    time.sleep(.1)
                host_scheduler.control(spec,'unregister')

class StartupAndDiagnosticsTests(unittest.TestCase):
    def test_definite_pre_RunEx_refusal_does_not_become_30_second_start_wait(self):
        p=folder();client=OwnerClient(ROOT,p,p/'runtime')
        error=core.StopBatch('HOST_TASK_COLLISION',diagnostics={'launch_attempted':False})
        with patch('sw_mcp.conversation.host_scheduler.register_host'),patch('sw_mcp.conversation.owner_transport.start_host',side_effect=error) as start:
            for _ in range(2):
                with self.assertRaises(core.StopBatch) as e:client.connect()
                self.assertEqual(e.exception.code,'HOST_TASK_COLLISION')
            self.assertEqual(start.call_count,2)
        self.assertTrue(core.read(p/'owner-starting.json')['launch_rejected_before_RunEx'])
        self.assertEqual(len(list((p/'ipc').glob('*/start-rejected.json'))),2)

    def test_unknown_RunEx_outcome_keeps_protection(self):
        p=folder();client=OwnerClient(ROOT,p,p/'runtime')
        with patch('sw_mcp.conversation.host_scheduler.register_host'),patch('sw_mcp.conversation.owner_transport.start_host',side_effect=core.StopBatch('HOST_CONTROL_UNCONFIRMED')) as start:
            with self.assertRaises(core.StopBatch):client.connect()
            with self.assertRaises(core.StopBatch) as e:client.connect()
            self.assertEqual(e.exception.code,'TASK_OWNER_START_UNCONFIRMED');self.assertEqual(start.call_count,1)
        self.assertNotIn('launch_rejected_before_RunEx',core.read(p/'owner-starting.json'))

    def test_host_error_points_to_working_offline_diagnostics_not_broken_owner_query(self):
        for code in ('HOST_TASK_COLLISION','HOST_PRINCIPAL_UNVERIFIABLE','TASK_OWNER_START_UNCONFIRMED'):
            error=transport_refusal(core.StopBatch(code)).structured_content['error']
            self.assertEqual(error['next_action']['options_status'],'host_infrastructure_review_required_no_parameter_change')
            self.assertEqual(error['next_action']['arguments'],{'collect_evidence':True})
            self.assertFalse(error['next_action']['automatic_retry'])
        p=folder();mcp=StrictMCPServer('offline-test')
        @mcp.tool()
        async def get_mechanism_task(collect_evidence:bool=False):raise AssertionError('dispatcher must intercept')
        with patch.dict(os.environ,{'SW_MCP_TASK_WORK':str(p),'SW_MCP_TASK_RUNTIME':str(p/'runtime')}):client=attach(mcp,ROOT)
        with patch.object(client,'connect',side_effect=AssertionError('no startup for evidence')):
            value=asyncio.run(mcp.call_tool('get_mechanism_task',{'collect_evidence':True})).structured_content
        self.assertTrue(value['ok']);self.assertEqual(value['result']['CAD_calls'],0);self.assertTrue(Path(value['result']['zip_path']).is_file())

    def test_twenty_reported_native_codes_have_deliberate_nonautomatic_guidance(self):
        codes=set(NATIVE_ACTION_CLASSES)|{'EXECUTOR_ALREADY_RUNNING'}
        self.assertEqual(len(codes),20)
        backend='\n'.join(p.read_text(encoding='utf-8-sig') for p in (ROOT/'executor').glob('*.cs'))
        backend+='\n'+'\n'.join(p.read_text(encoding='utf8') for p in (ROOT/'sw_mcp').glob('*.py'))
        for code in codes:
            with self.subTest(code=code):
                self.assertIn(code,backend)
                action=operational_error(code,code)['next_action']
                self.assertNotEqual(action['options_status'],'no_safe_parameter_change_inferred_from_error_code')
                self.assertFalse(action['automatic_retry']);self.assertEqual(action['options'],[])

class UpgradeEntryTests(unittest.TestCase):
    def test_policy_refusal_lists_all_paths_without_running_package_code(self):
        files=contents();m=json.loads(files['发布清单.json'])
        names=['sw_mcp/unknown/private.py','runs/secret.py','executor/bin/secret.cs']
        m['files'] += [{'path':n,'bytes':0,'sha256':hashlib.sha256(b'').hexdigest()} for n in names]
        with self.assertRaises(ReleasePathPolicyError) as e:validate_manifest(m,lambda _:self.fail('refused package should not execute or read sources'))
        self.assertEqual(e.exception.diagnostics['rejected_paths'],names)

    def test_new_package_runner_targets_old_install_without_loading_old_validator(self):
        p=folder();target=p/'old';(target/'scripts').mkdir(parents=True)
        old=target/'scripts/verify_release.py';old.write_text("raise AssertionError('installed validator must not execute')\n",encoding='utf8')
        (target/'motion_server.py').write_bytes(b'# old installed entry\n');(target/'executor').mkdir()
        files=contents();files['sw_mcp/conversation/__init__.py']=b'# new public subpackage\n'
        m=json.loads(files['发布清单.json']);name='sw_mcp/conversation/__init__.py'
        m['files'].append({'path':name,'bytes':len(files[name]),'sha256':hashlib.sha256(files[name]).hexdigest()});files['发布清单.json']=json.dumps(m,ensure_ascii=False).encode()
        package=p/'new.zip'
        with zipfile.ZipFile(package,'w') as z:
            for n,b in files.items():z.writestr('Solidworks_ClashMate_MechDog/'+n,b)
        package.with_suffix('.zip.sha256').write_text(hashlib.sha256(package.read_bytes()).hexdigest()+'  new.zip\n',encoding='utf8')
        with patch.object(upgrader,'idle_installation',return_value=nullcontext()):
            value=upgrader.upgrade(package,target,sys.executable,dry_run=True,install=False)
        self.assertEqual(value['path_policy_source'],'running_upgrade_entry')
        self.assertEqual(value['upgrade_entry'],str(Path(upgrader.__file__).resolve()))
        self.assertFalse(value['embedded_validator_executed']);self.assertFalse(value['target_mutation_started'])
        self.assertIn('installed validator must not execute',old.read_text())

if __name__=='__main__':unittest.main(verbosity=2)
