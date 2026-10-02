using FusionRpg.Data;
using FusionRpg.Tools.CreatureCorpusDump;

// creature-seed module 1 (spec-corpus-dump.md): the whole almanac_seed/spawn_stats/recipes table,
// not the C# generator's opinion of it — the defect CreatureCorpusEmit had (Program.cs:45-52) is
// what this tool exists to fix. Every database read goes through RpgStore; no SQL here.
// Usage:
//   dotnet run --project gk-forge/tools/CreatureCorpusDump -- <server data dir> [output root]
//   dotnet run --project gk-forge/tools/CreatureCorpusDump -- <server data dir> --check      (owner, local, real DB)
//   dotnet run --project gk-forge/tools/CreatureCorpusDump -- --verify <dump root>           (CI — no DB needed)
//   dotnet run --project gk-forge/tools/CreatureCorpusDump -- --rehash-manifest <dump root>  (CI — no DB needed)
//   dotnet run --project gk-forge/tools/CreatureCorpusDump -- --base-stats <server data dir> [output root] [--check]
//        the game's own static type_base_stats table, committed as its own self-describing file so
//        a generator never has to open the uncommitted local rpg-hot.sqlite (creature-seed R-CS1)
if (args.Length >= 2 && args[0] == "--verify")
{
    var (ok, reason) = DumpWriter.VerifyCommittedTree(Path.GetFullPath(args[1]));
    if (!ok)
    {
        Console.Error.WriteLine($"corpus-dump --verify: {args[1]} FAILED self-consistency — {reason}");
        return 1;
    }
    // The static base-stat capture is a SEPARATE, self-describing file with its own hash (see
    // DumpTypeBaseStatsFile) — verified here too, so one CI step still covers the whole committed
    // tree, without folding an independent capture into the four-file manifest hash.
    var (statsOk, statsReason) = DumpWriter.VerifyCommittedTypeBaseStats(Path.GetFullPath(args[1]));
    if (!statsOk)
    {
        Console.Error.WriteLine($"corpus-dump --verify: {args[1]}/{DumpWriter.TypeBaseStatsFileName} FAILED self-consistency — {statsReason}");
        return 1;
    }
    Console.WriteLine($"corpus-dump --verify: {args[1]} is self-consistent ({reason}; base-stats {statsReason}).");
    return 0;
}

// `--rehash-manifest` rewrites ONLY `_manifest.json`, from the four payload files already on disk.
// It exists because a committed tree can carry a contentHash captured from payload bytes this repo
// never held while every COUNT still matches — a stale hash, not a stale corpus. The default run is
// the wrong instrument there (it re-exports all four payloads from today's database: measured
// baselineCount 82 -> 913, recipeCount 1295 -> 0), so this mode recomputes the hash from the
// committed bytes instead. Idempotent: a tree whose hash already matches is left untouched.
if (args.Length >= 2 && args[0] == "--rehash-manifest")
{
    var rehash = DumpWriter.RehashCommittedManifest(Path.GetFullPath(args[1]));
    if (!rehash.Ok)
    {
        Console.Error.WriteLine($"corpus-dump --rehash-manifest: {args[1]} REFUSED — {rehash.Reason}");
        return 1;
    }
    if (!rehash.Changed)
    {
        Console.WriteLine(
            $"corpus-dump --rehash-manifest: {args[1]} already current — {rehash.Reason} (nothing written).");
        return 0;
    }
    Console.WriteLine(
        $"corpus-dump --rehash-manifest: rewrote {Path.Combine(Path.GetFullPath(args[1]), DumpWriter.ManifestFileName)} — " +
        $"contentHash {rehash.DeclaredHash} -> {rehash.RecomputedHash}; capturedUtc preserved ({rehash.CapturedUtc}); " +
        "the four payload files were read, never written.");
    return 0;
}

// `--base-stats` writes ONLY type-base-stats.json. Deliberately not part of the default run: the
// four almanac/baseline/recipe payload files are a 2026-08-23 snapshot, and re-emitting them from
// today's database would be a large, unrelated diff nobody asked for. Re-capturing the static table
// is its own act, so it gets its own flag.
// `--rehash-type-base-stats` rewrites ONLY that file's contentHash, recomputed from its own committed
// entries. Its sibling `--rehash-manifest` recovered the manifest envelope; this envelope had no such
// mode, so its stale hash was a finding no one could act on. See RehashTypeBaseStats for the measurement.
if (args.Length >= 2 && args[0] == "--rehash-type-base-stats")
{
    var rehash = DumpWriter.RehashTypeBaseStats(Path.GetFullPath(args[1]));
    if (!rehash.Ok)
    {
        Console.Error.WriteLine($"corpus-dump --rehash-type-base-stats: {args[1]} REFUSED - {rehash.Reason}");
        return 1;
    }
    if (!rehash.Changed)
    {
        Console.WriteLine(
            $"corpus-dump --rehash-type-base-stats: {args[1]} already current - {rehash.Reason} (nothing written).");
        return 0;
    }
    Console.WriteLine(
        $"corpus-dump --rehash-type-base-stats: rewrote {Path.Combine(Path.GetFullPath(args[1]), DumpWriter.TypeBaseStatsFileName)} - " +
        $"contentHash {rehash.DeclaredHash} -> {rehash.RecomputedHash}; capturedUtc preserved ({rehash.CapturedUtc}); " +
        "the entries were read, never written.");
    return 0;
}

if (args.Length >= 2 && args[0] == "--base-stats")
{
    var bsCheckOnly = args.Contains("--check");
    var bsPositional = args.Skip(1).Where(a => a != "--check").ToArray();
    var bsDataDir = Path.GetFullPath(bsPositional[0]);
    var bsOutputRoot = Path.GetFullPath(bsPositional.Length > 1
        ? bsPositional[1]
        : Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "data", "seed", "creatures", "_dump"));

    var bsTuningDir = ResolveTuningDir(bsDataDir);
    if (bsTuningDir is null)
    {
        Console.Error.WriteLine($"no tuning dir found (looked in {Path.Combine(bsDataDir, "tuning")} and data/tuning)");
        return 1;
    }
    ConfigureDerivedStats(bsTuningDir);

    var bsStore = new RpgStore(bsDataDir);
    bsStore.Init();
    var file = DumpWriter.BuildTypeBaseStatsFile(CorpusReader.BuildTypeBaseStats(bsStore));
    var rendered = DumpWriter.RenderTypeBaseStatsFile(file);

    if (bsCheckOnly)
    {
        if (DumpWriter.TypeBaseStatsMatchesDisk(bsOutputRoot, rendered))
        {
            Console.WriteLine($"corpus-dump --base-stats --check: {Path.Combine(bsOutputRoot, DumpWriter.TypeBaseStatsFileName)} is current (hash {file.ContentHash}).");
            return 0;
        }
        Console.Error.WriteLine($"corpus-dump --base-stats --check: {Path.Combine(bsOutputRoot, DumpWriter.TypeBaseStatsFileName)} is STALE — re-run without --check and commit the result.");
        Console.Error.WriteLine($"  expected hash {file.ContentHash}, plant={file.PlantCount} zombie={file.ZombieCount} capturedUtc={file.CapturedUtc}");
        return 1;
    }

    DumpWriter.WriteTypeBaseStats(bsOutputRoot, rendered);
    Console.WriteLine(
        $"corpus-dump --base-stats: wrote {Path.Combine(bsOutputRoot, DumpWriter.TypeBaseStatsFileName)} — " +
        $"plant={file.PlantCount} zombie={file.ZombieCount} capturedUtc={file.CapturedUtc} hash={file.ContentHash}");
    return 0;
}

if (args.Length < 1)
{
    Console.Error.WriteLine("usage: CreatureCorpusDump <server data dir> [output root, default data/seed/creatures/_dump] [--check]");
    Console.Error.WriteLine("       CreatureCorpusDump --verify <dump root>   (CI, no database needed)");
    Console.Error.WriteLine("       CreatureCorpusDump --rehash-manifest <dump root>   (CI, no database needed)");
    return 1;
}

var checkOnly = args.Contains("--check");
var positional = args.Where(a => a != "--check").ToArray();

var dataDir = Path.GetFullPath(positional[0]);
var outputRoot = Path.GetFullPath(positional.Length > 1
    ? positional[1]
    : Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "data", "seed", "creatures", "_dump"));

var tuningDir = ResolveTuningDir(dataDir);
if (tuningDir is null)
{
    Console.Error.WriteLine($"no tuning dir found (looked in {Path.Combine(dataDir, "tuning")} and data/tuning)");
    return 1;
}
ConfigureDerivedStats(tuningDir);

var store = new RpgStore(dataDir);
store.Init();

var payload = CorpusReader.BuildPayload(store);

// capturedUtc: the store's own max(RebuiltUtc) over every exported almanac row — never
// DateTime.UtcNow (spec §2). A dump with zero rows has no rebuilt stamp to read; that is a
// preflight failure elsewhere, not something this tool papers over with wall-clock time.
var capturedUtc = CorpusReader.CapturedUtc(payload);

var tree = DumpWriter.BuildTree(payload, capturedUtc);

if (checkOnly)
{
    var matches = DumpWriter.MatchesDisk(outputRoot, tree);
    if (matches)
    {
        Console.WriteLine($"corpus-dump --check: tree at {outputRoot} is current (hash {tree.Manifest.ContentHash}).");
        return 0;
    }
    Console.Error.WriteLine($"corpus-dump --check: tree at {outputRoot} is STALE — run without --check and commit the result.");
    Console.Error.WriteLine($"  expected hash {tree.Manifest.ContentHash}, plant={tree.Manifest.PlantCount} zombie={tree.Manifest.ZombieCount} baselines={tree.Manifest.BaselineCount} recipes={tree.Manifest.RecipeCount}");
    return 1;
}

DumpWriter.WriteToDisk(outputRoot, tree);
Console.WriteLine(
    $"corpus-dump: wrote {outputRoot} — plant={tree.Manifest.PlantCount} zombie={tree.Manifest.ZombieCount} " +
    $"baselines={tree.Manifest.BaselineCount} recipes={tree.Manifest.RecipeCount} capturedUtc={capturedUtc} hash={tree.Manifest.ContentHash}");
return 0;

static string? ResolveTuningDir(string dataDir) => new[]
    {
        Path.Combine(dataDir, "tuning"),
        Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "data", "tuning")
    }
    .Select(Path.GetFullPath)
    .FirstOrDefault(d => File.Exists(Path.Combine(d, "derived-stats.v2.json")));

// RpgStore's static ctor builds a DerivedStatRegistry, which reads DerivedStatPolicy — throws
// unless Configure has run first (tunables-ssot.md T5). Same fix CreatureCorpusEmit needed.
static void ConfigureDerivedStats(string tuningDir) =>
    FusionRpg.Core.Stats.Derived.DerivedStatPolicy.Configure(
        FusionRpg.Core.Stats.Derived.DerivedStatTuningLoader.Parse(
            File.ReadAllText(Path.Combine(tuningDir, "derived-stats.v2.json"))));
