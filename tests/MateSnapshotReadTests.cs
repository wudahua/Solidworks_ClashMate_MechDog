// Compiles the actual collectors against getter stand-ins. No COM or SolidWorks.
using System;
using System.Linq;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using SolidWorks.Interop.sldworks;
namespace SolidWorks.Interop.swconst {public enum swMateType_e {swMateCONCENTRIC=1}}
namespace SolidWorks.Interop.sldworks {
 public interface IModelDocExtension {object GetPersistReference3(object value);}
 public interface IModelDoc2 {IModelDocExtension Extension{get;}}
 public interface IComponent2 {string Name2{get;}}
 public interface IMateEntity2 {object Reference{get;}object ReferenceComponent{get;}int ReferenceType2{get;}}
 public interface IMate2 {int Type{get;}int Alignment{get;}object[] DisplayDimension2{get;}int GetMateEntityCount();IMateEntity2 MateEntity(int i);}
 public interface IFeature {int GetID();string GetTypeName2();object GetSpecificFeature2();object GetDefinition();object IsSuppressed2(int scope,object configs);string Name{get;}}
 public interface IScrewMateFeatureData {int RevolutionType{get;}double RevolutionVal{get;}bool Reverse{get;}int MateAlignment{get;}}
 public interface IDistanceMateFeatureData {bool IsAdvancedMate{get;}double MinimumDistance{get;}double MaximumDistance{get;}bool FlipDimension{get;}int MateAlignment{get;}}
 public interface IConcentricMateFeatureData {bool LockRotation{get;}}
 public interface IGearMateFeatureData {double GearRatioNumerator{get;}double GearRatioDenominator{get;}bool Reverse{get;}}
 public interface IDisplayDimension {object GetDimension2(int index);}
 public interface IDimension {double SystemValue{get;}}
}
class ReadComponent:IComponent2 {
 public string Value;public int Reads;public bool Throw;
 public string Name2{get{Reads++;if(Throw)throw new InvalidOperationException("COMPONENT_NAME_READ_FAILED");return Value;}}
}
class ReadEntity:IMateEntity2 {
 public object Ref,Owner;public object Reference{get{return Ref;}}public object ReferenceComponent{get{return Owner;}}public int ReferenceType2{get{return 2;}}
}
class ReadDimension:IDimension,IDisplayDimension {
 public double Value;public double SystemValue{get{return Value;}}public object GetDimension2(int i){return this;}
}
class ReadDefinition:IConcentricMateFeatureData,IGearMateFeatureData,IScrewMateFeatureData,IDistanceMateFeatureData {
 public bool Locked=true,Reversed=true;public double Numerator=2,Denominator=3;
 public int RevolutionMode=1;public double Lead=.3,Minimum=.001,Maximum=.755;public bool Advanced;
 public int RevolutionType{get{return RevolutionMode;}}public double RevolutionVal{get{return Lead;}}public int MateAlignment{get{return 1;}}
 public bool IsAdvancedMate{get{return Advanced;}}public double MinimumDistance{get{return Minimum;}}public double MaximumDistance{get{return Maximum;}}public bool FlipDimension{get{return false;}}
 public bool LockRotation{get{return Locked;}}public double GearRatioNumerator{get{return Numerator;}}
 public double GearRatioDenominator{get{return Denominator;}}public bool Reverse{get{return Reversed;}}
}
class ReadMate:IMate2 {
 public int Kind,TypeReads;public bool MissingDimension;public ReadDimension Dimension=new ReadDimension();public ReadEntity[] Entities;
 public int Type{get{TypeReads++;return Kind;}}public int Alignment{get{return 1;}}
 public object[] DisplayDimension2{get{return new object[]{MissingDimension?null:Dimension};}}
 public int GetMateEntityCount(){return Entities.Length;}public IMateEntity2 MateEntity(int i){return Entities[i];}
}
class ReadFeature:IFeature {
 public int Id,SpecificReads;public bool Suppressed;public ReadMate Mate;public ReadDefinition Definition=new ReadDefinition();public bool Limit,MissingDefinition;
 public string GetTypeName2(){return Limit?"MateLimitDistanceDim":"MateDistanceDim";}
 public int GetID(){return Id;}public object GetSpecificFeature2(){SpecificReads++;return Mate;}public object GetDefinition(){return MissingDefinition?null:Definition;}
 public object IsSuppressed2(int scope,object configs){if(scope!=1||configs!=null)throw new Exception("SUPPRESSION_SCOPE_CHANGED");return new[]{Suppressed};}
 public string Name{get{return "配合"+Id;}}
}
class ReadExtension:IModelDocExtension {
 public int Calls;public Dictionary<object,object> Values=new Dictionary<object,object>();
 public object GetPersistReference3(object value){Calls++;object result;return Values.TryGetValue(value,out result)?result:null;}
}
class ReadDocument:IModelDoc2 {
 public IFeature[] Features;public ReadExtension Ext=new ReadExtension();public IModelDocExtension Extension{get{return Ext;}}
}
class ReadWorld {
 public ReadDocument Doc=new ReadDocument();public ReadComponent A=new ReadComponent{Value="组件A"},B=new ReadComponent{Value="组件B"};
 public ReadFeature F(int id){return Doc.Features.Cast<ReadFeature>().First(f=>f.Id==id);}
 public static ReadWorld Create() {
  var w=new ReadWorld();int[] kinds={0,1,5,6,10,16};var fs=new List<ReadFeature>();
  for(int i=0;i<6;i++) {
   var entities=new[]{new ReadEntity{Ref=new object(),Owner=w.A},new ReadEntity{Ref=new object(),Owner=w.B}};
   foreach(var entity in entities)w.Doc.Ext.Values[entity.Ref]=new byte[]{(byte)(i+1),(byte)(entity.Owner==w.A?1:2)};
   var mate=new ReadMate{Kind=kinds[i],Entities=entities};mate.Dimension.Value=i==2?.0123:.523;
   fs.Add(new ReadFeature{Id=i+1,Mate=mate});
  }
  w.Doc.Features=fs.AsEnumerable().Reverse().Cast<IFeature>().ToArray();return w;
 }
 public void Reset(){foreach(var f in Doc.Features.Cast<ReadFeature>()){f.SpecificReads=0;f.Mate.TypeReads=0;}A.Reads=0;B.Reads=0;Doc.Ext.Calls=0;}
 public object Counts(){return new{type_reads=Doc.Features.Cast<ReadFeature>().Sum(f=>f.Mate.TypeReads),specific_reads=Doc.Features.Cast<ReadFeature>().Sum(f=>f.SpecificReads),component_name_reads=A.Reads+B.Reads,persistent_reads=Doc.Ext.Calls};}
}
public partial class Cad {
 public static readonly JavaScriptSerializer Json=new JavaScriptSerializer{MaxJsonLength=16777216};
 static IFeature[] BasicMateFeatures(IModelDoc2 doc){return ((ReadDocument)doc).Features;}
 public string TestRead(IModelDoc2 doc,bool legacy,bool identity,bool refs) {
  if(identity)return legacy?LegacyMateSnapshotReader.MateIdentity(doc,null,refs):ProbeWorkingState.MateIdentity(doc,null,refs);
  return legacy?LegacyImportMateParameters(doc,refs):ProbeWorkingState.MateParameters(doc,refs);
 }
}
class MateSnapshotReadTests {
 static void Require(bool condition,string message){if(!condition)throw new Exception(message);}
 static object Error(Func<string> read) {
  try{read();throw new Exception("EXPECTED_REFUSAL_MISSING");}
  catch(CadFault e){return new{type=e.GetType().Name,code=e.Code,message=e.Message,details=e.Diagnostics};}
  catch(InvalidOperationException e){return new{type=e.GetType().Name,message=e.Message};}
  catch(Exception e){if(e.Message=="MATE_PARAMETER_UNREADABLE")return new{type=e.GetType().Name,message=e.Message};throw;}
 }
 static int Main(string[] args) {
  Console.OutputEncoding=new System.Text.UTF8Encoding(false);
  try {
   string mode=args[0];var w=ReadWorld.Create();var cad=new Cad();bool identity=mode.StartsWith("identity")||mode.StartsWith("bad_ref");bool refs=identity||mode=="discarded_refs";
   if(mode.StartsWith("nonlinear_")) {
    bool limit=mode.Contains("limit"),identityMode=mode.Contains("identity");var f=w.F(3);f.Mate.Kind=limit?5:17;f.Limit=limit;f.Definition.Advanced=limit;
    if(mode.Contains("missing"))f.MissingDefinition=true;
    if(mode.Contains("invalid_bounds"))f.Definition.Minimum=2;
    if(mode.Contains("invalid_lead"))f.Definition.Lead=double.NaN;
    if(mode.Contains("missing")||mode.Contains("invalid_")){Console.WriteLine(Cad.Json.Serialize(new{error=Error(()=>cad.TestRead(w.Doc,false,identityMode,identityMode))}));return 0;}
    string before=cad.TestRead(w.Doc,false,identityMode,identityMode);
    if(mode.Contains("changed_current"))f.Mate.Dimension.Value=.1;
    if(mode.Contains("changed_bounds"))f.Definition.Maximum=.8;
    if(mode.Contains("changed_lead"))f.Definition.Lead=.4;
    if(mode.Contains("changed_reverse"))f.Definition.Reversed=false;
    if(mode.Contains("changed_mode"))f.Definition.RevolutionMode=0;
    string after=cad.TestRead(w.Doc,false,identityMode,identityMode);Console.WriteLine(Cad.Json.Serialize(new{changed=before!=after,rows=Cad.Json.DeserializeObject(after)}));return 0;
   }
   if(mode=="identity_without_refs")refs=false;
   if(mode=="empty")w.Doc.Features=new IFeature[0];
   if(mode=="duplicate")w.Doc.Features=w.Doc.Features.Concat(new[]{new ReadFeature{Id=1,Mate=new ReadMate{Kind=99,Entities=new ReadEntity[0]}}}).ToArray();
   if(mode=="unknown_type")w.F(1).Mate.Kind=42;
   if(mode=="null_owner")w.F(1).Mate.Entities[0].Owner=null;
   if(mode=="missing_dimension")w.F(3).Mate.MissingDimension=true;
   if(mode=="bad_ref_null")w.F(1).Mate.Entities[0].Ref=null;
   if(mode=="bad_ref_persistent")w.Doc.Ext.Values[w.F(1).Mate.Entities[0].Ref]=null;
   if(mode=="bad_ref_empty")w.Doc.Ext.Values[w.F(1).Mate.Entities[0].Ref]=new byte[0];
   if(mode=="name_failure")w.A.Throw=true;
   if(mode=="culture")System.Threading.Thread.CurrentThread.CurrentCulture=new System.Globalization.CultureInfo("fr-FR");
   if(mode=="missing_dimension"||mode.StartsWith("bad_ref")||mode=="name_failure") {
    object a=Error(()=>cad.TestRead(w.Doc,true,identity,refs)),b=Error(()=>cad.TestRead(w.Doc,false,identity,refs));Require(Cad.Json.Serialize(a)==Cad.Json.Serialize(b),"ERROR_CONTRACT_CHANGED");
    Console.WriteLine(Cad.Json.Serialize(new{mode=mode,errors_equal=true,error=b}));return 0;
   }
   string first=cad.TestRead(w.Doc,false,identity,refs);
   if(mode=="changed_names")w.A.Value="改名后A";
   if(mode=="changed_dimension")w.F(3).Mate.Dimension.Value=.0456;
   if(mode=="changed_suppression")w.F(2).Suppressed=true;
   if(mode=="changed_gear"){w.F(5).Definition.Numerator=7;w.F(5).Definition.Denominator=11;w.F(5).Definition.Reversed=false;}
   if(mode=="changed_type"){w.F(1).Mate.Kind=5;w.F(1).Mate.Dimension.Value=.0789;}
   w.Reset();string legacy=cad.TestRead(w.Doc,true,identity,refs);object oldCounts=w.Counts();
   w.Reset();string current=cad.TestRead(w.Doc,false,identity,refs);object newCounts=w.Counts();
   Require(legacy==current,"FULL_SNAPSHOT_BYTES_CHANGED");if(mode.StartsWith("changed_"))Require(first!=current,"STALE_SNAPSHOT_REUSED");
   Console.WriteLine(Cad.Json.Serialize(new{mode=mode,all_bytes_equal=true,rows=Cad.Json.DeserializeObject(current),old_counts=oldCounts,new_counts=newCounts,changed_since_previous_call=first!=current}));return 0;
  }catch(Exception e){Console.Error.WriteLine(e.ToString());return 1;}
 }
}
