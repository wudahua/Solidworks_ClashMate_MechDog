// Compile the production empty-instance exit guard without CAD/interop.
using System;
using System.Web.Script.Serialization;
namespace SolidWorks.Interop.sldworks {
    public interface IModelDoc2 { string GetPathName(); string GetTitle(); int GetType(); }
}
class Document : SolidWorks.Interop.sldworks.IModelDoc2 {
    public string GetPathName(){return "C:\\owned-runtime\\case.SLDASM";}
    public string GetTitle(){return "case";}
    public new int GetType(){return 2;}
}
public class FakeSw {
    public bool Visible;public object[] Documents=new object[0];public int Exits,Reads;
    public int GetProcessID(){return 42;}
    public string RevisionNumber(){return "stub";}
    public object GetDocuments(){Reads++;return Documents;}
    public void ExitApp(){Exits++;}
}
public partial class Cad {
    public FakeSw Sw=new FakeSw();public string Root;
    public static JavaScriptSerializer Json=new JavaScriptSerializer();
    public Cad(string root){Root=root;}
    public void CloseUserDocuments(string[] paths){throw new Exception("MUST_NOT_CLOSE_ANY_DOCUMENT");}
}
class StartupEmptyControlTests {
    static int Main(){
        Console.OutputEncoding = new System.Text.UTF8Encoding(false);
        var empty=new Cad("C:\\owned-runtime");empty.AcceptanceControl("exit_empty",42);
        if(empty.Sw.Exits!=1)throw new Exception("Empty owned instance did not exit");
        var occupied=new Cad("C:\\owned-runtime");occupied.Sw.Documents=new object[]{new Document()};
        try{occupied.AcceptanceControl("exit_empty",42);throw new Exception("Document not refused");}
        catch(Exception e){if(e.Message!="OWNED_INSTANCE_NOT_EMPTY_REFUSE_EXIT")throw;}
        if(occupied.Sw.Exits!=0)throw new Exception("Opened document instance exited");
        var wrong=new Cad("C:\\owned-runtime");
        try{wrong.AcceptanceControl("exit_empty",43);throw new Exception("Wrong PID not refused");}
        catch(Exception e){if(e.Message!="OWNED_PID_MISMATCH")throw;}
        if(wrong.Sw.Reads!=0||wrong.Sw.Exits!=0)throw new Exception("Wrong PID was touched");
        Console.WriteLine("3 native empty-exit guard cases passed; CAD not loaded");return 0;
    }
}
