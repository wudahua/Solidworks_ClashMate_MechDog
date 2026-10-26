using System;
using System.Linq;

// Exact decimation of a complete uniform native grid. No interpolation,
// nearest-time rounding, missing-frame filling or looser clock tolerance.
public static class NativeGridSubset {
    public static bool TrySelect(double[] raw,double[] expected,double duration,int requestedFps,int nativeFps,out double[] selected,out int[] indices,out double error) {
        selected=null;indices=null;error=0;
        if(raw==null||expected==null||raw.Length>100001||expected.Length<2||nativeFps<=requestedFps||requestedFps<5||requestedFps>120||nativeFps%requestedFps!=0||
            double.IsNaN(duration)||double.IsInfinity(duration)||duration<=0||Math.Abs(duration*nativeFps-Math.Round(duration*nativeFps))>1e-8||Math.Abs(duration*requestedFps-Math.Round(duration*requestedFps))>1e-8||
            raw.Length!=Math.Round(duration*nativeFps)+1||expected.Length!=Math.Round(duration*requestedFps)+1)return false;
        for(int i=0;i<raw.Length;i++)if(double.IsNaN(raw[i])||double.IsInfinity(raw[i])||Math.Abs(raw[i]-(double)i/nativeFps)>1e-7||(i>0&&raw[i]<=raw[i-1]))return false;
        int stride=nativeFps/requestedFps;indices=new int[expected.Length];selected=new double[expected.Length];
        for(int i=0;i<expected.Length;i++) {
            int index=i*stride;
            if(double.IsNaN(expected[i])||double.IsInfinity(expected[i])||Math.Abs(expected[i]-(double)i/requestedFps)>1e-7||index>=raw.Length){selected=null;indices=null;return false;}
            double delta=Math.Abs(raw[index]-expected[i]);if(delta>1e-7){selected=null;indices=null;return false;}
            error=Math.Max(error,delta);indices[i]=index;selected[i]=raw[index];
        }
        return true;
    }
}
