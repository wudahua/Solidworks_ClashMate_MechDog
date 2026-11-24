using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using System.Xml;

internal sealed class MaterialCatalog {
    static readonly JavaScriptSerializer json=new JavaScriptSerializer{MaxJsonLength=16777216};
    public readonly string FilePath,Hash;
    readonly Dictionary<string,int> Names=new Dictionary<string,int>(StringComparer.Ordinal);
    MaterialCatalog(string path) {
        FilePath=path;
        var settings=new XmlReaderSettings{DtdProcessing=DtdProcessing.Prohibit,XmlResolver=null,MaxCharactersInDocument=16000000};
        using(var stream=new FileStream(path,FileMode.Open,FileAccess.Read,FileShare.Read))
        using(var hash=SHA256.Create()) {
            Hash=BitConverter.ToString(hash.ComputeHash(stream));
            stream.Position=0;
            using(var reader=XmlReader.Create(stream,settings)) {
                while(reader.Read()) {
                    if(reader.NodeType!=XmlNodeType.Element||reader.LocalName!="material")continue;
                    string name=reader.GetAttribute("name");
                    if(string.IsNullOrWhiteSpace(name))continue;
                    int count;
                    Names.TryGetValue(name,out count);
                    Names[name]=count+1;
                }
            }
        }
    }

    string[] Suggestions(string requested) {
        var words=requested.Split((char[])null,StringSplitOptions.RemoveEmptyEntries);
        return Names.Where(p=>p.Value==1&&p.Key.Count(c=>!char.IsLowSurrogate(c))<=256)
            .Select(p=>new{name=p.Key,whole=p.Key.IndexOf(requested,StringComparison.OrdinalIgnoreCase)>=0,
                shared=words.Count(w=>p.Key.IndexOf(w,StringComparison.OrdinalIgnoreCase)>=0)})
            .Where(p=>p.whole||p.shared>0).OrderByDescending(p=>p.whole).ThenByDescending(p=>p.shared)
            .ThenBy(p=>Math.Abs(p.name.Length-requested.Length)).ThenBy(p=>p.name,StringComparer.Ordinal)
            .Take(5).Select(p=>p.name).ToArray();
    }

    public static MaterialCatalog Read(string[] databases,string database) {
        var paths=databases.Where(d=>Path.GetFileName(d).Equals(database,StringComparison.OrdinalIgnoreCase)).ToArray();
        if(paths.Length!=1)
            throw new CadFault("PARAMETER_NOT_APPLICABLE","材质库文件名须在本机 SolidWorks 登记的库中唯一匹配。",
                new{requested_database=database,database_status=paths.Length==0?"not_registered":"ambiguous",
                    database_files=databases.Select(Path.GetFileName).Distinct(StringComparer.OrdinalIgnoreCase).Take(50).ToArray()});
        try {return new MaterialCatalog(paths[0]);}
        catch(IOException) {throw UnreadableMaterialCatalog(database);}
        catch(UnauthorizedAccessException) {throw UnreadableMaterialCatalog(database);}
        catch(XmlException) {throw UnreadableMaterialCatalog(database);}
    }

    static CadFault UnreadableMaterialCatalog(string database) {
        return new CadFault("PARAMETER_NOT_APPLICABLE","无法读取所选材质库，请核对 SolidWorks 材质库设置。",
            new{requested_database=database,database_status="unreadable"});
    }

    public void RequireExact(string database,string material) {
        int matches;
        Names.TryGetValue(material,out matches);
        if(matches!=1)
            throw new CadFault("PARAMETER_NOT_APPLICABLE","材质名须在所选 SolidWorks 材质库中精确且唯一匹配。",
                new{requested_database=database,requested_material=material,
                    material_status=matches==0?"no_exact_match":"duplicate_exact_name",
                    candidate_materials=Suggestions(material)});
    }

    public static object Page(string[] databases,string id,string database,string query,string cursor,int pageSize) {
        if(string.IsNullOrWhiteSpace(database)||query==null||cursor==null||pageSize<1||pageSize>100)
            throw new CadFault("INVALID_ARGUMENT","材质名查询须指定材质库和有效页大小。");
        var catalog=Read(databases,database);
        string key;
        using(var hash=SHA256.Create()) {
            string identity=json.Serialize(new[]{id,catalog.FilePath,catalog.Hash,query});
            key=BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(identity))).Replace("-","");
        }
        int offset=0;
        if(cursor.Length>0) {
            var pieces=cursor.Split(':');
            if(pieces.Length!=2||pieces[1]!=key||!int.TryParse(pieces[0],out offset)||offset<=0)
                throw new CadFault("INVALID_ARGUMENT","材质名游标与当前副本、材质库或搜索条件不匹配，请从首页重新查询。");
        }
        var names=catalog.Names.Where(p=>p.Key.IndexOf(query,StringComparison.OrdinalIgnoreCase)>=0)
            .OrderBy(p=>p.Key,StringComparer.Ordinal).ToArray();
        if(offset>0&&offset>=names.Length)
            throw new CadFault("INVALID_ARGUMENT","材质名游标已超出范围，请从首页重新查询。");
        var rows=new List<object>();
        int bytes=0;
        foreach(var pair in names.Skip(offset).Take(pageSize)) {
            bool tooLong=pair.Key.Count(c=>!char.IsLowSurrogate(c))>256;
            var row=new{material=tooLong?null:pair.Key,unique_exact_match=pair.Value==1,name_exceeds_assignment_limit=tooLong};
            int size=Encoding.UTF8.GetByteCount(json.Serialize(row));
            if(rows.Count>0&&bytes+size>8000)break;
            rows.Add(row);
            bytes+=size;
        }
        int end=offset+rows.Count;
        return new{model_id=id,material_database=Path.GetFileName(catalog.FilePath),material_query=query,
            total_matches=names.Length,offset=offset,rows=rows,next_cursor=end<names.Length?end.ToString()+":"+key:null,
            write_dispatched=false};
    }

}
