using System;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;

public static class NativeRestorationGateTests {
    public static void Main(string[] args) {
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        string mode=args[0];var gate=new NativeRestorationGate();int calls=0;bool nativeFlag=false;int reads=0,writes=0;
        Exception failure=mode=="com"?new COMException("controlled",unchecked((int)0x80010100)):
            mode=="nested_com"?new InvalidOperationException("wrapper",new COMException("controlled")):
            mode=="inventory"?new ComponentInventoryReadFault(new{controlled=true}):
            mode=="command"?new NativeCommandStateException(new Exception("controlled")):
            mode=="context"?new Exception("SESSION_CONFLICT: changed document"):
            new Exception("REBUILD_FAILED");
        if(mode=="constructor_com_write"||mode=="constructor_com_readback") {
            string type=null;
            try {new NativeCommandBatch(()=>{reads++;if(mode=="constructor_com_readback"&&reads==2)throw new COMException("controlled");return nativeFlag;},v=>{writes++;if(mode=="constructor_com_write")throw new COMException("controlled");nativeFlag=v;});}
            catch(Exception error){type=error.GetType().Name;}
            Console.WriteLine(new JavaScriptSerializer().Serialize(new{type=type,reads=reads,writes=writes}));return;
        }
        if(mode=="restore_com"||mode=="restore_known_error") {
            string type=null;
            try{gate.Restore(()=>{calls++;if(mode=="restore_com")throw new COMException("controlled");throw new InvalidOperationException("known");});}
            catch(Exception error){type=error.GetType().Name;}
            bool subsequent=gate.Restore(()=>calls++);
            Console.WriteLine(new JavaScriptSerializer().Serialize(new{type=type,deferred=gate.Deferred,calls=calls,subsequent_callback_ran=subsequent}));return;
        }
        if(mode=="batch"||mode=="nested_batch") {
            var outer=new NativeCommandBatch(()=>{reads++;return nativeFlag;},v=>{writes++;nativeFlag=v;});
            NativeCommandBatch inner=mode=="nested_batch"?new NativeCommandBatch(()=>{reads++;return nativeFlag;},v=>{writes++;nativeFlag=v;}):null;
            int beforeReads=reads,beforeWrites=writes;
            if(inner!=null){inner.Abandon();inner.Dispose();}
            outer.Abandon();outer.Dispose();outer.Dispose();
            Console.WriteLine(new JavaScriptSerializer().Serialize(new{unchanged_callbacks=reads==beforeReads&&writes==beforeWrites,reads=reads,writes=writes,flag=nativeFlag,outer=outer.Export(),inner=inner==null?null:inner.Export()}));return;
        }
        gate.Defer(failure);bool restored=gate.Restore(()=>calls++);
        if(mode=="sticky"){gate.Defer(new COMException("controlled"));gate.Defer(new Exception("REBUILD_FAILED"));restored=gate.Restore(()=>calls++);}
        Console.WriteLine(new JavaScriptSerializer().Serialize(new{deferred=gate.Deferred,restore_callback_ran=restored,calls=calls}));
    }
}
