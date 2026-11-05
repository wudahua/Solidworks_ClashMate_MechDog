using System;
using System.Linq;
using System.Collections.Generic;
using System.Web.Script.Serialization;

// Diagnostics only: never authorizes, normalizes, or substitutes a signature.
public static class ConnectionSignatureDiff {
    public static string[] Fields(string before,string after) {
        var json=new JavaScriptSerializer{MaxJsonLength=Int32.MaxValue,RecursionLimit=256};
        var a=json.Deserialize<Dictionary<string,object>>(before);
        var b=json.Deserialize<Dictionary<string,object>>(after);
        return a.Keys.Union(b.Keys).OrderBy(k=>k,StringComparer.Ordinal).Where(k=>
            !a.ContainsKey(k)||!b.ContainsKey(k)||json.Serialize(a[k])!=json.Serialize(b[k])).ToArray();
    }
}
