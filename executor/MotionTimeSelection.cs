using System;

public static class MotionTimeSelection {
    public static double Argument(double time,double duration){
        // Native last-frame times can be one floating-point step below duration.
        // The internal-frame epsilon must never push that endpoint past the study.
        double endpointRoundoff=Math.Max(1e-12,Math.Abs(duration)*1e-12);
        if(Math.Abs(time)<=endpointRoundoff)return 0;
        if(Math.Abs(time-duration)<=endpointRoundoff)return duration;
        return time>0&&time<duration?Math.Min(duration,time+1e-8):time;
    }
}
