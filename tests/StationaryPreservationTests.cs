using System;
using System.Linq;
using System.Web.Script.Serialization;
class StationaryPreservationTests {
    static void Main() {
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        Func<bool,bool,bool,bool,bool,int,bool,bool> p=StationaryPreservationPolicy.Allowed;
        var r=new[]{p(true,true,false,true,false,3,false),
            p(false,true,false,true,false,3,false),p(true,false,false,true,false,3,false),
            p(true,true,true,true,false,3,false),p(true,true,false,false,false,3,false),
            p(true,true,false,true,true,3,false),p(true,true,false,true,false,3,true)};
        Console.Write(new JavaScriptSerializer().Serialize(new{cases=r,native_states=new[]{-1,0,1,2,3,4}.Select(n=>p(true,true,false,true,false,n,false)).ToArray()}));
    }
}
