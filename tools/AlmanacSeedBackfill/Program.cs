using System.Text.Json;
using FusionRpg.Data;

// `creature-seed` module 13 (`catalog-runtime`) precondition, found running the real flip 2026-09-05:
// species-import's own name resolution (RpgStore.Species.cs's GetAlmanacSeed(side, gameTypeId)) falls
// back to "Creature {gameTypeId}" for every species on a database whose `almanac_seed` table has never
// been populated — which only happens via live, incremental in-game almanac browsing
// (RebuildAlmanacSeed's own source, type_almanac_dump). The committed corpus dump
// (gk-data/packs/fusion/data/seed/creatures/_dump/almanac/{plant,zombie}.json, corpus-dump/module 1) already carries that same
// already-parsed shape, captured once elsewhere. This tool loads it directly, once, so a database that
// has never had a human browse the in-game almanac still gets real names instead of placeholders.
//
// Usage: dotnet run --project gk-forge/tools/AlmanacSeedBackfill -- [--dump <dir>] [--db <dir>]
//        --dump   default: gk-data/packs/fusion/data/seed/creatures/_dump, found by walking up from the working directory
//        --db     default: $FUSIONRPG_DATA, else dist/FusionRpg.Server/data beside the repo root
//
// Exit codes: 0 written, 2 could not start.

var args2 = args.ToList();
string? dumpOverride = TakeOption("--dump");
string? dbOverride = TakeOption("--db");

string? TakeOption(string flag)
{
    var i = args2.IndexOf(flag);
    if (i < 0 || i + 1 >= args2.Count) return null;
    var value = args2[i + 1];
    args2.RemoveRange(i, 2);
    return value;
}

var dumpRoot = dumpOverride ?? FindUp("data", "seed", "creatures", "_dump");
if (dumpRoot is null || !Directory.Exists(dumpRoot))
{
    Console.Error.WriteLine("could not locate data/seed/creatures/_dump; pass --dump <dir>");
    return 2;
}

var plantPath = Path.Combine(dumpRoot, "almanac", "plant.json");
var zombiePath = Path.Combine(dumpRoot, "almanac", "zombie.json");
if (!File.Exists(plantPath) || !File.Exists(zombiePath))
{
    Console.Error.WriteLine($"missing {plantPath} or {zombiePath}");
    return 2;
}

var dataDir = dbOverride
              ?? Environment.GetEnvironmentVariable("FUSIONRPG_DATA")
              ?? FindUp("dist", "FusionRpg.Server", "data");
if (string.IsNullOrWhiteSpace(dataDir))
{
    Console.Error.WriteLine("no database directory: pass --db <dir> or set FUSIONRPG_DATA");
    return 2;
}

var jsonOpts = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };

List<DumpRow> ReadSide(string path)
{
    var rows = JsonSerializer.Deserialize<List<DumpRow>>(File.ReadAllText(path), jsonOpts);
    return rows ?? throw new InvalidOperationException($"{path}: did not deserialize to an array");
}

var plantRows = ReadSide(plantPath);
var zombieRows = ReadSide(zombiePath);
Console.WriteLine($"read {plantRows.Count} plant + {zombieRows.Count} zombie rows from {dumpRoot}");

var dtos = plantRows.Concat(zombieRows).Select(ToDto).ToList();

FusionRpg.Core.Stats.Derived.DerivedStatPolicy.Configure(
    FusionRpg.Core.Stats.Derived.DerivedStatTuningLoader.Parse(
        File.ReadAllText(Path.Combine(FindTuningDir(), "derived-stats.v2.json"))));

var store = new RpgStore(dataDir);
store.Init();
var written = store.UpsertAlmanacSeedBulk(dtos);
Console.WriteLine($"{written} almanac_seed rows written to {dataDir}");
return 0;

static AlmanacSeedDto ToDto(DumpRow r) => new()
{
    Side = r.Side,
    TypeId = r.TypeId,
    TypeName = r.TypeName,
    DisplayName = r.DisplayName,
    FlavorInfo = r.FlavorInfo,
    FlavorIntroduce = r.FlavorIntroduce,
    SunCost = r.SunCost,
    CooldownSec = r.CooldownSec,
    CostStatus = r.CostStatus ?? "absent",
    Hp = r.Hp,
    Attack = r.Attack,
    Armor = r.Armor,
    ArmorMax = r.ArmorMax,
    StatsObserved = r.StatsObserved,
    ContractVersion = r.ContractVersion,
    RebuiltUtc = r.RebuiltUtc ?? ""
};

static string FindTuningDir()
{
    var found = FindUp("data", "tuning");
    if (found is null) throw new InvalidOperationException("could not locate data/tuning");
    return found;
}

static string? FindUp(params string[] segments)
{
    var dir = new DirectoryInfo(Directory.GetCurrentDirectory());
    while (dir is not null)
    {
        var candidate = Path.Combine(new[] { dir.FullName }.Concat(segments).ToArray());
        if (Directory.Exists(candidate)) return candidate;
        dir = dir.Parent;
    }
    return null;
}

// Mirrors CreatureCorpusDump's own DumpAlmanacRow shape exactly (gk-forge/tools/CreatureCorpusDump/DumpWriter.cs's
// AlmanacRowNode) — this file's own JSON is that record's serialized form, captured once and
// committed. A local record here, not a shared one, since this tool has no other reason to reference
// CreatureCorpusDump's project.
sealed record DumpRow(
    string Side, int TypeId, string? TypeName, string? DisplayName, string? FlavorInfo,
    string? FlavorIntroduce, int? SunCost, double? CooldownSec, string? CostStatus,
    long? Hp, long? Attack, long? Armor, long? ArmorMax, bool StatsObserved,
    int ContractVersion, string? RebuiltUtc);
