using System;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;

public static class DeferredNativeCommandStateTests {
    public static void Main(string[] args) {
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        string mode=args[0],error=null;var state=new DeferredNativeCommandState();
        int reads=0,writes=0,validated=0,notifications=0;bool flag=true,prepared=false;
        if(mode!="empty")state.Remember("model-a",mode=="not_owned");
        if(mode=="conflict")state.Remember("model-b",false);
        if(mode=="already_false")flag=false;
        try {
            prepared=state.PrepareRestore(mode=="wrong_model"?"model-b":"model-a",
                ()=>{validated++;if(mode=="foreign_documents")throw new InvalidOperationException("foreign");},
                ()=>{reads++;if(mode=="read_failure")throw new COMException("controlled");return flag;},
                v=>{writes++;if(mode=="write_failure")throw new COMException("controlled");if(mode!="bad_readback")flag=v;});
            if(mode=="complete"||mode=="changed_during_restore") {
                if(mode=="changed_during_restore")flag=true;
                state.CompleteRestore("model-a",()=>{reads++;return flag;});
            }
        }catch(Exception failure){error=failure.GetType().Name;}
        if(mode=="batch_notification"||mode=="nested_notification"||mode=="constructor_notification"||mode=="restore_notification") {
            state=new DeferredNativeCommandState();reads=writes=validated=0;flag=false;
            NativeCommandBatch.FailureObserver=(failure,previous)=>{notifications++;state.Remember("model-a",previous);};
            try {
                var batch=new NativeCommandBatch(()=>{reads++;return flag;},v=>{writes++;flag=v;if(mode=="constructor_notification"||mode=="restore_notification"&&!v)throw new COMException("controlled");});
                if(mode=="nested_notification") {var inner=new NativeCommandBatch(()=>{reads++;return flag;},v=>{writes++;flag=v;});inner.Abandon();inner.Dispose();}
                if(mode=="restore_notification")batch.Dispose();else{batch.Abandon();batch.Dispose();}
            }catch(Exception failure){error=failure.GetType().Name;}
            finally{NativeCommandBatch.FailureObserver=null;}
        }
        Console.WriteLine(new JavaScriptSerializer().Serialize(new{prepared=prepared,pending=state.Pending,reads=reads,writes=writes,validated=validated,flag=flag,error=error,notifications=notifications}));
    }
}
