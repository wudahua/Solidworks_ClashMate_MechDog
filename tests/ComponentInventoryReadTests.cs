using System;
using System.Runtime.InteropServices;
using System.Web.Script.Serialization;
class ComponentInventoryReadTests {
    class Item {public int Id;public Item(int id){Id=id;}}
    static void Main(string[] args) {
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        string mode=args[0];int calls=0,pauses=0,contexts=0;var a=new Item(1);var b=new Item(2);var wrong=new object();
        Func<object[]> fetch=()=>{calls++;if(mode=="com_error")throw new COMException("native failure");
            if(mode=="fetch_invalidcast")throw new InvalidCastException("array interface unavailable");
            if(mode=="missing")return null;if(mode=="empty")return new object[0];
            if(mode=="count_change"&&calls>1)return new object[]{a};
            if(mode=="always_bad"||mode=="count_change"||mode=="recover_once"&&calls==1||mode=="recover_twice"&&calls<3)return new object[]{a,wrong};
            if(mode=="null_entry")return new object[]{a,null};return new object[]{b,a};};
        Func<string> context=()=>{contexts++;return mode=="context_change"&&contexts>1?"different_document_or_configuration":"same_document_and_configuration";};
        object answer;
        try {var rows=ComponentInventoryRead.Read<Item>(fetch,context,()=>pauses++);answer=new{ok=true,rows=Array.ConvertAll(rows,v=>v.Id),same_original_instances=rows.Length==0||Object.ReferenceEquals(rows[0],b),calls=calls,pauses=pauses};}
        catch(Exception e){var f=e as CadFault;answer=new{ok=false,calls=calls,pauses=pauses,type=e.GetType().Name,code=f==null?null:f.Code,details=f==null?null:f.Diagnostics,message=e.Message};}
        Console.Write(new JavaScriptSerializer().Serialize(answer));
    }
}
