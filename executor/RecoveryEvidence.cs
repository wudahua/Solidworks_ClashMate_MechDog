using System;
using System.Linq;
using System.Collections.Generic;
using System.Windows.Forms;
using SolidWorks.Interop.sldworks;

public partial class Cad {
    static object FailureEvidence(Exception error) {
        var fault=error as CadFault;
        return new{code=HistoryErrorCode(error),message=error.Message,details=fault==null?null:fault.Diagnostics,hresult=error.HResult,exception_chain=error.ToString()};
    }
    static object PoseChange(Dictionary<string,double[]> before,Dictionary<string,double[]> after) {
        PoseDifference(before,after); // Reject an incomplete or changed component set.
        var rows=before.Select(p=>new{instance=p.Key,translation_m=PoseValidation.TranslationDistance(p.Value,after[p.Key]),rotation_rad=PoseValidation.RotationDistance(p.Value,after[p.Key])}).ToArray();
        return new{checked_component_count=rows.Length,maximum_translation_m=rows.Length==0?0:rows.Max(r=>r.translation_m),maximum_rotation_rad=rows.Length==0?0:rows.Max(r=>r.rotation_rad),within_pose_tolerance=before.All(p=>PoseValidation.Matches(p.Value,after[p.Key])),worst_translation_components=rows.OrderByDescending(r=>r.translation_m).Take(5).ToArray(),worst_rotation_components=rows.OrderByDescending(r=>r.rotation_rad).Take(5).ToArray()};
    }
}
