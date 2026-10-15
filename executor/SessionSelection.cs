using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;

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
    public string selection_mode,process_identity_before,process_identity_after;
    public int[] auto_candidate_pids=new int[0];
    public bool? auto_inventory_complete;
    public string next_action="update_SW_MCP_PROCESS_ID_or_use_explicit_auto_and_reload_client";
}

// Selection policy has no COM side effects; both paths must validate the same identity.
public static class SessionConnector {
    public static T Connect<T>(string selected, IDictionary<int,Func<T>> registered,
        Func<T> active, Func<T,int> processId, Func<T,string> revision, ConnectionDiagnostics info,Func<SessionInventory> inventory=null) where T:class {
        int pid;
        bool automatic=string.Equals(selected,"auto",StringComparison.OrdinalIgnoreCase);
        bool explicitPid = !string.IsNullOrEmpty(selected)&&!automatic;
        info.selection_mode=automatic?"explicit_auto_verified_unique_process":explicitPid?"explicit_pid":"legacy_unique_ROT_registration";
        var pids = registered.Keys.OrderBy(x=>x).ToArray();
        info.available_pids = pids.Take(32).ToArray();
        info.available_pids_truncated = pids.Length > 32;
        if(automatic){
            if(inventory==null)throw new CadFault("AUTO_SESSION_INVENTORY_UNAVAILABLE","无法核验自动选择所需的本机进程身份；请显式选择 PID。",info);
            var snapshot=inventory();info.auto_inventory_complete=snapshot.Complete;info.auto_candidate_pids=snapshot.Identities.Keys.OrderBy(v=>v).Take(32).ToArray();
            if(!snapshot.Complete)throw new CadFault("AUTO_SESSION_INVENTORY_UNAVAILABLE","至少一个 SolidWorks 进程身份不可核验；未自动连接，请核对权限及 PID。",info);
            if(snapshot.Identities.Count==0)throw new CadFault("COM_SESSION_NOT_FOUND","未找到当前用户桌面会话中运行的 SolidWorks；请先启动 SolidWorks，再重试连接。",info);
            if(snapshot.Identities.Count>1)throw new CadFault("AMBIGUOUS_COM_SESSION","发现多个 SolidWorks 实例或辅助进程，拒绝猜选；请核对 available_pids/auto_candidate_pids 并显式指定 SW_MCP_PROCESS_ID。",info);
            pid=snapshot.Identities.Keys.Single();info.process_identity_before=snapshot.Identities[pid];
        }else if(explicitPid) {
            if(!int.TryParse(selected,out pid) || pid<=0)
                throw new CadFault("INVALID_SOLIDWORKS_PID","SW_MCP_PROCESS_ID 必须是正整数或显式 auto。",info);
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
            if(info.actual_pid!=pid) throw new CadFault("COM_SESSION_ID_MISMATCH","返回实例与所选 PID 不一致；没有连接或发送 CAD 请求。请核对 available_pids；首次连接且未派发CAD请求时，可用 get_environment(solidworks_pid=新PID字符串或auto) 显式纠正，否则更新 SW_MCP_PROCESS_ID 并重载客户端。",info);
            info.revision=revision(session);
            if(string.IsNullOrWhiteSpace(info.revision)) throw new CadFault("COM_SESSION_UNAVAILABLE","无法读取 SolidWorks revision。",info);
            if(automatic){var after=inventory();string identity;info.process_identity_after=after.Identities.TryGetValue(pid,out identity)?identity:null;
                if(!after.Complete||after.Identities.Count!=1||info.process_identity_after!=info.process_identity_before)throw new CadFault("AUTO_SESSION_IDENTITY_CHANGED","连接期间实例集合或进程启动身份发生变化，未派发 CAD 请求；重新核对 PID。",info);}
            return session;
        } catch(COMException e) {
            info.native_hresult=e.HResult;
            throw new CadFault("COM_SESSION_UNAVAILABLE","SolidWorks COM 连接不可用；核对 PID、桌面会话和权限级别。",info);
        }
    }
}

