using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text.RegularExpressions;
using SolidWorks.Interop.sldworks;

public static class SolidWorksConnection {
    [DllImport("ole32.dll")]static extern int GetRunningObjectTable(int reserved,out IRunningObjectTable table);
    [DllImport("ole32.dll")]static extern int CreateBindCtx(int reserved,out IBindCtx context);
    [DllImport("ole32.dll",CharSet=CharSet.Unicode)]static extern int CLSIDFromProgID(string progId,out Guid clsid);
    [DllImport("oleaut32.dll")]static extern int GetActiveObject(ref Guid clsid,IntPtr reserved,[MarshalAs(UnmanagedType.IUnknown)]out object result);

    internal static ISldWorks ActiveObject() {
        Guid clsid; Marshal.ThrowExceptionForHR(CLSIDFromProgID("SldWorks.Application",out clsid));
        object result; Marshal.ThrowExceptionForHR(GetActiveObject(ref clsid,IntPtr.Zero,out result));
        return result as ISldWorks;
    }

    static void Release(object value) {if(value!=null && Marshal.IsComObject(value)) Marshal.ReleaseComObject(value);}

    public static ISldWorks Connect(out ConnectionDiagnostics info) {
        info=new ConnectionDiagnostics();
        IRunningObjectTable rot=null; IBindCtx context=null; IEnumMoniker list=null;
        var monikers=new Dictionary<int,IMoniker>();
        try {
            Marshal.ThrowExceptionForHR(GetRunningObjectTable(0,out rot));
            Marshal.ThrowExceptionForHR(CreateBindCtx(0,out context));
            rot.EnumRunning(out list);
            var item=new IMoniker[1];
            while(list.Next(1,item,IntPtr.Zero)==0) {
                var moniker=item[0]; bool retained=false; info.rot_entry_count++;
                try {
                    string name; moniker.GetDisplayName(context,null,out name);
                    var match=Regex.Match(name,"^SolidWorks_PID_([0-9]+)$"); int pid;
                    if(match.Success && int.TryParse(match.Groups[1].Value,out pid) && pid>0 && !monikers.ContainsKey(pid)) {
                        monikers[pid]=moniker; retained=true;
                    }
                } catch(COMException) {info.rot_display_name_errors++;}
                finally {if(!retained) Release(moniker);}
            }
            var registered=new Dictionary<int,Func<ISldWorks>>();
            foreach(var pair in monikers) {
                var moniker=pair.Value;
                registered[pair.Key]=()=>{object result; rot.GetObject(moniker,out result); return result as ISldWorks;};
            }
            return SessionConnector.Connect(System.Environment.GetEnvironmentVariable("SW_MCP_PROCESS_ID"),registered,
                ActiveObject,sw=>sw.GetProcessID(),sw=>sw.RevisionNumber(),info,SessionInventory.ReadVerified);
        } catch(COMException e) {
            info.native_hresult=e.HResult;
            throw new CadFault("COM_SESSION_UNAVAILABLE","无法枚举当前桌面 COM 会话，请核对权限级别。",info);
        } finally {
            foreach(var moniker in monikers.Values) Release(moniker);
            Release(list); Release(context); Release(rot);
        }
    }
}
