// P-A 工具：从 IoStore 里读出某个 Texture2D 的 cooked 平台数据（mip 列表 / 每 mip 的字节与偏移基准）。
// 用途：为「同尺寸 BC1 替换 mip0」提供精确的负载偏移与长度（再用字节匹配在解包出的 .uexp 里定位）。
// 只读：不写游戏目录；把二进制 mip dump 到 outDir。
using System.Reflection;
using System.Security.Cryptography;
using CUE4Parse.Compression;
using CUE4Parse.FileProvider;
using CUE4Parse.MappingsProvider.Usmap;
using CUE4Parse.UE4.Versions;

// Speak UTF-8 on stdout/stderr however we were started.  core/common.py decodes
// subprocess output as UTF-8, but .NET uses the *console* code page and falls
// back to the ANSI code page (GBK) when the process has no console at all --
// which is exactly the case for the --windowed GUI exe.  Non-ASCII texture or
// package names would otherwise reach the builder as mojibake.
static void ForceUtf8Stdio()
{
    var enc = new System.Text.UTF8Encoding(false);   // no BOM
    try { Console.OutputEncoding = enc; } catch { }  // also puts an attached console on 65001
    try { Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), enc) { AutoFlush = true }); } catch { }
    try { Console.SetError(new StreamWriter(Console.OpenStandardError(), enc) { AutoFlush = true }); } catch { }
}
ForceUtf8Stdio();

if (args.Length < 3)
{
    Console.Error.WriteLine("usage: tex-inspect <Paks dir> <package path> <out dir> [usmap]");
    return 2;
}

var paks = Path.GetFullPath(args[0]);
var target = args[1].Replace('\\', '/');
var listOnly = target == "--list";
var audioOut = target == "--audio-out";
if (!listOnly && !audioOut &&
    !target.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase) &&
    !target.EndsWith(".umap", StringComparison.OrdinalIgnoreCase)) target += ".uasset";
var outDir = Path.GetFullPath(args[2]);
if (!listOnly && !audioOut) Directory.CreateDirectory(outDir);
var usmap = audioOut
    ? (args.Length > 4 ? Path.GetFullPath(args[4]) : "")
    : (args.Length > 3 ? Path.GetFullPath(args[3]) : "");

// Oodle：找现成的 oo2core，找不到就报错（不联网）
var candidates = new[]
{
    Path.Combine(AppContext.BaseDirectory, "native", "oo2core_9_win64.dll"),
    @"D:\dsharnessProject\CalabiyauGalMaker\tools\cue4parse-inspector\bin\Release\net10.0\native\oo2core_9_win64.dll",
    @"D:\dsharnessProject\CalabiyauGalMaker\tools\cue4parse-inspector\bin\Release\net10.0\oo2core_9_win64.dll",
};
var oodle = candidates.FirstOrDefault(File.Exists);
if (oodle is null) { Console.Error.WriteLine("oo2core_9_win64.dll not found"); return 5; }
OodleHelper.Initialize(oodle);
Console.WriteLine($"Oodle: {oodle}");
var zlib = new[]
{
    Path.Combine(AppContext.BaseDirectory, "native", "zlib-ng2.dll"),
    @"D:\dsharnessProject\CalabiyauGalMaker\tools\cue4parse-inspector\bin\Release\net10.0\native\zlib-ng2.dll",
}.FirstOrDefault(File.Exists);
if (zlib is not null) { ZlibHelper.Initialize(zlib); Console.WriteLine($"Zlib: {zlib}"); }

var provider = new DefaultFileProvider(paks, SearchOption.TopDirectoryOnly,
    new VersionContainer(EGame.GAME_UE5_7), StringComparer.OrdinalIgnoreCase);
if (usmap.Length > 0)
{
    provider.MappingsContainer = new FileUsmapTypeMappingsProvider(usmap);
    Console.WriteLine($"Mapping: {usmap}");
}
provider.Initialize();
provider.Mount();
provider.PostMount();
Console.WriteLine($"Files: {provider.Files.Count}");

// --audio-out <assetPath> <outWav>：把 USoundWave 的负载（引擎实际会读的字节）导出成 .wav，
// 用于 A4 判据「造出来的音频资产解码回 WAV 与源 WAV 逐字节一致」。
if (audioOut)
{
    var aPath = args[2].Replace('\\', '/');
    if (!aPath.EndsWith(".uasset", StringComparison.OrdinalIgnoreCase)) aPath += ".uasset";
    var wavOut = Path.GetFullPath(args[3]);
    if (!provider.TryGetGameFile(aPath, out var gfa)) { Console.Error.WriteLine($"lookup failed: {aPath}"); return 3; }
    var pkga = provider.LoadPackage(gfa);
    var exa = pkga.GetExports().First();
    Console.WriteLine($"EXPORT name={exa.Name} type={exa.GetType().FullName}");
    if (exa is not CUE4Parse.UE4.Assets.Exports.Sound.USoundWave sw)
    { Console.Error.WriteLine("FATAL: not a USoundWave"); return 4; }
    Console.WriteLine($"bStreaming={sw.bStreaming}");
    var ms = new MemoryStream();
    if (sw.RunningPlatformData is not null)
    {
        var rpd = sw.RunningPlatformData;
        Console.WriteLine($"NumChunks={rpd.NumChunks} AudioFormat=\"{rpd.AudioFormat.Text}\"");
        foreach (var c in rpd.Chunks)
        {
            var d = c.BulkData?.Data;
            Console.WriteLine($"  chunk DataSize={c.DataSize} AudioDataSize={c.AudioDataSize} actualBytes={(d?.Length ?? -1)}");
            if (d is not null) ms.Write(d, 0, d.Length);
        }
    }
    else if (sw.RawData?.Data is byte[] rd)
    {
        Console.WriteLine($"RawData bytes={rd.Length}");
        ms.Write(rd, 0, rd.Length);
    }
    var payload = ms.ToArray();
    if (payload.Length == 0) { Console.Error.WriteLine("FATAL: no payload bytes"); return 5; }
    if (!(payload.Length >= 12 && payload[0] == 0x52 && payload[1] == 0x49 && payload[2] == 0x46 && payload[3] == 0x46))
        Console.WriteLine("WARN: payload is not a RIFF/WAVE file (raw PCM)");
    File.WriteAllBytes(wavOut, payload);
    Console.WriteLine($"wrote {wavOut} {payload.Length} B sha256={Convert.ToHexString(SHA256.HashData(payload))[..16]}");
    return 0;
}

// --list：把所有资产路径打出来（只读侦察"游戏里有没有 X 类资产"）
if (listOnly)
{
    foreach (var k in provider.Files.Keys.OrderBy(x => x, StringComparer.OrdinalIgnoreCase))
        Console.WriteLine(k);
    return 0;
}

if (!provider.TryGetGameFile(target, out var gf))
{
    Console.Error.WriteLine($"lookup failed: {target}");
    return 3;
}
Console.WriteLine($"GameFile: {gf.Path} size={gf.Size}");
var pkg = provider.LoadPackage(gf);
Console.WriteLine($"Exports: {pkg.GetExports().Count()}");
foreach (var export in pkg.GetExports())
{
    Console.WriteLine($"EXPORT name={export.Name} type={export.GetType().FullName}");
    Dump(export, "  ", 0, 5);
}
return 0;

void Dump(object? value, string indent, int depth, int maxDepth)
{
    if (value is null) { Console.WriteLine($"{indent}<null>"); return; }
    var t = value.GetType();
    if (value is string s) { Console.WriteLine($"{indent}\"{s}\""); return; }
    if (value is Array arr)
    {
        if (value is byte[] bytes)
        {
            var head = Convert.ToHexString(bytes.AsSpan(0, Math.Min(32, bytes.Length)));
            var sha = Convert.ToHexString(SHA256.HashData(bytes)).Substring(0, 16);
            Console.WriteLine($"{indent}byte[{bytes.Length}] sha256={sha} head={head}");
            return;
        }
        Console.WriteLine($"{indent}{t.Name}[{arr.Length}]");
        if (depth >= maxDepth) return;
        var i = 0;
        foreach (var item in arr)
        {
            if (i++ > 40) { Console.WriteLine($"{indent}  ..."); break; }
            Console.WriteLine($"{indent} [{i - 1}]");
            Dump(item, indent + "   ", depth + 1, maxDepth);
        }
        return;
    }
    if (value is System.Collections.IDictionary dict)
    {
        Console.WriteLine($"{indent}{t.Name} count={dict.Count}");
        if (depth >= maxDepth) return;
        var k = 0;
        foreach (System.Collections.DictionaryEntry e in dict)
        {
            if (k++ > 20) { Console.WriteLine($"{indent}  ..."); break; }
            Console.WriteLine($"{indent} key={e.Key}");
            Dump(e.Value, indent + "   ", depth + 1, maxDepth);
        }
        return;
    }
    if (value is System.Collections.IEnumerable seq && value is not string)
    {
        var list = new List<object?>();
        foreach (var item in seq) { list.Add(item); if (list.Count > 300) break; }
        Console.WriteLine($"{indent}{t.Name} count={list.Count}");
        if (depth >= maxDepth) return;
        for (var i = 0; i < list.Count; i++)
        {
            Console.WriteLine($"{indent} [{i}]");
            Dump(list[i], indent + "   ", depth + 1, maxDepth);
        }
        return;
    }
    if (t.IsPrimitive || t.IsEnum || value is decimal)
    {
        Console.WriteLine($"{indent}{value}");
        return;
    }
    Console.WriteLine($"{indent}{t.FullName}");
    if (depth >= maxDepth) return;
    foreach (var p in t.GetProperties(BindingFlags.Public | BindingFlags.Instance))
    {
        if (p.GetIndexParameters().Length != 0) continue;
        object? v = null;
        try { v = p.GetValue(value); } catch (Exception ex) { Console.WriteLine($"{indent} {p.Name}=<err {ex.GetType().Name}>"); continue; }
        Console.WriteLine($"{indent} {p.Name}:");
        Dump(v, indent + "   ", depth + 1, maxDepth);
    }
    foreach (var f in t.GetFields(BindingFlags.Public | BindingFlags.Instance))
    {
        object? v = null;
        try { v = f.GetValue(value); } catch (Exception ex) { Console.WriteLine($"{indent} {f.Name}=<err {ex.GetType().Name}>"); continue; }
        Console.WriteLine($"{indent} {f.Name}:");
        Dump(v, indent + "   ", depth + 1, maxDepth);
    }
}
