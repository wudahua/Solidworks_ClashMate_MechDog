using System;
using System.Collections.Generic;
using System.Linq;
using System.Runtime.InteropServices;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    sealed class RepairFeature {
        public int native_feature_id {get;set;}
        public string name {get;set;}
        public string type {get;set;}
    }
    sealed class RepairOccurrence {
        public string component_id {get;set;}
        public string instance {get;set;}
        public int native_feature_id {get;set;}
        public bool is_pattern_instance {get;set;}
        public RepairFeature[] parent_features {get;set;}
    }
    sealed class RepairMirror {
        public int native_feature_id {get;set;}
        public string name {get;set;}
        public bool suppressed {get;set;}
        public bool definition_available {get;set;}
        public string[] definition_source_component_ids {get;set;}
        public RepairFeature[] parent_features {get;set;}
        public RepairFeature[] child_features {get;set;}
    }
    sealed class RepairStructure {
        public RepairOccurrence[] components {get;set;}
        public RepairMirror[] mirrors {get;set;}
        public object[] patterns {get;set;}
        public object[] issues {get;set;}
        public bool feature_inventory_truncated {get;set;}
    }
    sealed class RepairState {
        public Dictionary<string,double[]> Poses;
        public Dictionary<string,string> Parts;
        public Dictionary<int,string> Mates;
        public Dictionary<int,string> Mirrors;
        public string[] PatternOccurrences;
        public string MateParameters;
        public string StudyClocks;
    }
    sealed class AssemblyRepairPlan {
        public string ModelId;
        public int Revision;
        public bool Consumed;
        public RepairState Before;
        public Dictionary<string,string> InputHashes;
        public List<Dictionary<string,object>> MateChanges;
        public RepairMirror[] Mirrors;
    }
    readonly Dictionary<string,AssemblyRepairPlan> assemblyRepairPlans=new Dictionary<string,AssemblyRepairPlan>();

    static void RequireAssemblyRepair(bool condition,string reason) {
        if(!condition)throw new CadFault("ASSEMBLY_REPAIR_SCOPE_UNVERIFIED","装配改造的作用域或保存状态未通过核对。",new{reason});
    }

    static IFeature[] AssemblyMirrorFeatures(IModelDoc2 doc) {
        var result=new List<IFeature>();
        var feature=doc.FirstFeature() as IFeature;
        for(int scanned=0;feature!=null;scanned++) {
            RequireAssemblyRepair(scanned<512,"assembly_feature_inventory_truncated");
            if(feature.GetTypeName2()=="MirrorCompFeat")result.Add(feature);
            feature=feature.GetNextFeature() as IFeature;
        }
        return result.ToArray();
    }

    RepairState AssemblyRepairState(UserModel model,IModelDoc2 doc) {
        var components=UserComponents(doc);
        RequireAssemblyRepair(doc.GetConfigurationCount()==1&&components.Length>1&&components.Length<=128&&
            components.All(c=>ConnectionTopLevel(c)&&!c.IsSuppressed()&&!c.IsVirtual&&!c.IsSpeedPak&&MaterialPart(model,c)!=null),
            "requires_single_configuration_flat_resolved_external_parts");
        var studies=StudyStates(doc);
        RequireAssemblyRepair(studies.All(s=>Math.Abs(s.time_s)<1e-8),"historical_studies_must_be_at_zero_time");
        var mates=EGAllMates(doc);
        return new RepairState{Poses=Transforms(doc),Parts=components.ToDictionary(c=>c.Name2,c=>Json.Serialize(new{path=c.GetPathName(),
            configuration=c.ReferencedConfiguration,fixed_component=c.IsFixed()})),
            Mates=mates.ToDictionary(f=>f.GetID(),f=>f.Name),
            Mirrors=AssemblyMirrorFeatures(doc).ToDictionary(f=>f.GetID(),f=>Json.Serialize(new{f.Name,suppressed=EGSuppressed(f)})),
            PatternOccurrences=components.Where(c=>c.IsPatternInstance()).Select(c=>c.Name2).OrderBy(n=>n,StringComparer.Ordinal).ToArray(),
            MateParameters=ImportMateParameters(doc),StudyClocks=Json.Serialize(studies.OrderBy(s=>s.name,StringComparer.Ordinal)
                .Select(s=>new{s.name,s.time_s,s.type,s.fps,s.duration_s}).ToArray())};
    }

    RepairMirror[] PlanAssemblyMirrorIndependence(IModelDoc2 doc,RepairState before) {
        var structure=Json.Deserialize<RepairStructure>(Json.Serialize(AssemblyStructureObservation(doc)));
        RequireAssemblyRepair(!structure.feature_inventory_truncated && structure.issues.Length==0 && structure.patterns.Length==0,
            "incomplete_mirror_structure_or_non_mirror_pattern");
        var occurrences=structure.components.ToDictionary(c=>c.native_feature_id);
        RequireAssemblyRepair(new HashSet<string>(structure.components.Select(c=>c.instance)).SetEquals(before.Parts.Keys)&&
            new HashSet<string>(structure.components.Where(c=>c.is_pattern_instance).Select(c=>c.instance)).SetEquals(before.PatternOccurrences),
            "mirror_component_inventory_mismatch");
        var members=structure.components.Where(c=>c.is_pattern_instance).ToArray();
        var mirrors=structure.mirrors.Where(m=>m.child_features.Length>0).ToDictionary(m=>m.native_feature_id);
        RequireAssemblyRepair(members.Length>0&&mirrors.Count>0&&mirrors.Count<=16&&
            structure.mirrors.Where(m=>!mirrors.ContainsKey(m.native_feature_id)).All(m=>m.definition_source_component_ids.Length==0),
            "no_supported_complete_mirror_chain");
        Func<RepairOccurrence,int[]> producers=c=>c.parent_features.Where(p=>p.type=="MirrorCompFeat").Select(p=>p.native_feature_id).ToArray();
        RequireAssemblyRepair(members.All(c=>c.parent_features.Length<64&&producers(c).Length>0&&producers(c).All(i=>mirrors.ContainsKey(i)&&
            mirrors[i].child_features.Any(f=>f.native_feature_id==c.native_feature_id))),"incomplete_mirror_member_parents");
        var byComponent=structure.components.ToDictionary(c=>c.component_id);
        var dependencies=new Dictionary<int,HashSet<int>>();
        foreach(var m in mirrors.Values) {
            RequireAssemblyRepair(!m.suppressed&&m.definition_available&&m.parent_features.Length<64&&m.child_features.Length<256&&
                m.definition_source_component_ids.Length>0&&m.child_features.All(c=>occurrences.ContainsKey(c.native_feature_id)&&
                    occurrences[c.native_feature_id].is_pattern_instance&&producers(occurrences[c.native_feature_id]).Contains(m.native_feature_id))&&
                m.definition_source_component_ids.All(byComponent.ContainsKey),"incomplete_mirror_definition_or_children");
            var sources=m.definition_source_component_ids.Select(id=>byComponent[id]).ToArray();
            RequireAssemblyRepair(m.parent_features.Where(f=>f.type=="Reference"||f.type=="ReferencePattern")
                .All(f=>sources.Any(c=>c.native_feature_id==f.native_feature_id)),"unbound_mirror_source");
            dependencies.Add(m.native_feature_id,new HashSet<int>(sources.Where(c=>c.is_pattern_instance).SelectMany(producers)
                .Concat(m.parent_features.Where(f=>f.type=="MirrorCompFeat").Select(f=>f.native_feature_id))));
        }
        var remaining=new HashSet<int>(mirrors.Keys);
        var order=new List<RepairMirror>();
        RequireAssemblyRepair(dependencies.Values.All(v=>v.All(remaining.Contains)),"unbound_mirror_dependency");
        while(remaining.Count>0) {
            var leaves=remaining.Where(id=>!remaining.Any(other=>dependencies[other].Contains(id))).OrderBy(id=>id).ToArray();
            RequireAssemblyRepair(leaves.Length>0,"cyclic_mirror_dependencies");
            // Keep each dependent branch adjacent to its source when possible.
            var selectedId=leaves[0];
            order.Add(mirrors[selectedId]);remaining.Remove(selectedId);
        }
        return order.ToArray();
    }

    static bool RepairInventoryMatches<T>(Dictionary<T,string> expected,Dictionary<T,string> actual) {
        return expected.Count==actual.Count&&expected.All(p=>actual.ContainsKey(p.Key)&&actual[p.Key]==p.Value);
    }

    void VerifyAssemblyRepairState(UserModel model,IModelDoc2 doc,RepairState before,string expectedMates,int[] removed,bool requireIndependent) {
        var after=AssemblyRepairState(model,doc);
        RequireAssemblyRepair(RepairInventoryMatches(before.Parts,after.Parts)&&RepairInventoryMatches(before.Mates,after.Mates)&&
            RepairInventoryMatches(before.Mirrors.Where(p=>!removed.Contains(p.Key)).ToDictionary(p=>p.Key,p=>p.Value),after.Mirrors)&&
            before.StudyClocks==after.StudyClocks&&expectedMates==after.MateParameters&&
            (requireIndependent?after.PatternOccurrences.Length==0:after.PatternOccurrences.SequenceEqual(before.PatternOccurrences))&&
            before.Poses.Count==after.Poses.Count&&before.Poses.All(p=>after.Poses.ContainsKey(p.Key)&&PoseValidation.Matches(p.Value,after.Poses[p.Key])),
            "assembly_repair_changed_unapproved_state");
        RequireMatesHealthy(doc);
    }

    public object PreviewAssemblyRepair(string id,string proposalJson,bool independentizeMirrors) {
        var model=GetUserModel(id);
        var data=Json.Deserialize<Dictionary<string,object>>(proposalJson);
        using(var scope=new Scope(this,model.Path,null)) {
            var doc=scope.Doc;Fingerprint(doc,model.Path);VerifyUserSources(model);RequireMatesHealthy(doc);
            var before=AssemblyRepairState(model,doc);
            var changes=ReadConnectionMateChanges(doc,data);
            RequireAssemblyRepair(independentizeMirrors?changes.Count==0:changes.Count>0,"one_distinct_repair_operation_required");
            ConnectionExpectedMateParameters(before.MateParameters,changes);
            var mirrors=independentizeMirrors?PlanAssemblyMirrorIndependence(doc,before):new RepairMirror[0];
            var plan=new AssemblyRepairPlan{ModelId=id,Revision=model.Revision,Before=before,MateChanges=changes,Mirrors=mirrors,
                InputHashes=model.Files.ToDictionary(p=>p,FileHash,StringComparer.OrdinalIgnoreCase)};
            var planId=Guid.NewGuid().ToString("N");assemblyRepairPlans[planId]=plan;
            return new{plan_id=planId,model_id=id,mate_changes=changes,
                mirror_features=mirrors.Select(m=>new{m.native_feature_id,m.name}).ToArray(),
                independent_occurrences=independentizeMirrors?before.PatternOccurrences:new string[0],
                component_count=before.Parts.Count,existing_mate_count=before.Mates.Count,expected_added_mates=0,
                write_dispatched=false,requires_explicit_confirmation=true,motion_verified=false};
        }
    }

    void DissolveAssemblyRepairMirror(IModelDoc2 doc,RepairMirror item) {
        var feature=AssemblyMirrorFeatures(doc).SingleOrDefault(f=>f.GetID()==item.native_feature_id);
        RequireAssemblyRepair(feature!=null&&feature.Name==item.name&&!EGSuppressed(feature),"mirror_feature_identity_changed");
        doc.ClearSelection2(true);
        try {
            var selection=(ISelectionMgr)doc.SelectionManager;
            RequireAssemblyRepair(feature.Select2(false,0)&&selection.GetSelectedObjectCount2(-1)==1,"mirror_feature_selection_failed");
            var selected=selection.GetSelectedObject6(1,-1) as IFeature;
            RequireAssemblyRepair(selected!=null&&selected.GetID()==item.native_feature_id&&selected.GetTypeName2()=="MirrorCompFeat",
                "mirror_feature_selection_identity_changed");
            RequireAssemblyRepair(((IAssemblyDoc)doc).DissolveComponentPattern()&&
                !AssemblyMirrorFeatures(doc).Any(f=>f.GetID()==item.native_feature_id),"native_mirror_dissolve_not_verified");
        } finally {doc.ClearSelection2(true);}
    }

    public object ApplyAssemblyRepair(string planId,bool confirmed) {
        AssemblyRepairPlan plan;
        if(!assemblyRepairPlans.TryGetValue(planId,out plan)||plan.Consumed)throw new CadFault("CONNECTION_PLAN_STALE","装配改造方案不存在或已消费。");
        if(!confirmed)throw new CadFault("CONFIRMATION_REQUIRED","须确认具体旧配合状态或镜向独立化范围。");
        var model=GetUserModel(plan.ModelId);
        if(model.Revision!=plan.Revision||plan.InputHashes.Any(p=>FileHash(p.Key)!=p.Value))
            throw new CadFault("CONNECTION_PLAN_STALE","装配副本自预演后已变化，未执行改造。");
        var before=plan.Before;var removed=plan.Mirrors.Select(m=>m.native_feature_id).ToArray();
        var expectedMates=ConnectionExpectedMateParameters(before.MateParameters,plan.MateChanges);
        using(var scope=new Scope(this,model.Path,null)) {
            VerifyUserSources(model);
            VerifyAssemblyRepairState(model,scope.Doc,before,before.MateParameters,new int[0],false);
            if(removed.Length>0)
                RequireAssemblyRepair(PlanAssemblyMirrorIndependence(scope.Doc,before).Select(m=>m.native_feature_id).SequenceEqual(removed),
                    "mirror_dependency_order_changed");
        }
        var checkpoint=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(CreateUserCheckpoint(model.Id)));
        string checkpointId=(string)checkpoint["checkpoint_id"];
        var completedMirrors=new List<int>();
        plan.Consumed=true;
        LastOperationRestoration="pending";
        try {
            using(var scope=new Scope(this,model.Path,null)) {
                var doc=scope.Doc;
                try {
                    PrepareConnectionModelScope(model,doc);
                    VerifyAssemblyRepairState(model,doc,before,before.MateParameters,new int[0],false);
                    ApplyConnectionMateChanges(doc,plan.MateChanges);
                    foreach(var item in plan.Mirrors) {
                        Progress(activeJobId,"repair_dissolve_mirrors",completedMirrors.Count,removed.Length,null);
                        DissolveAssemblyRepairMirror(doc,item);
                        completedMirrors.Add(item.native_feature_id);
                    }
                    RequireAssemblyRepair(doc.EditRebuild3(),"assembly_repair_rebuild_failed");
                    VerifyAssemblyRepairState(model,doc,before,expectedMates,removed,removed.Length>0);
                    Progress(activeJobId,"repair_save_and_verify",0,0,null);
                    Save(doc,model.Path);
                    VerifyAssemblyRepairState(model,doc,before,expectedMates,removed,removed.Length>0);
                } catch(Exception error) {scope.DeferRestoration(error);throw;}
            }
            CloseUserDocuments(model.Files);
            using(var reopened=new Scope(this,model.Path,null)) {
                Fingerprint(reopened.Doc,model.Path);
                VerifyAssemblyRepairState(model,reopened.Doc,before,expectedMates,removed,removed.Length>0);
            }
            VerifyUserSources(model);
            RequireAssemblyRepair(plan.InputHashes.Where(p=>!p.Key.Equals(model.Path,StringComparison.OrdinalIgnoreCase))
                .All(p=>FileHash(p.Key)==p.Value),"dependent_part_file_changed");
            model.Revision++;SaveUserModel(model);LastOperationRestoration="restored";
            return new{model_id=model.Id,checkpoint_id=checkpointId,mate_changes=plan.MateChanges,mirror_feature_ids=removed,
                independent_occurrences=removed.Length>0?before.PatternOccurrences:new string[0],added_mates=0,
                mate_inventory_verified=true,poses_references_fixed_flags_verified=true,reopened_verified=true,
                source_files_unchanged=true,motion_verified=false};
        } catch(Exception failure) {
            if(failure is COMException||failure is NativeCommandStateException||LastContextRestoration=="unknown") {
                LastOperationRestoration="unknown";throw;
            }
            try {RestoreUserCheckpoint(model.Id,checkpointId);}
            catch(Exception rollback) {
                LastOperationRestoration="unknown";
                throw new CadFault("CONNECTION_NATIVE_UNKNOWN","改造失败后无法核验恢复。",new{checkpoint_id=checkpointId,
                    completed_mirror_feature_ids=completedMirrors,original_failure=FailureEvidence(failure),rollback_failure=FailureEvidence(rollback)});
            }
            LastOperationRestoration="restored";
            throw new CadFault("ASSEMBLY_REPAIR_ROLLED_BACK","装配改造未通过，已恢复检查点。",new{checkpoint_id=checkpointId,
                completed_mirror_feature_ids=completedMirrors,original_failure=FailureEvidence(failure),rollback_verified=true});
        }
    }
}
