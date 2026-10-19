using System;
using System.Linq;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    static IFace2[] ComponentFaces(IComponent2 c,out string status) {
        status="unknown";
        if(c.IsSuppressed()){status="suppressed";return new IFace2[0];}
        if(c.GetModelDoc2()==null)throw new CadFault("UNRESOLVED_COMPONENT","组件未解析，不能确认其几何是否为空。",new{instance=c.Name2,path=c.GetPathName(),stage="get_model_document"});
        try {
            object info;
            var solidRaw=c.GetBodies3(0,out info);var sheetRaw=c.GetBodies3(1,out info);
            if(solidRaw!=null&&!(solidRaw is Array)||sheetRaw!=null&&!(sheetRaw is Array))throw new CadFault("COMPONENT_GEOMETRY_VARIANT","原生体枚举返回不支持的数据类型，不能判为空体。",new{instance=c.Name2,stage="body_variant"});
            var solids=solidRaw==null?new object[0]:((Array)solidRaw).Cast<object>().ToArray();
            var sheets=sheetRaw==null?new object[0]:((Array)sheetRaw).Cast<object>().ToArray();
            status=solids.Length+sheets.Length==0?"resolved_bodyless":sheets.Length>0?"resolved_with_surface_bodies":"resolved_solid";
            return solids.Concat(sheets).Cast<IBody2>().SelectMany(b=>(b.GetFaces() as object[]??new object[0]).Cast<IFace2>()).ToArray();
        }catch(COMException e){throw new CadFault("COMPONENT_GEOMETRY_COM_FAILED","无法读取组件几何；其他组件仍可查询。",new{instance=c.Name2,path=c.GetPathName(),stage="enumerate_bodies_and_faces",native_hresult=e.HResult,native_message=e.Message});}
    }
    static object GeometryIssue(IComponent2 c,string cid,string reason,Exception error=null) {
        var fault=error as CadFault;
        return new{component_id=cid,instance=c.Name2,reason=reason,diagnostics=fault==null?(object)null:fault.Diagnostics};
    }
    static void BoundGeometryPage(Dictionary<string,object> response,List<Dictionary<string,object>> page,int offset,int total,int requested,Func<int,string> cursor) {
        try{GeometryPageBudget.Apply(response,page,offset,total,requested,cursor,x=>Json.Serialize(x));}
        catch(InvalidOperationException error){throw new CadFault("GEOMETRY_RESPONSE_BUDGET_EXCEEDED","分页无法在响应预算内安全前进，请按组件或紧凑模式重新查询；未返回自指游标。",new{cause=error.Message,offset=offset,total=total,requested_limit=requested,payload_budget_bytes=16000});}
    }
}
