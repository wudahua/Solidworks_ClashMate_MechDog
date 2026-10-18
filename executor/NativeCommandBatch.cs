using System;

// ISldWorks.CommandInProgress is the documented out-of-process API batch mode.
// Preserve the prior flag, including true; this owns no application lifecycle.
public sealed class NativeCommandStateException : Exception {
    public NativeCommandStateException(Exception inner):base("COMMAND_STATE_RESTORE_FAILED",inner){}
}
public sealed class NativeCommandBatch : IDisposable {
    readonly Func<bool> read;readonly Action<bool> write;readonly bool previous;bool changed,disposed;
    public bool Previous {get{return previous;}}
    public NativeCommandBatch(Func<bool> getter,Action<bool> setter){
        read=getter;write=setter;previous=read();
        if(!previous){changed=true;try{write(true);if(!read())throw new InvalidOperationException("COMMAND_BATCH_NOT_ACCEPTED");}catch{Restore();throw;}}
    }
    void Restore(){if(!changed)return;try{write(previous);if(read()!=previous)throw new InvalidOperationException("COMMAND_FLAG_READBACK_MISMATCH");changed=false;}catch(Exception e){throw new NativeCommandStateException(e);}}
    public void Dispose(){if(disposed)return;disposed=true;Restore();}
}
