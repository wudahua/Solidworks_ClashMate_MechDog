using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    public sealed class ImportMateWitness {public int id,type,alignment,error;public string name;public string[] references;}
    sealed class ImportMateBinding {public IMate2 Mate;public int Index,ComponentId,ReferenceType;public object Reference;public string Encoded;}
    ImportMateBinding[] ImportMateBindings(IModelDoc2 doc){return BasicMateFeatures(doc).GroupBy(f=>f.GetID()).Select(g=>g.First()).SelectMany(f=>{var mate=(IMate2)f.GetSpecificFeature2();return Enumerable.Range(0,mate.GetMateEntityCount()).Select(i=>{var entity=mate.MateEntity(i);var component=entity.ReferenceComponent as IComponent2;object reference=entity.Reference;return new ImportMateBinding{Mate=mate,Index=i,ComponentId=component==null?-1:component.GetID(),ReferenceType=entity.ReferenceType2,Reference=reference,Encoded=Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(reference))};});}).ToArray();}
    object MigrateImportMateReferences(IModelDoc2 doc,ImportWitness witness,ImportMateBinding[] bindings){
        var mapping=new Dictionary<string,string>();var changes=new List<object>();
        foreach(var b in bindings){var current=b.Mate.MateEntity(b.Index);var component=current.ReferenceComponent as IComponent2;object reference=current.Reference;int same=Sw.IsSame(b.Reference,reference);if(same!=(int)SolidWorks.Interop.swconst.swObjectEquality.swObjectSame||current.ReferenceType2!=b.ReferenceType||(component==null?-1:component.GetID())!=b.ComponentId)throw new CadFault("VIRTUAL_MATE_REFERENCE_IDENTITY_UNPROVEN","外部化后的配合实体未通过原生对象相同性核对，未按几何改绑。",new{entity_index=b.Index,native_object_equality=same,component_id=b.ComponentId});
            string encoded=Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(reference));string existing;if(mapping.TryGetValue(b.Encoded,out existing)&&existing!=encoded)throw new Exception("VIRTUAL_REFERENCE_MIGRATION_AMBIGUOUS");mapping[b.Encoded]=encoded;if(encoded!=b.Encoded)changes.Add(new{before=b.Encoded,after=encoded,native_object_equality=same,component_id=b.ComponentId});
        }
        var mates=Json.Deserialize<ImportMateWitness[]>(witness.Mates);foreach(var mate in mates)mate.references=mate.references.Select(r=>mapping.ContainsKey(r)?mapping[r]:r).ToArray();witness.Mates=Json.Serialize(mates);return new{checked_reference_count=bindings.Length,migrated_reference_count=changes.Count,native_object_identity_required=true,changes=changes.ToArray()};
    }
    sealed class ImportWitness {
        public string Configuration;
        public Dictionary<string,double[]> Poses;
        public Dictionary<string,string> ComponentConfigurations;
        public Dictionary<string,string[]> PartConfigurations;
        public Dictionary<string,double[]> PartBoxes;
        public Dictionary<string,int> BodyCounts;
        public Dictionary<string,double[][]> GeometryProperties;
        public string Mates,Studies;
    }
    string ComponentReference(IModelDoc2 doc,IComponent2 c){return c.GetID().ToString(System.Globalization.CultureInfo.InvariantCulture);}
    ImportWitness VirtualWitness(IModelDoc2 doc) {
        var components=UserComponents(doc);
        if(components.Any(c=>c.IsSuppressed()||c.IsSpeedPak||c.GetModelDoc2()==null||c.GetPathName().EndsWith(".SLDASM",StringComparison.OrdinalIgnoreCase)))throw new CadFault("VIRTUAL_IMPORT_COMPONENT_SCOPE_UNSUPPORTED","外部化首批仅支持全部已加载的顶层刚体零件；抑制、SpeedPak或子装配未纳入此路径。",new{scope="top_level_loaded_parts_only"});
        var configurations=(Array)doc.GetConfigurationNames();if(configurations==null||configurations.Length!=1)throw new CadFault("VIRTUAL_ASSEMBLY_CONFIGURATIONS_UNVALIDATED","含虚拟零件的多配置装配尚未完成外部化验收，未自动转换。",new{assembly_configuration_count=configurations==null?0:configurations.Length});
        if(components.Length>500)throw new Exception("VIRTUAL_IMPORT_COMPONENT_BUDGET_EXCEEDED");
        var refs=components.ToDictionary(c=>ComponentReference(doc,c),c=>c);
        var witness=new ImportWitness{Configuration=doc.ConfigurationManager.ActiveConfiguration.Name,Poses=refs.ToDictionary(p=>p.Key,p=>(double[])p.Value.GetTotalTransform(false).ArrayData),ComponentConfigurations=refs.ToDictionary(p=>p.Key,p=>p.Value.ReferencedConfiguration),PartConfigurations=refs.ToDictionary(p=>p.Key,p=>((Array)((IModelDoc2)p.Value.GetModelDoc2()).GetConfigurationNames()).Cast<object>().Select(Convert.ToString).OrderBy(v=>v,StringComparer.Ordinal).ToArray()),PartBoxes=refs.ToDictionary(p=>p.Key,p=>(double[])((IPartDoc)p.Value.GetModelDoc2()).GetPartBox(true))};
        witness.BodyCounts=refs.ToDictionary(p=>p.Key,p=>PartBodyCount((IPartDoc)p.Value.GetModelDoc2()));
        witness.GeometryProperties=refs.ToDictionary(p=>p.Key,p=>ImportGeometryProperties((IPartDoc)p.Value.GetModelDoc2()));
        witness.Mates=Json.Serialize(BasicMateFeatures(doc).GroupBy(f=>f.GetID()).Select(g=>g.First()).OrderBy(f=>f.GetID()).Select(f=>{var m=(IMate2)f.GetSpecificFeature2();bool warning;return new ImportMateWitness{id=f.GetID(),name=f.Name,type=m.Type,alignment=m.Alignment,error=f.GetErrorCode2(out warning),references=Enumerable.Range(0,m.GetMateEntityCount()).Select(i=>Convert.ToBase64String((byte[])doc.Extension.GetPersistReference3(m.MateEntity(i).Reference))).ToArray()};}).ToArray());
        var manager=(SolidWorks.Interop.swmotionstudy.IMotionStudyManager)doc.Extension.GetMotionStudyManager();witness.Studies=Json.Serialize(Names(manager).OrderBy(v=>v,StringComparer.Ordinal).Select(n=>{var s=(SolidWorks.Interop.swmotionstudy.IMotionStudy)manager.GetMotionStudy(n);return new{name=n,settings=HistorySettings(s),time=s.GetTime(),active=s.IsActive};}).ToArray());return witness;
    }
    static int PartBodyCount(IPartDoc part){var solids=part.GetBodies2(0,false) as Array;var surfaces=part.GetBodies2(1,false) as Array;return (solids==null?0:solids.Length)+(surfaces==null?0:surfaces.Length);}
    static double[][] ImportGeometryProperties(IPartDoc part){
        var sheets=part.GetBodies2(1,false) as Array;if(sheets!=null&&sheets.Length>0)throw new CadFault("VIRTUAL_IMPORT_SURFACE_BODIES_UNVALIDATED","当前外部化几何复核仅校准实体体；曲面体另行验收。",new{surface_body_count=sheets.Length});
        var solids=part.GetBodies2(0,false) as Array;if(solids==null)return new double[0][];
        return solids.Cast<IBody2>().Select(b=>{var properties=b.GetMassProperties(1.0) as double[];if(properties==null||properties.Any(v=>double.IsNaN(v)||double.IsInfinity(v)))throw new Exception("VIRTUAL_GEOMETRY_PROPERTIES_UNAVAILABLE");return properties.Concat(new[]{(double)b.GetFaceCount(),(double)b.GetEdgeCount()}).ToArray();}).OrderBy(v=>string.Join(",",v.Select(x=>x.ToString("R",System.Globalization.CultureInfo.InvariantCulture))),StringComparer.Ordinal).ToArray();
    }
    object CompareVirtualWitness(ImportWitness before,ImportWitness after) {
        bool identity=before.Poses.Keys.OrderBy(v=>v).SequenceEqual(after.Poses.Keys.OrderBy(v=>v));
        bool pose=identity&&before.Poses.All(p=>PoseValidation.Matches(p.Value,after.Poses[p.Key]));
        bool configuration=identity&&before.Configuration==after.Configuration&&before.ComponentConfigurations.All(p=>after.ComponentConfigurations[p.Key]==p.Value)&&before.PartConfigurations.All(p=>after.PartConfigurations[p.Key].SequenceEqual(p.Value));
        bool geometry=identity&&before.GeometryProperties.All(p=>{var values=after.GeometryProperties[p.Key];return p.Value.Length==values.Length&&Enumerable.Range(0,p.Value.Length).All(i=>p.Value[i].Length==values[i].Length&&p.Value[i].Zip(values[i],(a,b)=>Math.Abs(a-b)<=Math.Max(1e-12,Math.Max(Math.Abs(a),Math.Abs(b))*1e-9)).All(v=>v));});
        bool mates=before.Mates==after.Mates,studies=before.Studies==after.Studies;
        var result=new{component_identity_preserved=identity,poses_preserved=pose,configurations_preserved=configuration,solid_geometry_properties_and_topology_preserved=geometry,approximate_part_boxes_not_used_as_acceptance=true,mate_identity_and_references_preserved=mates,study_settings_times_activation_preserved=studies,native_drive_inventory_claim="not_proven_by_this_import",pose_translation_tolerance_m=PoseValidation.TranslationToleranceM,pose_rotation_tolerance_rad=PoseValidation.RotationToleranceRad};
        if(!identity||!pose||!configuration||!geometry||!mates||!studies)throw new CadFault("VIRTUAL_EXTERNALIZATION_VERIFICATION_FAILED","外部化后的身份、姿态、配置、几何或配合/算例状态未通过核验；未开放此副本的运动操作。",result);
        return result;
    }
    void RequireCopyReferenceClosure(UserModel model,bool allowVirtualHints) {
        foreach(string p in model.Files)foreach(string reference in DiskDependencies(p,true)) {
            if(allowVirtualHints&&ImportReferences.VirtualHint(reference))continue;
            if(!model.Files.Contains(reference,StringComparer.OrdinalIgnoreCase))throw new CadFault("COPY_REFERENCE_NOT_ISOLATED","副本仍有未隔离依赖，未继续导入。",new{reference_name=Path.GetFileName(reference),model_id=model.Id});
        }
    }
    object ImportWithVirtualParts(string source,string configuration,string purpose,string parentModelId,string copyId) {
        using(var operation=BeginSaveObservationOperation("import_assembly")) {
            LastOperationRestoration="not_required";LoadUserMotion();source=Path.GetFullPath(source);
            if(!source.EndsWith(".SLDASM",StringComparison.OrdinalIgnoreCase)||!File.Exists(source))throw new Exception("ASSEMBLY_FILE_REQUIRED");
            Progress(activeJobId,"scan_dependencies",0,0,null);var catalog=new[]{source}.Concat(DiskDependencies(source,true)).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();var inputs=catalog.Where(p=>!ImportReferences.VirtualHint(p)).ToArray();var hinted=catalog.Where(ImportReferences.VirtualHint).ToArray();
            if(catalog.Length>533||hinted.Length>32)throw new Exception("VIRTUAL_IMPORT_REFERENCE_BUDGET_EXCEEDED");
            foreach(string hint in hinted)if(!hint.EndsWith(".SLDPRT",StringComparison.OrdinalIgnoreCase))throw new CadFault("VIRTUAL_SUBASSEMBLY_UNSUPPORTED","虚拟子装配未纳入受限外部化路径。",new{reference_name=Path.GetFileName(hint)});
            var documents=(Sw.GetDocuments() as object[]??new object[0]).Cast<IModelDoc2>().ToArray();foreach(string p in inputs){ImportReferences.RequireExternal(p);var open=documents.FirstOrDefault(d=>d.GetPathName().Equals(p,StringComparison.OrdinalIgnoreCase));if(open!=null&&open.GetSaveFlag())throw new CadFault("SOURCE_REFERENCE_HAS_UNSAVED_CHANGES","源文档有未保存修改，未从过期磁盘内容导入。",new{reference_name=Path.GetFileName(p)});}
            string uid=copyId??Guid.NewGuid().ToString("N");if(!System.Text.RegularExpressions.Regex.IsMatch(uid,"^[a-f0-9]{32}$"))throw new Exception("INVALID_IMPORT_COPY_ID");string directory=Path.Combine(UserFolder,uid),files=Path.Combine(directory,"files");Directory.CreateDirectory(files);
            var m=new UserModel{Id="user_"+uid,Directory=directory,Purpose=purpose,ParentModelId=parentModelId,ImportState="incomplete",Files=inputs.Select((p,i)=>Path.Combine(files,i.ToString("D4")+"_"+uid.Substring(0,8)+"_"+Path.GetFileName(p))).ToArray()};m.Path=m.Files[0];foreach(string p in inputs)m.SourceHashes[p]=FileHash(p);
            var evidence=new Dictionary<string,object>{{"model_id",m.Id},{"stage","copy_files"},{"materialize_virtual_components",true},{"source_hashes",m.SourceHashes},{"source_documents_directly_opened",false},{"virtual_hint_count",hinted.Length},{"completed",false}};Action saveEvidence=()=>AtomicJson(Path.Combine(directory,"import-evidence.json"),evidence);
            for(int i=0;i<inputs.Length;i++){File.Copy(inputs[i],m.Files[i],false);File.SetAttributes(m.Files[i],FileAttributes.Normal);}SaveUserModel(m);saveEvidence();
            try {
                foreach(string p in inputs){int i=Array.IndexOf(inputs,p);foreach(string reference in DiskDependencies(p,false)){if(ImportReferences.VirtualHint(reference))continue;int j=Array.FindIndex(inputs,v=>v.Equals(reference,StringComparison.OrdinalIgnoreCase));if(j<0||!Sw.ReplaceReferencedDocument(m.Files[i],reference,m.Files[j]))throw new CadFault("COPY_REFERENCE_REDIRECT_FAILED","副本外部引用重定向失败。",new{reference_name=Path.GetFileName(reference),model_id=m.Id});}}
                RequireCopyReferenceClosure(m,true);VerifyUserSources(m);evidence["stage"]="native_virtual_classification";saveEvidence();ImportWitness before;var conversions=new List<object>();int virtualComponentCount=0;
                using(var scope=new Scope(this,m.Path,null)) {
                    if(!string.IsNullOrEmpty(configuration)&&scope.Doc.ConfigurationManager.ActiveConfiguration.Name!=configuration&&!scope.Doc.ShowConfiguration2(configuration))throw new Exception("CONFIGURATION_NOT_FOUND");m.Configuration=scope.Doc.ConfigurationManager.ActiveConfiguration.Name;SaveUserModel(m);before=VirtualWitness(scope.Doc);
                    var components=UserComponents(scope.Doc);var bindings=ImportMateBindings(scope.Doc);var virtuals=components.Where(c=>c.IsVirtual).ToArray();if(virtuals.Length>32)throw new Exception("VIRTUAL_IMPORT_COMPONENT_BUDGET_EXCEEDED");var virtualPaths=new HashSet<string>(virtuals.Select(c=>c.GetPathName()),StringComparer.OrdinalIgnoreCase);
                    foreach(var c in components)if(!c.IsVirtual&&!m.Files.Contains(c.GetPathName(),StringComparer.OrdinalIgnoreCase))throw new CadFault("COPY_REFERENCE_NOT_ISOLATED","原生组件路径未隔离，未外部化。",new{model_id=m.Id,instance=c.Name2});
                    // Native internal dependencies must be closed over already isolated copies or confirmed embedded documents.
                    foreach(var c in virtuals){var doc=(IModelDoc2)c.GetModelDoc2();var partConfigurations=doc.GetConfigurationNames() as Array;if(partConfigurations==null||partConfigurations.Length!=1)throw new CadFault("VIRTUAL_PART_CONFIGURATIONS_UNVALIDATED","虚拟零件多配置未纳入首批外部化验收，未转换。",new{model_id=m.Id,instance=c.Name2});var raw=doc.GetDependencies2(true,true,false) as Array;if(raw==null)throw new CadFault("VIRTUAL_DEPENDENCY_INVENTORY_UNAVAILABLE","无法核验虚拟零件内部依赖，未转换。",new{model_id=m.Id,instance=c.Name2});var values=raw.Cast<object>().Select(Convert.ToString).ToArray();if(values.Length%2!=0)throw new Exception("DEPENDENCY_LIST_INVALID");for(int i=1;i<values.Length;i+=2)if(!m.Files.Contains(values[i],StringComparer.OrdinalIgnoreCase)&&!virtualPaths.Contains(values[i]))throw new CadFault("VIRTUAL_EXTERNAL_REFERENCE_UNVALIDATED","虚拟零件还有未隔离的外部或派生依赖，未自动转换。",new{model_id=m.Id,instance=c.Name2,reference_name=Path.GetFileName(values[i])});}
                    virtualComponentCount=virtuals.Length;evidence["native_virtual_component_count"]=virtuals.Length;evidence["native_virtual_instances"]=virtuals.Select(c=>c.Name2).ToArray();saveEvidence();
                    foreach(var group in virtuals.GroupBy(c=>c.GetPathName(),StringComparer.OrdinalIgnoreCase)) {
                        var members=group.ToArray();string target=Path.Combine(files,"virtual_"+uid.Substring(0,8)+"_"+conversions.Count.ToString("D4")+".SLDPRT");if(File.Exists(target))throw new Exception("VIRTUAL_TARGET_ALREADY_EXISTS");var names=members.Select(c=>c.Name2).ToArray();var nativeIds=members.Select(c=>c.GetID()).ToArray();var oldReferences=members.Select(c=>Convert.ToBase64String((byte[])scope.Doc.Extension.GetPersistReference3(c))).ToArray();m.Files=m.Files.Concat(new[]{target}).ToArray();SaveUserModel(m);evidence["stage"]="externalize_virtual_part";evidence["target_file"]=target;saveEvidence();Progress(activeJobId,"externalize_virtual_part",conversions.Count,virtuals.Length,null);
                        bool saved=members[0].SaveVirtualComponent(target);if(!saved||!File.Exists(target)||!members.Select(c=>c.GetID()).SequenceEqual(nativeIds)||members.Any(c=>c.IsVirtual||!c.GetPathName().Equals(target,StringComparison.OrdinalIgnoreCase)))throw new CadFault("VIRTUAL_EXTERNALIZATION_NOT_CONFIRMED","原生外部化返回、共享实例或目标文件路径未通过核对；未把重复实例拆成独立零件。",new{model_id=m.Id,native_save_virtual_return=saved,instances=names});
                        conversions.Add(new{instances_before=names,instances_after=members.Select(c=>c.Name2).ToArray(),native_component_ids=nativeIds,persistent_references_before=oldReferences,persistent_references_after=members.Select(c=>Convert.ToBase64String((byte[])scope.Doc.Extension.GetPersistReference3(c))).ToArray(),identity_binding="same_native_component_objects_and_unchanged_component_ids_then_reopen",shared_instance_count=members.Length,target=target,native_save_virtual_return=saved});evidence["conversions"]=conversions.ToArray();saveEvidence();
                    }
                    Save(scope.Doc,m.Path);evidence["mate_reference_migration"]=MigrateImportMateReferences(scope.Doc,before,bindings);saveEvidence();VerifyUserSources(m);
                }
                CloseUserDocuments(m.Files);evidence["stage"]="reopen_verify_externalized_copy";saveEvidence();object verification;
                using(var scope=new Scope(this,m.Path,null)){RequireCopyReferenceClosure(m,false);if(UserComponents(scope.Doc).Any(c=>c.IsVirtual))throw new CadFault("VIRTUAL_COMPONENT_STILL_EMBEDDED","重新打开后仍有虚拟组件，未完成导入。",new{model_id=m.Id});verification=CompareVirtualWitness(before,VirtualWitness(scope.Doc));InspectUserCore(m,scope.Doc);Fingerprint(scope.Doc,scope.DocumentPath);}
                VerifyUserSources(m);m.ImportState="complete";SaveUserModel(m);evidence["verification"]=verification;evidence["stage"]="verified_externalized_copy";evidence["completed"]=true;saveEvidence();var checkpoint=CreateUserCheckpoint(m.Id);var preflight=PreflightUserMotion(m.Id,null);LastOperationRestoration="restored";
                return new{model_id=m.Id,path=m.Path,configuration=m.Configuration,file_count=m.Files.Length,source_files_unchanged=true,materialization=new{requested=true,virtual_component_count=virtualComponentCount,externalized_files=conversions.Count,conversions=conversions.Take(20).ToArray(),returned_conversion_count=Math.Min(20,conversions.Count),conversions_truncated=conversions.Count>20,full_evidence_path=Path.Combine(directory,"import-evidence.json"),verification=verification,scope="single_configuration_top_level_loaded_virtual_parts"},checkpoint=checkpoint,preflight=preflight};
            } catch(Exception failure) {
                m.ImportState="incomplete";SaveUserModel(m);
                evidence["stage"]="failed";evidence["failure_code"]=HistoryErrorCode(failure);evidence["failure_details"]=FailureEvidence(failure);bool cleanup=false;
                try{CloseUserDocuments(m.Files);VerifyUserSources(m);cleanup=true;}catch(Exception e){evidence["cleanup_error"]=e.ToString();}
                evidence["copy_closed_and_sources_unchanged"]=cleanup;saveEvidence();LastOperationRestoration=cleanup&&LastContextRestoration!="unknown"?"restored":"unknown";
                throw new CadFault("VIRTUAL_IMPORT_FAILED","受限外部化导入未完成；原始错误和隔离副本已保留，不能使用未完成副本进行运动操作。",new{model_id=m.Id,affected_model_id=m.Id,original_error_code=HistoryErrorCode(failure),original_error=FailureEvidence(failure),copy_closed_and_sources_unchanged=cleanup,import_state=m.ImportState,evidence_path=Path.Combine(directory,"import-evidence.json")});
            }
        }
    }
}
