// Offline fixture launcher. Only child's raw environment block is changed.
using System;using System.Text;using System.Collections;using System.Collections.Generic;using System.Runtime.InteropServices;
class RawDuplicateEnv {
 [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)]struct SI {public int cb;public string r,d,t;public int x,y,xs,ys,xc,yc,fill,flags;public short show,res;public IntPtr bytes,input,output,error;}
 [StructLayout(LayoutKind.Sequential)]struct PI {public IntPtr process,thread;public uint pid,tid;}
 [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]static extern bool CreateProcessW(string app,StringBuilder cmd,IntPtr pa,IntPtr ta,bool inherit,uint flags,IntPtr environment,string cwd,ref SI si,out PI pi);
 [DllImport("kernel32.dll")]static extern IntPtr GetStdHandle(int n);
 [DllImport("kernel32.dll")]static extern uint WaitForSingleObject(IntPtr h,uint timeout);
 [DllImport("kernel32.dll")]static extern bool GetExitCodeProcess(IntPtr h,out uint code);
 [DllImport("kernel32.dll")]static extern bool CloseHandle(IntPtr h);
 static string Quote(string s){var b=new StringBuilder("\"");int n=0;foreach(char c in s){if(c=='\\'){n++;continue;}if(c=='\"')b.Append('\\',n*2+1).Append(c);else b.Append('\\',n).Append(c);n=0;}return b.Append('\\',n*2).Append('"').ToString();}
 static int Main(string[] args){
  var values=new List<string>();foreach(DictionaryEntry e in Environment.GetEnvironmentVariables()){string key=(string)e.Key;if(!key.Equals("HTTPS_PROXY",StringComparison.OrdinalIgnoreCase))values.Add(key+"="+(string)e.Value);}
  values.Add("HTTPS_PROXY=http://fixture.invalid:9");values.Add("https_proxy=http://fixture.invalid:9");values.Sort(StringComparer.OrdinalIgnoreCase);
  IntPtr env=Marshal.StringToHGlobalUni(String.Join("\0",values.ToArray())+"\0\0");
  var cmd=new StringBuilder();foreach(string arg in args){if(cmd.Length>0)cmd.Append(' ');cmd.Append(Quote(arg));}
  var si=new SI();si.cb=Marshal.SizeOf(typeof(SI));si.flags=0x100;si.input=GetStdHandle(-10);si.output=GetStdHandle(-11);si.error=GetStdHandle(-12);PI pi;
  try {if(!CreateProcessW(args[0],cmd,IntPtr.Zero,IntPtr.Zero,true,0x08000400,env,null,ref si,out pi))throw new System.ComponentModel.Win32Exception(Marshal.GetLastWin32Error());}
  finally{Marshal.FreeHGlobal(env);}
  CloseHandle(pi.thread);try{WaitForSingleObject(pi.process,0xffffffff);uint code;if(!GetExitCodeProcess(pi.process,out code))return 99;return (int)code;}finally{CloseHandle(pi.process);}
 }
}
