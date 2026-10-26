using System;
using System.Collections.Generic;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

public partial class Cad {
    object ComponentConstraintObservation(IComponent2 component) {
        try {
            int value=component.GetConstrainedStatus();
            return new{status="observed",native_value=(int?)value,
                native_name=Enum.GetName(typeof(swConstrainedStatus_e),value),
                fully_constrained=value==(int)swConstrainedStatus_e.swFullyConstrained,
                source="IComponent2.GetConstrainedStatus",fixed_flag_is_not_DOF=true,
                remaining_DOF=(object)null,error=(string)null};
        }catch(Exception error) {
            return new{status="unavailable",native_value=(int?)null,native_name=(string)null,
                fully_constrained=false,source="IComponent2.GetConstrainedStatus",fixed_flag_is_not_DOF=true,
                remaining_DOF=(object)null,error=error.GetType().Name};
        }
    }
}
