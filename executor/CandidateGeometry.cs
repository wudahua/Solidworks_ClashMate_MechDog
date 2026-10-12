using System;
using System.Linq;
using System.Globalization;

public static class CandidateGeometry {
    public static string Key(string component,string kind,double[] direction,double[] point) {
        double length=Math.Sqrt(direction.Sum(v=>v*v));
        if(length<1e-12||direction.Concat(point).Any(v=>double.IsNaN(v)||double.IsInfinity(v)))throw new ArgumentException("Invalid candidate geometry");
        var axis=direction.Select(v=>v/length).ToArray();
        if(axis.First(v=>Math.Abs(v)>1e-10)<0)axis=axis.Select(v=>-v).ToArray();
        double along=axis.Zip(point,(a,b)=>a*b).Sum();
        var position=kind=="cylindrical_axis"?point.Zip(axis,(p,a)=>p-along*a).ToArray():new[]{along};
        return component+"|"+kind+"|"+string.Join(",",axis.Concat(position).Select(v=>Math.Round(v/1e-8,MidpointRounding.AwayFromZero).ToString("0",CultureInfo.InvariantCulture)));
    }
}
