// Recovery may reconstruct only the recorded active study, once, without changing its settings.
public static class CheckpointCachePolicy {
    public static bool Allows(int type,bool active,bool alreadyAttempted,double duration,int fps) {
        return active&&!alreadyAttempted&&(type==1||type==4)&&StudyCacheBudget.Allows(duration,fps);
    }
}
