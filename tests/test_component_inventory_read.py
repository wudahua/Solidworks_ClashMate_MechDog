"""Bounded full-inventory reacquisition; never retries native failures or accepts a partial set."""
import json,os,pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
@unittest.skipUnless(os.name=='nt','Windows compiler required')
class ComponentReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup);cls.exe=pathlib.Path(cls.temp.name)/'inventory.exe'
        compiler=pathlib.Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        r=subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(cls.exe),*[str(ROOT/n) for n in ('executor/CadFault.cs','executor/ComponentInventoryRead.cs','tests/ComponentInventoryReadTests.cs')]],capture_output=True,timeout=30)
        if r.returncode:raise AssertionError((r.stdout+r.stderr).decode(errors='replace'))
    def read(self,mode):
        r=subprocess.run([str(self.exe),mode],capture_output=True,timeout=10);self.assertEqual(r.returncode,0,r.stderr);return json.loads(r.stdout)
    def test_valid_set_is_read_once_preserving_order_and_exact_objects(self):
        r=self.read('valid');self.assertTrue(r['ok']);self.assertEqual(r['rows'],[2,1]);self.assertTrue(r['same_original_instances']);self.assertEqual(r['calls'],1);self.assertEqual(r['pauses'],0)
    def test_one_bad_interface_reacquires_whole_set(self):
        r=self.read('recover_once');self.assertTrue(r['ok']);self.assertEqual(r['calls'],2);self.assertEqual(r['rows'],[2,1])
    def test_third_read_can_recover_but_never_exceeds_three(self):
        r=self.read('recover_twice');self.assertTrue(r['ok']);self.assertEqual(r['calls'],3);self.assertEqual(r['pauses'],2)
    def test_persistent_bad_interface_is_structured_failure_no_partial_rows(self):
        r=self.read('always_bad');self.assertFalse(r['ok']);self.assertEqual(r['code'],'API_TYPE_MISMATCH');self.assertEqual(r['calls'],3);self.assertNotIn('rows',r)
        self.assertFalse(r['details']['components_skipped']);self.assertFalse(r['details']['native_write_replayed']);self.assertFalse(r['details']['partial_inventory_returned'])
    def test_changed_count_refuses_instead_of_silently_dropping_component(self):
        r=self.read('count_change');self.assertFalse(r['ok']);self.assertEqual(r['details']['reason'],'component_count_changed');self.assertEqual(r['calls'],2)
    def test_changed_document_or_configuration_is_never_retried(self):
        r=self.read('context_change');self.assertFalse(r['ok']);self.assertEqual(r['details']['reason'],'document_context_changed')
    def test_native_com_failure_is_not_retried(self):
        r=self.read('com_error');self.assertEqual(r['type'],'COMException');self.assertEqual(r['calls'],1);self.assertEqual(r['pauses'],0)
    def test_array_getter_failure_is_not_a_bad_element_retry(self):
        r=self.read('fetch_invalidcast');self.assertEqual(r['type'],'InvalidCastException');self.assertEqual(r['calls'],1)
    def test_null_collection_is_not_replaced_by_empty(self):
        r=self.read('missing');self.assertFalse(r['ok']);self.assertEqual(r['details']['reason'],'native_collection_missing');self.assertEqual(r['calls'],1)
    def test_null_element_is_never_omitted(self):self.assertFalse(self.read('null_entry')['ok'])
    def test_real_empty_collection_remains_empty(self):self.assertEqual(self.read('empty')['rows'],[])
if __name__=='__main__':unittest.main()
