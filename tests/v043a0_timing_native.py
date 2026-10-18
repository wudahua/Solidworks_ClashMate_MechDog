"""Owned-instance run/verify phase accounting; never connects to user CAD."""
import json
import v042a7_performance_native as harness

code=harness.matrix.CS.replace('cad=new Cad(a[0]);','cad=new Cad(a[0]);cad.Sw.Visible=true;')
needle='r["completed"]=true;save();return 0;'
assert needle in code
extra=r'''foreach(string key in new[]{"run","verify"}){var output=D(r[key]);string rid=(string)output["run_id"];var solve=D(Cad.Json.DeserializeObject(File.ReadAllText(Path.Combine(a[0],"runs",rid,"solve.json"))));var timing=D(solve["solve_performance"]);var phases=D(timing["phase_totals_ms"]);double total=Convert.ToDouble(timing["total_elapsed_ms"]),attributed=phases.Values.Sum(v=>Convert.ToDouble(v));if(phases.Count<20||Math.Abs(total-attributed)>1e-5||!(bool)timing["execution_completed"])throw new Exception("SOLVE_TIMING_ACCOUNTING_FAILED");foreach(string required in new[]{"scope_snapshot_capture_and_save","load_motion_addin","native_calculate","verify_native_time_axis","sampling_loop","capture_fingerprint_and_hashes","write_pose_csv","scope_restore_snapshot_and_context"})if(!phases.ContainsKey(required))throw new Exception("MISSING_TIMING_PHASE "+required);r[key+"_timing_verified"]=timing;}r["completed"]=true;save();return 0;'''
harness.matrix.CS=code.replace(needle,extra)

if __name__=='__main__':
    report=harness.main()
    if report:print(json.dumps({'timing_native_completed':True,'directory':report['directory']}),flush=True)
