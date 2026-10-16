"""Existing-cache budgets and movement retry policy; no CAD or process enumeration."""
import json, os, subprocess, uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    folder=ROOT/'runs/alpha9-policy'/uuid.uuid4().hex[:8];folder.mkdir(parents=True)
    source=folder/'Checks.cs'
    source.write_text(r'''using System;using System.Linq;using System.Collections.Generic;using System.Web.Script.Serialization;
class Checks {
 static int n;static void Check(bool x){n++;if(!x)throw new Exception("check "+n);}
 static Dictionary<string,object> D(object o){var j=new JavaScriptSerializer();return j.Deserialize<Dictionary<string,object>>(j.Serialize(o));}
 static double[] P(double x=0,double t=0){double c=Math.Cos(t),s=Math.Sin(t);return new[]{c,s,0,-s,c,0,0,0,1,x,0,0,1,0,0,0};}
 static int Main(){
 foreach(var fps in new[]{25,120,300,1000})Check(StudyCacheBudget.Allows(1,fps));
 Check(StudyCacheBudget.Allows(5,300));Check(StudyCacheBudget.Allows(6,300));Check(!StudyCacheBudget.Allows(6.001,300));Check(!StudyCacheBudget.Allows(5,1000));
 foreach(var duration in new[]{double.NaN,double.PositiveInfinity,0,-1,30.001})Check(!StudyCacheBudget.Allows(duration,30));
 Check(!StudyCacheBudget.Allows(1,0));Check(!StudyCacheBudget.Allows(1,1001));Check(StudyCacheBudget.Allows(30,60));
 Check(!(bool)D(StudyCacheBudget.Describe(30,300))["recalculation_with_original_settings_allowed"]);
 Check(D(StudyCacheBudget.ResetGuidance("inactive",30,300,4,false))["arguments"]==null);Check(D(StudyCacheBudget.ResetGuidance("animation",30,300,1,true))["arguments"]==null);
 Check(!(bool)D(D(StudyCacheBudget.ResetGuidance("cached",30,300,4,true))["arguments"])["allow_recalculate"]);Check((bool)D(D(StudyCacheBudget.ResetGuidance("highfps",5,300,4,false))["arguments"])["allow_recalculate"]);
 var before=new Dictionary<string,double[]>{{"fixed",P()},{"a",P()},{"b",P()}};var after=new Dictionary<string,double[]>{{"fixed",P()},{"a",P(.02,Math.PI)},{"b",P(.0001,.001)}};
 var strict=MatePosePolicy.Evaluate(before,after,1,1);var explicitBudget=MatePosePolicy.Evaluate(before,after,25,180);
 Check(!(bool)strict["accepted"]);Check((bool)explicitBudget["accepted"]);Check((int)strict["changed_component_count"]==2&&(int)explicitBudget["changed_component_count"]==2);Check((int)strict["exceeded_component_count"]==1&&(int)explicitBudget["exceeded_component_count"]==0);
 var guidance=D(MatePosePolicy.RepreviewGuidance("MATE_POSE_CHANGE_EXCEEDS_CONFIRMED_BUDGET",strict));Check((bool)guidance["re_preview_with_explicit_budget_allowed"]);Check((string)guidance["failure_category"]=="confirmed_movement_budget_exceeded");Check(!(bool)guidance["automatic_budget_expansion"]);
 Check(!(bool)D(MatePosePolicy.RepreviewGuidance("MATE_REBUILD_FAILED",strict))["re_preview_with_explicit_budget_allowed"]);
 strict["component_scope_verified"]=false;Check(!(bool)D(MatePosePolicy.RepreviewGuidance("MATE_POSE_CHANGE_EXCEEDS_CONFIRMED_BUDGET",strict))["re_preview_with_explicit_budget_allowed"]);
 Check(!(bool)D(MatePosePolicy.RepreviewGuidance("MATE_POSE_CHANGE_EXCEEDS_CONFIRMED_BUDGET",null))["re_preview_with_explicit_budget_allowed"]);
 Console.WriteLine(n);return 0;}}
''',encoding='utf-8',newline='\n')
    exe=folder/'Checks.exe';compiler=Path(os.environ['WINDIR'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler),'/nologo','/reference:System.Web.Extensions.dll','/out:'+str(exe)]+[str(ROOT/'executor'/n) for n in ['CadFault.cs','PoseValidation.cs','MatePosePolicy.cs','StudyCacheBudget.cs']]+[str(source)],check=True)
    count=int(subprocess.check_output([str(exe)],text=True).strip());result={'all_passed':True,'checks':count,'cad_connection_used':False}
    (folder/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
if __name__=='__main__':main()
