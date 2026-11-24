using System;
using System.Collections.Generic;

class AperturePoseReviewTests {
    static object Field(object value,string name){return value.GetType().GetProperty(name).GetValue(value,null);}
    static double[] Pose(double x,double angle){
        double c=Math.Cos(angle),s=Math.Sin(angle);
        return new[]{c,s,0,-s,c,0,0,0,1,x,0,0,1,0,0,0};
    }
    static void Check(bool condition,string message){if(!condition)throw new Exception(message);}
    static int Main(){
        Console.OutputEncoding=new System.Text.UTF8Encoding(false);
        var initial=new Dictionary<string,double[]>{{"shift",Pose(0,0)},{"rotate",Pose(0,0)},{"invalid",Pose(0,0)}};
        var actual=new Dictionary<string,double[]>{{"shift",Pose(.04672,0)},{"rotate",Pose(0,.38515)},{"invalid",Pose(double.NaN,0)}};
        var result=AperturePoseReview.Describe(40,initial,actual);
        Check((string)Field(result,"comparison")=="last_frame_to_saved_pose"&&(double)Field(result,"time_s")==4,"endpoint");
        Check((int)Field(result,"invalid_pose_count")==1,"invalid pose");
        Check(Math.Abs((double)Field(result,"maximum_translation_m")-.04672)<1e-12,"translation");
        Check(Math.Abs((double)Field(result,"maximum_rotation_rad")-.38515)<1e-12,"rotation");
        Check((string)Field(((Array)Field(result,"worst_translation_components")).GetValue(0),"instance")=="shift","translation ranking");
        Check((string)Field(((Array)Field(result,"worst_rotation_components")).GetValue(0),"instance")=="rotate","rotation ranking");
        Check((double)Field(result,"allowed_translation_m")==1e-7&&(double)Field(result,"allowed_rotation_rad")==1e-6,"thresholds changed");
        Check(!PoseValidation.Matches(Pose(0,0),Pose(5e-7,0))&&!PoseValidation.Matches(Pose(0,0),Pose(0,5e-6)),"10x looser threshold");
        Check(!(bool)Field(result,"root_cause_proven"),"cause inferred");
        Check((string)Field(AperturePoseReview.Describe(0,initial,actual),"comparison")=="first_frame_to_saved_pose","first frame");
        return 0;
    }
}
