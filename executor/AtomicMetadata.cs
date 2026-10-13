using System;
using System.IO;
using System.Threading;

public static class AtomicMetadata {
    public static void Write(string path,string json){
        Directory.CreateDirectory(Path.GetDirectoryName(path));string temp=path+"."+Guid.NewGuid().ToString("N")+".tmp";
        try{
            File.WriteAllText(temp,json);
            for(int attempt=0;;attempt++){
                try{if(File.Exists(path))File.Replace(temp,path,null);else File.Move(temp,path);return;}
                catch(IOException error){int code=error.HResult&0xffff;if(attempt>=6||(code!=32&&code!=33))throw new IOException("Metadata replacement failed: "+path,error);Thread.Sleep(20*(attempt+1));}
            }
        }finally{if(File.Exists(temp))try{File.Delete(temp);}catch(IOException){}}
    }
}
