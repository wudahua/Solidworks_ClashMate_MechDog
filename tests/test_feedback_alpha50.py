"""Reported host regressions with real child processes; no CAD or network."""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from test_service import temporary_workspace

ROOT=Path(__file__).resolve().parents[1]


class MetadataTests(unittest.TestCase):
    def test_actual_inventory_count_does_not_overwrite_historic_prepare_or_use_expected_count(self):
        from types import SimpleNamespace
        from sw_mcp.conversation.assembly_snapshot import record_native_inventory,summary
        task={'task_id':'a'*32,'phase':'verified','busy':False,'closed':False,'assembly_brief':{'mate_count':0},
              'proposal':{'expected_added_mates':99}}
        session=SimpleNamespace(model='model',result_inspection={'mates':[{},{}],'components':[{}, {}, {}]})
        record_native_inventory(task,session,{'checkpoint_id':'checkpoint'})
        view=summary(task)
        self.assertEqual(view['assembly_brief']['mate_count'],0)
        self.assertEqual(view['current_assembly_observation']['mate_count'],2)
        self.assertFalse(view['current_assembly_observation']['live_query_performed_by_get'])
        task['closed']=True
        self.assertTrue(summary(task)['current_assembly_observation']['historical_after_finish'])
        self.assertFalse(task['current_assembly_observation']['historical_after_finish'])

    def test_upgrade_lists_old_unfinished_tasks_without_moving_or_claiming_outcome(self):
        from scripts.upgrade import managed_history_review
        with temporary_workspace() as directory:
            root=Path(directory);folder=root/'runs/dialogue/task-old';folder.mkdir(parents=True)
            p=folder/'任务状态.json';p.write_text(json.dumps({'task_id':'a'*32,'phase':'failed','closed':False}),encoding='utf8')
            before=p.read_bytes();v=managed_history_review(root)
            self.assertEqual(len(v['unfinished_tasks']),1);self.assertEqual(p.read_bytes(),before)
            self.assertFalse(v['records_modified']);self.assertTrue(v['scan_complete'])
            self.assertEqual(v['unfinished_tasks'][0]['next_action']['tool'],'get_mechanism_task')
            self.assertEqual(v['unfinished_tasks'][0]['native_outcome'],'not_inferred_from_snapshot')

    def test_public_default_coordinates_before_compacting_and_full_record_opts_out(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import Mock,patch
        import motion_server
        engine=SimpleNamespace(get=Mock(return_value={'phase':'running'}))
        with patch.object(motion_server,'_task_engine',engine):
            result=asyncio.run(motion_server.mcp.call_tool('get_mechanism_task',{'task_id':'a'*32}))
            self.assertFalse(result.is_error);self.assertTrue(engine.get.call_args.kwargs['compact'])
            result=asyncio.run(motion_server.mcp.call_tool('get_mechanism_task',{'task_id':'a'*32,'full_record':True}))
            self.assertFalse(result.is_error);self.assertFalse(engine.get.call_args.kwargs['compact'])

    def test_geometry_groups_are_questions_not_rigid_ownership_or_complete_plans(self):
        from sw_mcp.assembly_intent_guide import build
        cs=[{'component_id':str(i),'instance':'part-'+str(i),'fixed_component':i==0} for i in range(4)]
        rows=[{'component_id':str(i),'kind':'cylindrical_axis','axis_global':[0,0,1],
               'reference_point_global_m':[.01 if i==3 else 0,0,i*.01]} for i in range(4)]
        survey={'components':cs,'mates':[]};before=json.dumps(survey,sort_keys=True)
        result=build(survey,{'rows':rows,'analytic_geometry_complete':True})
        self.assertEqual(result['group_count'],1);self.assertTrue(result['geometry_search_complete'])
        self.assertEqual(result['groups'][0]['members'],['part-0','part-1','part-2'])
        self.assertEqual(result['components_without_axis_group'],['part-3'])
        self.assertFalse(result['rigid_ownership_inferred']);self.assertFalse(result['automatic_plan_available'])
        self.assertEqual(result['whole_assembly_route']['public_execution_confirmation_count'],1)
        self.assertEqual(before,json.dumps(survey,sort_keys=True))

    def test_guide_budget_and_incomplete_geometry_never_claim_complete_search(self):
        from sw_mcp import assembly_intent_guide as guide
        from unittest.mock import patch
        s={'components':[{'component_id':'a','instance':'a'}],'mates':[]}
        row={'component_id':'a','kind':'cylindrical_axis','axis_global':[0,0,1],'reference_point_global_m':[0,0,0]}
        with patch.object(guide,'MAX_AXIS_ROWS',1):
            v=guide.build(s,{'rows':[row,row],'analytic_geometry_complete':True})
        self.assertTrue(v['budget_reached']);self.assertFalse(v['geometry_search_complete'])
        self.assertFalse(guide.build(s,{'rows':[row],'analytic_geometry_complete':False})['geometry_search_complete'])

    def test_plane_normal_is_not_a_material_hinge_axis(self):
        from sw_mcp.assembly_intent_guide import build
        s={'components':[{'component_id':str(i),'instance':str(i)} for i in range(2)],'mates':[]}
        rows=[{'component_id':str(i),'kind':'planar_normal','axis_global':[0,0,1],
               'reference_point_global_m':[0,0,0]} for i in range(2)]
        self.assertEqual(build(s,{'rows':rows,'analytic_geometry_complete':True})['group_count'],0)

    def test_driver_success_is_not_reported_as_verified_mechanism_outputs(self):
        from sw_mcp.conversation.task_views import conclusions
        v=conclusions({'verification':{'declared_scope_passed':True,'direction_verified_about_selected_native_axis':True}})
        self.assertEqual(v['driver_direction_validation'],'pass')
        self.assertEqual(v['mechanism_output_validation'],'not_verified')
        self.assertEqual(v['restoration_status'],'not_verified')

    def test_public_build_native_and_dialogue_versions_are_equal(self):
        from sw_mcp.conversation import core
        def version(name,pattern):
            return re.search(pattern,(ROOT/name).read_text('utf8')).group(1)
        self.assertEqual(core.VERSION,version('scripts/build_release.py',r'VERSION = "([^"]+)"'))
        for name in ('motion_server.py','executor/UserMotion.cs'):
            self.assertEqual(core.VERSION,version(name,r'version="([^"]+)"'))
        self.assertEqual(core.KIT_VERSION,'formal-dialogue-'+core.VERSION)

    def test_every_native_console_entry_selects_utf8(self):
        for path in (ROOT/'tests').glob('*.cs'):
            text=path.read_text('utf8')
            if re.search(r'static\s+(?:void|int)\s+Main\s*\(',text):
                # The raw environment launcher forwards child bytes unchanged.
                if path.name=='RawDuplicateEnvironmentFixture.cs':continue
                with self.subTest(path=path.name):self.assertRegex(text,r'Console.OutputEncoding\s*=.*UTF8Encoding')


@unittest.skipUnless(os.name=='nt','Windows process/encoding fixtures')
class HostChildTests(unittest.TestCase):
    def compile(self,exe,sources,main=None):
        csc=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        args=[str(csc),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(exe)]
        if main:args.append('/main:'+main)
        p=subprocess.run(args+[str(p) for p in sources],capture_output=True,timeout=30)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_five_component_errors_are_utf8_even_after_forced_CP936(self):
        with temporary_workspace() as folder:
            root=Path(folder);wrapper=root/'Runner.cs';exe=root/'fixture.exe'
            wrapper.write_text('using System;using System.Reflection;class Runner {static void Main(string[] a){Console.OutputEncoding=System.Text.Encoding.GetEncoding(936);typeof(ComponentInventoryReadTests).GetMethod("Main",BindingFlags.NonPublic|BindingFlags.Static).Invoke(null,new object[]{a});}}',encoding='utf8')
            self.compile(exe,[wrapper,ROOT/'tests/ComponentInventoryReadTests.cs',ROOT/'executor/ComponentInventoryRead.cs',ROOT/'executor/CadFault.cs'],'Runner')
            for mode in ('always_bad','count_change','context_change','missing','null_entry'):
                with self.subTest(mode=mode):
                    p=subprocess.run([str(exe),mode],capture_output=True,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
                    self.assertEqual(p.returncode,0,p.stderr)
                    value=json.loads(p.stdout.decode('utf8'))
                    self.assertFalse(value['ok']);self.assertEqual(value['code'],'API_TYPE_MISMATCH')

    def test_real_PS51_duplicate_proxy_block_preserves_host_policy_and_script_semantics(self):
        with temporary_workspace() as folder:
            root=Path(folder)/"space ' quote";scripts=root/'scripts';scripts.mkdir(parents=True)
            launch=root/'raw.exe';self.compile(launch,[ROOT/'tests/RawDuplicateEnvironmentFixture.cs'])
            shutil.copyfile(ROOT/'upgrade.ps1',root/'upgrade.ps1')
            (scripts/'sibling.py').write_text('value=73\n',encoding='utf8')
            policy=root/'policy';policy.mkdir()
            (policy/'sitecustomize.py').write_text('import sys;sys.cm_test_policy_loaded=True\n',encoding='utf8')
            (scripts/'upgrade.py').write_text('''import os,sys,json,sibling,ctypes
k=ctypes.windll.kernel32
k.GetEnvironmentStringsW.restype=ctypes.c_void_p
k.FreeEnvironmentStringsW.argtypes=[ctypes.c_void_p]
p=k.GetEnvironmentStringsW();offset=0;keys=[]
try:
 while True:
  row=ctypes.wstring_at(p+offset*2)
  if not row:break
  offset+=len(row)+1
  name=row.split("=",1)[0]
  if name.upper()=="HTTPS_PROXY":keys.append(name)
finally:k.FreeEnvironmentStringsW(p)
print(json.dumps({"ok":True,"message":"中文参数","args":sys.argv[1:],"encoding":os.environ.get("PYTHONIOENCODING"),"policy":getattr(sys,"cm_test_policy_loaded",False),"sibling":sibling.value,"raw_proxy_keys":keys},ensure_ascii=False))
raise SystemExit(37)
''',encoding='utf8')
            ps=shutil.which('powershell.exe');self.assertIsNotNone(ps)
            env={**os.environ,'PYTHONPATH':str(policy),'PYTHONIOENCODING':'ascii'}
            cmd=[str(launch),ps,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(root/'upgrade.ps1'),
                 '-SourcePackage',str(root/'未使用 " quote.zip'),'-TargetDir',str(root/'target'),'-PythonPath',sys.executable]
            p=subprocess.run(cmd,capture_output=True,env=env,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertEqual(p.returncode,37,p.stdout+p.stderr)
            value=json.loads(p.stdout.decode('utf8'))
            self.assertTrue(value['ok']);self.assertTrue(value['policy']);self.assertEqual(value['sibling'],73)
            self.assertEqual(value['message'],'中文参数');self.assertEqual(value['encoding'],'utf-8')
            self.assertEqual(set(value['raw_proxy_keys']),{'HTTPS_PROXY','https_proxy'})
            self.assertEqual(len(value['raw_proxy_keys']),2)
            self.assertEqual(value['args'][1],str(root/'未使用 " quote.zip'))
            self.assertFalse((root/'target').exists());self.assertEqual(env['PYTHONIOENCODING'],'ascii')


if __name__=='__main__':unittest.main()
