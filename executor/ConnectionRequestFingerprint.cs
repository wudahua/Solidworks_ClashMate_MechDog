using System;
using System.Security.Cryptography;
using System.Text;

// Bind the exact received UTF-8 request before any double parsing/reserialization.
public static class ConnectionRequestFingerprint {
    public static string Hash(string request) {
        if(request==null)throw new ArgumentNullException("request");
        using(var hash=SHA256.Create())return BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(request))).Replace("-","").ToLowerInvariant();
    }
}
