using FusionRpg.Core.Creatures;
using FusionRpg.Core.Creatures.Fusion;
using FusionRpg.Core.Creatures.Generation;
using FusionRpg.Core.Power;
using FusionRpg.Core.Stats.Aptitudes;
using FusionRpg.Data;

// `fusion-recipe-generator` (creature-seed module 17, spec-fusion-recipe-generator.md §1
// `distribution-index`) — deterministic, no model calls. Re-derives the real concrete roster from
// anchors (SpeciesExpander, the SAME method species-import already uses — never a second derivation),
// imports it into a throwaway temp-directory store purely as the computation vehicle
// BuildCreatureSpeciesSnapshot() needs, then reuses CreatureRecipeCatalog's own real search
// (NearestPopulatedRungBelow) to report, per rarity rung at or above OutputEligibilityFloor: the
// output count, the nearest populated rung below, that rung's count, C(n,2), and whether a shortfall
// exists (outputCount > C(n,2)) — the exact capacity ceiling that broke the real 829-species roster
// live (found running the catalog-runtime flip, 2026-09-05).
//
// Usage: dotnet run --project gk-forge/tools/CreatureRecipeDistributionIndex -- [--seed <dir>]
//        --seed   default: gk-data/packs/fusion/data/seed/creatures/species, found by walking up from the working directory
//
// Exit codes: 0 always (this is a report, never a gate — §1's own "closed-loop first" rule: a
// shortfall here does not fail the run, it decides whether fusion-recipe-propose needs to run at all).

var args2 = args.ToList();
string? seedOverride = TakeOption("--seed");

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

var species = new List<ConcreteSpecies>();
foreach (var anchor in anchors)
{
    if (SpeciesExpander.UnresolvedFields(anchor).Count > 0) continue; // same skip SpeciesBuildPlanGen/CreatureSpeciesImport already apply
    try { species.Add(SpeciesExpander.Expand(anchor, aptitudeTuning, powerTuning, shapeTuning, threatTuning)); }
    catch (Exception ex) { Console.Error.WriteLine($"'{anchor.SpeciesId}': {ex.Message}"); return 1; }
}

if (species.Count == 0)
{
    Console.Error.WriteLine("no resolved species to index — nothing to report");
    return 2;
}

FusionRpg.Core.Stats.Derived.DerivedStatPolicy.Configure(
    FusionRpg.Core.Stats.Derived.DerivedStatTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "derived-stats.v2.json"))));

var tempDir = Path.Combine(Path.GetTempPath(), "fusionrpg-distindex-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(tempDir);
try
{
    var store = new RpgStore(tempDir);
    store.Init();
    var outcome = store.ImportSpecies(species);
    if (!outcome.IsOk)
    {
        Console.Error.WriteLine($"{outcome.Errors.Count} error(s) importing into the computation store — nothing indexed");
        Console.Error.WriteLine("  first: " + outcome.Errors[0]);
        return 1;
    }

    var snapshot = store.BuildCreatureSpeciesSnapshot();
    CreatureSpeciesCatalog.Configure(snapshot);

    var rows = FusionRecipeDistributionIndex.Compute();

    Console.WriteLine("rarity        outputs  nearestBelow  belowCount  maxPairs  shortfall");
    foreach (var row in rows)
    {
        var belowRarity = row.NearestBelow?.ToString() ?? "(none)";
        Console.WriteLine($"{row.Rarity,-12}  {row.OutputCount,7}  {belowRarity,-12}  {row.BelowCount,10}  {row.MaxPairs,8}  {(row.Shortfall ? "YES" : "")}");
        if (row.Shortfall)
            Console.WriteLine($"  -> deficit: {row.Deficit} output(s) beyond what {row.BelowCount} candidate(s) below can support");
    }

    if (!rows.Any(r => r.Shortfall))
        Console.WriteLine("\nno shortfall — every rung's output count fits within its input rung's pairing capacity");

    return 0;
}
finally
{
    try { Directory.Delete(tempDir, recursive: true); } catch { /* temp dir, best-effort cleanup */ }
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
