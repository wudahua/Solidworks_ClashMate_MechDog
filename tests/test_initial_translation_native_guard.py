"""Compile and exercise actual native admission/readback, without CAD."""
import copy,json,os,subprocess,uuid,unittest
from pathlib import Path
from sw_mcp import initial_translation
from tests.test_initial_translation import survey,goal

ROOT=Path(__file__).resolve().parents[1]

class NativeTranslationGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.name!='nt':raise unittest.SkipTest('Windows .NET compiler required')
        cls.folder=ROOT/'runs'/('translation-guard-'+uuid.uuid4().hex);cls.folder.mkdir(parents=True);cls.exe=cls.folder/'guard.exe'
        compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        environment={**os.environ,'TEMP':str(cls.folder),'TMP':str(cls.folder)}
        result=subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(cls.exe),
            str(ROOT/'executor/InitialTranslationGuard.cs'),str(ROOT/'tests/InitialTranslationGuardFixture.cs')],capture_output=True,env=environment,creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:raise AssertionError(result.stdout.decode(errors='replace')+result.stderr.decode(errors='replace'))
    def value(self):
        s=survey();virtual,proof=initial_translation.propose(s,[goal()])
        return {'proof':proof,'poses':{c['component_id']:c['transform'] for c in s['components']},
            'actual':{c['component_id']:c['transform'] for c in virtual['components']},
            'flags':{c['component_id']:c['fixed_component'] for c in s['components']},'names':{c['component_id']:c['instance'] for c in s['components']}}
    def run_guard(self,value):
        p=subprocess.run([str(self.exe)],input=json.dumps(value,allow_nan=False).encode(),capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(p.returncode,0,p.stderr);return json.loads(p.stdout)
    def test_valid_bounded_initialization_remains_unconfirmed_until_execute(self):
        value=self.value();r=self.run_guard(value);self.assertTrue(r['accepted'] and r['requires_confirmation'])
    def test_stale_original_and_missing_inventory_are_rejected(self):
        for action in (lambda v:v['poses'][next(iter(v['poses']))].__setitem__(9,.123),lambda v:v['poses'].pop(next(iter(v['poses'])))):
            v=self.value();action(v);self.assertFalse(self.run_guard(v)['accepted'])
    def test_rotations_fixed_movement_and_false_summary_rejected(self):
        for mutate in (lambda e:e['after'].__setitem__(0,.99),lambda e:e.__setitem__('fixed',not e['fixed'])):
            v=self.value();mutate(v['proof']['entries'][0]);self.assertFalse(self.run_guard(v)['accepted'])
        v=self.value();v['proof']['requires_alignment_confirmation']=False;self.assertFalse(self.run_guard(v)['accepted'])
    def test_prediction_cannot_be_relabeled_native_verified(self):
        v=self.value();v['proof']['native_pose_verified']=True;self.assertFalse(self.run_guard(v)['accepted'])
    def test_budget_cap_boolean_and_incorrect_delta_rejected(self):
        for budget in (.01,True):
            v=self.value();v['proof']['translation_budget_m']=budget;self.assertFalse(self.run_guard(v)['accepted'])
        v=self.value();v['proof']['entries'][0]['delta_m'][0]+=.000001;self.assertFalse(self.run_guard(v)['accepted'])
    def test_readback_drift_is_rejected_even_within_old_broad_pose_tolerance(self):
        v=self.value();cid=next(iter(v['actual']));v['actual'][cid][9]+=1e-8
        self.assertFalse(self.run_guard(v)['accepted'])
    def test_actual_initialization_rotation_readback_remains_strict(self):
        from sw_mcp import connection_trials as trials
        v=self.value();v['actual']['moving']=trials.target(v['actual']['moving'],[0,0,1],1e-10,True)
        self.assertFalse(self.run_guard(v)['accepted'])

if __name__=='__main__':unittest.main()
