using System;
using System.Linq;
using System.Collections.Generic;
using System.Web.Script.Serialization;

// Pure admission/readback guard. This class never accesses CAD or authorizes a write.
public sealed class InitialTranslationGuard {
    public readonly Dictionary<string,double[]> Before=new Dictionary<string,double[]>(),After=new Dictionary<string,double[]>();
    public readonly Dictionary<string,bool> Fixed=new Dictionary<string,bool>();
    public double Budget,Maximum;public bool RequiresConfirmation;
    static double Number(object x) {
        if(x is bool||!(x is double||x is int||x is long||x is decimal))throw new ArgumentException("initial_translation_number_invalid");
        double d=Convert.ToDouble(x);if(double.IsNaN(d)||double.IsInfinity(d))throw new ArgumentException("initial_translation_number_invalid");return d;
    }
    static double[] Array(object value,int count) {
        var a=value as System.Collections.IEnumerable;if(a==null||value is string)throw new ArgumentException("initial_translation_array_invalid");
        var list=new List<double>();foreach(object x in a)list.Add(Number(x));
        if(list.Count!=count)throw new ArgumentException("initial_translation_array_invalid");return list.ToArray();
    }
    static bool Same(double[] a,double[] b,double translationTolerance) {
        return a!=null&&b!=null&&a.Length==16&&b.Length==16&&Enumerable.Range(0,16).All(i=>Math.Abs(a[i]-b[i])<=(i>=9&&i<12?translationTolerance:1e-12));
    }
    public static InitialTranslationGuard Read(string json,Dictionary<string,double[]> current,Dictionary<string,bool> flags,Dictionary<string,string> names) {
        var serializer=new JavaScriptSerializer();serializer.MaxJsonLength=int.MaxValue;
        var data=serializer.Deserialize<Dictionary<string,object>>(json);var result=new InitialTranslationGuard();
        if((string)data["mode"]!="explicit_zero_mate_translation_only"||Number(data["maximum_rotation_rad"])!=0||
            !(data["native_pose_verified"] is bool)|| (bool)data["native_pose_verified"]||
            !(data["coaxial_tolerance_relaxed"] is bool)||(bool)data["coaxial_tolerance_relaxed"])
            throw new ArgumentException("initial_translation_prediction_invalid");
        result.Budget=Number(data["translation_budget_m"]);
        if(result.Budget<=0||result.Budget>1e-5)throw new ArgumentException("initial_translation_budget_invalid");
        var entries=serializer.Deserialize<List<Dictionary<string,object>>>(serializer.Serialize(data["entries"]));
        if(entries.Count<1||entries.Count>128||current.Count!=entries.Count||flags.Count!=current.Count||names.Count!=current.Count||!flags.Values.Any(v=>v))throw new ArgumentException("initial_translation_inventory_invalid");
        foreach(var entry in entries) {
            string cid=(string)entry["component_id"];double[] before=Array(entry["before"],16),after=Array(entry["after"],16),delta=Array(entry["delta_m"],3);
            if(!current.ContainsKey(cid)||!flags.ContainsKey(cid)||!names.ContainsKey(cid)||names[cid]!=(string)entry["instance"]||result.Before.ContainsKey(cid)||
                !(entry["fixed"] is bool)||(bool)entry["fixed"]!=flags[cid]||!Same(before,current[cid],1e-12))throw new ArgumentException("initial_translation_before_state_mismatch");
            // No rotation, scale, shear or fixed-state changes, including tiny ones.
            for(int i=0;i<16;i++)if(i<9||i>=12)if(after[i]!=before[i])throw new ArgumentException("initial_translation_rotation_or_scale_changed");
            for(int i=0;i<3;i++)if(Math.Abs((after[9+i]-before[9+i])-delta[i])>1e-12||flags[cid]&&(delta[i]!=0||after[9+i]!=before[9+i]))throw new ArgumentException("initial_translation_delta_or_fixed_mismatch");
            double distance=Math.Sqrt(delta.Sum(x=>x*x));if(distance>result.Budget)throw new ArgumentException("initial_translation_budget_exceeded");
            result.Maximum=Math.Max(result.Maximum,distance);result.Before.Add(cid,before);result.After.Add(cid,after);result.Fixed.Add(cid,flags[cid]);
        }
        result.RequiresConfirmation=result.Maximum>0;
        if(!(data["requires_alignment_confirmation"] is bool)||(bool)data["requires_alignment_confirmation"]!=result.RequiresConfirmation||Math.Abs(Number(data["maximum_translation_m"])-result.Maximum)>1e-12)
            throw new ArgumentException("initial_translation_summary_mismatch");
        return result;
    }
    public void RequireAfter(Dictionary<string,double[]> actual,Dictionary<string,bool> flags) {
        if(actual.Count!=After.Count||flags.Count!=Fixed.Count||After.Any(p=>!actual.ContainsKey(p.Key)||!Same(p.Value,actual[p.Key],1e-9))||Fixed.Any(p=>!flags.ContainsKey(p.Key)||p.Value!=flags[p.Key]))
            throw new ArgumentException("initial_translation_native_readback_mismatch");
        foreach(var p in actual) {
            double distance=Math.Sqrt(Enumerable.Range(9,3).Sum(i=>(p.Value[i]-Before[p.Key][i])*(p.Value[i]-Before[p.Key][i])));
            if(distance>Budget||Fixed[p.Key]&&distance>1e-12)throw new ArgumentException("initial_translation_native_budget_or_fixed_mismatch");
        }
    }
}
