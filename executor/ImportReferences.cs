using System;
using System.IO;
using System.Text.RegularExpressions;

public static class ImportReferences {
    public static bool VirtualHint(string path) {
        return Regex.IsMatch(path??"",@"(?:^|[\\/])VC~~[\\/]",RegexOptions.IgnoreCase)&&Path.GetFileNameWithoutExtension(path).Contains("^")&&new[]{".SLDPRT",".SLDASM"}.ContainsExtension(Path.GetExtension(path));
    }
    static bool ContainsExtension(this string[] values,string extension){foreach(string v in values)if(v.Equals(extension,StringComparison.OrdinalIgnoreCase))return true;return false;}
    public static void RequireExternal(string path) {
        if(VirtualHint(path))throw new CadFault("VIRTUAL_COMPONENT_REFERENCE_UNSUPPORTED","检测到疑似内嵌虚拟组件引用；旧临时路径不等于丢失外部零件。当前默认导入不外部化，请显式开启副本外部化或在装配副本中另存为外部零件。",new{reference_name=Path.GetFileName(path),reference_status="suspected_virtual_embedded_reference",classification_source="VC_directory_and_embedded_name_hint_not_native_confirmation",native_is_virtual_checked=false,required_option="materialize_virtual_components",required_value=true,old_machine_path_redacted=true});
        if(!new[]{".SLDASM",".SLDPRT"}.ContainsExtension(Path.GetExtension(path)))throw new CadFault("SOURCE_REFERENCE_TYPE_UNSUPPORTED","引用不是受支持的零件或装配文件。",new{reference_name=Path.GetFileName(path),reference_status="unsupported_document_type"});
        if(!File.Exists(path))throw new CadFault("SOURCE_REFERENCE_MISSING","外部零件或装配引用在当前路径不可读；未将其判为已确认虚拟组件。",new{reference_name=Path.GetFileName(path),reference_status="missing_or_unreadable_external_file",native_is_virtual_checked=false});
    }
}
