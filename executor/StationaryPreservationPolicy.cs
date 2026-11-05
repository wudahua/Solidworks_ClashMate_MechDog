// Eligibility only. This never certifies grounding, rigidity, or motion.
public static class StationaryPreservationPolicy {
    public static bool Allowed(bool declaredStationary,bool fixedAnchor,bool fixedComponent,
            bool topLevelPart,bool patternInstance,int nativeStatus,bool hasSupplement) {
        return declaredStationary&&fixedAnchor&&!fixedComponent&&topLevelPart&&!patternInstance&&nativeStatus==3&&!hasSupplement;
    }
}
