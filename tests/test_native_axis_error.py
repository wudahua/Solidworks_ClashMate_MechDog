"""Exercise the production C# error formatter without SDK or CAD activation."""
import json,os,subprocess,unittest,uuid
from pathlib import Path
from transport_cleanup import remove_test_root

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name=='nt','Windows .NET Framework executor formatter')
class NativeAxisErrorTests(unittest.TestCase):
    def test_axis_failure_pointer_and_original_com_hresult_survive_formatting(self):
        compiler=Path(os.environ.get('WINDIR','C:/Windows'))/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
        if not compiler.is_file():self.skipTest('.NET Framework compiler unavailable')
        base=ROOT/'runs/axis-error-tests';folder=base/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
        self.addCleanup(remove_test_root,folder,base)
        source=(ROOT/'executor/Program.cs').read_text('utf-8-sig')
        start=source.index('    static object Error(')
        end=source.index('    [STAThread] static int Main',start)
        method=source[start:end]  # Compile the actual pure formatter, not a copied implementation.
        header='using System;using System.IO;using System.Text;using System.Collections.Generic;using System.Runtime.InteropServices;using System.Text.RegularExpressions;using System.Web.Script.Serialization;\n'
        main='''static void Main(){
 Console.OutputEncoding=new UTF8Encoding(false);
 var error=new COMException("stale native result",unchecked((int)0x80010108));
 error.Data["time_axis_read_failure"]=new Dictionary<string,object>{{"time_axis_file","fixture/time-axis.json"},{"verified",false},{"automatic_recalculate",false},{"stage","native_plot_get_values"}};
 Console.WriteLine(new JavaScriptSerializer().Serialize(new[]{Error(error,"restored"),Error(new Exception("MOTION_RESULTS_INCOMPLETE"),"restored")}));
}'''
        helper=folder/'FormatterCheck.cs';helper.write_text(header+'class FormatterCheck{\n'+method+main+'\n}',encoding='utf-8')
        executable=folder/'FormatterCheck.exe'
        built=subprocess.run([str(compiler),'/nologo','/codepage:65001','/reference:System.Web.Extensions.dll','/out:'+str(executable),str(ROOT/'executor/CadFault.cs'),str(helper)],capture_output=True,timeout=30)
        self.assertEqual(built.returncode,0,(built.stdout+built.stderr).decode('utf-8',errors='replace'))
        run=subprocess.run([str(executable)],capture_output=True,timeout=15)
        self.assertEqual(run.returncode,0,run.stderr.decode('utf-8',errors='replace'))
        com,ordinary=json.loads(run.stdout.decode('utf-8-sig'))
        self.assertEqual(com['code'],'COM_CALL_FAILED')
        self.assertEqual(com['assertion'],'inconclusive')
        self.assertEqual(com['restoration_status'],'restored')
        self.assertEqual(com['diagnostics']['native_hresult'],-2147417848)
        self.assertEqual(com['diagnostics']['hresult_source'],'native_com')
        details=com['diagnostics']['details']['time_axis_read_failure']
        self.assertEqual(details['time_axis_file'],'fixture/time-axis.json')
        self.assertEqual(details['stage'],'native_plot_get_values')
        self.assertFalse(details['verified']);self.assertFalse(details['automatic_recalculate'])
        self.assertEqual(ordinary['code'],'MOTION_RESULTS_INCOMPLETE')
        self.assertIsNone(ordinary['diagnostics']['native_hresult'])
        self.assertIsNone(ordinary['diagnostics']['details']['time_axis_read_failure'])


if __name__=='__main__':unittest.main()
