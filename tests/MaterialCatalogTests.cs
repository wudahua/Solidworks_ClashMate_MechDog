using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Web.Script.Serialization;

class MaterialCatalogTests {
    static readonly JavaScriptSerializer Json=new JavaScriptSerializer();
    static void Check(bool condition,string context) {
        if(!condition)throw new Exception(context);
    }
    static object Field(object value,string name) {
        return value.GetType().GetProperty(name).GetValue(value,null);
    }
    static void Refuses(Action operation,string code,string field=null,string value=null) {
        try {operation();}
        catch(CadFault error) {
            Check(error.Code==code,"unexpected code: "+error.Code);
            if(field!=null)Check((string)Field(error.Diagnostics,field)==value,"unexpected status: "+field);
            return;
        }
        throw new Exception("expected "+code);
    }
    static int Main(string[] args) {
        Console.OutputEncoding=new System.Text.UTF8Encoding(false);
        string root=args[0],first=Path.Combine(root,"sample.sldmat"),other=Path.Combine(root,"other.sldmat");
        string duplicate=Path.Combine(Directory.CreateDirectory(Path.Combine(root,"other")).FullName,"sample.sldmat");
        string xml="<materials>"+string.Join("",new[]{"6061 Alloy (SS)","6061-T6","6061 Pure","6061 A","6061 BB",
            "Alloy D","Alloy E","Alloy F","duplicate","duplicate",new string('长',257)}
            .Concat(Enumerable.Range(0,110).Select(i=>"bulk-"+i.ToString("D3")))
            .Select(label=>"<material name=\""+label+"\"/>"))+"</materials>";
        File.WriteAllText(first,xml);
        File.WriteAllText(duplicate,"<materials/>");
        File.WriteAllText(other,"<!DOCTYPE materials [<!ENTITY x 'invalid'>]><materials><material name=\"&x;\"/></materials>");
        string[] registered={first,other};
        Refuses(()=>MaterialCatalog.Read(registered,"absent.sldmat"),"PARAMETER_NOT_APPLICABLE","database_status","not_registered");
        Refuses(()=>MaterialCatalog.Read(new[]{first,duplicate},"sample.sldmat"),"PARAMETER_NOT_APPLICABLE","database_status","ambiguous");
        Refuses(()=>MaterialCatalog.Read(registered,"other.sldmat"),"PARAMETER_NOT_APPLICABLE","database_status","unreadable");

        var material=MaterialCatalog.Read(registered,"SAMPLE.sldmat");
        material.RequireExact("sample.sldmat","6061-T6");
        Refuses(()=>material.RequireExact("sample.sldmat","6061-t6"),"PARAMETER_NOT_APPLICABLE","material_status","no_exact_match");
        Refuses(()=>material.RequireExact("sample.sldmat","duplicate"),"PARAMETER_NOT_APPLICABLE","material_status","duplicate_exact_name");
        try {material.RequireExact("sample.sldmat","6061 Alloy");throw new Exception("expected a spelling refusal");}
        catch(CadFault error) {
            var candidates=(string[])Field(error.Diagnostics,"candidate_materials");
            Check(candidates.Length==5&&candidates[0]=="6061 Alloy (SS)"&&candidates.Contains("6061-T6"),"candidate order or cap");
        }

        Func<string,int,object> bulk=(cursor,size)=>MaterialCatalog.Page(registered,"model","sample.sldmat","BULK-",cursor,size);
        Refuses(()=>bulk("",0),"INVALID_ARGUMENT");
        Refuses(()=>bulk("",101),"INVALID_ARGUMENT");
        var firstPage=bulk("",100);
        string next=(string)Field(firstPage,"next_cursor");
        Check((int)Field(firstPage,"total_matches")==110&&(int)Field(firstPage,"offset")==0&&next!=null,"first page");
        var firstRows=(IList<object>)Field(firstPage,"rows");
        Check(firstRows.Count>50&&firstRows.Count<=100&&(string)Field(firstRows[0],"material")=="bulk-000","first page contents");
        Check(firstRows.Sum(row=>System.Text.Encoding.UTF8.GetByteCount(Json.Serialize(row)))<=8000,"page byte limit");
        var continuation=bulk(next,100);
        var rest=(IList<object>)Field(continuation,"rows");
        Check((int)Field(continuation,"offset")==firstRows.Count&&rest.Count==110-firstRows.Count
            &&(string)Field(rest[0],"material")=="bulk-"+firstRows.Count.ToString("D3")
            &&Field(continuation,"next_cursor")==null,"continuation or ending");
        Check(((IList<object>)Field(bulk("",1),"rows")).Count==1,"minimum page size");
        Refuses(()=>bulk("invalid",1),"INVALID_ARGUMENT");
        Refuses(()=>MaterialCatalog.Page(registered,"model","sample.sldmat","other",next,1),"INVALID_ARGUMENT");
        Refuses(()=>MaterialCatalog.Page(registered,"other-model","sample.sldmat","BULK-",next,1),"INVALID_ARGUMENT");
        var duplicateRow=((IList<object>)Field(MaterialCatalog.Page(registered,"model","sample.sldmat","duplicate","",1),"rows")).Single();
        Check(!(bool)Field(duplicateRow,"unique_exact_match"),"query advertised a duplicate as unique");
        var longRow=((IList<object>)Field(MaterialCatalog.Page(registered,"model","sample.sldmat","长","",1),"rows")).Single();
        Check(Field(longRow,"material")==null&&(bool)Field(longRow,"name_exceeds_assignment_limit"),"oversize name");
        File.AppendAllText(first,"\n");
        Refuses(()=>bulk(next,1),"INVALID_ARGUMENT");
        Check(Json.Serialize(bulk("",1)).Contains("\"write_dispatched\":false"),"read only");
        Console.WriteLine("Material catalog policy passed without CAD.");
        return 0;
    }
}
