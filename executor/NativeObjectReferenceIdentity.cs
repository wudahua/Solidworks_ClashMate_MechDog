using System;

// Persistent reference bytes can be canonicalized by save/reopen. Only native
// identity in the bound document and component may establish equivalence.
public static class NativeObjectReferenceIdentity {
    public static bool Matches<T>(T actual,string expected,Func<string,T> resolve,
                                 Func<T,T,bool> sameEntity,Func<T,T,bool> sameComponent) where T:class {
        if(actual==null||String.IsNullOrWhiteSpace(expected))return false;
        T resolved=resolve(expected);
        return resolved!=null&&sameComponent(actual,resolved)&&sameEntity(actual,resolved);
    }
}
