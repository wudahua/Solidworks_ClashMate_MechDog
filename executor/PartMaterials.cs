using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Xml;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    sealed class MaterialEdit {
        public string part_file,configuration,previous_material,previous_database,material,database;
        public string PartPath,DatabasePath,DatabaseHash;
    }
    sealed class PartMaterialPlan {
        public string ModelId;
        public int Revision;
        public Dictionary<string,string> InputHashes;
        public MaterialEdit[] Changes;
        public bool Consumed;
    }
    readonly Dictionary<string,PartMaterialPlan> materialPlans=new Dictionary<string,PartMaterialPlan>();

    string[] MaterialDatabases() {
        var files=Sw.GetMaterialDatabases() as Array;
        return files==null?new string[0]:files.Cast<object>().OfType<string>()
            .Where(p=>Path.IsPathRooted(p)&&Path.GetExtension(p).Equals(".sldmat",StringComparison.OrdinalIgnoreCase)&&File.Exists(p))
            .Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
    }

    sealed class MaterialCatalog {
        public readonly string Path,Hash;
        public readonly Dictionary<string,int> Names=new Dictionary<string,int>(StringComparer.Ordinal);
        public MaterialCatalog(string path) {
            Path=path;
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
    }

    static string[] MaterialSuggestions(MaterialCatalog catalog,string requested) {
        var words=requested.Split((char[])null,StringSplitOptions.RemoveEmptyEntries);
        return catalog.Names.Where(p=>p.Value==1&&p.Key.Count(c=>!char.IsLowSurrogate(c))<=256)
            .Select(p=>new{name=p.Key,whole=p.Key.IndexOf(requested,StringComparison.OrdinalIgnoreCase)>=0,
                shared=words.Count(w=>p.Key.IndexOf(w,StringComparison.OrdinalIgnoreCase)>=0)})
            .Where(p=>p.whole||p.shared>0).OrderByDescending(p=>p.whole).ThenByDescending(p=>p.shared)
            .ThenBy(p=>Math.Abs(p.name.Length-requested.Length)).ThenBy(p=>p.name,StringComparer.Ordinal)
            .Take(5).Select(p=>p.name).ToArray();
    }

    static MaterialCatalog ReadMaterialCatalog(string[] databases,string database) {
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

    public object InspectMaterialNames(string id,string database,string query,string cursor,int pageSize) {
        GetUserModel(id);
        if(string.IsNullOrWhiteSpace(database)||query==null||cursor==null||pageSize<1||pageSize>100)
            throw new CadFault("INVALID_ARGUMENT","材质名查询须指定材质库和有效页大小。");
        var catalog=ReadMaterialCatalog(MaterialDatabases(),database);
        string key;
        using(var hash=SHA256.Create()) {
            string identity=Json.Serialize(new[]{id,catalog.Path,catalog.Hash,query});
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
            int size=Encoding.UTF8.GetByteCount(Json.Serialize(row));
            if(rows.Count>0&&bytes+size>8000)break;
            rows.Add(row);
            bytes+=size;
        }
        int end=offset+rows.Count;
        return new{model_id=id,material_database=Path.GetFileName(catalog.Path),material_query=query,
            total_matches=names.Length,offset=offset,rows=rows,next_cursor=end<names.Length?end.ToString()+":"+key:null,
            write_dispatched=false};
    }

    static IModelDoc2 MaterialPart(UserModel model,IComponent2 occurrence) {
        string path=occurrence.GetPathName();
        var part=occurrence.GetModelDoc2() as IModelDoc2;
        if(!(part is IPartDoc)||!model.Files.Contains(path,StringComparer.OrdinalIgnoreCase)||
                !string.Equals(part.GetPathName(),path,StringComparison.OrdinalIgnoreCase))return null;
        return part;
    }

    static object MaterialRows(IEnumerable<MaterialEdit> changes) {
        return changes.Select(c=>new{c.part_file,c.configuration,c.previous_material,c.previous_database,c.material,c.database}).ToArray();
    }

    static bool SameMaterialDatabase(string nativeDatabase,string installedFile) {
        return string.Equals(Path.GetFileName(nativeDatabase),installedFile,StringComparison.OrdinalIgnoreCase)||
            string.Equals(Path.GetFileName(nativeDatabase),Path.GetFileNameWithoutExtension(installedFile),StringComparison.OrdinalIgnoreCase);
    }

    public object PreviewPartMaterials(string id,string assignmentsJson) {
        var model=GetUserModel(id);
        var assignments=Json.Deserialize<List<Dictionary<string,string>>>(assignmentsJson);
        if(assignments==null||assignments.Count<1||assignments.Count>64)
            throw new CadFault("PARAMETER_NOT_APPLICABLE","材质方案每批须包含1至64个零件配置。");
        using(var scope=new Scope(this,model.Path,null)) {
            var databases=MaterialDatabases();
            var catalogs=new Dictionary<string,MaterialCatalog>(StringComparer.OrdinalIgnoreCase);
            var components=UserComponents(scope.Doc).Where(c=>!c.IsSuppressed()).ToArray();
            var changes=new List<MaterialEdit>();
            var seen=new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach(var values in assignments) {
                if(values.Count!=4||new[]{"part_file","configuration","database","material"}.Any(k=>!values.ContainsKey(k)||string.IsNullOrWhiteSpace(values[k])))
                    throw new CadFault("PARAMETER_NOT_APPLICABLE","材质方案须使用盘点返回的零件文件、配置、材质库文件名和准确材质名。");
                var picks=components.Where(c=>Path.GetFileName(c.GetPathName()).Equals(values["part_file"],StringComparison.OrdinalIgnoreCase)
                    &&c.ReferencedConfiguration==values["configuration"]).ToArray();
                if(picks.Length==0||picks.Select(c=>c.GetPathName()).Distinct(StringComparer.OrdinalIgnoreCase).Count()!=1)
                    throw new CadFault("PARAMETER_NOT_APPLICABLE","零件配置没有唯一绑定到当前隔离副本。",new{part_file=values["part_file"],configuration=values["configuration"]});
                MaterialCatalog catalog;
                if(!catalogs.TryGetValue(values["database"],out catalog)) {
                    catalog=ReadMaterialCatalog(databases,values["database"]);
                    catalogs.Add(values["database"],catalog);
                }
                int materialMatches;
                catalog.Names.TryGetValue(values["material"],out materialMatches);
                if(materialMatches!=1)
                    throw new CadFault("PARAMETER_NOT_APPLICABLE","材质名须在所选 SolidWorks 材质库中精确且唯一匹配。",
                        new{requested_database=values["database"],requested_material=values["material"],
                            material_status=materialMatches==0?"no_exact_match":"duplicate_exact_name",
                            candidate_materials=MaterialSuggestions(catalog,values["material"])});
                var part=MaterialPart(model,picks[0]);
                if(part==null||part.GetConfigurationByName(values["configuration"])==null||part.GetSaveFlag())
                    throw new CadFault("PARAMETER_NOT_APPLICABLE","目标零件或配置未解析，或含未保存变化。");
                string path=part.GetPathName(),conf=values["configuration"];
                if(!seen.Add(path+"\0"+conf))throw new CadFault("PARAMETER_NOT_APPLICABLE","同一个零件配置不能重复赋材质。");
                string previousDatabase;
                string prior=((IPartDoc)part).GetMaterialPropertyName2(conf,out previousDatabase);
                if(prior==values["material"]&&SameMaterialDatabase(previousDatabase,values["database"]))
                    throw new CadFault("PARAMETER_NOT_APPLICABLE","目标已有相同材质，请从方案移除无需改动的配置。",new{part_file=values["part_file"],configuration=conf});
                changes.Add(new MaterialEdit{part_file=Path.GetFileName(path),configuration=conf,material=values["material"],
                    database=Path.GetFileName(catalog.Path),PartPath=path,DatabasePath=catalog.Path,DatabaseHash=catalog.Hash,
                    previous_material=prior,previous_database=Path.GetFileName(previousDatabase)});
            }
            VerifyUserSources(model);
            var idPlan=Guid.NewGuid().ToString("N");
            materialPlans[idPlan]=new PartMaterialPlan{ModelId=id,Revision=model.Revision,Changes=changes.ToArray(),
                InputHashes=model.Files.ToDictionary(p=>p,p=>FileHash(p),StringComparer.OrdinalIgnoreCase)};
            return new{plan_id=idPlan,model_id=id,assignments=MaterialRows(changes),write_dispatched=false,
                requires_explicit_confirmation=true,source_files_unchanged=true};
        }
    }

    void VerifyAssignedMaterials(UserModel model,PartMaterialPlan plan,IModelDoc2 doc) {
        var occurrences=UserComponents(doc).Where(c=>!c.IsSuppressed()).ToArray();
        foreach(var change in plan.Changes) {
            var occurrence=occurrences.FirstOrDefault(c=>string.Equals(c.GetPathName(),change.PartPath,StringComparison.OrdinalIgnoreCase)
                &&c.ReferencedConfiguration==change.configuration);
            var part=occurrence==null?null:MaterialPart(model,occurrence);
            string database=null;
            string actual=part==null?null:((IPartDoc)part).GetMaterialPropertyName2(change.configuration,out database);
            if(actual!=change.material||!SameMaterialDatabase(database,change.database))
                throw new CadFault("PART_MATERIAL_READBACK_FAILED","零件配置的材质未通过原生读回。",
                    new{change.part_file,change.configuration,requested_material=change.material,requested_database=change.database,
                        actual_material=actual,actual_database=database});
        }
    }

    public object ApplyPartMaterials(string planId,bool confirmed) {
        PartMaterialPlan plan;
        if(!materialPlans.TryGetValue(planId,out plan)||plan.Consumed)throw new CadFault("CONNECTION_PLAN_STALE","材质方案已失效。");
        if(!confirmed)throw new CadFault("CONFIRMATION_REQUIRED","须确认零件配置及材质变更。");
        var model=GetUserModel(plan.ModelId);
        if(model.Revision!=plan.Revision||plan.InputHashes.Any(p=>FileHash(p.Key)!=p.Value)||
                plan.Changes.Any(c=>FileHash(c.DatabasePath)!=c.DatabaseHash))
            throw new CadFault("CONNECTION_PLAN_STALE","副本或材质库自确认方案后已变化。");
        var checkpoint=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(CreateUserCheckpoint(model.Id)));
        string checkpointId=(string)checkpoint["checkpoint_id"];
        plan.Consumed=true;
        LastOperationRestoration="pending";
        try {
            using(var scope=new Scope(this,model.Path,null)) {
                var doc=scope.Doc;
                var occurrences=UserComponents(doc).Where(c=>!c.IsSuppressed()).ToArray();
                var before=Transforms(doc);
                string mates=ImportMateParameters(doc);
                foreach(var change in plan.Changes) {
                    var member=occurrences.First(c=>string.Equals(c.GetPathName(),change.PartPath,StringComparison.OrdinalIgnoreCase)
                        &&c.ReferencedConfiguration==change.configuration);
                    var part=MaterialPart(model,member);
                    if(part==null)throw new CadFault("PART_MATERIAL_READBACK_FAILED","目标零件脱离隔离副本。");
                    ((IPartDoc)part).SetMaterialPropertyName2(change.configuration,change.DatabasePath,change.material);
                }
                VerifyAssignedMaterials(model,plan,doc);
                SaveOwnedDocuments(model);
                VerifyAssignedMaterials(model,plan,doc);
                var after=Transforms(doc);
                if(mates!=ImportMateParameters(doc)||before.Count!=after.Count||
                        before.Any(p=>!after.ContainsKey(p.Key)||!PoseValidation.Matches(p.Value,after[p.Key])))
                    throw new CadFault("PART_MATERIAL_READBACK_FAILED","保存改变了配合或组件姿态。");
            }
            VerifyUserSources(model);
            model.Revision++;
            SaveUserModel(model);
            LastOperationRestoration="restored";
            return new{model_id=model.Id,assignments=MaterialRows(plan.Changes),materials_verified=true,source_files_unchanged=true,
                mates_and_poses_unchanged=true,checkpoint_id=checkpointId};
        } catch(Exception error) {
            if(error is COMException||error is NativeCommandStateException||LastContextRestoration=="unknown") {
                LastOperationRestoration="unknown";
                throw;
            }
            RestoreUserCheckpoint(model.Id,checkpointId);
            LastOperationRestoration="restored";
            throw new CadFault("PART_MATERIAL_WRITE_ROLLED_BACK","材质没有写入已验证成果，已恢复原检查点。",
                new{checkpoint_id=checkpointId,original_failure=FailureEvidence(error),rollback_verified=true});
        }
    }

    object InspectAssemblyMassProperties(string id) {
        var model=GetUserModel(id);
        using(var scope=new Scope(this,model.Path,null)) {
            var properties=scope.Doc.Extension.CreateMassProperty2() as IMassProperty2;
            if(properties==null)throw new CadFault("PART_MASS_PROPERTIES_UNAVAILABLE","SolidWorks 未返回可用的质量属性。");
            properties.UseSystemUnits=true;
            if(!properties.Recalculate())throw new CadFault("PART_MASS_PROPERTIES_UNAVAILABLE","SolidWorks 未确认质量属性计算。");
            var center=properties.CenterOfMass as double[];
            var inertia=properties.PrincipalMomentsOfInertia as double[];
            double mass=properties.Mass,volume=properties.Volume;
            if(center==null||inertia==null||center.Length!=3||inertia.Length!=3||mass<=0||volume<=0||
                    center.Concat(inertia).Concat(new[]{mass,volume}).Any(x=>double.IsNaN(x)||double.IsInfinity(x)))
                throw new CadFault("PART_MASS_PROPERTIES_UNAVAILABLE","质量、质心、体积或主惯量数据不完整。");
            VerifyUserSources(model);
            return new{model_id=id,mass_kg=mass,volume_m3=volume,effective_density_kg_m3=mass/volume,
                center_of_mass_m=center,principal_moments_kg_m2=inertia,
                configuration=scope.Doc.ConfigurationManager.ActiveConfiguration.Name,native_density_fallback_may_apply=true,
                coordinate_frame="assembly_model_default",material_coverage_verified=false,write_dispatched=false,source_files_unchanged=true};
        }
    }
    sealed class PartMaterialObservation {
        public string part_file,configuration,material_name,material_database,status;
        public int? native_hresult;
        public readonly List<string> instances=new List<string>();
    }

    object InspectPartMaterials(string id) {
        var model=GetUserModel(id);
        using(var scope=new Scope(this,model.Path,null)) {
            var doc=scope.Doc;
            Fingerprint(doc,scope.DocumentPath);
            var parts=new Dictionary<string,PartMaterialObservation>(StringComparer.OrdinalIgnoreCase);
            var skipped=new List<object>();
            var components=UserComponents(doc);
            foreach(var c in components) {
                string instance=c.Name2;
                if(c.IsSuppressed()) {skipped.Add(new{instance=instance,reason="suppressed_occurrence"});continue;}
                var loaded=c.GetModelDoc2() as IModelDoc2;
                if(loaded!=null&&!(loaded is IPartDoc)) {
                    skipped.Add(new{instance=instance,reason="assembly_document"});continue;
                }
                string configuration=c.ReferencedConfiguration,path=c.GetPathName();
                if(string.IsNullOrEmpty(path)||loaded==null||string.IsNullOrEmpty(configuration)) {
                    skipped.Add(new{instance=instance,reason="part_or_reference_configuration_unavailable"});continue;
                }
                if(!model.Files.Any(p=>string.Equals(p,path,StringComparison.OrdinalIgnoreCase))||
                    !string.Equals(loaded.GetPathName(),path,StringComparison.OrdinalIgnoreCase))
                    throw new CadFault("COPY_REFERENCE_NOT_ISOLATED","材质盘点遇到未绑定到隔离副本的零件引用。",new{instance=instance});
                string key=path+"\0"+configuration;
                PartMaterialObservation row;
                if(!parts.TryGetValue(key,out row)) {
                    row=new PartMaterialObservation{part_file=System.IO.Path.GetFileName(path),configuration=configuration};
                    parts.Add(key,row);
                    try {
                        if(loaded.GetConfigurationByName(configuration)==null)row.status="configuration_unavailable";
                        else {
                            string database;
                            var name=((IPartDoc)loaded).GetMaterialPropertyName2(configuration,out database);
                            row.material_name=string.IsNullOrWhiteSpace(name)?null:name;
                            row.material_database=string.IsNullOrWhiteSpace(database)?null:database;
                            row.status=row.material_name==null?"part_material_unassigned":"part_material_observed";
                        }
                    }catch(COMException error){row.status="native_material_unavailable";row.native_hresult=error.HResult;}
                }
                row.instances.Add(instance);
            }
            VerifyUserSources(model);
            return new{model_id=id,scope="active_occurrences_part_material_by_referenced_configuration",
                assembly_configuration=doc.ConfigurationManager.ActiveConfiguration.Name,observed_occurrence_count=components.Length,
                part_configuration_count=parts.Count,part_configurations_with_material=parts.Values.Count(r=>r.status=="part_material_observed"),
                part_configurations_without_material=parts.Values.Count(r=>r.status=="part_material_unassigned"),
                part_configurations_unresolved=parts.Values.Count(r=>r.status!="part_material_observed"&&r.status!="part_material_unassigned"),
                parts=parts.Values.ToArray(),skipped_occurrences=skipped.ToArray(),
                material_database_files=MaterialDatabases().Select(Path.GetFileName).ToArray(),body_material_overrides_read=false,
                mass_properties_read=false,configuration_switched=false,write_dispatched=false,source_files_unchanged=true};
        }
    }
}
