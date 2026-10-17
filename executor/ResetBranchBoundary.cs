using System;
using System.IO;
using System.Linq;
using System.Text.RegularExpressions;

// Only this explicitly named worker may edit its one new registered model.
public static class ResetBranchBoundary {
    public static string Validate(string worker,string id,string directory,string assembly,string[] files,string purpose,string state) {
        string root=Path.GetFullPath(worker);var parent=Directory.GetParent(root);
        if(parent==null||parent.Name!="probes"||parent.Parent==null||parent.Parent.Name!="runs"||parent.Parent.Parent==null||!Regex.IsMatch(Path.GetFileName(root),"^reset_[a-f0-9]{8}$")||!Regex.IsMatch(id??"","^user_[a-f0-9]{32}$")||purpose!="reset_branch"||state!="incomplete")throw new Exception("RESET_BRANCH_WORKER_BOUNDARY_INVALID");
        string boundary=Path.Combine(parent.Parent.Parent.FullName,"experiments","user_assemblies",id.Substring(5));
        if(!Path.IsPathRooted(directory)||!string.Equals(Path.GetFullPath(directory),boundary,StringComparison.OrdinalIgnoreCase)||files==null||files.Length<1||files.Length>533||files.Distinct(StringComparer.OrdinalIgnoreCase).Count()!=files.Length||!files.Contains(assembly,StringComparer.OrdinalIgnoreCase)||files.Count(p=>p.EndsWith(".SLDASM",StringComparison.OrdinalIgnoreCase))!=1||!assembly.EndsWith(".SLDASM",StringComparison.OrdinalIgnoreCase)||files.Any(p=>!Path.IsPathRooted(p)||!string.Equals(Path.GetDirectoryName(Path.GetFullPath(p)),Path.Combine(boundary,"files"),StringComparison.OrdinalIgnoreCase)||!new[]{".sldasm",".sldprt"}.Contains(Path.GetExtension(p).ToLowerInvariant())))throw new Exception("RESET_BRANCH_WORKER_BOUNDARY_INVALID");
        return boundary;
    }
}
