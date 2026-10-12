using System;

public class CadFault : Exception {
    public readonly string Code;
    public readonly object Diagnostics;
    public CadFault(string code,string message,object diagnostics=null):base(message){Code=code;Diagnostics=diagnostics;}
}
