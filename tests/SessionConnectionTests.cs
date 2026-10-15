using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
#if NATIVE_SESSION_TESTS
using SolidWorks.Interop.sldworks;
#endif

class SessionConnectionTests {
    class Fake {public int pid; public string revision="34.0.0";}
    static int checks;
    static int lookups;
    static Fake Active(){lookups++;return new Fake{pid=22};}
    static void Check(bool ok,string name){if(!ok)throw new Exception(name);checks++;}
    static Fake Connect(string pid,Dictionary<int,Func<Fake>> entries,ConnectionDiagnostics info){
        return SessionConnector.Connect(pid,entries,Active,s=>s.pid,s=>s.revision,info);
    }
    static void Reject(Action action,string code){try{action();}catch(CadFault e){Check(e.Code==code,code);return;}throw new Exception("Expected "+code);}
    static Dictionary<int,Func<Fake>> Empty(){return new Dictionary<int,Func<Fake>>();}
    [STAThread] static int Main(string[] args){try{Run(args);return 0;}catch(Exception e){Console.Error.WriteLine(e.ToString());return 1;}}
    static void Run(string[] args){
#if !NATIVE_SESSION_TESTS
        if(args.Length!=0)throw new ArgumentException("Native flags require an explicitly compiled native probe");
#endif
#if NATIVE_SESSION_TESTS
        if(args.Length==2 && args[0]=="--close-owned") {
            System.Environment.SetEnvironmentVariable("SW_MCP_PROCESS_ID",args[1]);
            ConnectionDiagnostics connection;var owned=SolidWorksConnection.Connect(out connection);
            if(owned.GetProcessID()!=int.Parse(args[1]))throw new Exception("OWNED_PID_MISMATCH");
            if((owned.GetDocuments() as object[]??new object[0]).Length!=0)throw new Exception("OPEN_DOCUMENT_REFUSE_EXIT");
            owned.ExitApp(); Console.WriteLine("OWNED_EMPTY_TEST_INSTANCE_EXIT_REQUESTED");return;
        }
        #endif
        var info=new ConnectionDiagnostics();
        var entries=Empty(); entries[22]=()=>new Fake{pid=22};
        Check(Connect("22",entries,info).pid==22 && info.connection_source=="pid_moniker" && lookups==0,"PID preferred");
        info=new ConnectionDiagnostics(); Check(Connect(null,entries,info).pid==22 && lookups==0,"single PID automatic");
        entries[33]=()=>new Fake{pid=33};
        Reject(()=>Connect(null,entries,new ConnectionDiagnostics()),"AMBIGUOUS_COM_SESSION"); Check(lookups==0,"ambiguous cannot fallback");
        Reject(()=>Connect(null,Empty(),new ConnectionDiagnostics()),"COM_SESSION_NOT_FOUND"); Check(lookups==0,"no PID cannot use generic object");
        foreach(string value in new[]{"0","-1","no","2147483648"}) Reject(()=>Connect(value,Empty(),new ConnectionDiagnostics()),"INVALID_SOLIDWORKS_PID");
        info=new ConnectionDiagnostics();Check(Connect("22",Empty(),info).pid==22 && info.actual_pid==22 && info.configured_pid==22 && info.connection_source=="GetActiveObject_fallback","strict fallback");
        info=new ConnectionDiagnostics();Reject(()=>Connect("33",Empty(),info),"COM_SESSION_ID_MISMATCH");Check(info.actual_pid==22,"wrong identity recorded");
        info=new ConnectionDiagnostics();
        Reject(()=>SessionConnector.Connect<Fake>("22",Empty(),()=>{throw new COMException("no active object",unchecked((int)0x800401E3));},s=>s.pid,s=>s.revision,info),"COM_SESSION_UNAVAILABLE");
        Check(info.native_hresult==unchecked((int)0x800401E3) && info.connection_source=="GetActiveObject_fallback","generic lookup unavailable is diagnostic, not permission to launch");
        int before=lookups;entries=Empty();entries[22]=()=>new Fake{pid=44};
        Reject(()=>Connect("22",entries,new ConnectionDiagnostics()),"COM_SESSION_ID_MISMATCH");Check(lookups==before,"bad registered identity cannot fallback");
        entries[22]=()=>null;Reject(()=>Connect("22",entries,new ConnectionDiagnostics()),"COM_SESSION_UNAVAILABLE");Check(lookups==before,"bad interface cannot fallback");
        entries[22]=()=>{throw new COMException("denied",unchecked((int)0x80070005));};info=new ConnectionDiagnostics();
        Reject(()=>Connect("22",entries,info),"COM_SESSION_UNAVAILABLE");Check(lookups==before && info.native_hresult==unchecked((int)0x80070005),"COM HRESULT retained, no bypass");
        entries[22]=()=>new Fake{pid=22,revision=""};Reject(()=>Connect("22",entries,new ConnectionDiagnostics()),"COM_SESSION_UNAVAILABLE");
        var many=Empty();for(int i=1;i<=100;i++){int pid=i;many[i]=()=>new Fake{pid=pid};}
        info=new ConnectionDiagnostics();Reject(()=>Connect(null,many,info),"AMBIGUOUS_COM_SESSION");Check(info.available_pids.Length==32 && info.available_pids_truncated,"diagnostics bounded");
        var inventory=new SessionInventory();inventory.Identities[22]="start-A";int scans=0;
        var auto=SessionConnector.Connect("auto",Empty(),Active,v=>v.pid,v=>v.revision,new ConnectionDiagnostics(),()=>{scans++;return inventory;});Check(auto.pid==22&&scans==2,"auto unique missing ROT verified twice");
        inventory.Identities[33]="start-B";int calls=lookups;Reject(()=>SessionConnector.Connect("auto",Empty(),Active,v=>v.pid,v=>v.revision,new ConnectionDiagnostics(),()=>inventory),"AMBIGUOUS_COM_SESSION");Check(calls==lookups,"auto multiple no COM lookup");
        inventory.Identities.Remove(33);inventory.Complete=false;Reject(()=>SessionConnector.Connect("auto",Empty(),Active,v=>v.pid,v=>v.revision,new ConnectionDiagnostics(),()=>inventory),"AUTO_SESSION_INVENTORY_UNAVAILABLE");inventory.Complete=true;
        scans=0;Reject(()=>SessionConnector.Connect("auto",Empty(),Active,v=>v.pid,v=>v.revision,new ConnectionDiagnostics(),()=>{scans++;var snapshot=new SessionInventory();snapshot.Identities[22]=scans==1?"start-A":"start-reused-PID";return snapshot;}),"AUTO_SESSION_IDENTITY_CHANGED");
        try{SessionConnector.Connect("auto",Empty(),Active,v=>v.pid,v=>v.revision,new ConnectionDiagnostics(),()=>new SessionInventory());throw new Exception("missing zero-instance error");}catch(CadFault e){Check(e.Code=="COM_SESSION_NOT_FOUND"&&e.Message.Contains("请先启动")&&!e.Message.Contains("多个"),"zero instances action, not ambiguity");}
        object live=null;
#if NATIVE_SESSION_TESTS
        if(args.Length==2 && args[0]=="--live") {
            int pid=int.Parse(args[1]);System.Environment.SetEnvironmentVariable("SW_MCP_PROCESS_ID",args[1]);
            ConnectionDiagnostics normal; var sw=SolidWorksConnection.Connect(out normal);bool userControl=sw.UserControl;
            Check(sw.GetProcessID()==pid,"native PID identity");
            var fallback=new ConnectionDiagnostics();var actual=SessionConnector.Connect(args[1],new Dictionary<int,Func<ISldWorks>>(),SolidWorksConnection.ActiveObject,s=>s.GetProcessID(),s=>s.RevisionNumber(),fallback);
            Check(actual.GetProcessID()==pid && fallback.connection_source=="GetActiveObject_fallback","native fallback with missing PID inventory");
            var wrong=new ConnectionDiagnostics();Reject(()=>SessionConnector.Connect((pid+1).ToString(),new Dictionary<int,Func<ISldWorks>>(),SolidWorksConnection.ActiveObject,s=>s.GetProcessID(),s=>s.RevisionNumber(),wrong),"COM_SESSION_ID_MISMATCH");
            Check(sw.UserControl==userControl,"read-only probe retained UserControl");
            ConnectionDiagnostics autoInfo=null;var actualInventory=SessionInventory.ReadVerified();
            if(actualInventory.Complete&&actualInventory.Identities.Count==1&&actualInventory.Identities.ContainsKey(pid)){autoInfo=new ConnectionDiagnostics();var autoSw=SessionConnector.Connect("auto",new Dictionary<int,Func<ISldWorks>>(),SolidWorksConnection.ActiveObject,s=>s.GetProcessID(),s=>s.RevisionNumber(),autoInfo,SessionInventory.ReadVerified);Check(autoSw.GetProcessID()==pid&&autoInfo.process_identity_before==autoInfo.process_identity_after,"native auto missing ROT identity stable");}
            live=new{normal_connection=normal,forced_missing_pid_inventory_connection=fallback,auto_forced_missing_rot=autoInfo,wrong_pid=wrong,forced_inventory_is_test_only=true,user_control_before=userControl,user_control_after=sw.UserControl};
        }
#endif
        Console.WriteLine(new JavaScriptSerializer().Serialize(new{all_passed=true,checks=checks,live=live}));
    }
}
