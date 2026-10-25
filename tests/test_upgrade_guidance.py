"""Read-only lock diagnosis and bounded task views; real no-CAD process leases."""
import ctypes,json,os,subprocess,sys,time,unittest,uuid,zipfile
from pathlib import Path
from unittest.mock import patch
from scripts.lease_access import open_lease_file,lock_lease_file,lease_diagnostics
from scripts.upgrade import UpgradeFailure,idle_installation
from sw_mcp.bridge import Bridge,CadError
from sw_mcp.conversation.task_engine import TaskEngine,core
from sw_mcp.conversation.evidence_bundle import collect
from sw_mcp.task_errors import task_failure
from test_conversation_tasks import FakeSession

ROOT=Path(__file__).resolve().parents[1]


def folder():
    p=ROOT/'runs/upgrade-guidance-tests'/uuid.uuid4().hex[:8];p.mkdir(parents=True);return p


class LeaseGuidanceTests(unittest.TestCase):
    def holder(self,root,kind):
        source=('import sys\nfrom pathlib import Path\nfrom scripts.lease_access import open_lease_file,lock_lease_file\n'
            'from sw_mcp.bridge import Bridge\nroot=Path(sys.argv[1])\n'
            'if sys.argv[2]=="bridge":\n b=Bridge(root);b._acquire_lease()\n'
            'else:\n p=root/"runs/dialogue/conversation-owner.lock";p.parent.mkdir(parents=True,exist_ok=True);f=open_lease_file(p);f.write(b"0");f.flush();f.seek(0);lock_lease_file(f)\n'
            'print("ready",flush=True)\nsys.stdin.readline()\n'
            'if sys.argv[2]=="bridge": b.close()\nelse: f.close()\n')
        env={**os.environ,'PYTHONPATH':str(ROOT),'PYTHONIOENCODING':'utf-8'}
        p=subprocess.Popen([sys.executable,'-X','utf8','-c',source,str(root),kind],stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
        finished=[False]
        def cleanup():
            if finished[0]:return
            out,err=p.communicate('\n',timeout=15)
            self.assertEqual(p.returncode,0,err)
            finished[0]=True
        p.release_test_holder=cleanup
        self.addCleanup(cleanup)
        self.assertEqual(p.stdout.readline().strip(),'ready')
        return p
    def test_real_service_and_owner_leases_refuse_upgrade_without_path_mutation(self):
        root=folder();(root/'runs').mkdir();p=root/'runs/executor-owner.lock';p.write_bytes(b'0')
        before=(p.stat().st_ino,p.read_bytes());service=self.holder(root,'bridge');owner=self.holder(root,'owner')
        with patch('os.rename',side_effect=AssertionError('lock rename forbidden')):
            with self.assertRaises(UpgradeFailure) as caught:
                with idle_installation(root):self.fail('must refuse held lease')
        e=caught.exception;native=e.diagnostics['winerror']
        self.assertIn(native,(5,32,33));self.assertIsNone(service.poll());self.assertIsNone(owner.poll())
        self.assertEqual(e.code,'UPGRADE_LEASE_ACCESS_FAILED' if native==5 else 'UPGRADE_LEASE_BUSY')
        self.assertEqual(e.diagnostics['occupied_proven'],native in (32,33))
        if native==5:self.assertIn('finish_motion_session',e.payload()['error']['next_action']['instruction'])
        self.assertEqual(p.stat().st_ino,before[0])
        service.release_test_holder();owner.release_test_holder()
        self.assertEqual((p.stat().st_ino,p.read_bytes()),before)
        core.write(root/'observed-topology.json',{'winerror':native,'code':e.code,'actual_no_CAD_process_holders':2,
            'lock_identity_and_bytes_unchanged':True,'force_termination':False})
    def test_winerror5_policy_with_real_holders_is_ambiguous_not_asserted_busy(self):
        root=folder();(root/'runs').mkdir();p=root/'runs/executor-owner.lock';p.write_bytes(b'0')
        service=self.holder(root,'bridge');owner=self.holder(root,'owner')
        # Inject the reported native result; do not claim this reproduces the
        # remote OS/filter mechanism that made CreateFileW return 5.
        with patch('scripts.upgrade.open_lease_file',side_effect=ctypes.WinError(5)):
            with self.assertRaises(UpgradeFailure) as caught:
                with idle_installation(root):self.fail('must refuse')
        e=caught.exception;value=e.payload();d=e.diagnostics
        self.assertEqual(e.code,'UPGRADE_LEASE_ACCESS_FAILED');self.assertEqual(d['winerror'],5)
        self.assertFalse(d['occupied_proven']);self.assertFalse(d['service_presence_proven']);self.assertIsNone(d['owner_pid'])
        self.assertIn('same_installation_service_or_host_handle_topology',d['possible_causes'])
        self.assertFalse(d['lock_path_probe_mutation']);self.assertFalse(value['automatic_retry'])
        self.assertIn('无活动受管任务',value['error']['next_action']['instruction'])
        self.assertIn('不删除、重命名锁文件',value['error']['next_action']['instruction'])
        self.assertIsNone(service.poll());self.assertIsNone(owner.poll())
        with patch('sw_mcp.bridge.open_lease_file',side_effect=ctypes.WinError(5)):
            with self.assertRaises(CadError) as bridge_error:Bridge(root)._acquire_lease()
        self.assertEqual(bridge_error.exception.code,'MCP_LEASE_UNAVAILABLE')
        self.assertEqual(bridge_error.exception.diagnostics['winerror'],5)
        self.assertIn('finish_motion_session',str(bridge_error.exception))
        service.release_test_holder();owner.release_test_holder();self.assertEqual(p.read_bytes(),b'0')
    def test_actual_read_only_file_is_not_misclassified_as_service_occupancy(self):
        root=folder();(root/'runs').mkdir();p=root/'runs/executor-owner.lock';p.write_bytes(b'0')
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.SetFileAttributesW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint]
        self.assertTrue(kernel.SetFileAttributesW(str(p),1))
        try:
            with self.assertRaises(UpgradeFailure) as caught:
                with idle_installation(root):self.fail('read only')
            self.assertEqual(caught.exception.code,'UPGRADE_LEASE_ACCESS_FAILED')
            self.assertEqual(caught.exception.diagnostics['winerror'],5)
            self.assertFalse(caught.exception.diagnostics['occupied_proven'])
        finally:self.assertTrue(kernel.SetFileAttributesW(str(p),0x80))
        self.assertEqual(p.read_bytes(),b'0')
    def test_errno_without_native_error_is_not_fabricated_as_a_holder(self):
        value=lease_diagnostics(Path('fixture'),PermissionError(13,'denied'),'open_lease')
        self.assertIsNone(value['winerror']);self.assertFalse(value['occupied_proven'])
        self.assertFalse(value['service_presence_proven']);self.assertEqual(value['possible_causes'],[])
    def test_incomplete_rollback_warning_is_not_replaced_by_service_guidance(self):
        value=UpgradeFailure('UPGRADE_LEASE_ACCESS_FAILED','fixture',{'rollback_status':'incomplete','target_mutation_started':True}).payload()
        self.assertFalse(value['safe_to_start_mcp']);self.assertIn('不要启动 MCP',value['error']['next_action']['instruction'])
        self.assertIn('不强杀',value['error']['next_action']['instruction'])


class ResponseGuidanceTests(unittest.TestCase):
    def test_orphan_gate_hint_requires_known_idle_same_service_not_auto_finish(self):
        value=task_failure('ORPHAN_EXECUTOR_GATE_NOT_IDLE','occupied',task_id='a'*32)
        action=value['next_action'];self.assertEqual(action['tool'],'get_mechanism_task')
        self.assertFalse(action['automatic_retry']);self.assertIn('active_task为空',action['instruction'])
        hint=action['conditional_actions'][0];self.assertEqual(hint['tool'],'finish_motion_session')
        self.assertIn('no_active_managed_task',hint['when']);self.assertIn('recovery_confirmed_idle',hint['when'])
        self.assertEqual(value['restoration_status'],'unknown')
        self.assertNotIn('conditional_actions',task_failure('NATIVE_STATE_UNKNOWN','unknown')['next_action'])
    def make_engine(self,count):
        p=folder();source=p/'models/case.SLDASM';source.parent.mkdir();source.write_bytes(b'fixture')
        for index in range(count):(source.parent/f'notes-{index:04d}.md').write_text('non CAD')
        e=TaskEngine(p,p/'work',p/'runtime',FakeSession);self.addCleanup(e.shutdown)
        tid=e.prepare(str(source))['task_id'];self.wait(e,tid)
        return e,tid,source
    def wait(self,e,tid):
        for _ in range(500):
            value=e.get(tid)
            if not value['busy']:return value
            time.sleep(.005)
        self.fail('timeout')
    def test_large_view_bounded_but_full_inventory_survives_finish_reload_and_evidence(self):
        e,tid,source=self.make_engine(250);raw=e.tasks[tid];saved=Path(raw['directory'])/'任务状态.json'
        value=e.get(tid);summary=value['source_workspace_files_summary']
        self.assertEqual(len(value['source_workspace_files']),20);self.assertEqual(summary['total_count'],251);self.assertTrue(summary['truncated'])
        self.assertEqual(len(raw['source_workspace_files']),251);self.assertEqual(len(core.read(saved)['source_workspace_files']),251)
        (source.parent/'new.csv').write_text('new output')
        e.finish(tid);closed=self.wait(e,tid)
        self.assertTrue(closed['closed']);self.assertTrue(closed['finish']['source_files_unchanged'])
        self.assertEqual([r['path'] for r in closed['finish']['source_integrity']['added']],['new.csv'])
        package=collect(e.work,tid)
        with zipfile.ZipFile(package['zip_path']) as z:
            names=[n for n in z.namelist() if n.endswith('/任务状态.json')]
            self.assertEqual(len(names),1);full=json.loads(z.read(names[0]));self.assertEqual(len(full['source_workspace_files']),251)
        other=TaskEngine(e.project,e.work,e.runtime_base,FakeSession);self.addCleanup(other.shutdown)
        self.assertEqual(len(other.tasks[tid]['source_workspace_files']),251)
        self.assertEqual(other.get(tid)['source_workspace_files_summary']['total_count'],251)
    def test_small_view_is_complete_and_mutating_view_does_not_modify_baseline(self):
        e,tid,source=self.make_engine(2);value=e.get(tid)
        self.assertEqual(len(value['source_workspace_files']),3);self.assertFalse(value['source_workspace_files_summary']['truncated'])
        value['source_workspace_files'].clear();self.assertEqual(len(e.tasks[tid]['source_workspace_files']),3)


if __name__=='__main__':unittest.main(verbosity=2)
