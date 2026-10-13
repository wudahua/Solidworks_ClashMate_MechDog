using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text.RegularExpressions;
using SolidWorks.Interop.sldworks;

public class ConnectionDiagnostics {
    public int? configured_pid;
    public int? actual_pid;
    public int rot_entry_count;
    public int rot_display_name_errors;
    public int[] available_pids = new int[0];
    public bool available_pids_truncated;
    public string connection_source;
    public string revision;
    public int? native_hresult;
}

// Selection policy has no COM side effects; both paths must validate the same identity.
public static class SessionConnector {
    public static T Connect<T>(string selected, IDictionary<int,Func<T>> registered,
        Func<T> active, Func<T,int> processId, Func<T,string> revision, ConnectionDiagnostics info) where T:class {
        int pid;
        bool explicitPid = !string.IsNullOrEmpty(selected);
        var pids = registered.Keys.OrderBy(x=>x).ToArray();
        info.available_pids = pids.Take(32).ToArray();
        info.available_pids_truncated = pids.Length > 32;
        if(explicitPid) {
            if(!int.TryParse(selected,out pid) || pid<=0)
                throw new CadFault("INVALID_SOLIDWORKS_PID","SW_MCP_PROCESS_ID 必须是正整数。",info);
            info.configured_pid=pid;
        } else {
            if(pids.Length==0) throw new CadFault("COM_SESSION_NOT_FOUND","未找到 PID 注册项；请明确设置 SW_MCP_PROCESS_ID 后重试。",info);
            if(pids.Length!=1) throw new CadFault("AMBIGUOUS_COM_SESSION","发现多个 SolidWorks 实例，请设置 SW_MCP_PROCESS_ID。",info);
            pid=pids[0];
        }
        try {
            T session;
            Func<T> byPid;
            if(registered.TryGetValue(pid,out byPid)) {
                info.connection_source="pid_moniker";
                session=byPid();
            } else {
                // Generic active-object lookup does not prove that only one instance exists.
                info.connection_source="GetActiveObject_fallback";
                session=active();
            }
            if(session==null) throw new CadFault("COM_SESSION_UNAVAILABLE","返回的对象不提供 SolidWorks COM 接口。",info);
            info.actual_pid=processId(session);
            if(info.actual_pid!=pid) throw new CadFault("COM_SESSION_ID_MISMATCH","返回实例与所选 PID 不一致；没有连接或发送 CAD 请求。",info);
            info.revision=revision(session);
            if(string.IsNullOrWhiteSpace(info.revision)) throw new CadFault("COM_SESSION_UNAVAILABLE","无法读取 SolidWorks revision。",info);
            return session;
        } catch(COMException e) {
            info.native_hresult=e.HResult;
            throw new CadFault("COM_SESSION_UNAVAILABLE","SolidWorks COM 连接不可用；核对 PID、桌面会话和权限级别。",info);
        }
    }
}

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
                ActiveObject,sw=>sw.GetProcessID(),sw=>sw.RevisionNumber(),info);
        } catch(COMException e) {
            info.native_hresult=e.HResult;
            throw new CadFault("COM_SESSION_UNAVAILABLE","无法枚举当前桌面 COM 会话，请核对权限级别。",info);
        } finally {
            foreach(var moniker in monikers.Values) Release(moniker);
            Release(list); Release(context); Release(rot);
        }
    }
}
