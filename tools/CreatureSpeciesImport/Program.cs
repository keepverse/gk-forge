using FusionRpg.Core.Creatures.Generation;
using FusionRpg.Core.Power;
using FusionRpg.Core.Stats.Aptitudes;
using FusionRpg.Data;

// species-import (T4.6, spec-species-generator.md's downstream consumer, creature-seed module 13).
// Re-derives every real classified anchor (the SAME way CreatureSpeciesGen does), refuses the WHOLE
// import if the committed gk-data/packs/fusion/data/generated/creatures/** tree is stale against that re-derivation, then
// writes the roster in one transaction via RpgStore.ImportSpecies — never raw SQL.
//
// Usage: dotnet run --project gk-forge/tools/CreatureSpeciesImport -- [--seed <dir>] [--db <dir>] [--diff-catalog]
//        --seed   default: gk-data/packs/fusion/data/seed/creatures/species, found by walking up from the working directory
//        --out    default: gk-data/packs/fusion/data/generated/creatures — read for the staleness check, not written
//        --db     default: $FUSIONRPG_DATA, else dist/FusionRpg.Server/data beside the repo root
//        --diff-catalog   after a successful import, print the store-backed roster's field-by-field
//                         diff against the compiled legacy catalog (SpeciesDiff.Compare/Coverage,
//                         T4.8 step 4's own review artifact) — read-only, decides nothing, a human
//                         reads this before step 5's flip. No effect on exit code or what is written.
//
// Exit codes: 0 imported, 1 refused (stale tree or a bad row), 2 could not start.

var args2 = args.ToList();
string? seedOverride = TakeOption("--seed");
string? outOverride = TakeOption("--out");
string? dbOverride = TakeOption("--db");
var diffCatalog = args2.Remove("--diff-catalog");

string? TakeOption(string flag)
{
    var i = args2.IndexOf(flag);
    if (i < 0 || i + 1 >= args2.Count) return null;
    var value = args2[i + 1];
    args2.RemoveRange(i, 2);
    return value;
}

var seedRoot = seedOverride ?? FindUp("data", "seed", "creatures", "species");
if (seedRoot is null || !Directory.Exists(seedRoot))
{
    Console.Error.WriteLine("could not locate data/seed/creatures/species; pass --seed <dir>");
    return 2;
}

var tuningDir = FindUp("data", "tuning");
if (tuningDir is null)
{
    Console.Error.WriteLine("could not locate data/tuning; needed to load the shipped balance surface");
    return 2;
}

var outRoot = outOverride ?? Path.Combine(Directory.GetParent(tuningDir)!.FullName, "generated", "creatures");

var dataDir = dbOverride
              ?? Environment.GetEnvironmentVariable("FUSIONRPG_DATA")
              ?? FindUp("dist", "FusionRpg.Server", "data");
if (string.IsNullOrWhiteSpace(dataDir))
{
    Console.Error.WriteLine("no database directory: pass --db <dir> or set FUSIONRPG_DATA");
    return 2;
}

AptitudeTuning aptitudeTuning;
PowerTuning powerTuning;
CreatureShapeTuning shapeTuning;
CreatureThreatTuning threatTuning;
try
{
    aptitudeTuning = AptitudeTuningLoader.Parse(File.ReadAllText(Path.Combine(tuningDir, "aptitudes.v2.json")));
    powerTuning = PowerTuningLoader.Parse(File.ReadAllText(Path.Combine(tuningDir, "power-scale.v2.json")));
    shapeTuning = CreatureShapeTuningLoader.Parse(File.ReadAllText(Path.Combine(tuningDir, "creature-shape.v1.json")));
    threatTuning = CreatureThreatTuningLoader.Parse(File.ReadAllText(Path.Combine(tuningDir, "creature-threat.v1.json")));
}
catch (Exception ex)
{
    Console.Error.WriteLine($"could not load the balance surface: {ex.Message}");
    return 2;
}

var anchors = new List<AnchorRow>();
foreach (var file in Directory.GetFiles(seedRoot, "*.json", SearchOption.AllDirectories).OrderBy(f => f, StringComparer.Ordinal))
{
    if (Path.GetFileName(file).StartsWith('_')) continue;
    try { anchors.AddRange(AnchorRowReader.ReadAll(File.ReadAllText(file))); }
    catch (AnchorRowRejection ex) { Console.Error.WriteLine($"{file}: {ex.Message}"); return 1; }
}

// ---- re-derive every species, and refuse the WHOLE import if the committed tree disagrees ---------
// A species still "unresolved" on a voted field is skipped BEFORE expansion (SpeciesExpander.Expand
// fails loud on one, by design — see its own UnresolvedFields doc comment) — never imported, never
// counted toward the staleness check below, so a genuinely-incomplete classification does not block
// the whole roster's import.
var species = new List<ConcreteSpecies>();
var stale = new List<string>();
var skipped = new List<string>();
foreach (var anchor in anchors)
{
    var unresolvedFields = SpeciesExpander.UnresolvedFields(anchor);
    if (unresolvedFields.Count > 0)
    {
        skipped.Add($"{anchor.SpeciesId} ({string.Join(", ", unresolvedFields)})");
        continue;
    }

    ConcreteSpecies expanded;
    try { expanded = SpeciesExpander.Expand(anchor, aptitudeTuning, powerTuning, shapeTuning, threatTuning); }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"'{anchor.SpeciesId}': {ex.Message}");
        return 1;
    }

    var committedPath = Path.Combine(outRoot, anchor.SpeciesId + ".json");
    var committed = File.Exists(committedPath) ? File.ReadAllText(committedPath).ToLf() : null;
    if (committed != ConcreteSpeciesSerializer.Canonical(expanded)) stale.Add(anchor.SpeciesId);

    species.Add(expanded);
}

if (stale.Count > 0)
{
    Console.Error.WriteLine(
        $"{stale.Count} species stale against {outRoot} — the import refuses the WHOLE roster, not " +
        $"just the stale rows (a half-imported roster is a state nobody authored): {string.Join(", ", stale)}");
    Console.Error.WriteLine("run 'dotnet run --project tools/CreatureSpeciesGen' and commit the result first");
    return 1;
}

if (skipped.Count > 0)
{
    Console.WriteLine(
        $"{skipped.Count} species skipped — still unresolved on at least one voted field, not " +
        $"imported: {string.Join("; ", skipped)}");
}

// RpgStore's static ctor (RpgStore.Atoms.cs's ComposeKindRegistry) builds a DerivedStatRegistry,
// which reads DerivedStatPolicy.Tuning — a standalone tool must configure that hub itself before
// touching RpgStore, the same fix AtomImporter/Program.cs already carries (found running it for
// real 2026-08-30; every test project bootstraps this globally, so no in-process test catches it).
FusionRpg.Core.Stats.Derived.DerivedStatPolicy.Configure(
    FusionRpg.Core.Stats.Derived.DerivedStatTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "derived-stats.v2.json"))));

// ---- import, one transaction, via RpgStore — never raw SQL in this tool ---------------------------
var store = new RpgStore(dataDir);
// identity-rename T13: a real host that reaches RpgStore.Init() must configure the lead-names
// registry first — an empty save is named from it. Read beside the exe (the copy rule in the csproj),
// the same shape the server uses; a missing file throws rather than defaulting a player name.
FusionRpg.Core.Narrative.LeadNamesHub.Configure(
    FusionRpg.Core.Narrative.LeadNames.Parse(File.ReadAllText(Path.Combine(
        AppContext.BaseDirectory, "data", "seed", "narrative", "_registry", "names.en.v1.json"))));
store.Init();

var outcome = store.ImportSpecies(species);
if (!outcome.IsOk)
{
    Console.Error.WriteLine($"{outcome.Errors.Count} error(s) — the roster was refused; nothing was written");
    Console.Error.WriteLine("  first: " + outcome.Errors[0]);
    return 1;
}

Console.WriteLine(
    $"{species.Count} species: {outcome.Written} written, {outcome.Unchanged} unchanged, " +
    $"{outcome.Deleted} deleted (absent upstream)");

if (diffCatalog)
    PrintCatalogDiff(store);

return 0;

static void PrintCatalogDiff(RpgStore store)
{
    FusionRpg.Core.Creatures.CreatureSpeciesCatalog.ConfigureFromCompiledDefault();
    var compiled = FusionRpg.Core.Creatures.CreatureSpeciesCatalog.All.ToList();
    var storeBacked = store.BuildCreatureSpeciesSnapshot();

    var (onlyInCompiled, onlyInStoreBacked) = SpeciesDiff.Coverage(compiled, storeBacked);
    var fieldDiffs = SpeciesDiff.Compare(compiled, storeBacked);

    Console.WriteLine();
    Console.WriteLine("=== catalog diff: compiled (legacy) vs store-backed (this program's own corpus) ===");
    Console.WriteLine($"compiled: {compiled.Count} species, store-backed: {storeBacked.Count} species");
    Console.WriteLine($"only in compiled ({onlyInCompiled.Count}): {string.Join(", ", onlyInCompiled)}");
    Console.WriteLine($"only in store-backed ({onlyInStoreBacked.Count}, first 20 of possibly more): " +
        string.Join(", ", onlyInStoreBacked.Take(20)) + (onlyInStoreBacked.Count > 20 ? ", ..." : ""));
    Console.WriteLine($"present in both: {compiled.Count - onlyInCompiled.Count}");
    Console.WriteLine($"field disagreements: {fieldDiffs.Count}");

    var byField = fieldDiffs.GroupBy(d => d.Field).OrderByDescending(g => g.Count());
    foreach (var g in byField)
        Console.WriteLine($"  {g.Key,-16} {g.Count()} disagreement(s)");

    Console.WriteLine();
    Console.WriteLine("first 30 field disagreements, for a human to read:");
    foreach (var d in fieldDiffs.Take(30))
        Console.WriteLine($"  {d.SpeciesId,-24} {d.Field,-16} compiled='{d.Compiled}' storeBacked='{d.StoreBacked}'");
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
