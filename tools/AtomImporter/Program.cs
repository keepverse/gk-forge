using FusionRpg.Core.Effects.Atoms;
using FusionRpg.Core.Effects.Atoms.Power;
using FusionRpg.Data;
using FusionRpg.Data.Seed;
using FusionRpg.Tools.AtomImporter;

// The seed importer (E14a). Reads gk-data/packs/fusion/data/seed/**.json, validates everything, and writes it in one
// transaction — or writes nothing and says why.
//
// Usage: dotnet run --project gk-forge/tools/AtomImporter -- [seed root] [--db <dir>] [--check] [--validate]
//        seed root   default: gk-data/packs/fusion/data/seed, found by walking up from the working directory
//        --db        default: $FUSIONRPG_DATA, else dist/FusionRpg.Server/data beside the repo root
//        --check     validate against the real catalog and roll back — writes nothing
//        --validate  also run E14b's content checks (lint + power drift) over the imported batch
//                     and fail on a blocking finding (E24, completeness-audit.md B4 — these checks
//                     existed with zero callers outside their own tests)
//
// Exit codes: 0 imported/checked/validated clean, 1 refused, 2 could not start.
//
// This file holds arguments and a report. Every decision about content is in Core (the format) or
// the data project (the transaction), where scripts/guard-dal.ps1 applies — it does not scan
// tools/. Which files get swept is SeedScanner, next door, so a test can hold it to that.

var check = args.Contains("--check", StringComparer.Ordinal);
var validate = args.Contains("--validate", StringComparer.Ordinal);
var positional = new List<string>();
string? dbOverride = null;

for (var i = 0; i < args.Length; i++)
{
    if (args[i] == "--db" && i + 1 < args.Length) { dbOverride = args[++i]; continue; }
    if (args[i].StartsWith("--", StringComparison.Ordinal)) continue;
    positional.Add(args[i]);
}

var seedRoot = positional.Count > 0 ? Path.GetFullPath(positional[0]) : FindUp("data", "seed");
if (seedRoot is null || !Directory.Exists(seedRoot))
{
    Console.Error.WriteLine("could not locate data/seed; pass the seed root explicitly");
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

// SeedScanner and the sweep/read/collect sequence below now live in FusionRpg.Data.Seed
// (SeedImportRunner, E46 player-content-boot) — the server's own self-healing startup import calls
// the exact same members, so there is one implementation of "how a seed tree becomes catalog rows"
// rather than a second copy that can drift the way the affix folder once did unnoticed.
var roots = SeedImportRunner.Roots(seedRoot, explicitRoot: positional.Count > 0);
var files = SeedImportRunner.Files(roots);

if (files.Count == 0)
{
    // Never a silent green: an empty run and a clean run look identical from the exit code alone.
    Console.Error.WriteLine(
        roots.Count == 0
            ? $"no {string.Join("/ ", SeedScanner.OwnedFolders)}/ under {seedRoot} — nothing to import"
            : $"no *.json under {string.Join(", ", roots)} — nothing to import");
    return 1;
}

    // The lead-names registry is a process-wide static hub, and this tool is its own process. The
    // server configures it at boot and the Injector configures it at host start, so both reached
    // RpgStore's reader with it set — but the importer did not, and a cold import against an EMPTY
    // data dir (which is exactly what a first-time live-probe slot has) threw
    // "LeadNamesHub.Configure(...) has not run" and rolled the whole import back. A warm dir
    // re-imports clean, so the failure only ever appeared on a first deploy.
    //
    // Configured from the seed root THIS process was handed, not from an environment variable or a
    // guess about where the server keeps its published copy: the path is each host's own business,
    // and the read/parse/configure step is one shared implementation in Core.
    //
    // Conditional on the file being there, deliberately. A seed root may legitimately be partial —
    // ValidateGateCiTests plants a single atom into a temp root and asserts the tool's exit code for
    // it — and requiring the registry would invent a requirement that root does not have, turning a
    // structural-defect report into "could not start".
    //
    // MEASURED 2026-10-01, and the reasoning below was wrong in a way that matters. The original comment
    // said "if an import actually reaches the reader with the hub unconfigured, LeadNamesHub.Current
    // throws its own named refusal, which is the fail-closed behaviour" — as though a partial root never
    // got that far. It always does: `new RpgStore(freshDir)` seeds a player row when `players` is empty,
    // and that insert reads the lead-names registry through `RpgStore.OnboardingPlayerName()`. RpgStore's
    // own comment states the precondition outright — "the value is read at the insert, which is after boot
    // configured the hub; THE CALLER MUST HAVE CONFIGURED IT". So every planted-root import died with
    //     the import failed and was rolled back: LeadNamesHub.Configure(...) has not run
    // before validation ever ran, and both ValidateGateCiTests cases failed for that reason.
    //
    // Failing closed is right for a HOST and wrong here, and the difference is who owns the path. A server
    // or the Injector passes the path it owns and must throw if that file is missing — that is the
    // fail-closed behaviour, and it is unchanged. This tool is handed an arbitrary seed root, so when
    // that root carries no registry it falls back to the CONTENT PACK's, which is the same committed file
    // a host would have used. Nothing is weakened: a root that has a registry still uses its own, and the
    // fallback is a real committed file rather than a default.
    //
    // The fallback is also the only way the registry could ever arrive, because copying the real
    // registry INTO a planted root does not work: the scanner then treats it as a content file and
    // refuses it with `UnknownKind — kind ""`. Measured, 2026-10-01.
    var leadNamesPath = Path.Combine(seedRoot, "narrative", "_registry", "names.en.v1.json");
    if (!File.Exists(leadNamesPath))
    {
        var packNames = Path.Combine(FusionRpg.Core.Workspace.KeepverseRoots.Content(), "data",
                                     "seed", "narrative", "_registry", "names.en.v1.json");
        if (File.Exists(packNames))
            leadNamesPath = packNames;
    }
    if (File.Exists(leadNamesPath))
    {
        try
        {
            FusionRpg.Core.Narrative.LeadNamesHub.ConfigureFromFile(leadNamesPath);
        }
        catch (Exception ex) when (ex is FileNotFoundException or InvalidOperationException)
        {
            Console.Error.WriteLine($"lead names: {ex.Message}");
            return 2;
        }
    }

    SeedCollectResult collected;
    try
    {
        collected = SeedImportRunner.Collect(seedRoot, files);
    }
catch (IOException ex)
{
    Console.Error.WriteLine(ex.Message);
    return 2;
}

if (!collected.IsOk)
{
    Report(collected.Errors, "the files were refused; nothing was imported");
    return 1;
}

// RpgStore's static ctor (RpgStore.Atoms.cs's ComposeKindRegistry, aura-skill T2) builds a
// DerivedStatRegistry, which reads DerivedStatPolicy.Tuning -- this standalone tool never had a
// reason to configure that hub before T2 shipped, and nothing since caught the gap because every
// test project bootstraps every tuning hub globally. Found for real 2026-08-30 running this tool
// as part of an actual deploy: `new RpgStore(...)` failed with a bare "type initializer threw",
// its real cause hidden until InnerException was surfaced (see the catch below).
var tuningDir = FindUp("data", "tuning");
if (tuningDir is null)
{
    Console.Error.WriteLine("could not locate data/tuning; needed for DerivedStatPolicy before touching RpgStore");
    return 2;
}
FusionRpg.Core.Stats.Derived.DerivedStatPolicy.Configure(
    FusionRpg.Core.Stats.Derived.DerivedStatTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "derived-stats.v2.json"))));

ImportOutcome outcome;
RpgStore store;
try
{
    store = new RpgStore(dataDir);
    store.Init();
    outcome = store.ImportContent(collected.Content, dryRun: check);
}
catch (Exception ex)
{
    // The import is one transaction, so a throw anywhere inside it has already rolled back. What
    // this catch buys is a message instead of a stack trace — the author still needs to be told
    // the catalog is untouched, which a crash does not say.
    Console.Error.WriteLine($"the import failed and was rolled back: {ex.Message}");
    if (ex.InnerException != null)
        Console.Error.WriteLine($"  inner: {ex.InnerException}");
    return 1;
}

if (!outcome.IsOk)
{
    Report(outcome.Errors, "the catalog refused the import; nothing was written");
    return 1;
}

if (validate)
{
    // Lint(atoms, containers) and Drift(atoms) are well-defined over the batch just imported; a
    // power BUDGET is deliberately not run — see ValidationGate for why.
    var lint = ContentValidation.Lint(collected.Content.Atoms, collected.Content.Containers);
    var drift = ContentValidation.Drift(collected.Content.Atoms, store.GetPowerTables());
    var decision = ValidationGate.Decide(lint, drift);

    foreach (var line in decision.Lines) Console.WriteLine(line);

    if (!decision.Ok) return 1;
}

Console.WriteLine(
    $"{files.Count} file(s): {outcome.Atoms} atom(s), {outcome.Containers} container(s), " +
    $"{outcome.Curves} curve(s), {outcome.Rarities} rarity band(s), " +
    $"{outcome.Elements} element(s), {outcome.ChannelPolicies} channel policy row(s), " +
    $"{outcome.Affixes} affix(es)");
if (check)
{
    // The revision and the hash below are the CURRENT ones, read after the rollback — saying
    // "catalog revision now N" here would report a number this run did not produce.
    Console.WriteLine(outcome.RowsChanged == 0
        ? "--check: clean, and nothing would change"
        : $"--check: clean; {outcome.RowsChanged} row(s) would change. Nothing was written.");
    Console.WriteLine($"catalog still at revision {outcome.CatalogRevision}, content {Short(outcome)}");
    return 0;
}

Console.WriteLine(
    outcome.RowsChanged == 0
        ? "nothing changed — catalog revision and content hash both held"
        : $"{outcome.RowsChanged} row(s) changed; catalog revision now {outcome.CatalogRevision}");
Console.WriteLine($"content {Short(outcome)}");
return 0;

static string Short(ImportOutcome o) => o.ContentHash?.Short ?? "(unknown)";

static void Report(IReadOnlyList<SeedError> errors, string headline)
{
    Console.Error.WriteLine($"{errors.Count} error(s) — {headline}");
    foreach (var e in errors) Console.Error.WriteLine("  " + e);
}

static string? FindUp(params string[] segments) =>
    SeedImportRunner.FindUp(Directory.GetCurrentDirectory(), segments);
