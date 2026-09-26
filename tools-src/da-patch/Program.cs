// P-B 工具（UAssetAPI 1.1.0，VER_UE5_6 读 UE5.7 cooked 包）
//   probe     <uasset> <usmap>
//   roundtrip <uasset> <usmap> <outDir>                 只读回放：原样写回（验字节保真度）
//   addname   <uasset> <usmap> <outDir> <newName>       只在名字表追加一个 FName 后写回
using System.Reflection;
using System.Security.Cryptography;
using UAssetAPI;
using UAssetAPI.ExportTypes;
using UAssetAPI.PropertyTypes.Objects;
using UAssetAPI.PropertyTypes.Structs;
using UAssetAPI.UnrealTypes;
using UAssetAPI.Unversioned;

// Speak UTF-8 on stdout/stderr however we were started.  core/common.py decodes
// subprocess output as UTF-8, but .NET uses the *console* code page and falls
// back to the ANSI code page (GBK) when the process has no console at all --
// which is exactly the case for the --windowed GUI exe.  Measured: with a
// console da-patch writes UTF-8, without one it writes GBK, so "自定义名"
// came back as '\ufffd\u0536\ufffd\ufffd\ufffd\ufffd' and gate A7 aborted.
static void ForceUtf8Stdio()
{
    var enc = new System.Text.UTF8Encoding(false);   // no BOM
    try { Console.OutputEncoding = enc; } catch { }  // also puts an attached console on 65001
    try { Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), enc) { AutoFlush = true }); } catch { }
    try { Console.SetError(new StreamWriter(Console.OpenStandardError(), enc) { AutoFlush = true }); } catch { }
}
ForceUtf8Stdio();

var V = EngineVersion.VER_UE5_6;
var mode = args.Length > 0 ? args[0].ToLowerInvariant() : "probe";
if (args.Length < 3) { Console.Error.WriteLine("usage: da-patch probe|roundtrip|addname <uasset> <usmap> [outDir] [newName]"); return 2; }
var ua = Path.GetFullPath(args[1]);
var us = Path.GetFullPath(args[2]);

var mappings = new Usmap(us);
var asset = new UAsset(ua, true, V, mappings, CustomSerializationFlags.None);
Console.WriteLine($"loaded: names={asset.GetNameMapIndexList().Count} exports={asset.Exports.Count} unversioned={asset.HasUnversionedProperties} useSep={asset.UseSeparateBulkDataFiles}");
var ex = asset.Exports[0];
Console.WriteLine($"export: type={ex.GetType().Name} name={ex.ObjectName} classIndex={ex.ClassIndex} rawbytes={(ex as RawExport)?.Data?.Length ?? -1}");
if (ex is NormalExport ne)
{
    Console.WriteLine($"props={ne.Data.Count}");
    foreach (var p in ne.Data) Console.WriteLine($"  PROP {p.Name} type={p.PropertyType} clr={p.GetType().Name}");
    var m = ne.Data.OfType<MapPropertyData>().FirstOrDefault();
    if (m is not null) Console.WriteLine($"  (MapProperty '{m.Name}' 结构请用 props 模式转储)");
}
if (mode == "texrename")
{
    // texrename <uasset> <usmap> <outDir> <newObjectName> [newPackagePath]
    var newObj = args[4];
    var newPkg = args.Length > 5 ? args[5] : null;
    var ex2 = asset.Exports[0];
    Console.WriteLine($"rename export '{ex2.ObjectName}' -> '{newObj}'");
    ex2.ObjectName = new FName(asset, newObj, 0);
    if (newPkg is not null)
    {
        var nm0 = asset.GetNameMapIndexList();
        var oldPkg = nm0.FirstOrDefault(s => s.Value != null && s.Value.StartsWith("/Game/") && s.Value.Contains(Path.GetFileNameWithoutExtension(ua)));
        Console.WriteLine($"  old package-path name entry = '{oldPkg}'");
        var added = asset.AddNameReference(new FString(newPkg), false, false);
        Console.WriteLine($"  AddNameReference('{newPkg}') -> {added} (旧条目保留为悬挂名，不影响索引语义)");
    }
    var od = Path.GetFullPath(args[3]);
    Directory.CreateDirectory(od);
    var op = Path.Combine(od, newObj + ".uasset");
    asset.Write(op);
    // 也把 uexp 按新名字复制（供 retoc 用）
    var uexpSrc = Path.ChangeExtension(ua, ".uexp");
    if (File.Exists(uexpSrc)) File.Copy(uexpSrc, Path.ChangeExtension(op, ".uexp"), true);
    foreach (var f in Directory.GetFiles(od).OrderBy(x => x))
        Console.WriteLine($"  out {Path.GetFileName(f)} {new FileInfo(f).Length} B");
    return 0;
}

if (mode == "namerepl")
{
    // namerepl <uasset> <usmap> <outDir> <newObjectName> <oldFragment> <newPackagePath>
    //  把 cooked 包里"内部包路径"名字表条目**替换**成新路径（不是追加），
    //  并同时改 export 的 ObjectName —— 这样 retoc to-zen 算出的 IoStore package id
    //  才会等于 hash(新包名)，引擎才能按新包名找到它。
    var newObj = args[4];
    var oldFrag = args[5];
    var newPkg = args[6];
    var nm = asset.GetNameMapIndexList();
    var hits = Enumerable.Range(0, nm.Count)
        .Where(i => nm[i] != null && nm[i].Value != null && nm[i].Value.StartsWith("/Game/")
                    && nm[i].Value.EndsWith("/" + oldFrag)).ToList();
    Console.WriteLine($"old package-path name entries (/Game/.../{oldFrag}): [{string.Join(",", hits)}]");
    if (hits.Count != 1) { Console.Error.WriteLine("FATAL: expected exactly one old package-path entry"); return 3; }
    Console.WriteLine($"  replace [{hits[0]}] '{nm[hits[0]].Value}' -> '{newPkg}'");
    // GetNameMapIndexList() 返回 IReadOnlyList，改不动 —— 反射拿到真正可变的底层 List<FString>。
    var at = asset.GetType();
    object listObj = null; var foundVia = "";
    foreach (var f in at.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
    {
        if (f.FieldType == typeof(List<FString>)) { listObj = f.GetValue(asset); foundVia = "field " + f.Name; break; }
    }
    if (listObj == null)
    {
        foreach (var p in at.GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
        {
            if (p.PropertyType == typeof(List<FString>) && p.GetIndexParameters().Length == 0)
            { listObj = p.GetValue(asset); foundVia = "property " + p.Name; break; }
        }
    }
    if (listObj == null) { Console.Error.WriteLine("FATAL: cannot find a mutable List<FString> name map on UAsset"); return 4; }
    Console.WriteLine($"  mutable name map via {foundVia} (count={(listObj as List<FString>).Count})");
    (listObj as List<FString>)[hits[0]] = new FString(newPkg);
    // UAssetAPI 把"内部包路径"存在 UAsset.FolderName 里（cooked 包的真实身份）——
    // retoc to-zen 就是用它算 IoStore package id 的，必须一起改。
    Console.WriteLine($"  FolderName '{asset.FolderName}' -> '{newPkg}'");
    asset.FolderName = new FString(newPkg);
    var ex3 = asset.Exports[0];
    Console.WriteLine($"  export '{ex3.ObjectName}' -> '{newObj}'");
    ex3.ObjectName = new FName(asset, newObj, 0);
    var od3 = Path.GetFullPath(args[3]);
    Directory.CreateDirectory(od3);
    var op3 = Path.Combine(od3, newObj + ".uasset");
    asset.Write(op3);
    var uexpSrc3 = Path.ChangeExtension(ua, ".uexp");
    if (File.Exists(uexpSrc3)) File.Copy(uexpSrc3, Path.ChangeExtension(op3, ".uexp"), true);
    foreach (var f in Directory.GetFiles(od3).OrderBy(x => x))
        Console.WriteLine($"  out {Path.GetFileName(f)} {new FileInfo(f).Length} B sha={Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f)))[..16]}");
    return 0;
}

if (mode == "fields")
{
    // 反射列出 UAsset 上与"包名"相关的一切可变字段/属性（找 retoc 到底读哪个）
    var t0 = asset.GetType();
    Console.WriteLine($"UAsset type = {t0.FullName}");
    foreach (var f in t0.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
    {
        var n = f.Name.ToLowerInvariant();
        if (n.Contains("name") || n.Contains("folder") || n.Contains("path"))
        {
            object v = null; try { v = f.GetValue(asset); } catch { }
            Console.WriteLine($"  FIELD {f.Name} : {f.FieldType.Name} = {(v is FString fs ? "'" + fs.Value + "'" : v?.ToString())}");
        }
    }
    foreach (var p in t0.GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
    {
        var n = p.Name.ToLowerInvariant();
        if ((n.Contains("name") || n.Contains("folder") || n.Contains("path")) && p.GetIndexParameters().Length == 0)
        {
            object v = null; try { v = p.GetValue(asset); } catch { }
            Console.WriteLine($"  PROP  {p.Name} : {p.PropertyType.Name} = {(v is FString fs2 ? "'" + fs2.Value + "'" : v?.ToString())}");
        }
    }
    return 0;
}

if (mode == "imports")
{
    // 机器可读的 ImportMap 转储（供只读校验 / 硬断言用）：
    //   imports=<总数>
    //   mic=<MaterialInstanceConstant 条数>
    //   <idx>|<ClassPackage>|<ClassName>|<ObjectName>|<OuterIndex>
    var mic = 0;
    foreach (var im in asset.Imports) if (im.ClassName.ToString() == "MaterialInstanceConstant") mic++;
    Console.WriteLine($"imports={asset.Imports.Count}");
    Console.WriteLine($"mic={mic}");
    for (var i = 0; i < asset.Imports.Count; i++)
    {
        var im = asset.Imports[i];
        Console.WriteLine($"{i}|{im.ClassPackage}|{im.ClassName}|{im.ObjectName}|{im.OuterIndex}");
    }
    return 0;
}

if (mode == "extras")
{
    // 打印 export 的 Extras（= 属性块之后的"cooked 平台数据"原始字节）+ SerialSize。
    // 用途：给 USoundWave 这种"数据在 Extras 里"的资产做最小改动（只换 Extras）。
    var ne0 = (NormalExport)asset.Exports[0];
    var ex0 = ne0.Extras ?? Array.Empty<byte>();
    Console.WriteLine($"extras_len={ex0.Length}");
    for (var i = 0; i < ex0.Length; i += 16)
        Console.WriteLine($"  {i:X4}  {Convert.ToHexString(ex0, i, Math.Min(16, ex0.Length - i))}");
    var e0 = asset.Exports[0];
    Console.WriteLine($"serial_size={e0.SerialSize} serial_offset={e0.SerialOffset} outer={e0.OuterIndex} class={e0.ClassIndex}");
    var uexpPath = Path.ChangeExtension(ua, ".uexp");
    Console.WriteLine($"uexp_len={(File.Exists(uexpPath) ? new FileInfo(uexpPath).Length : -1)}");
    return 0;
}

if (mode == "props")
{
    // 反射式属性树转储（不依赖 UAssetAPI 具体 API 名）——用于看清 MapProperty 的键/值结构。
    var maxItems = args.Length > 3 ? int.Parse(args[3]) : 3;
    var skip = new[] { "Asset", "Mappings", "Ancestry", "Encoding", "MappingsContainer", "NameMap", "EnumMap", "Schemas" };

    static string Show(object? o)
    {
        if (o is null) return "<null>";
        if (o is FString fs) return "\"" + fs.Value + "\"";
        if (o is string s) return "\"" + s + "\"";
        var t = o.GetType();
        if (t.Name == "FName")
        {
            var vp = t.GetProperty("Value");
            var vv = vp?.GetValue(o);
            return "FName(" + (vv is FString f2 ? "\"" + f2.Value + "\"" : "?") + ")";
        }
        if (t.IsPrimitive || t.IsEnum || o is decimal) return o.ToString() ?? "";
        return t.Name;
    }

    void DumpObj(object? o, string ind, int d)
    {
        if (o is null) { Console.WriteLine($"{ind}<null>"); return; }
        var t = o.GetType();
        if (t.Name is "UAsset" or "Usmap" or "TypeMappings") { Console.WriteLine($"{ind}<{t.Name}>"); return; }
        if (o is string || o is FString || t.Name == "FName" || t.IsPrimitive || t.IsEnum)
        { Console.WriteLine($"{ind}{Show(o)}"); return; }
        if (d > 7) { Console.WriteLine($"{ind}{Show(o)} …"); return; }
        if (maxItems >= 0 && o is System.Collections.IEnumerable en && o is not string)
        {
            var i = 0;
            foreach (var it in en)
            {
                if (i++ >= maxItems) { Console.WriteLine($"{ind}…"); break; }
                Console.WriteLine($"{ind}[{i - 1}]");
                DumpObj(it, ind + "  ", d + 1);
            }
            if (i == 0) Console.WriteLine($"{ind}(empty)");
            return;
        }
        Console.WriteLine($"{ind}<{t.Name}>");
        foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.Instance))
        {
            if (skip.Contains(f.Name)) { Console.WriteLine($"{ind} .{f.Name} = <skipped>"); continue; }
            Console.WriteLine($"{ind} .{f.Name}:");
            DumpObj(f.GetValue(o), ind + "   ", d + 1);
        }
        foreach (var pr in t.GetProperties(BindingFlags.Public | BindingFlags.Instance))
        {
            if (pr.GetIndexParameters().Length != 0 || skip.Contains(pr.Name)) continue;
            object? v; try { v = pr.GetValue(o); } catch { continue; }
            Console.WriteLine($"{ind} #{pr.Name}:");
            DumpObj(v, ind + "   ", d + 1);
        }
    }
    foreach (var pd in ((NormalExport)asset.Exports[0]).Data)
    {
        if (pd is not MapPropertyData mpd)
        {
            // 非 Map 属性也要能看：MI 的 TextureParameterValues / ScalarParameterValues
            // 就藏在这里面（ObjectPropertyData 的 FPackageIndex + FloatPropertyData）。
            Console.WriteLine($"PROP {pd.Name} ({pd.GetType().Name})");
            DumpObj(pd, "  ", 0);
            continue;
        }
        Console.WriteLine($"MAP {Show(mpd.Name)} KeyType={Show(mpd.KeyType)} ValueType={Show(mpd.ValueType)}");
        DumpObj(mpd.Value, "  ", 0);
    }
    return 0;
}

if (mode == "sndmk")
{
    // sndmk <shellUasset> <usmap> <outDir> <newObjectName> <newPackagePath> <newFormatName> <wavFile>
    //   把 BINKA 壳改造成「流式 + AudioFormat=<newFormatName> + 单 chunk 内联负载 = 整个 RIFF/WAVE 文件」
    //   的 PCM SoundWave。属性块、flags、cue 表都不动，只换 Extras 的平台数据段。
    if (args.Length < 8) { Console.Error.WriteLine("usage: da-patch sndmk <uasset> <usmap> <outDir> <newObjName> <newPkgPath> <formatName> <wavFile>"); return 2; }
    var newName = args[4];
    var newPkg = args[5];
    var fmtName = args[6];
    var wavPath = Path.GetFullPath(args[7]);
    var wav = File.ReadAllBytes(wavPath);

    if (wav.Length < 44 || wav[0] != 0x52 || wav[1] != 0x49 || wav[2] != 0x46 || wav[3] != 0x46)
    { Console.Error.WriteLine("FATAL: payload is not a RIFF file"); return 5; }
    var fmtOff = -1; var dataOff = -1; var dataLen = 0;
    var p = 12;
    while (p + 8 <= wav.Length)
    {
        var id = System.Text.Encoding.ASCII.GetString(wav, p, 4);
        var sz = BitConverter.ToInt32(wav, p + 4);
        if (id == "fmt ") fmtOff = p + 8;
        else if (id == "data") { dataOff = p + 8; dataLen = sz; }
        p += 8 + sz + (sz & 1);
    }
    if (fmtOff < 0 || dataOff < 0) { Console.Error.WriteLine("FATAL: fmt/data chunk missing"); return 6; }
    var wTag = BitConverter.ToUInt16(wav, fmtOff + 0);
    var ch = BitConverter.ToUInt16(wav, fmtOff + 2);
    var rate = BitConverter.ToInt32(wav, fmtOff + 4);
    var bits = BitConverter.ToUInt16(wav, fmtOff + 14);
    if (wTag != 1) { Console.Error.WriteLine($"FATAL: fmt tag {wTag} != 1 (PCM)"); return 7; }
    var frames = (long)(dataLen / (ch * (bits / 8)));
    var duration = (float)((double)frames / rate);
    Console.WriteLine($"WAV tag={wTag} ch={ch} rate={rate} bits={bits} dataBytes={dataLen} frames={frames} duration={duration}");

    // 1) 改 4 个属性值
    var ne2 = (NormalExport)asset.Exports[0];
    foreach (var pd in ne2.Data)
    {
        var nm = pd.Name.ToString();
        switch (nm)
        {
            case "NumChannels":
                if (pd is IntPropertyData ic0) ic0.Value = (int)ch;
                Console.WriteLine($"  set NumChannels={ch}");
                break;
            case "SampleRate":
                if (pd is IntPropertyData ic1) ic1.Value = rate;
                Console.WriteLine($"  set SampleRate={rate}");
                break;
            case "Duration":
                if (pd is FloatPropertyData fcd) fcd.Value = duration;
                else if (pd is DoublePropertyData dcd) dcd.Value = duration;
                Console.WriteLine($"  set Duration={duration}");
                break;
            case "TotalSamples":
                if (pd is FloatPropertyData fct) fct.Value = (float)frames;
                else if (pd is IntPropertyData ict) ict.Value = (int)frames;
                Console.WriteLine($"  set TotalSamples={frames}");
                break;
        }
    }

    // 2) 名字表：把旧格式名（BINKA 之类）就地换成新格式名；把 /Game/... 包路径换成新路径
    var at = asset.GetType();
    object listObj = null;
    foreach (var f in at.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
        if (f.FieldType == typeof(List<FString>)) { listObj = f.GetValue(asset); break; }
    if (listObj is null)
        foreach (var pr in at.GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
            if (pr.PropertyType == typeof(List<FString>) && pr.GetIndexParameters().Length == 0) { listObj = pr.GetValue(asset); break; }
    if (listObj is null) { Console.Error.WriteLine("FATAL: cannot find mutable name map"); return 4; }
    var names = (List<FString>)listObj;
    var knownFormats = new[] { "BINKA", "ADPCM", "PCM", "OPUS", "RADA", "OGG", "VORBIS" };
    var fmtIdx = -1;
    for (var i = 0; i < names.Count; i++)
    {
        if (fmtIdx < 0 && knownFormats.Contains(names[i].Value)) { Console.WriteLine($"  name[{i}] '{names[i].Value}' -> '{fmtName}'"); names[i] = new FString(fmtName); fmtIdx = i; }
        else if (names[i].Value != null && names[i].Value.StartsWith("/Game/")) { Console.WriteLine($"  name[{i}] '{names[i].Value}' -> '{newPkg}'"); names[i] = new FString(newPkg); }
    }
    if (fmtIdx < 0) { Console.Error.WriteLine("FATAL: no known audio-format name entry found"); return 8; }
    Console.WriteLine($"  format name index = {fmtIdx}");
    Console.WriteLine($"  FolderName '{asset.FolderName}' -> '{newPkg}'");
    asset.FolderName = new FString(newPkg);
    Console.WriteLine($"  export name '{asset.Exports[0].ObjectName}' -> '{newName}'");
    asset.Exports[0].ObjectName = new FName(asset, newName, 0);

    // 3) 换 Extras：保留 [0..8)（cookedFlags + cue 计数），重写 GUID/NumChunks/AudioFormat/chunk
    var shellExtras = ne2.Extras ?? Array.Empty<byte>();
    Console.WriteLine($"  shell extras_len={shellExtras.Length} head={Convert.ToHexString(shellExtras, 0, Math.Min(16, shellExtras.Length))}");
    const int prefixKeep = 8; // Extras 的 [cookedFlags(4)][cueCount(4)]，其后紧跟 GUID
    if (shellExtras.Length < prefixKeep + 16 + 8) { Console.Error.WriteLine("FATAL: shell extras too short"); return 9; }
    var ms = new MemoryStream();
    ms.Write(shellExtras, 0, prefixKeep);
    var guid = Guid.NewGuid().ToByteArray();
    ms.Write(guid, 0, 16);
    var w4 = new byte[4]; var w8 = new byte[8];
    BitConverter.GetBytes(1).CopyTo(w4, 0); ms.Write(w4, 0, 4);              // NumChunks = 1
    BitConverter.GetBytes(fmtIdx).CopyTo(w8, 0);                            // FName(index, 0)
    ms.Write(w8, 0, 8);
    BitConverter.GetBytes(5).CopyTo(w4, 0); ms.Write(w4, 0, 4);             // IsCooked | IsInlined
    w4 = new byte[4]; ms.Write(w4, 0, 4);                                   // bulk 头 = 0（内联）
    ms.Write(wav, 0, wav.Length);                                           // RIFF/WAVE 负载
    BitConverter.GetBytes(wav.Length).CopyTo(w4, 0); ms.Write(w4, 0, 4);    // DataSize
    BitConverter.GetBytes(wav.Length).CopyTo(w4, 0); ms.Write(w4, 0, 4);    // AudioDataSize
    var extras = ms.ToArray();
    ne2.Extras = extras;
    Console.WriteLine($"  new extras_len={extras.Length} (payload {wav.Length})");

    var od = Path.GetFullPath(args[3]);
    Directory.CreateDirectory(od);
    var op = Path.Combine(od, newName + ".uasset");
    asset.Write(op);
    foreach (var f in Directory.GetFiles(od).OrderBy(x => x))
        Console.WriteLine($"  out {Path.GetFileName(f)} {new FileInfo(f).Length} B sha={Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f)))[..16]}");
    return 0;
}

if (mode == "type")
{
    // type <uasset> <usmap> <NamePrefix>   反射打印 UAssetAPI 里匹配的类型成员（诊断用）
    var pf = args.Length > 3 ? args[3] : "TMap";
    foreach (var t in typeof(UAsset).Assembly.GetTypes().Where(x => x.Name.StartsWith(pf, StringComparison.Ordinal)).OrderBy(x => x.FullName))
    {
        Console.WriteLine($"TYPE {t.FullName} genericDef={t.IsGenericTypeDefinition}");
        foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
            Console.WriteLine($"  field {(f.IsPublic ? "pub" : "pri")} {f.FieldType.Name} {f.Name}");
        foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.Static))
            Console.WriteLine($"  prop  {(p.GetMethod?.IsPublic == true ? "pub" : "pri")} {p.PropertyType.Name} {p.Name} set={p.CanWrite}");
        foreach (var mm in t.GetMethods(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance | BindingFlags.DeclaredOnly))
            if (!mm.IsSpecialName) Console.WriteLine($"  meth  {mm.ReturnType.Name} {mm.Name}({string.Join(",", mm.GetParameters().Select(x => x.ParameterType.Name))})");
    }
    return 0;
}

if (mode == "sndmap")
{
    // sndmap <uasset> <usmap> <outDir> <newKeyName> <assetPackagePath> <assetObjectName>
    //   在 DA_BGM/DA_Ambient/DA_Sounds 的 BGMMap（TMap<FName, TSoftObjectPtr<USoundWave>>）
    //   **末尾追加一行**（克隆最后一行的 PropertyData 对象，只改 FName 与软路径）。
    //   软路径不进 ImportMap ⇒ 零 import 手术（与背景 DA 的方案 A 同理）。
    if (args.Length < 7) { Console.Error.WriteLine("usage: da-patch sndmap <uasset> <usmap> <outDir> <keyName> <pkgPath> <objName>"); return 2; }
    var keyName = args[4];
    var pkgPath = args[5];
    var objName = args[6];

    // 只对 FName/FString/FSoftObjectPath/FTopLevelAssetPath/PropertyData 这几类做深克隆，
    // 避免浅克隆共享嵌套对象导致"改克隆体把原条目也改了"。
    var deepTypes = new[] { "FName", "FString", "FSoftObjectPath", "FTopLevelAssetPath", "NamePropertyData", "SoftObjectPropertyData" };
    object? Clone(object o)
    {
        var m = typeof(object).GetMethod("MemberwiseClone", BindingFlags.NonPublic | BindingFlags.Instance)!;
        return m.Invoke(o, null);
    }
    object? GetMember(object o, string name)
    {
        var t = o.GetType();
        var f = t.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
        if (f is not null) return f.GetValue(o);
        var p = t.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
        if (p is not null && p.GetIndexParameters().Length == 0) return p.GetValue(o);
        return null;
    }
    object? DeepClone(object? o, int d = 0)
    {
        if (o is null || d > 6) return o;
        var t = o.GetType();
        if (t.IsPrimitive || t.IsEnum || o is string || o is decimal) return o;
        var c = Clone(o);
        foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
        {
            if (f.IsInitOnly) continue;
            var v = f.GetValue(o);
            if (v is null || v.GetType().IsPrimitive || v is string) continue;
            if (deepTypes.Contains(v.GetType().Name)) f.SetValue(c, DeepClone(v, d + 1));
        }
        foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
        {
            if (p.GetIndexParameters().Length != 0 || !p.CanWrite) continue;
            object? v; try { v = p.GetValue(o); } catch { continue; }
            if (v is null || v.GetType().IsPrimitive || v is string) continue;
            if (deepTypes.Contains(v.GetType().Name)) { try { p.SetValue(c, DeepClone(v, d + 1)); } catch { } }
        }
        return c;
    }
    void SetFNameValue(object fn, string text)
    {
        var t = fn.GetType();
        var p = t.GetProperty("Value");
        if (p is not null && p.CanWrite) { p.SetValue(fn, new FString(text)); return; }
        foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
            if (f.FieldType == typeof(FString)) { f.SetValue(fn, new FString(text)); return; }
        var pf = t.GetField("Value", BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
        if (pf is not null) { pf.SetValue(fn, new FString(text)); return; }
        throw new InvalidOperationException("cannot set FName value on " + t.Name);
    }
    System.Collections.IList? GetList(object tm, string name)
    {
        var t = tm.GetType();
        foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
            if (string.Equals(f.Name, name, StringComparison.OrdinalIgnoreCase) && f.GetValue(tm) is System.Collections.IList l) return l;
        foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
            if (string.Equals(p.Name, name, StringComparison.OrdinalIgnoreCase) && p.GetIndexParameters().Length == 0
                && p.GetValue(tm) is System.Collections.IList l2) return l2;
        return null;
    }

    var mp = ((NormalExport)asset.Exports[0]).Data.OfType<MapPropertyData>().FirstOrDefault();
    if (mp is null) { Console.Error.WriteLine("FATAL: no MapProperty found"); return 3; }
    var mapObj = mp.Value;
    var pairs = new List<KeyValuePair<object, object>>();
    foreach (var kv in (System.Collections.IEnumerable)mapObj)
    {
        var kt = kv!.GetType();
        var k = kt.GetProperty("Key")!.GetValue(kv)!;
        var v = kt.GetProperty("Value")!.GetValue(kv)!;
        pairs.Add(new KeyValuePair<object, object>(k, v));
    }
    Console.WriteLine($"map entries = {pairs.Count}");
    // 从后往前挑一个"软路径非空"的条目当模板
    object? lastK = null, lastV = null;
    for (var i = pairs.Count - 1; i >= 0; i--)
    {
        var pv = GetMember(pairs[i].Value, "Value");
        var ap0 = pv is null ? null : GetMember(pv, "AssetPath");
        var pn0 = ap0 is null ? null : GetMember(ap0, "PackageName");
        if (pn0 is not null) { lastK = pairs[i].Key; lastV = pairs[i].Value; break; }
    }
    if (lastK is null || lastV is null) { Console.Error.WriteLine("FATAL: no non-null soft-path template entry"); return 5; }
    var newK = DeepClone(lastK)!;
    var newV = DeepClone(lastV)!;

    // 改 key：NamePropertyData.Value = FName(keyName)
    var keyFName = GetMember(newK, "Value") ?? throw new InvalidOperationException("key has no Value");
    Console.WriteLine($"  key -> {keyName}");
    SetFNameValue(keyFName, keyName);

    // 改 value：SoftObjectPropertyData.Value(FSoftObjectPath).AssetPath(PackageName/AssetName)
    var sv = GetMember(newV, "Value") ?? throw new InvalidOperationException("value has no Value");
    var ap = GetMember(sv, "AssetPath") ?? throw new InvalidOperationException("no AssetPath");
    var pnF = GetMember(ap, "PackageName") ?? throw new InvalidOperationException("no PackageName");
    var anF = GetMember(ap, "AssetName") ?? throw new InvalidOperationException("no AssetName");
    Console.WriteLine($"  pkg -> {pkgPath}");
    Console.WriteLine($"  obj -> {objName}");
    SetFNameValue(pnF, pkgPath);
    SetFNameValue(anF, objName);

    // 注册新名字（UAssetAPI 写盘时按名字表索引，必须先在名字表里）
    foreach (var nm in new[] { keyName, pkgPath, objName })
    {
        var idx = asset.AddNameReference(new FString(nm), false, false);
        Console.WriteLine($"  AddNameReference('{nm}') -> {idx}");
    }

    // TMap 内部是 KeyedCollection2，Keys/Values 只是投影 ⇒ 必须走 Add(TKey,TValue)
    var mapT = mapObj.GetType();
    var addM = mapT.GetMethods(BindingFlags.Public | BindingFlags.Instance)
        .Where(x => x.Name == "Add" && x.GetParameters().Length == 2 && x.GetParameters()[0].ParameterType != typeof(object))
        .OrderBy(x => x.GetParameters()[0].ParameterType == typeof(object) ? 1 : 0)
        .FirstOrDefault();
    if (addM is null) { Console.Error.WriteLine("FATAL: no usable TMap.Add(TKey,TValue)"); return 4; }
    Console.WriteLine($"  using map.Add({addM.GetParameters()[0].ParameterType.Name}, {addM.GetParameters()[1].ParameterType.Name})");
    addM.Invoke(mapObj, new object?[] { newK, newV });
    var cnt = mapT.GetProperty("Count")!.GetValue(mapObj);
    Console.WriteLine($"  appended -> count {cnt}");

    var od = Path.GetFullPath(args[3]);
    Directory.CreateDirectory(od);
    var op = Path.Combine(od, Path.GetFileName(ua));
    asset.Write(op);
    foreach (var f in Directory.GetFiles(od).OrderBy(x => x))
        Console.WriteLine($"  out {Path.GetFileName(f)} {new FileInfo(f).Length} B sha={Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f)))[..16]}");
    return 0;
}

// ---------------------------------------------------------------------------
// ImportMap 手术共用件（mimk / bgref 都用）
//   原则：**只追加、不重排**；template 一律从本资产已有的原生 import 里克隆，
//   连字段组合（ClassPackage/ClassName/PackageName/bImportOptional）都照抄，
//   以免手搓出来的 Import 与引擎预期不一致。FName / FPackageIndex 必须换成
//   新对象，否则改克隆体会把原生 import 一起改掉（MemberwiseClone 是浅克隆）。
// ---------------------------------------------------------------------------
static object? _GetM(object o, string name)
{
    var t = o.GetType();
    var f = t.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
    if (f is not null) return f.GetValue(o);
    var p = t.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
    if (p is not null && p.GetIndexParameters().Length == 0) return p.GetValue(o);
    return null;
}

static void _SetM(object o, string name, object? v)
{
    var t = o.GetType();
    var f = t.GetField(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
    if (f is not null) { f.SetValue(o, v); return; }
    var p = t.GetProperty(name, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
    if (p is not null && p.CanWrite) { p.SetValue(o, v); return; }
    throw new InvalidOperationException("cannot set " + t.Name + "." + name);
}

static object _Shallow(object o) =>
    typeof(object).GetMethod("MemberwiseClone", BindingFlags.NonPublic | BindingFlags.Instance)!
        .Invoke(o, null)!;

static string _FNameText(object? fn) => fn is null ? "" : (_GetM(fn, "Value")?.ToString() ?? "");

static FPackageIndex _IdxLike(object proto, int v)
{
    // 克隆一个已有的 FPackageIndex 再改 Index：不走 ctor，避免 trim 掉私有构造。
    var o = (FPackageIndex)_Shallow(proto);
    typeof(FPackageIndex).GetField("Index")!.SetValue(o, v);
    return o;
}

static System.Collections.IList _ImportList(UAsset a, string label)
{
    var list = a.Imports as System.Collections.IList;
    if (list is null || list.IsFixedSize)
    {
        var copy = new List<Import>(a.Imports);
        _SetM(a, "Imports", copy);
        list = copy;
        Console.WriteLine($"  ({label}) asset.Imports was not a growable IList -> replaced by List<Import>");
    }
    return list;
}

/// 在 DA / MI 的 ImportMap 末尾追加「一个包引用」：Package + 对象，返回对象 import 的下标。
/// pkgTemplate / objTemplate 是本资产里已有的原生成对 import（保证字段形状一致）。
static int _AppendPackageRef(UAsset a, System.Collections.IList imports,
                             object pkgTemplate, object objTemplate,
                             string pkgPath, string objName, string label)
{
    a.AddNameReference(new FString(pkgPath), false, false);
    a.AddNameReference(new FString(objName), false, false);
    var pkgIdx = imports.Count;
    var objIdx = pkgIdx + 1;

    var newPkg = _Shallow(pkgTemplate);
    _SetM(newPkg, "ObjectName", new FName(a, pkgPath, 0));
    var newObj = _Shallow(objTemplate);
    _SetM(newObj, "ObjectName", new FName(a, objName, 0));
    _SetM(newObj, "OuterIndex", _IdxLike(_GetM(objTemplate, "OuterIndex")!, -(pkgIdx + 1)));

    imports.Add(newPkg);
    imports.Add(newObj);
    Console.WriteLine($"  import[{pkgIdx}] Package {pkgPath}");
    Console.WriteLine($"  import[{objIdx}] {_FNameText(_GetM(newObj, "ClassName"))} {objName} "
                      + $"outer={-(pkgIdx + 1)}  -> FPackageIndex {-(objIdx + 1)}");
    return objIdx;
}

if (mode == "mimk")
{
    // mimk <miShell.uasset> <usmap> <outDir> <newObjectName> <newPackagePath>
    //      <texturePackagePath> <textureObjectName> [ParamName=Value ...]
    //   克隆一个背景预览 MI（UMaterialInstanceConstant）：
    //     * 内部身份三处一起改（FolderName + 名字表包路径 + export ObjectName）
    //     * 在本 MI 自己的 ImportMap 末尾追加 2 条 import（Package + Texture2D）
    //     * 把 TextureParameterValues 里的对象引用重指到我们的贴图包（缩略图的真源）
    //     * 按名字改标量参数（SpriteWidth/SpriteHeight/TextureWidth/TextureHeight/SpriteX/Y...）
    if (args.Length < 8)
    {
        Console.Error.WriteLine("usage: da-patch mimk <mi.uasset> <usmap> <outDir> <newObj> "
                                + "<newPkg> <texPkg> <texObj> [Name=Value ...]");
        return 2;
    }
    var miNewObj = args[4];
    var miNewPkg = args[5];
    var texPkg = args[6];
    var texObj = args[7];
    var wantScalars = new Dictionary<string, float>(StringComparer.OrdinalIgnoreCase);
    for (var i = 8; i < args.Length; i++)
    {
        var kv = args[i].Split(new[] { '=' }, 2);
        if (kv.Length != 2) { Console.Error.WriteLine($"FATAL: bad parameter spec '{args[i]}'"); return 2; }
        wantScalars[kv[0]] = float.Parse(kv[1], System.Globalization.CultureInfo.InvariantCulture);
    }

    var neMi = (NormalExport)asset.Exports[0];
    var importsMi = _ImportList(asset, "mimk");
    // CP-37: passing "-" as the texture means "keep the shell's own TextureParameterValues".
    // The native preview MI shells already point SourceTexture at the game's preview atlas, and the
    // atlas route must NOT append a second import pair for it: our MI then keeps exactly the native
    // shape and the only semantic change is SpriteX/SpriteY (the two scalars the game copies into the
    // right-hand preview block and the timeline cell).  Any other value keeps the CP-34 behaviour.
    var keepTex = texPkg == "-" || texObj == "-";

    object? pkgTemplate = null, objTemplate = null;
    var objTemplateIdx = -1;
    for (var i = 0; i < importsMi.Count; i++)
    {
        var im = importsMi[i]!;
        var outer = _GetM(im, "OuterIndex");
        var oi = outer is null ? 0 : Convert.ToInt32(_GetM(outer, "Index"));
        if (_FNameText(_GetM(im, "ClassName")) == "Texture2D" && oi < 0)
        {
            objTemplate = im;
            objTemplateIdx = i;
            pkgTemplate = importsMi[-oi - 1];
        }
    }
    if (objTemplate is null || pkgTemplate is null)
    {
        Console.Error.WriteLine("FATAL: this MI has no (Package -> Texture2D) import pair to clone");
        return 5;
    }
    Console.WriteLine($"  templates: pkg='{_FNameText(_GetM(pkgTemplate, "ObjectName"))}' "
                      + $"obj='{_FNameText(_GetM(objTemplate, "ObjectName"))}'");
    int texObjIdx;
    if (keepTex)
    {
        texPkg = _FNameText(_GetM(pkgTemplate, "ObjectName"));
        texObj = _FNameText(_GetM(objTemplate, "ObjectName"));
        texObjIdx = objTemplateIdx;
        Console.WriteLine($"  keep-tex: SourceTexture stays on the shell's own import[{texObjIdx}] "
                          + $"{texPkg}/{texObj} (no import appended)");
    }
    else
    {
        texObjIdx = _AppendPackageRef(asset, importsMi, pkgTemplate, objTemplate, texPkg, texObj, "mimk");
    }
    var texRef = -(texObjIdx + 1);

    PropertyData? tpv = null, spv = null;
    foreach (var pd in neMi.Data)
    {
        if (pd.Name.ToString() == "TextureParameterValues") tpv = pd;
        else if (pd.Name.ToString() == "ScalarParameterValues") spv = pd;
    }
    if (tpv is null) { Console.Error.WriteLine("FATAL: no TextureParameterValues on this MI"); return 6; }

    void Flatten(PropertyData pd, List<PropertyData> acc)
    {
        acc.Add(pd);
        if (pd is ArrayPropertyData ap && ap.Value != null)
            foreach (var e in ap.Value) Flatten(e, acc);
        if (pd is StructPropertyData spx && spx.Value != null)
            foreach (var e in spx.Value) Flatten(e, acc);
    }

    var flatT = new List<PropertyData>();
    Flatten(tpv, flatT);
    var objRefs = flatT.OfType<ObjectPropertyData>().ToList();
    Console.WriteLine($"  TextureParameterValues: {objRefs.Count} object reference(s) -> {texRef}");
    if (objRefs.Count == 0)
    {
        Console.Error.WriteLine("FATAL: no ObjectPropertyData inside TextureParameterValues");
        return 7;
    }
    foreach (var op in objRefs)
    {
        var cur = op.Value is null ? 0 : Convert.ToInt32(_GetM(op.Value, "Index"));
        Console.WriteLine($"    {op.Name} was {cur} -> {texRef}");
        if (keepTex)
        {
            if (cur != texRef)
            {
                Console.Error.WriteLine($"FATAL: -keep-tex but {op.Name} points at import {cur}, "
                                        + $"expected the shell's own {texRef}");
                return 9;
            }
        }
        else
        {
            op.Value = _IdxLike(op.Value ?? _GetM(objTemplate, "OuterIndex")!, texRef);
        }
    }

    var setDone = new List<string>();
    var kept = new List<string>();
    if (spv is ArrayPropertyData spa && spa.Value != null)
    {
        foreach (var el in spa.Value)
        {
            var fx = new List<PropertyData>();
            Flatten(el, fx);
            var nmProp = fx.OfType<NamePropertyData>().FirstOrDefault();
            var flProp = fx.OfType<FloatPropertyData>().FirstOrDefault();
            if (nmProp is null || flProp is null)
            {
                Console.WriteLine("    (unparsed scalar element: "
                                  + string.Join(",", fx.Select(x => x.GetType().Name + ":" + x.Name)) + ")");
                continue;
            }
            var pname = nmProp.Value.ToString();
            if (wantScalars.TryGetValue(pname, out var v))
            {
                Console.WriteLine($"    scalar {pname}: {flProp.Value} -> {v}");
                flProp.Value = v;
                setDone.Add(pname);
            }
            else
            {
                Console.WriteLine($"    scalar {pname}: {flProp.Value} (kept)");
                kept.Add(pname);
            }
        }
    }
    var absent = wantScalars.Keys.Where(k => !setDone.Contains(k, StringComparer.OrdinalIgnoreCase)).ToList();
    Console.WriteLine($"  scalars set=[{string.Join(",", setDone)}] absent=[{string.Join(",", absent)}] "
                      + $"kept=[{string.Join(",", kept)}]");

    // ---- 内部身份：FolderName + 名字表包路径条目 + export ObjectName
    var nmList = asset.GetNameMapIndexList();
    var frag = Path.GetFileNameWithoutExtension(ua);
    var hits = Enumerable.Range(0, nmList.Count)
        .Where(i => nmList[i] != null && nmList[i].Value != null && nmList[i].Value.StartsWith("/Game/")
                    && nmList[i].Value.EndsWith("/" + frag)).ToList();
    Console.WriteLine($"  old package-path name entries (/Game/.../{frag}): [{string.Join(",", hits)}]");
    if (hits.Count != 1)
    {
        Console.Error.WriteLine("FATAL: expected exactly one old package-path entry in the MI");
        return 8;
    }
    object? nmObj = null;
    foreach (var f in asset.GetType().GetFields(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
        if (f.FieldType == typeof(List<FString>)) { nmObj = f.GetValue(asset); break; }
    if (nmObj is null)
        foreach (var p in asset.GetType().GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
            if (p.PropertyType == typeof(List<FString>) && p.GetIndexParameters().Length == 0)
            { nmObj = p.GetValue(asset); break; }
    if (nmObj is null) { Console.Error.WriteLine("FATAL: cannot find a mutable List<FString> name map"); return 4; }
    Console.WriteLine($"  name[{hits[0]}] '{((List<FString>)nmObj)[hits[0]]}' -> '{miNewPkg}'");
    ((List<FString>)nmObj)[hits[0]] = new FString(miNewPkg);
    Console.WriteLine($"  FolderName '{asset.FolderName}' -> '{miNewPkg}'");
    asset.FolderName = new FString(miNewPkg);
    Console.WriteLine($"  export '{asset.Exports[0].ObjectName}' -> '{miNewObj}'");
    asset.Exports[0].ObjectName = new FName(asset, miNewObj, 0);

    var odMi = Path.GetFullPath(args[3]);
    Directory.CreateDirectory(odMi);
    var opMi = Path.Combine(odMi, miNewObj + ".uasset");
    asset.Write(opMi);
    foreach (var f in Directory.GetFiles(odMi).OrderBy(x => x))
        Console.WriteLine($"  out {Path.GetFileName(f)} {new FileInfo(f).Length} B "
                          + $"sha={Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f)))[..16]}");
    Console.WriteLine($"MIMK_OK obj={miNewObj} pkg={miNewPkg} tex={texPkg}/{texObj} texRef={texRef} "
                      + $"imports={importsMi.Count} scalars={string.Join(",", setDone)} "
                      + $"absent={string.Join(",", absent)}");
    return 0;
}

if (mode == "bgref")
{
    // bgref <da.uasset> <usmap> <outDir> <miPackagePath> <miObjectName>
    //   在 DA_Backgrounds 的 ImportMap **末尾追加 2 条**（Package + MaterialInstanceConstant），
    //   打印该 MI 对象的 FPackageIndex（负值）供 python 写进新行的 @30。
    //   既有 333 条 import 的下标与字节完全不变（只追加不重排）。
    if (args.Length < 6)
    {
        Console.Error.WriteLine("usage: da-patch bgref <da.uasset> <usmap> <outDir> <miPkg> <miObj>");
        return 2;
    }
    var miPkg = args[4];
    var miObj = args[5];
    var importsDa = _ImportList(asset, "bgref");

    object? pkgTemplate = null, objTemplate = null;
    for (var i = 0; i < importsDa.Count; i++)
    {
        var im = importsDa[i]!;
        var outer = _GetM(im, "OuterIndex");
        var oi = outer is null ? 0 : Convert.ToInt32(_GetM(outer, "Index"));
        if (_FNameText(_GetM(im, "ClassName")) == "MaterialInstanceConstant" && oi < 0)
        {
            objTemplate = im;
            pkgTemplate = importsDa[-oi - 1];
            break;
        }
    }
    if (objTemplate is null || pkgTemplate is null)
    {
        Console.Error.WriteLine("FATAL: this DA has no (Package -> MaterialInstanceConstant) pair to clone");
        return 5;
    }
    Console.WriteLine($"  templates: pkg='{_FNameText(_GetM(pkgTemplate, "ObjectName"))}' "
                      + $"obj='{_FNameText(_GetM(objTemplate, "ObjectName"))}'");
    var beforeImports = importsDa.Count;
    var objIdxNew = _AppendPackageRef(asset, importsDa, pkgTemplate, objTemplate, miPkg, miObj, "bgref");

    var odDa = Path.GetFullPath(args[3]);
    Directory.CreateDirectory(odDa);
    var opDa = Path.Combine(odDa, Path.GetFileName(ua));
    asset.Write(opDa);
    foreach (var f in Directory.GetFiles(odDa).OrderBy(x => x))
        Console.WriteLine($"  out {Path.GetFileName(f)} {new FileInfo(f).Length} B "
                          + $"sha={Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f)))[..16]}");
    Console.WriteLine($"BGREF_OK ref={-(objIdxNew + 1)} imports={beforeImports}->{importsDa.Count} "
                      + $"pkg='{miPkg}' obj='{miObj}'");
    return 0;
}

if (mode == "miprobe")
{
    // miprobe <mi.uasset> <usmap>
    //   机器可读地打印这个 MI 的**渲染真值**：Parent / SourceTexture（参数名 + FPackageIndex
    //   + 解析到的 import）/ 全部标量参数值。判据用它，而不是"看起来像"。
    var neMp = (NormalExport)asset.Exports[0];

    string ResolveRef(object? idxObj)
    {
        if (idxObj is null) return "null";
        var raw = Convert.ToInt32(_GetM(idxObj, "Index"));
        if (raw >= 0) return $"export[{raw}]";
        var i = -raw - 1;
        if (i < 0 || i >= asset.Imports.Count) return $"import[{i}] OUT-OF-RANGE(={asset.Imports.Count})";
        var im = asset.Imports[i];
        return $"import[{i}] {_FNameText(_GetM(im, "ClassPackage"))}."
               + $"{_FNameText(_GetM(im, "ClassName"))} {_FNameText(_GetM(im, "ObjectName"))}";
    }

    void FlattenMp(PropertyData pd, List<PropertyData> acc)
    {
        acc.Add(pd);
        if (pd is ArrayPropertyData ap && ap.Value != null)
            foreach (var e in ap.Value) FlattenMp(e, acc);
        if (pd is StructPropertyData spx && spx.Value != null)
            foreach (var e in spx.Value) FlattenMp(e, acc);
    }

    Console.WriteLine($"MIPROBE export={asset.Exports[0].ObjectName} props={neMp.Data.Count} "
                      + $"imports={asset.Imports.Count} names={asset.GetNameMapIndexList().Count}");
    Console.WriteLine($"MIPROBE classIndex={asset.Exports[0].ClassIndex} -> "
                      + $"{ResolveRef(asset.Exports[0].ClassIndex)}");
    Console.WriteLine($"MIPROBE folder={asset.FolderName}");
    foreach (var pd in neMp.Data)
    {
        var pname = pd.Name.ToString();
        if (pname == "Parent" && pd is ObjectPropertyData pop)
            Console.WriteLine($"MIPROBE parent ref={pop.Value} -> {ResolveRef(pop.Value)}");
        else if (pname is "TextureParameterValues" or "ScalarParameterValues")
        {
            var arr = pd as ArrayPropertyData;
            var n = arr?.Value?.Length ?? 0;
            Console.WriteLine($"MIPROBE {pname} count={n}");
            for (var k = 0; k < n; k++)
            {
                var fx = new List<PropertyData>();
                FlattenMp(arr!.Value![k], fx);
                var np = fx.OfType<NamePropertyData>().FirstOrDefault();
                var who = np is null ? "?" : np.Value.ToString();
                if (pname == "ScalarParameterValues")
                {
                    var fp = fx.OfType<FloatPropertyData>().FirstOrDefault();
                    Console.WriteLine($"MIPROBE scalar name={who} value={(fp is null ? "?" : fp.Value.ToString(System.Globalization.CultureInfo.InvariantCulture))}");
                }
                else
                {
                    var op = fx.OfType<ObjectPropertyData>().FirstOrDefault();
                    Console.WriteLine($"MIPROBE texture name={who} ref={op?.Value} -> {ResolveRef(op?.Value)}");
                }
            }
        }
    }
    Console.WriteLine("MIPROBE_OK");
    return 0;
}

if (mode == "probe" || mode == "names")
{
    var nm = asset.GetNameMapIndexList();
    for (var i = 0; i < nm.Count; i++) Console.WriteLine($"  name[{i}] = {nm[i]}");
    Console.WriteLine($"imports={asset.Imports.Count}");
    foreach (var im in asset.Imports) Console.WriteLine($"  import {im.ClassPackage} {im.ClassName} {im.ObjectName} outer={im.OuterIndex}");
    return 0;
}

if (mode == "addname")
{
    var newName = args[4];
    var idx = asset.AddNameReference(new FString(newName), false, false);
    Console.WriteLine($"AddNameReference('{newName}') -> index {idx}; names now {asset.GetNameMapIndexList().Count}");
}

var outDir = Path.GetFullPath(args[3]);
Directory.CreateDirectory(outDir);
var outPath = Path.Combine(outDir, Path.GetFileName(ua));
asset.Write(outPath);
foreach (var f in Directory.GetFiles(outDir).OrderBy(x => x))
    Console.WriteLine($"  out {Path.GetFileName(f)} {new FileInfo(f).Length} B sha={Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f)))[..16]}");
return 0;
