"""Scissor zero reset: cached deviation disposition and final live proof."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import v042a4_reset_native as regression

needle='r["in_place"]=inPlace;'
replacement=needle+r'''
var deviation=D(inPlace["cached_memory_pose_deviation"]);bool cachedMatches=(bool)deviation["cached_memory_matches_reopened_file"];if(deviation.ContainsKey("within_pose_tolerance")||!((string)inPlace["pose_change_scope"]).Contains("pre_operation_live"))throw new Exception("POSE_COMPARISON_SCOPE_AMBIGUOUS");
if(!cachedMatches&&!((System.Collections.IEnumerable)inPlace["warning_codes"]).Cast<object>().Any(v=>((string)v).Contains("CACHED_MEMORY_POSE_DEVIATION")))throw new Exception("CACHED_DEVIATION_NOT_DISPOSITIONED");
if(!(bool)D(inPlace["committed_pose_validation"])["within_pose_tolerance"])throw new Exception("COMMITTED_LIVE_POSE_UNVERIFIED");
'''
assert needle in regression.matrix.CS
regression.matrix.CS=regression.matrix.CS.replace(needle,replacement)
if __name__ == '__main__': regression.matrix.main()
