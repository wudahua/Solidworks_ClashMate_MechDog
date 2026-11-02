using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

// A single document/configuration is edited per declared transaction. The full
// imported file set remains in every checkpoint, including the outer assembly.
public partial class Cad {
    class ConnectionLayerState {
        public string Root,Selected,Instance,Configuration,ProtectedParameters;
        public Dictionary<string,double[]> RootPoses;
        public Dictionary<string,string> PartFiles;
    }
    readonly Dictionary<string,ConnectionLayerState> connectionLayers=new Dictionary<string,ConnectionLayerState>();
    string ConnectionLayerProtectedParameters(UserModel m,IModelDoc2 root,string selected) {
        var all=UserComponents(root);var documents=new Dictionary<string,IModelDoc2>(StringComparer.OrdinalIgnoreCase);
        documents[root.GetPathName()]=root;
        foreach(var c in all) {
            var d=c.GetModelDoc2() as IModelDoc2;
            if(c.IsSuppressed()||c.IsVirtual||c.IsSpeedPak||d==null||!m.Files.Contains(c.GetPathName(),StringComparer.OrdinalIgnoreCase))
                throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","分层检查要求全部节点完整解析并位于当前隔离副本。");
            if(d.GetType()==2) {
                if(c.Solving!=0||d.ConfigurationManager.ActiveConfiguration.Name!=c.ReferencedConfiguration)
                    throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","子装配须保持原有刚性及匹配配置，未自动切换。");
                documents[d.GetPathName()]=d;
            }
        }
        var rows=new SortedDictionary<string,object>(StringComparer.OrdinalIgnoreCase);
        foreach(var pair in documents)if(!String.Equals(pair.Key,selected,StringComparison.OrdinalIgnoreCase)) {
            var doc=pair.Value;RequireMatesHealthy(doc);
            rows[pair.Key]=new {configuration=doc.ConfigurationManager.ActiveConfiguration.Name,
                parameters=ImportMateParameters(doc),references=ProbeWorkingState.MateIdentity(doc),
                direct_children=(((IAssemblyDoc)doc).GetComponents(true) as object[]??new object[0]).Cast<IComponent2>()
                    .OrderBy(c=>c.Name2,StringComparer.Ordinal).Select(c=>new{instance=c.Name2,path=c.GetPathName(),
                        configuration=c.ReferencedConfiguration,fixed_component=c.IsFixed(),solving=c.Solving}).ToArray()};
        }
        return Json.Serialize(rows);
    }
    public object SurveyConnectionLayers(string id) {
        var m=GetUserModel(id);ConnectionLayerState state;
        string root=connectionLayers.TryGetValue(id,out state)?state.Root:m.Path;
        using(var scope=new Scope(this,root,null)) {
            var doc=scope.Doc;var cs=UserComponents(doc);var hierarchy=ConnectionHierarchyForModel(m,doc);
            bool complete=cs.All(c=>!c.IsSuppressed()&&!c.IsVirtual&&!c.IsSpeedPak&&c.GetModelDoc2()!=null&&m.Files.Contains(c.GetPathName(),StringComparer.OrdinalIgnoreCase));
            bool rigidTree=hierarchy==null||hierarchy.Values.All(n=>n.DocumentType!=2||n.Solving==0);
            var rows=new List<object>();
            foreach(var c in cs) {
                var child=c.GetModelDoc2() as IModelDoc2;if(child==null||child.GetType()!=2)continue;
                string path=c.GetPathName();bool unique=cs.Count(v=>String.Equals(v.GetPathName(),path,StringComparison.OrdinalIgnoreCase))==1;
                bool eligible=complete&&rigidTree&&unique&&!c.IsSuppressed()&&!c.IsVirtual&&!c.IsSpeedPak&&c.Solving==0&&
                    child.ConfigurationManager.ActiveConfiguration.Name==c.ReferencedConfiguration&&m.Files.Contains(path,StringComparer.OrdinalIgnoreCase);
                var direct=(((IAssemblyDoc)child).GetComponents(true) as object[]??new object[0]).Cast<IComponent2>().ToArray();
                rows.Add(new{instance=c.Name2,component_id=GTComponentId(doc,c),document_path=path,configuration=c.ReferencedConfiguration,
                    native_rigid=c.Solving==0,shared_document_instances=cs.Count(v=>String.Equals(v.GetPathName(),path,StringComparison.OrdinalIgnoreCase)),
                    internal_direct_components=direct.Length,internal_fixed_components=direct.Count(v=>v.IsFixed()),
                    internal_mates=BasicMateFeatures(child).Length,scope_selectable=eligible,
                    internal_completeness="not_certified_by_rigid_parent_mode_requires_scoped_goal_review",
                    refusal_reason=eligible?null:!unique?"shared_document_requires_multi_instance_policy":"unresolved_flexible_or_configuration_mismatch"});
            }
            return new{root_assembly_path=root,active_document_path=m.Path,layers=rows,inventory_complete=complete,
                one_document_per_transaction=true,automatic_recursive_completion=false,
                scope="document_level_inventory_not_internal_mate_completeness_or_design_intent",source_files_unchanged=UserSourcesUnchanged(m)};
        }
    }
    public object SelectConnectionLayer(string id,string instance) {
        var m=GetUserModel(id);
        if(connectionLayers.ContainsKey(id))throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","本次已选择内部装配范围；后续任务使用成果总装继续其他层，不在活方案中切换文档。");
        string root=m.Path;IComponent2 selected;string path,configuration;ConnectionLayerState state;
        using(var scope=new Scope(this,root,null)) {
            var doc=scope.Doc;var cs=UserComponents(doc);ConnectionHierarchyObservation(doc);
            var matches=cs.Where(c=>String.Equals(c.Name2,instance,StringComparison.Ordinal)).ToArray();
            if(matches.Length!=1)throw new CadFault("CONNECTION_INTENT_INVALID","内部装配范围必须匹配当前清单中的唯一完整实例名称，未猜测或截断名称。");
            selected=matches[0];var child=selected.GetModelDoc2() as IModelDoc2;path=selected.GetPathName();configuration=selected.ReferencedConfiguration;
            if(child==null||child.GetType()!=2||selected.Solving!=0||selected.IsVirtual||selected.IsSuppressed()||selected.IsSpeedPak||
                child.ConfigurationManager.ActiveConfiguration.Name!=configuration||!m.Files.Contains(path,StringComparer.OrdinalIgnoreCase)||
                cs.Count(c=>String.Equals(c.GetPathName(),path,StringComparison.OrdinalIgnoreCase))!=1)
                throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","首批内部补齐只支持独立文档的唯一刚性实例及匹配配置，不改共享实例、柔性或配置。");
            RequireMatesHealthy(child);
            state=new ConnectionLayerState{Root=root,Selected=path,Instance=instance,Configuration=configuration,RootPoses=Transforms(doc),
                ProtectedParameters=ConnectionLayerProtectedParameters(m,doc,path),
                PartFiles=m.Files.Where(p=>p.EndsWith(".SLDPRT",StringComparison.OrdinalIgnoreCase)).ToDictionary(p=>p,p=>FileHash(p),StringComparer.OrdinalIgnoreCase)};
        }
        using(var childScope=new Scope(this,path,null)) {
            if(childScope.Doc.ConfigurationManager.ActiveConfiguration.Name!=configuration)throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","打开子装配后的活动配置不符，未切换配置。");
        }
        m.Path=path;m.Configuration=configuration;m.Components.Clear();m.Entities.Clear();m.EntityRegistrationRevisions.Clear();m.EntityQueries.Clear();
        m.Revision++;SaveUserModel(m);
        using(var active=new Scope(this,path,null)){InspectUserCore(m,active.Doc);SaveUserModel(m);}
        connectionModelScopes.Remove(id);connectionLayers.Add(id,state);
        return new{model_id=id,root_assembly_path=root,selected_assembly_path=path,selected_instance=instance,configuration=configuration,
            full_import_file_count=m.Files.Length,protected_parameters_sha256=ConnectionRequestFingerprint.Hash(state.ProtectedParameters),original_files_written=false,mates_written=false,configuration_changed=false,
            shared_document_policy="unique_instance_only",parent_mode_changed=false};
    }
    public object VerifyConnectionLayer(string id,bool rebuildRoot=false) {
        var m=GetUserModel(id);ConnectionLayerState state;
        if(!connectionLayers.TryGetValue(id,out state))return new{applicable=false,passed=true};
        if(!String.Equals(m.Path,state.Selected,StringComparison.OrdinalIgnoreCase))throw new CadFault("CONNECTION_EVIDENCE_FAILED","当前登记文档与已绑定的内部范围不同。");
        using(var scope=new Scope(this,state.Root,null)) {
            var doc=scope.Doc;
            if(rebuildRoot&&!doc.EditRebuild3())throw new CadFault("CONNECTION_EVIDENCE_FAILED","内部补齐后的总装重建未通过，不能保留为成功。");
            var actual=Transforms(doc);bool poses=actual.Count==state.RootPoses.Count&&state.RootPoses.All(p=>actual.ContainsKey(p.Key)&&PoseValidation.Matches(p.Value,actual[p.Key]));
            string protectedParameters=ConnectionLayerProtectedParameters(m,doc,state.Selected);
            bool parameters=state.ProtectedParameters==protectedParameters;
            bool parts=state.PartFiles.All(p=>File.Exists(p.Key)&&FileHash(p.Key)==p.Value);
            if(!poses||!parameters||!parts||!UserSourcesUnchanged(m))throw new CadFault("CONNECTION_EVIDENCE_FAILED","总装姿态、非目标层配合／固定状态、零件文件或源文件发生改变。",new{root_poses_preserved=poses,non_target_assembly_parameters_preserved=parameters,part_files_preserved=parts});
            if(rebuildRoot){SaveOwnedDocuments(m);VerifyConnectionLayer(id,false);}
            return new{applicable=true,passed=true,root_assembly_path=state.Root,selected_assembly_path=state.Selected,
                selected_instance=state.Instance,root_poses_preserved=true,non_target_assembly_parameters_preserved=true,
                root_poses_expected=state.RootPoses,root_poses_actual=actual,
                protected_parameters_expected_sha256=ConnectionRequestFingerprint.Hash(state.ProtectedParameters),
                protected_parameters_actual_sha256=ConnectionRequestFingerprint.Hash(protectedParameters),
                preserved_part_file_sha256=state.PartFiles,
                part_files_preserved=true,source_files_unchanged=true,root_rebuilt=rebuildRoot,
                internal_completeness_scope="declared_targets_in_selected_document_only_not_recursive_all_layers"};
        }
    }
}
