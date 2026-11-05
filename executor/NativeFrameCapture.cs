using System;
using System.Diagnostics;

// Time selection and its message pumping must run outside our read batch.
// Only the bounded, complete pose read owns CommandInProgress for this frame.
public static class NativeFrameCapture {
    public static T Capture<T>(Action select,Func<T> read,Func<bool> flag,Action<bool> set,
        Func<Exception,bool> defer,Action<NativeCommandBatch> observed,Action<double> guardTiming=null) {
        var timer=Stopwatch.StartNew();bool busy;
        try{busy=flag();}finally{if(guardTiming!=null)guardTiming(timer.Elapsed.TotalMilliseconds);}
        if(busy)throw new NativeCommandStateException(new InvalidOperationException("FRAME_SELECTION_REQUIRES_IDLE_COMMAND_STATE"));
        select();
        var batch=new NativeCommandBatch(flag,set);
        try {
            if(batch.Previous)throw new NativeCommandStateException(new InvalidOperationException("FRAME_SELECTION_LEFT_UNOWNED_COMMAND_STATE"));
            return read();
        }catch(Exception failure){if(defer(failure))batch.Abandon(failure);throw;}
        finally{try{batch.Dispose();}finally{if(observed!=null)observed(batch);}}
    }
}
