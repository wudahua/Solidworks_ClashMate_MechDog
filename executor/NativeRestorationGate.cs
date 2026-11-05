using System;
using System.Runtime.InteropServices;

// A returned communication/type/context failure does not prove that another
// native restore or application-state setter is safe. Preserve the checkpoint.
public sealed class NativeRestorationGate {
    public bool Deferred {get;private set;}
    public bool Defer(Exception failure) {
        for(var e=failure;e!=null;e=e.InnerException) {
            if(e is COMException||e is ComponentInventoryReadFault||e is NativeCommandStateException||
                (e.Message??"").StartsWith("SESSION_CONFLICT",StringComparison.Ordinal))Deferred=true;
        }
        return Deferred;
    }
    public bool Restore(Action restore) {
        if(Deferred)return false;
        try{restore();return true;}catch{StopAfterRestoreFailure();throw;}
    }
    public void StopAfterRestoreFailure(){Deferred=true;}
}
