using System;
using System.Runtime.InteropServices;

// Reacquire a stale READ reference once. No activation, time selection,
// calculation, document open or other write belongs in these delegates.
public static class MotionReferenceRead {
    public static T Read<T>(Func<T> freshRead,Action verifyIdentity,Action<object> observe) {
        try{return freshRead();}
        catch(COMException original) {
            if(original.HResult!=unchecked((int)0x80010108))throw;
            try{observe(new{stage="read_reference_disconnected",native_hresult=original.HResult,additional_native_writes=0,maximum_read_attempts=2});}
            catch(Exception audit){original.Data["read_reference_audit_error"]=audit.GetType().FullName;throw original;}
            verifyIdentity();
            try{T value=freshRead();observe(new{stage="fresh_same_identity_read_completed",additional_native_writes=0,read_attempts=2});return value;}
            catch(Exception failure){failure.Data["first_read_native_hresult"]=original.HResult;throw;}
        }
    }
}
