"""Wire identity, real .NET round trips, and unchanged physical acceptance."""
import copy,hashlib,json,math,os,subprocess,tempfile,unittest
from pathlib import Path
from sw_mcp import connection_trials as trials

ROOT=Path(__file__).resolve().parents[1]


def target():
    # The near-zero coefficient which exposed the real reducer round trip.
    return [0.,0.,1.,0.,1.,0.,-1.,0.,-9.742732028096571e-17,0.,0.,0.,1.,0.,0.,0.]


def evidence(p,wire=None):
    wire=json.dumps(p) if wire is None else wire
    return {'target':copy.deepcopy(p),'request_target_sha256':hashlib.sha256(wire.encode('utf8')).hexdigest()}


class TargetBindingTests(unittest.TestCase):
    def test_exact_target_is_bound_to_original_wire(self):
        p=target();r=trials.require_target_binding(evidence(p),p,json.dumps(p))
        self.assertTrue(r['request_sha256_verified']);self.assertEqual(r['nonidentical_coefficients'],[])
    def test_reducer_one_ulp_serialization_difference_is_accepted(self):
        p=target();e=evidence(p);e['target'][8]=-9.74273202809657e-17
        self.assertNotEqual(e['target'],p)
        r=trials.require_target_binding(e,p,json.dumps(p))
        self.assertEqual(len(r['nonidentical_coefficients']),1);self.assertFalse(r['mechanical_tolerances_changed'])
    def test_above_ulp_limit_is_rejected_even_if_physically_tiny(self):
        p=target();e=evidence(p)
        for _ in range(trials.TARGET_SERIALIZATION_ULPS+1):e['target'][8]=math.nextafter(e['target'][8],math.inf)
        with self.assertRaisesRegex(ValueError,'coefficient_mismatch'):trials.require_target_binding(e,p,json.dumps(p))
    def test_matching_numbers_cannot_substitute_missing_or_wrong_request_hash(self):
        p=target()
        for bad in (None,'0'*64,True):
            e=evidence(p);e['request_target_sha256']=bad
            with self.assertRaisesRegex(ValueError,'fingerprint'):trials.require_target_binding(e,p,json.dumps(p))
    def test_hash_binds_whitespace_as_received_not_reserialized_numbers(self):
        p=target();wire=' \t'+json.dumps(p)+' '
        trials.require_target_binding(evidence(p,wire),p,wire)
        with self.assertRaisesRegex(ValueError,'fingerprint'):trials.require_target_binding(evidence(p),p,wire)
    def test_expected_target_must_match_the_wire(self):
        p=target();wire_target=target();wire_target[9]=.001;wire=json.dumps(wire_target)
        with self.assertRaisesRegex(ValueError,'does_not_match'):trials.require_target_binding(evidence(p,wire),p,wire)
    def test_boolean_nonfinite_invalid_size_and_scaled_target_rejected(self):
        p=target()
        for index,value in ((0,True),(9,float('nan')),(10,float('inf')),(12,2)):
            e=evidence(p);e['target'][index]=value
            with self.assertRaises(ValueError):trials.require_target_binding(e,p,json.dumps(p))
        e=evidence(p);e['target'].pop()
        with self.assertRaises(ValueError):trials.require_target_binding(e,p,json.dumps(p))
        with self.assertRaises(ValueError):trials.require_target_binding(evidence(p),p,'not-json')
    def test_zero_does_not_allow_arbitrary_small_coefficients(self):
        p=target();p[8]=0.;e=evidence(p);e['target'][8]=1e-30
        with self.assertRaisesRegex(ValueError,'coefficient_mismatch'):trials.require_target_binding(e,p,json.dumps(p))
    def test_absolute_translation_cap_cannot_expand_at_large_world_coordinates(self):
        p=target();p[9]=1e9;e=evidence(p);e['target'][9]=math.nextafter(p[9],math.inf)
        with self.assertRaisesRegex(ValueError,'coefficient_mismatch'):trials.require_target_binding(e,p,json.dumps(p))
    def test_mechanical_pose_and_angle_tolerances_unchanged(self):
        self.assertEqual(trials.POSITION_TOLERANCE_M,1e-7)
        self.assertEqual(trials.ANGLE_TOLERANCE_RAD,1e-6)
    def test_valid_wire_binding_does_not_make_a_moving_fixed_body_pass(self):
        from tests.test_assembly_connections import survey
        # Independent physical audit still rejects a moved fixed reference.
        poses={c['component_id']:c['transform'] for c in survey()['components']}
        goal={'kind':'rigid','component_a':'moving','component_b':'body'}
        b=trials.bind(goal,poses);t=trials.trials(goal,poses)[0]
        e=evidence(t['target']);e.update(before=poses,after=copy.deepcopy(poses),restored=poses,
            fixed_states={'body':True,'moving':False},original_mates_parameters_unchanged=True,restoration_status='restored')
        e['after']['body']=trials.target(poses['body'],[1,0,0],.001)
        trials.require_target_binding(e,t['target'],json.dumps(t['target']))
        self.assertFalse(trials.audit(e,[b],0,t,poses)['passed'])


@unittest.skipUnless(os.name=='nt','Real .NET Framework wire fixture requires Windows')
class DotNetWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.binary=Path(cls.temp.name)/'ConnectionTargetWireFixture.exe'
        compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        if not compiler.is_file():raise unittest.SkipTest('Windows .NET Framework compiler unavailable')
        r=subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(cls.binary),
            str(ROOT/'executor/ConnectionRequestFingerprint.cs'),str(ROOT/'tests/ConnectionTargetWireFixture.cs')],
            capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        if r.returncode:raise AssertionError(r.stdout+r.stderr)
    def test_real_native_serializer_and_production_fingerprint_pass_python_binding(self):
        p=target();wire=json.dumps(p)
        r=subprocess.run([str(self.binary)],input=wire.encode(),capture_output=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(r.returncode,0,r.stderr)
        e=json.loads(r.stdout.decode('utf-8-sig'))
        proof=trials.require_target_binding(e,p,wire)
        self.assertTrue(proof['request_sha256_verified'])


if __name__=='__main__':unittest.main()
