// Compile the production SolverEvidence method against a controlled interface
// lifetime. No CAD, COM registration, native writes or retries are used.
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
namespace SolidWorks.Interop.swmotionstudy {
 public interface IMotionStudy {object GetResults(int kind);object GetProperties(int kind);double GetDuration();bool SetDuration(double value);int StudyType{get;}bool IsActive{get;}bool IsPlaying{get;}}
 public interface IMotionStudyResults {bool IsOutOfDate();}
 public interface IMotionStudyProperties {int GetFrameRate();bool SetFrameRate(int fps);}
}
public static class NativeOutputGridPolicy {public static bool Allows(double d,int f){return true;}public static object Describe(double d,int f){return null;}}
public static class MotionBudgets {public static bool ProbeAllows(double d,int f){return true;}}
public class CadFault:Exception {public string Code;public CadFault(string code,string message,object details):base(message){Code=code;}}
public partial class Cad {
 Dictionary<string,object> HistorySettings(SolidWorks.Interop.swmotionstudy.IMotionStudy study){return new Dictionary<string,object>{{"duration_s",4.0},{"fps",30}};}
 object FailureEvidence(Exception error){return error.GetType().Name;}
 public void Observe(SolidWorks.Interop.swmotionstudy.IMotionStudy study,string stage){RequireCurrentFreshSolveResults(study,"bound-model","bound-study",stage);}
}
class LifetimeResult:SolidWorks.Interop.swmotionstudy.IMotionStudyResults {
 public int Reads;public bool Disconnected,Stale;
 public bool IsOutOfDate(){Reads++;if(Disconnected)throw new COMException("controlled disconnected",unchecked((int)0x80010108));return Stale;}
}
class LifetimeStudy:SolidWorks.Interop.swmotionstudy.IMotionStudy {
 public int Gets;public string Mode;public LifetimeResult Old=new LifetimeResult(),Current=new LifetimeResult();
 public object GetResults(int kind){Gets++;if(kind!=4)throw new Exception("wrong native result type");if(Mode=="getter_com")throw new COMException("controlled getter failure");if(Mode=="null")return null;return Gets==1?Old:Current;}
 public object GetProperties(int kind){return null;}public double GetDuration(){return 4;}public bool SetDuration(double v){return true;}
 public int StudyType{get{return 4;}}public bool IsActive{get{return true;}}public bool IsPlaying{get{return false;}}
}
class CurrentSolveResultsTests {
 public static void Main(string[] args){var study=new LifetimeStudy{Mode=args[0]};string error=null;bool before=false,after=false;
  if(study.Mode=="stale")study.Old.Stale=true;if(study.Mode=="result_com")study.Old.Disconnected=true;
  try{var cad=new Cad();cad.Observe(study,"after_calculate");before=true;if(study.Mode=="replace_after_sampling"){study.Old.Disconnected=true;cad.Observe(study,"after_sampling");after=true;}}
  catch(Exception e){error=e is CadFault?((CadFault)e).Code:e.GetType().Name;}
  Console.WriteLine(new JavaScriptSerializer().Serialize(new{gets=study.Gets,old_reads=study.Old.Reads,current_reads=study.Current.Reads,before=before,after=after,error=error}));
 }
}
