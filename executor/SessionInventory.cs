using System;
using System.Linq;
using System.Diagnostics;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Security.Principal;

public sealed class SessionInventory {
    public bool Complete=true;
    public readonly Dictionary<int,string> Identities=new Dictionary<int,string>();
    public int ExcludedOtherSessions;
    [DllImport("advapi32.dll",SetLastError=true)]static extern bool OpenProcessToken(IntPtr process,uint access,out IntPtr token);
    [DllImport("kernel32.dll")]static extern bool CloseHandle(IntPtr handle);
    public static SessionInventory ReadVerified(){
        var result=new SessionInventory();int desktopSession=Process.GetCurrentProcess().SessionId;
        string owner=WindowsIdentity.GetCurrent().User.Value;
        foreach(var process in Process.GetProcessesByName("SLDWORKS"))using(process){
            try {
                if(process.SessionId!=desktopSession){result.ExcludedOtherSessions++;continue;}
                IntPtr token;
                if(!OpenProcessToken(process.Handle,8,out token))throw new System.ComponentModel.Win32Exception();
                string targetOwner;
                try{using(var identity=new WindowsIdentity(token))targetOwner=identity.User.Value;}finally{CloseHandle(token);}
                if(targetOwner!=owner){result.ExcludedOtherSessions++;continue;}
                string executable=System.IO.Path.GetFullPath(process.MainModule.FileName);
                if(!System.IO.Path.GetFileName(executable).Equals("SLDWORKS.exe",StringComparison.OrdinalIgnoreCase))throw new InvalidOperationException();
                result.Identities[process.Id]=process.StartTime.ToUniversalTime().ToString("o")+"|"+desktopSession+"|"+executable.ToLowerInvariant();
            }catch{result.Complete=false;}
        }
        return result;
    }
}
