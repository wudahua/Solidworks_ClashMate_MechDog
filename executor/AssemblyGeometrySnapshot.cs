using System;
using System.Collections.Generic;
using System.Linq;

// Compact analytic-face observations only; no persistent reference registration.
public sealed class AssemblyGeometrySnapshot {
    public const int MaximumRows=20000;
    public readonly List<object> Rows=new List<object>();
    public int Omitted,Invalid;
    public bool HasCapacity {get{return Rows.Count<MaximumRows;}}
    public bool Complete {get{return Omitted==0&&Invalid==0;}}
    static bool Finite(double v){return !Double.IsNaN(v)&&!Double.IsInfinity(v);}
    static double[] Apply(double[] pose,double[] v,bool point){return Enumerable.Range(0,3).Select(j=>Enumerable.Range(0,3).Sum(i=>v[i]*pose[i*3+j])+(point?pose[9+j]:0)).ToArray();}
    public void Skip(int count){Omitted+=count;}
    public void Add(string component,string instance,string owner,bool cylinder,int index,double[] data,double[] pose,double area) {
        if(!HasCapacity){Omitted++;return;}
        if(data==null||data.Length<(cylinder?7:6)||pose==null||pose.Length<12||data.Any(v=>!Finite(v))||pose.Any(v=>!Finite(v))||!Finite(area)||area<0||cylinder&&data[6]<=0){Invalid++;return;}
        if(pose.Length>12&&Math.Abs(pose[12]-1)>1e-8){Invalid++;return;}
        for(int i=0;i<3;i++)for(int j=0;j<3;j++)if(Math.Abs(Enumerable.Range(0,3).Sum(k=>pose[3*i+k]*pose[3*j+k])-(i==j?1:0))>1e-6){Invalid++;return;}
        double determinant=pose[0]*(pose[4]*pose[8]-pose[5]*pose[7])-pose[1]*(pose[3]*pose[8]-pose[5]*pose[6])+pose[2]*(pose[3]*pose[7]-pose[4]*pose[6]);
        if(Math.Abs(determinant-1)>1e-6){Invalid++;return;}
        var axis=Apply(pose,cylinder?data.Skip(3).Take(3).ToArray():data.Take(3).ToArray(),false);
        double norm=Math.Sqrt(axis.Sum(x=>x*x));if(norm<1e-12){Invalid++;return;}
        Rows.Add(new{component_id=component,instance=instance,reference_owner_instance=owner,
            kind=cylinder?"cylindrical_axis":"planar_normal",reference_kind=cylinder?"cylindrical_face":"planar_face",
            reference_index=index,axis_global=axis.Select(v=>v/norm).ToArray(),
            reference_point_global_m=Apply(pose,cylinder?data.Take(3).ToArray():data.Skip(3).Take(3).ToArray(),true),
            cylinder_radius_m=cylinder?(double?)data[6]:null,area_m2=area,
            registration_status="observation_only_not_native_write_reference"});
    }
}
