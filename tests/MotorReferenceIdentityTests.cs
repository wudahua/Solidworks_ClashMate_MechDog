using System;
class MotorReferenceIdentityTests {
    class Face {public string Entity,Owner;public Face(string entity,string owner){Entity=entity;Owner=owner;}}
    static void Require(bool v){if(!v)throw new Exception("native_identity_policy_failed");}
    static int Main(){
        var current=new Face("native-face-1","instance-1");
        Func<string,Face> resolve=s=>s=="old-valid-alias"?current:null;
        Func<Face,Face,bool> same=(a,b)=>a.Entity==b.Entity;
        Func<Face,Face,bool> owner=(a,b)=>a.Owner==b.Owner;
        Require(NativeObjectReferenceIdentity.Matches(current,"old-valid-alias",resolve,same,owner));
        Require(!NativeObjectReferenceIdentity.Matches(new Face("coplanar-other-face","instance-1"),"old-valid-alias",resolve,same,owner));
        Require(!NativeObjectReferenceIdentity.Matches(new Face("native-face-1","instance-2"),"old-valid-alias",resolve,same,owner));
        Require(!NativeObjectReferenceIdentity.Matches(current,"stale",resolve,same,owner));
        Require(!NativeObjectReferenceIdentity.Matches<Face>(null,"old-valid-alias",resolve,same,owner));
        bool propagated=false;try{NativeObjectReferenceIdentity.Matches<Face>(current,"old-valid-alias",s=>{throw new InvalidOperationException();},same,owner);}catch(InvalidOperationException){propagated=true;}Require(propagated);
        Console.OutputEncoding=new System.Text.UTF8Encoding(false);Console.Write("6 PASS");return 0;
    }
}
