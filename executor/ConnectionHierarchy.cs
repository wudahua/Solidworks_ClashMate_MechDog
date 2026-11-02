using System;
using System.Linq;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;

// Private next-stage observer. No solving-mode setter or hierarchy mutation.
public partial class Cad {
    class ConnectionHierarchyNode {
        public string Id,Parent,Instance,Configuration;public int DocumentType;public int? Solving;public bool? ParentDocumentFixed;
    }
    Dictionary<string,ConnectionHierarchyNode> ConnectionHierarchyObservation(IModelDoc2 doc) {
        var cs=UserComponents(doc);var rows=new Dictionary<string,ConnectionHierarchyNode>();
        var localChildren=new Dictionary<string,Dictionary<string,IComponent2>>(StringComparer.OrdinalIgnoreCase);
        foreach(var c in cs) {
            var model=c.GetModelDoc2() as IModelDoc2;
            if(c.IsSuppressed()||c.IsSpeedPak||c.IsVirtual||model==null)throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","子装配层级要求完整解析的外部组件，未静默跳过缺失或虚拟节点。");
            int kind=model.GetType();if(kind!=1&&kind!=2)throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","组件文档类型尚未支持。");
            var parent=c.GetParent() as IComponent2;string parentId=parent==null||parent.IsRoot()?null:GTComponentId(doc,parent);
            string id=GTComponentId(doc,c);
            bool? parentFixed=null;
            if(parentId!=null) {
                var owner=parent.GetModelDoc2() as IModelDoc2;
                if(owner==null||owner.GetType()!=2||owner.ConfigurationManager.ActiveConfiguration.Name!=parent.ReferencedConfiguration)
                    throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","内部固定状态要求匹配的所属装配配置，未从顶层IsFixed推断。");
                string key=owner.GetPathName()+"|"+parent.ReferencedConfiguration;Dictionary<string,IComponent2> children;
                if(!localChildren.TryGetValue(key,out children)) {
                    children=(((IAssemblyDoc)owner).GetComponents(true) as object[]??new object[0]).Cast<IComponent2>().ToDictionary(v=>v.Name2,StringComparer.Ordinal);
                    localChildren.Add(key,children);
                }
                string prefix=parent.Name2+"/";
                if(!c.Name2.StartsWith(prefix,StringComparison.Ordinal))throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","内部组件完整名称未匹配父级路径。");
                IComponent2 local;
                if(!children.TryGetValue(c.Name2.Substring(prefix.Length),out local)||!String.Equals(local.GetPathName(),c.GetPathName(),StringComparison.OrdinalIgnoreCase)||local.ReferencedConfiguration!=c.ReferencedConfiguration)
                    throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","无法核对所属文档中的同一组件实例，未猜测内部固定标志。");
                parentFixed=local.IsFixed();
            }
            rows.Add(id,new ConnectionHierarchyNode{Id=id,Instance=c.Name2,Parent=parentId,DocumentType=kind,Solving=kind==2?(int?)c.Solving:null,Configuration=c.ReferencedConfiguration,ParentDocumentFixed=parentFixed});
        }
        foreach(var row in rows.Values) {
            if(row.Parent!=null&&(!rows.ContainsKey(row.Parent)||rows[row.Parent].DocumentType!=2))throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","组件父级不在完整原生清单中，未假定其相对地面固定。");
            var seen=new HashSet<string>();string cursor=row.Id;
            while(cursor!=null) {
                if(!seen.Add(cursor)||seen.Count>8)throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","组件层级循环或超出已核验深度。");
                cursor=rows[cursor].Parent;
            }
            if(row.DocumentType==2&&row.Solving!=0&&row.Solving!=1)throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","子装配刚性／柔性状态未明确读出。");
        }
        return rows;
    }
    bool ConnectionTopLevel(IComponent2 component) {
        var parent=component.GetParent() as IComponent2;return parent==null||parent.IsRoot();
    }
    bool ConnectionReferenceOwnerAllowed(IModelDoc2 doc,IComponent2 physical,IComponent2 logical) {
        if(physical==null||logical==null)return false;
        string target=GTComponentId(doc,logical);var cursor=physical;var seen=new HashSet<string>();
        for(int depth=0;depth<8;depth++) {
            string id=GTComponentId(doc,cursor);if(!seen.Add(id))return false;
            if(id==target)return true;
            var parent=cursor.GetParent() as IComponent2;
            if(parent==null||parent.IsRoot()||parent.Solving!=0)return false;
            cursor=parent;
        }
        return false;
    }
    string ConnectionSelectedReferenceOwner(IModelDoc2 doc,object reference,IComponent2 logical) {
        var entity=reference as IEntity;
        var owner=entity==null?logical:entity.GetComponent() as IComponent2;
        if(!ConnectionReferenceOwnerAllowed(doc,owner,logical))throw new CadFault("CONNECTION_REFERENCE_INVALID","材料参考未归属于明确刚性体或其已核验刚性子件。");
        return GTComponentId(doc,owner);
    }
    Dictionary<string,ConnectionHierarchyNode> ConnectionHierarchyForModel(UserModel model,IModelDoc2 doc) {
        return model.Files.Count(p=>p.EndsWith(".SLDASM",StringComparison.OrdinalIgnoreCase))>1?ConnectionHierarchyObservation(doc):null;
    }
    object WithConnectionHierarchy(object row,Dictionary<string,ConnectionHierarchyNode> hierarchy,string id) {
        if(hierarchy==null)return row;
        var node=hierarchy[id];var data=Json.Deserialize<Dictionary<string,object>>(Json.Serialize(row));
        data["native_hierarchy_observed"]=true;data["parent_component_id"]=node.Parent;data["document_type"]=node.DocumentType;data["subassembly_solving"]=node.Solving;
        data["parent_document_fixed_component"]=node.ParentDocumentFixed;
        data["fixed_flag_observation_scope"]=node.Parent==null?"assembly_root":"root_context_only";
        return data;
    }
    class ConnectionInternalWitness {
        public string Parameters;public Dictionary<string,double[]> LocalPoses;
    }
    double[] ConnectionRelativePose(double[] child,double[] parent) {
        if(!ConnectionRigidTransform(child)||!ConnectionRigidTransform(parent))throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","内部相对姿态要求单位尺度刚体变换。");
        var result=new double[16];result[12]=1;
        for(int i=0;i<3;i++)for(int j=0;j<3;j++)for(int k=0;k<3;k++)result[3*i+j]+=child[3*i+k]*parent[3*j+k];
        for(int j=0;j<3;j++)for(int k=0;k<3;k++)result[9+j]+=(child[9+k]-parent[9+k])*parent[3*j+k];
        return result;
    }
    ConnectionInternalWitness ConnectionInternalAssemblyWitness(UserModel model,IModelDoc2 doc) {
        var hierarchy=ConnectionHierarchyForModel(model,doc);if(hierarchy==null)return null;
        var records=new SortedDictionary<string,object>(StringComparer.OrdinalIgnoreCase);var cs=UserComponents(doc);var poses=Transforms(doc);var local=new Dictionary<string,double[]>();
        foreach(var node in hierarchy.Values)if(node.Parent!=null)local[node.Id]=ConnectionRelativePose(poses[node.Instance],poses[hierarchy[node.Parent].Instance]);
        foreach(var c in cs) {
            var node=hierarchy[GTComponentId(doc,c)];if(node.DocumentType!=2)continue;
            if(node.Solving!=0)throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","首批仅支持已观察为刚性的子装配，未改变求解方式。");
            var assembly=c.GetModelDoc2() as IModelDoc2;string path=assembly.GetPathName();string configuration=assembly.ConfigurationManager.ActiveConfiguration.Name;
            if(configuration!=node.Configuration)throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","子装配引用配置与当前可读文档不一致，未切换配置或猜测内部状态。");
            if(records.ContainsKey(path))continue;
            RequireMatesHealthy(assembly);
            var supportedTypes=new HashSet<int>(new[]{0,1,2,3,5,6,10,16});
            var unsupported=BasicMateFeatures(assembly).Select(feature=>new{feature_id=feature.GetID(),name=feature.Name,type=((IMate2)feature.GetSpecificFeature2()).Type})
                .Where(mate=>!supportedTypes.Contains(mate.type)).ToArray();
            if(unsupported.Length>0)throw new CadFault("CONNECTION_SCOPE_UNSUPPORTED","内部配合参数尚不能完整记录，保留调查结果，未宣称内部状态已验证。",new{path=path,unsupported_internal_mates=unsupported});
            var children=(((IAssemblyDoc)assembly).GetComponents(true) as object[]??new object[0]).Cast<IComponent2>().OrderBy(v=>v.Name2,StringComparer.Ordinal).Select(v=>new{
                instance=v.Name2,configuration=v.ReferencedConfiguration,fixed_component=v.IsFixed(),solving=v.Solving}).ToArray();
            records[path]=new{path=path,configuration=configuration,children=children,mate_parameters=ImportMateParameters(assembly),
                material_reference_identity=ProbeWorkingState.MateIdentity(assembly)};
        }
        return new ConnectionInternalWitness{Parameters=Json.Serialize(new{hierarchy=hierarchy.Values.OrderBy(v=>v.Id).Select(v=>new{v.Id,v.Parent,v.DocumentType,v.Solving,v.Configuration,v.ParentDocumentFixed}).ToArray(),assemblies=records}),LocalPoses=local};
    }
    bool ConnectionInternalWitnessMatches(ConnectionInternalWitness expected,ConnectionInternalWitness actual) {
        if(expected==null||actual==null)return expected==null&&actual==null;
        return expected.Parameters==actual.Parameters&&expected.LocalPoses.Count==actual.LocalPoses.Count&&
            expected.LocalPoses.All(v=>actual.LocalPoses.ContainsKey(v.Key)&&PoseValidation.Matches(v.Value,actual.LocalPoses[v.Key]));
    }
}
