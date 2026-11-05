using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;

public static class NativeFrameCaptureTests {
    public static void Main(string[] args) {
        string mode=args[0],error=null;bool flag=mode=="foreign_entry";
        int reads=0,writes=0,selections=0,poses=0,notifications=0,observations=0;var events=new List<string>();
        NativeCommandBatch.FailureObserver=(e,p)=>notifications++;
        try {
            for(int i=0;i<(mode=="two_frames"?2:1);i++) {
                NativeFrameCapture.Capture(
                    ()=>{selections++;events.Add("select:"+flag);if(mode=="select_com")throw new COMException("controlled");if(mode=="foreign_after_selection")flag=true;},
                    ()=>{poses++;events.Add("read:"+flag);if(!flag)throw new Exception("READ_NOT_BATCHED");if(mode=="read_com")throw new COMException("controlled");if(mode=="read_known")throw new InvalidOperationException("controlled");return poses;},
                    ()=>{reads++;return flag;},
                    v=>{writes++;events.Add("write:"+v);if(mode=="enter_com"&&v||mode=="restore_com"&&!v)throw new COMException("controlled");flag=v;},
                    e=>e is COMException||e is NativeCommandStateException,
                    b=>{observations++;events.Add("observed:"+flag);});
            }
        }catch(Exception failure){error=failure.GetType().Name;}
        finally{NativeCommandBatch.FailureObserver=null;}
        Console.WriteLine(new JavaScriptSerializer().Serialize(new{flag=flag,reads=reads,writes=writes,selections=selections,poses=poses,
            notifications=notifications,observations=observations,error=error,events=events}));
    }
}
