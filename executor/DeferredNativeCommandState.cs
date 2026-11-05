using System;

// Kept only by the original executor. A replacement connection cannot adopt it.
// Capture performs no native call; restoration is an explicit checkpoint action.
public sealed class DeferredNativeCommandState {
    string model;bool conflict;
    public bool Pending {get{return model!=null;}}
    public void Remember(string modelId,bool previous) {
        if(previous||string.IsNullOrEmpty(modelId))return;
        if(model!=null&&model!=modelId){conflict=true;return;}
        model=modelId;
    }
    void Require(string modelId) {
        if(conflict||model!=modelId)throw new NativeCommandStateException(new InvalidOperationException("DEFERRED_COMMAND_STATE_MODEL_MISMATCH"));
    }
    public bool PrepareRestore(string modelId,Action validateOwnedDocuments,Func<bool> read,Action<bool> write) {
        if(!Pending)return false;
        Require(modelId);validateOwnedDocuments();
        bool current=read();if(current)write(false);
        if(read())throw new NativeCommandStateException(new InvalidOperationException("DEFERRED_COMMAND_FLAG_READBACK_MISMATCH"));
        return true;
    }
    public void CompleteRestore(string modelId,Func<bool> read) {
        if(!Pending)return;
        Require(modelId);
        if(read())throw new NativeCommandStateException(new InvalidOperationException("DEFERRED_COMMAND_FLAG_CHANGED_DURING_RECOVERY"));
        model=null;conflict=false;
    }
    public object Describe(){return new{required=Pending,model_id=model,conflicting_model_observations=conflict,expected_owned_previous_flag=false,original_executor_required=true,automatic_flag_write_performed=false};}
}
