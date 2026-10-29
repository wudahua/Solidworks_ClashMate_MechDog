using System;
using System.Web.Script.Serialization;
class ConnectionTargetWireFixture {
    static int Main() {
        string request=Console.In.ReadToEnd();
        var json=new JavaScriptSerializer();
        var target=json.Deserialize<double[]>(request);
        Console.WriteLine(json.Serialize(new{request_target_sha256=ConnectionRequestFingerprint.Hash(request),target=target}));
        return 0;
    }
}
