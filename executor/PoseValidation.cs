using System;
using System.Linq;

public static class PoseValidation {
    public const double TranslationToleranceM=1e-7;
    public const double RotationToleranceRad=1e-6;
    public static double TranslationDistance(double[] a,double[] b) {
        return Math.Sqrt(Enumerable.Range(9,3).Sum(i=>Math.Pow(a[i]-b[i],2)));
    }
    public static double RotationDistance(double[] a,double[] b) {
        // For rigid rotations ||R1-R2||F = 2*sqrt(2)*sin(angle/2).
        // This avoids acos(trace) losing precision for near-identical rotations.
        return 2*Math.Asin(Math.Min(1,Math.Sqrt(Enumerable.Range(0,9).Sum(i=>Math.Pow(a[i]-b[i],2))/8)));
    }
    public static bool Matches(double[] a,double[] b) {
        if(a==null||b==null||a.Length<12||b.Length<12||a.Concat(b).Any(v=>double.IsNaN(v)||double.IsInfinity(v)))return false;
        return TranslationDistance(a,b)<=TranslationToleranceM&&RotationDistance(a,b)<=RotationToleranceRad;
    }
}
