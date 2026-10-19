using System;
using System.Diagnostics;
using System.Collections.Generic;

// ISldWorks.CommandInProgress is the documented out-of-process API batch mode.
// Preserve the prior flag, including true; this owns no application lifecycle.
public sealed class NativeCommandStateException : Exception {
    public NativeCommandStateException(Exception inner):base("COMMAND_STATE_RESTORE_FAILED",inner){}
}
public sealed class NativeCommandBatch : IDisposable {
    readonly Func<bool> read;readonly Action<bool> write;readonly bool previous;bool changed,disposed;
    readonly Stopwatch clock=Stopwatch.StartNew();
    readonly DateTime started=DateTime.UtcNow;
    DateTime? entered,finished;
    double enterMs,restoreMs,readPreviousMs,enableWriteMs,enableReadbackMs,restoreWriteMs,restoreReadbackMs;
    bool restored;
    public bool Previous {get{return previous;}}
    public NativeCommandBatch(Func<bool> getter,Action<bool> setter){
        read=getter;write=setter;var step=Stopwatch.StartNew();previous=read();readPreviousMs=step.Elapsed.TotalMilliseconds;
        if(!previous){changed=true;try{step.Restart();write(true);enableWriteMs=step.Elapsed.TotalMilliseconds;step.Restart();bool accepted=read();enableReadbackMs=step.Elapsed.TotalMilliseconds;if(!accepted)throw new InvalidOperationException("COMMAND_BATCH_NOT_ACCEPTED");}catch{Restore();throw;}}
        enterMs=clock.Elapsed.TotalMilliseconds;entered=DateTime.UtcNow;
    }
    void Restore(){if(!changed){restored=true;return;}try{var step=Stopwatch.StartNew();write(previous);restoreWriteMs=step.Elapsed.TotalMilliseconds;step.Restart();bool current=read();restoreReadbackMs=step.Elapsed.TotalMilliseconds;if(current!=previous)throw new InvalidOperationException("COMMAND_FLAG_READBACK_MISMATCH");changed=false;restored=true;}catch(Exception e){throw new NativeCommandStateException(e);}}
    public void Dispose(){if(disposed)return;disposed=true;var step=Stopwatch.StartNew();try{Restore();}finally{restoreMs=step.Elapsed.TotalMilliseconds;finished=DateTime.UtcNow;}}
    public object Export(){return new{scope="local_native_command_batch_enter_and_restore_not_work_body",previous=previous,restored=restored,disposed=disposed,entered_at_utc=entered.HasValue?entered.Value.ToString("o",System.Globalization.CultureInfo.InvariantCulture):null,started_at_utc=started.ToString("o",System.Globalization.CultureInfo.InvariantCulture),finished_at_utc=finished.HasValue?finished.Value.ToString("o",System.Globalization.CultureInfo.InvariantCulture):null,enter_elapsed_ms=enterMs,restore_elapsed_ms=restoreMs,read_previous_ms=readPreviousMs,enable_write_ms=enableWriteMs,enable_readback_ms=enableReadbackMs,restore_write_ms=restoreWriteMs,restore_readback_ms=restoreReadbackMs,subtiming_relation="children_of_enter_or_restore_do_not_sum_again",cross_request_state_cache=false};}
}
