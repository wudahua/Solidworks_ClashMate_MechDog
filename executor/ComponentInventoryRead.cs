using System;
using System.Threading;

public sealed class ComponentInventoryReadFault : CadFault {
    public ComponentInventoryReadFault(object details):base("API_TYPE_MISMATCH",
        "组件集合未能完整转换为组件接口；仅重取只读集合，未跳过组件或重放写入。",details){}
}

// Reacquire only a malformed read, never an operation that failed in COM.
// The caller still verifies all physical identities, poses and checkpoint data.
public static class ComponentInventoryRead {
    public static T[] Read<T>(Func<object[]> fetch,Func<string> context,Action pause=null) where T:class {
        string initial=context();int firstCount=-1;
        for(int attempt=1;attempt<=3;attempt++) {
            if(attempt>1&&context()!=initial)throw Failure("document_context_changed",attempt,firstCount,-1,null);
            var raw=fetch();
            if(raw==null)throw Failure("native_collection_missing",attempt,firstCount,-1,null);
            if(firstCount<0)firstCount=raw.Length;
            if(raw.Length!=firstCount)throw Failure("component_count_changed",attempt,firstCount,raw.Length,null);
            var typed=new T[raw.Length];int bad=-1;
            for(int i=0;i<raw.Length;i++){typed[i]=raw[i] as T;if(typed[i]==null){bad=i;break;}}
            if(context()!=initial)throw Failure("document_context_changed",attempt,firstCount,-1,null);
            if(bad<0)return typed;
            if(attempt==3)throw Failure("untyped_component_entry",attempt,firstCount,bad,raw[bad]==null?"null":raw[bad].GetType().FullName);
            if(pause!=null)pause();else Thread.Sleep(25);
        }
        throw new InvalidOperationException("UNREACHABLE_COMPONENT_READ");
    }
    static ComponentInventoryReadFault Failure(string reason,int attempt,int expected,int observed,string type) {
        return new ComponentInventoryReadFault(new{reason=reason,read_attempts=attempt,expected_component_count=expected,
            observed_count_or_bad_index=observed,untyped_entry_managed_type=type,read_only_reacquisition=true,
            partial_inventory_returned=false,components_skipped=false,native_write_replayed=false,maximum_read_attempts=3});
    }
}
