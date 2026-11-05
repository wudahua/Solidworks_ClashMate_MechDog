using System;
using System.Web.Script.Serialization;
class ConnectionSignatureDiffTests {
    static void Main(string[] args) {
        Console.Write(new JavaScriptSerializer().Serialize(ConnectionSignatureDiff.Fields(args[0],args[1])));
    }
}
