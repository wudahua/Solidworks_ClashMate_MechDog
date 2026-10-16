using System;
using System.Text;
using System.Collections.Generic;

public static class ReplayCsv {
    public static bool Allows(int frames,int components,int frame,double duration,int fps) {
        return frames>=2&&frames<=1801&&components>=1&&components<=500&&(long)frames*components<=100000&&frame>=0&&frame<frames
            &&!double.IsNaN(duration)&&!double.IsInfinity(duration)&&duration>0&&duration<=30&&fps>=5&&fps<=120
            &&Math.Abs(duration*fps-Math.Round(duration*fps))<=1e-8&&Math.Round(duration*fps)+1==frames;
    }
    public static string[] Parse(string line) {
        var fields=new List<string>();var field=new StringBuilder();bool quoted=false,closed=false;
        for(int i=0;i<line.Length;i++) {
            char c=line[i];
            if(quoted){if(c=='"'){if(i+1<line.Length&&line[i+1]=='"'){field.Append('"');i++;}else{quoted=false;closed=true;}}else field.Append(c);}
            else if(c==','){fields.Add(field.ToString());field.Clear();closed=false;}
            else if(c=='"'&&field.Length==0&&!closed)quoted=true;
            else {if(closed||c=='"')throw new Exception("REPLAY_CSV_INVALID_QUOTING");field.Append(c);}
        }
        if(quoted)throw new Exception("REPLAY_CSV_INVALID_QUOTING");fields.Add(field.ToString());return fields.ToArray();
    }
}
