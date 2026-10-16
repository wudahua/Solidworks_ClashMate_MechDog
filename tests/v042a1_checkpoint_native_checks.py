"""Owned-copy native motor comparison. No user session or source file is modified."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import checkpoint_probe_native_checks as matrix
import v042_checkpoint_native_checks
matrix.CS=matrix.CS.replace('report["after"]=cad.ProbeTestCounts(id);', '''
 var repeated=D(cad.PreviewBasicMate(id,(string)faces[0]["entity_id"],(string)faces[1]["entity_id"],"concentric",Convert.ToInt32(existing["alignment"])==0?"anti_aligned":"aligned",0,false,""));
 try{cad.ApplyBasicMate((string)repeated["plan_id"],true);throw new Exception("REPEATED_BAD_MATE_COMMITTED");}catch(CadFault e){var d=D(e.Diagnostics);if(e.Code!="MATE_APPLY_ROLLED_BACK"||!(bool)d["rollback_verified"]||d["checkpoint_probe"]==null)throw;report["repeated_rollback"]=d;save();}
 report["after"]=cad.ProbeTestCounts(id);''')
matrix.CS=matrix.CS.replace('var d=D(e.Diagnostics);if(e.Code!="MATE_APPLY_ROLLED_BACK"','var d=D(e.Diagnostics);if(d["checkpoint_probe"]==null)throw new Exception("FAILURE_PROBE_SUMMARY_MISSING");if(e.Code!="MATE_APPLY_ROLLED_BACK"')
matrix.CS=matrix.CS.replace('if(!injected||e.Code!=', 'if(d["checkpoint_probe"]==null)throw new Exception("PREMUTATION_PROBE_SUMMARY_MISSING");if(!injected||e.Code!=')
if __name__=='__main__':matrix.main()

