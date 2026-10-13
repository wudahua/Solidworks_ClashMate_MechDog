public static class MotionFeatureEvidence {
    public static string Status(string raw,bool active) {
        return raw=="native_null"?(active?"native_null_study_active":"native_null_study_inactive"):raw;
    }
    public static string Presence(string raw,int count) {
        return raw=="enumerated"&&count>0?"features_observed":"unknown";
    }
}
