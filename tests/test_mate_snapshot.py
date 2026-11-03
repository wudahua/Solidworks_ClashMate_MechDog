"""Actual production collectors vs frozen alpha38 reader, without CAD/COM."""
import json,os,pathlib,subprocess,tempfile,unittest
from sw_mcp.conversation import core
ROOT=pathlib.Path(__file__).resolve().parents[1]

@unittest.skipUnless(os.name=='nt','Requires Windows .NET Framework compiler; no CAD')
class MateSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='cm-mate-snapshot-');cls.addClassCleanup(cls.temp.cleanup)
        folder=core.no_links(pathlib.Path(cls.temp.name));cls.binary=folder/'MateSnapshotReadTests.exe'
        compiler=pathlib.Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        if not compiler.is_file():raise unittest.SkipTest('.NET Framework compiler unavailable')
        args=[str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(cls.binary)]
        args += [str(ROOT/name) for name in ('executor/CadFault.cs','executor/NativeMateSnapshot.cs','executor/LegacyMateSnapshotRead.cs','tests/MateSnapshotReadTests.cs')]
        run=subprocess.run(args,capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        if run.returncode:raise AssertionError((run.stdout+run.stderr).decode('utf-8-sig',errors='replace'))
    def read(self,mode):
        r=subprocess.run([str(self.binary),mode],capture_output=True,timeout=20,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(r.returncode,0,r.stderr.decode('utf-8-sig',errors='replace'))
        return json.loads(r.stdout.decode('utf-8-sig'))
    def test_complete_parameter_schema_and_values_match_legacy_bytes(self):
        v=self.read('parameters');self.assertTrue(v['all_bytes_equal']);rows=v['rows']
        self.assertEqual([r['id'] for r in rows],list(range(1,7)))
        self.assertEqual(set(rows[0]),{'id','type','alignment','lock_rotation','distance_m','angle_rad','component_bindings','suppression'})
        self.assertEqual(rows[0]['component_bindings'],['组件A','组件B']);self.assertEqual(rows[0]['suppression'],[False])
        self.assertIs(rows[1]['lock_rotation'],True);self.assertEqual(rows[2]['distance_m'],.0123);self.assertEqual(rows[3]['angle_rad'],.523)
        self.assertEqual(rows[4]['gear_parameters'],{'numerator':2,'denominator':3,'reverse':True})
    def test_full_reference_identity_bytes_are_not_removed(self):
        v=self.read('identity');self.assertTrue(v['all_bytes_equal']);self.assertEqual(v['rows'][0]['references'],['AQE=','AQI='])
        self.assertEqual(v['new_counts']['persistent_reads'],12)
    def test_identity_without_references_retains_null_field(self):
        v=self.read('identity_without_refs');self.assertTrue(all(r['references'] is None for r in v['rows']));self.assertEqual(v['new_counts']['persistent_reads'],0)
    def test_explicit_discarded_reference_mode_still_validates_references(self):
        v=self.read('discarded_refs');self.assertEqual(v['new_counts']['persistent_reads'],12);self.assertNotIn('references',v['rows'][0])
    def test_empty_inventory_returns_empty_array(self):self.assertEqual(self.read('empty')['rows'],[])
    def test_duplicate_native_feature_id_keeps_first(self):
        v=self.read('duplicate');self.assertEqual(len(v['rows']),6);self.assertEqual(v['rows'][0]['type'],0)
    def test_unknown_native_mate_type_is_retained(self):self.assertEqual(self.read('unknown_type')['rows'][0]['type'],42)
    def test_each_feature_and_type_read_once_and_names_shared_only_inside_snapshot(self):
        v=self.read('parameters');n=v['new_counts'];o=v['old_counts']
        self.assertEqual(n['specific_reads'],6);self.assertEqual(n['type_reads'],6);self.assertEqual(n['component_name_reads'],2)
        self.assertGreater(o['specific_reads'],n['specific_reads']);self.assertGreater(o['type_reads'],n['type_reads']);self.assertEqual(o['component_name_reads'],12)
    def test_names_reread_after_next_call(self):
        v=self.read('changed_names');self.assertTrue(v['changed_since_previous_call']);self.assertEqual(v['rows'][0]['component_bindings'][0],'改名后A')
    def test_distance_reread_after_next_call(self):self.assertEqual(self.read('changed_dimension')['rows'][2]['distance_m'],.0456)
    def test_suppression_reread_after_next_call(self):self.assertEqual(self.read('changed_suppression')['rows'][1]['suppression'],[True])
    def test_gear_ratio_and_direction_reread_after_next_call(self):self.assertEqual(self.read('changed_gear')['rows'][4]['gear_parameters'],{'numerator':7,'denominator':11,'reverse':False})
    def test_native_type_change_is_not_cached(self):
        r=self.read('changed_type')['rows'][0];self.assertEqual(r['type'],5);self.assertEqual(r['distance_m'],.0789)
    def test_unavailable_reference_owner_stays_null(self):self.assertIsNone(self.read('null_owner')['rows'][0]['component_bindings'][0])
    def test_unreadable_dimension_refuses_whole_snapshot(self):self.assertEqual(self.read('missing_dimension')['error']['message'],'MATE_PARAMETER_UNREADABLE')
    def test_null_reference_preserves_typed_refusal(self):
        e=self.read('bad_ref_null')['error'];self.assertEqual(e['code'],'CONNECTION_REFERENCE_INVALID');self.assertFalse(e['details']['reference_object_available'])
    def test_missing_persistent_bytes_preserves_typed_refusal(self):
        e=self.read('bad_ref_persistent')['error'];self.assertTrue(e['details']['reference_object_available']);self.assertFalse(e['details']['signature_complete'])
    def test_empty_persistent_bytes_refused(self):self.assertEqual(self.read('bad_ref_empty')['error']['details']['reason'],'native_mate_reference_identity_unavailable')
    def test_native_getter_failure_not_swallowed(self):self.assertEqual(self.read('name_failure')['error']['message'],'COMPONENT_NAME_READ_FAILED')
    def test_numeric_output_does_not_follow_localized_decimal_separator(self):self.assertEqual(self.read('culture')['rows'][2]['distance_m'],.0123)

if __name__=='__main__':unittest.main()
