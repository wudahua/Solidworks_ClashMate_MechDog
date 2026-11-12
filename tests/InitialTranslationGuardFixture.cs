using System;
using System.Collections.Generic;
using System.Web.Script.Serialization;
class InitialTranslationGuardFixture {
    static int Main() {
        var json=new JavaScriptSerializer();var input=json.Deserialize<Dictionary<string,object>>(Console.In.ReadToEnd());
        try {
            var poses=json.Deserialize<Dictionary<string,double[]>>(json.Serialize(input["poses"]));
            var flags=json.Deserialize<Dictionary<string,bool>>(json.Serialize(input["flags"]));
            var names=json.Deserialize<Dictionary<string,string>>(json.Serialize(input["names"]));
            var guard=InitialTranslationGuard.Read(json.Serialize(input["proof"]),poses,flags,names);
            if(input.ContainsKey("actual"))guard.RequireAfter(json.Deserialize<Dictionary<string,double[]>>(json.Serialize(input["actual"])),flags);
            Console.WriteLine(json.Serialize(new{accepted=true,requires_confirmation=guard.RequiresConfirmation,maximum=guard.Maximum}));
        }catch(Exception error){Console.WriteLine(json.Serialize(new{accepted=false,reason=error.Message}));}
        return 0;
    }
}
