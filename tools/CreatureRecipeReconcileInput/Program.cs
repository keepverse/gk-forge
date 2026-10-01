using System.Text.Json;
using System.Text.Json.Serialization;
using FusionRpg.Core.Creatures;
using FusionRpg.Core.Creatures.Fusion;
using FusionRpg.Core.Creatures.Generation;
using FusionRpg.Core.Power;
using FusionRpg.Core.Stats.Aptitudes;
using FusionRpg.Core.Workspace;
using FusionRpg.Data;

// `fusion-recipe-generator` (creature-seed module 17, spec-fusion-recipe-generator.md §3 step 1) — the
// CLI seam `gk-forge/tools/seedsmith/seedsmith/adapters/creatures/fusion/reconcile.py` calls into so the
// deterministic pass and the deficit set are read from the REAL C# (CreatureRecipeCatalog.BuildDeterministicOnly(),
// EligibleOutputs(), UnresolvedOutputs(), CandidatePoolBelow()), never reimplemented in Python.
// Deterministic, no model calls — same corpus-loading pipeline as
// gk-forge/tools/CreatureRecipeDistributionIndex/Program.cs (anchor -> SpeciesExpander -> temp RpgStore ->
// BuildCreatureSpeciesSnapshot), reused rather than duplicated in spirit (the loading steps are
// necessarily repeated per-process since this runs as a separate executable, but the DOMAIN LOGIC
// each one calls — NearestPopulatedRungBelow, CandidatePoolBelow, Build() — lives in exactly one
// place: CreatureRecipeCatalog.cs).
//
// Usage: dotnet run --project gk-forge/tools/CreatureRecipeReconcileInput -- [--seed <dir>] [--max-rungs <n>]
//   --seed       default: gk-data/packs/fusion/data/seed/creatures/species, found by walking up from the working directory
//   --max-rungs  how many POPULATED rungs below a deficit output to include (default 3, spec §2)
//
// Output: one JSON object to stdout (see the record types below for the exact shape). Exit 2 on a
// load failure, 0 otherwise — this tool only reports; reconcile.py alone decides pass/fail.

var args2 = args.ToList();
string? seedOverride = TakeOption("--seed");
var maxRungsRaw = TakeOption("--max-rungs");
var maxRungs = maxRungsRaw is null ? 3 : int.Parse(maxRungsRaw);

string? TakeOption(string flag)
{
    var i = args2.IndexOf(flag);
    if (i < 0 || i + 1 >= args2.Count) return null;
    var value = args2[i + 1];
    args2.RemoveRange(i, 2);
    return value;
}

// Resolved through the production KeepverseRoots rather than a walk up from the working
// directory. FindUp("data","tuning") could only ever work in the pre-split monorepo: after
// the split `data/seed` is gk-data's pack and `data/tuning` is gk-core's, and NO split
// repository has both - so walking up from gk-forge could find neither. That made this
// tool exit 2 in every split checkout, which is what kept the C#-seam case in
// tests/test_fusion_recipe.py skipped: an "environmental" skip for a real defect.
var seedRoot = seedOverride ?? Path.Combine(KeepverseRoots.Content(), "data", "seed", "creatures", "species");
if (seedRoot is null || !Directory.Exists(seedRoot))
{
    Console.Error.WriteLine("could not locate data/seed/creatures/species; pass --seed <dir>");
    return 2;
}

var tuningDir = Path.Combine(KeepverseRoots.Core(), "data", "tuning");
if (!Directory.Exists(tuningDir))
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
    if (SpeciesExpander.UnresolvedFields(anchor).Count > 0) continue; // same skip species-import/the other CLI tools apply
    try { species.Add(SpeciesExpander.Expand(anchor, aptitudeTuning, powerTuning, shapeTuning, threatTuning)); }
    catch (Exception ex) { Console.Error.WriteLine($"'{anchor.SpeciesId}': {ex.Message}"); return 1; }
}

if (species.Count == 0)
{
    Console.Error.WriteLine("no resolved species to reconcile — nothing to report");
    return 2;
}

FusionRpg.Core.Stats.Derived.DerivedStatPolicy.Configure(
    FusionRpg.Core.Stats.Derived.DerivedStatTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "derived-stats.v2.json"))));

var tempDir = Path.Combine(Path.GetTempPath(), "fusionrpg-reconcileinput-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(tempDir);
try
{
    // The lead-names registry is a process-wide static hub and this tool is its own process, so
    // nothing else has configured it. `store.Init()` seeds the player, and that insert reads the
    // registry through `RpgStore.OnboardingPlayerName()`, so an unconfigured hub throws
    // "LeadNamesHub.Configure(...) has not run" out of Init - the identical failure the seed
    // importer hit on a cold data dir and which AGENTS.md records as fixed there by routing both
    // callers through the ONE `LeadNamesHub.ConfigureFromFile`. This is that same single call, not a
    // second copy: the registry is the content pack's committed file, and it is required rather
    // than defaulted, because a guessed lead name is an identity nobody could tell from an
    // authored one.
    var leadNamesPath = Path.Combine(KeepverseRoots.Content(), "data", "seed",
                                     "narrative", "_registry", "names.en.v1.json");
    if (!File.Exists(leadNamesPath))
    {
        Console.Error.WriteLine(
            $"lead-names registry not found at '{leadNamesPath}'; needed to seed the player name.");
        return 2;
    }
    FusionRpg.Core.Narrative.LeadNamesHub.ConfigureFromFile(leadNamesPath);

    var store = new RpgStore(tempDir);
    store.Init();
    var outcome = store.ImportSpecies(species);
    if (!outcome.IsOk)
    {
        Console.Error.WriteLine($"{outcome.Errors.Count} error(s) importing into the computation store — nothing reconciled");
        Console.Error.WriteLine("  first: " + outcome.Errors[0]);
        return 1;
    }

    var snapshot = store.BuildCreatureSpeciesSnapshot();
    CreatureSpeciesCatalog.Configure(snapshot);

    var output = new ReconcileInput(
        EligibleOutputs: CreatureRecipeCatalog.EligibleOutputs().Select(ToSpeciesRef).ToList(),
        DeterministicRecipes: CreatureRecipeCatalog.BuildDeterministicOnly().Select(r => new RecipeRef(
            r.RecipeId, r.OutputSpeciesId, r.InputSpeciesIdA, r.InputSpeciesIdB)).ToList(),
        Deficits: CreatureRecipeCatalog.UnresolvedOutputs().Select(o => ToDeficit(o, maxRungs)).ToList());

    Console.WriteLine(JsonSerializer.Serialize(output, JsonOptions));
    return 0;
}
finally
{
    try { Directory.Delete(tempDir, recursive: true); } catch { /* temp dir, best-effort cleanup */ }
}

static SpeciesRef ToSpeciesRef(CreatureSpeciesDef s) =>
    new(s.SpeciesId, s.ElementPrimary.ToString().ToLowerInvariant(), s.BaseRarity.ToId());

static DeficitRef ToDeficit(CreatureSpeciesDef output, int maxRungs)
{
    var pool = CreatureRecipeCatalog.CandidatePoolBelow(output.BaseRarity, maxRungs);
    var nearestPopulatedRung = pool.Count > 0 ? pool[0].Species.BaseRarity.ToId() : null;
    var candidates = pool.Select(p => new CandidateRef(
        p.Species.SpeciesId,
        p.Species.ElementPrimary.ToString().ToLowerInvariant(),
        p.Species.BaseRarity.ToId(),
        AcquisitionFlags(p.Species.Acquisition),
        p.RungDistance)).ToList();

    return new DeficitRef(output.SpeciesId, output.ElementPrimary.ToString().ToLowerInvariant(),
        output.BaseRarity.ToId(), nearestPopulatedRung, candidates);
}

// CreatureAcquisition is [Flags] — a candidate could carry more than one (e.g. Summonable |
// EventOnly). `.ToString()` on a combined value renders "Summonable, EventOnly", not a JSON array;
// this decomposes it into individual flag names so the seam's `acquisition` field is genuinely an
// array, matching `anchor/schema.py`'s own ACQUISITION array-of-flags shape.
static string[] AcquisitionFlags(CreatureAcquisition acquisition) =>
    Enum.GetValues<CreatureAcquisition>()
        .Where(f => f != CreatureAcquisition.None && acquisition.HasFlag(f))
        .Select(f => f.ToString())
        .ToArray();

// The upward-walk helper this file used to resolve its roots is gone with its last caller. It
// could not answer in the split workspace, so keeping it would keep a function whose only
// failure mode is "returns null, and the caller exits 2". KeepverseRoots answers the same
// question from the workspace, which is where the split put the data.


partial class Program
{
    internal static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        DefaultIgnoreCondition = JsonIgnoreCondition.Never,
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    };
}

internal record SpeciesRef(string SpeciesId, string ElementPrimary, string Rarity);

internal record RecipeRef(string RecipeId, string OutputSpeciesId, string InputSpeciesIdA, string InputSpeciesIdB);

internal record CandidateRef(
    string SpeciesId, string ElementPrimary, string Rarity, string[] Acquisition, int RungDistance);

internal record DeficitRef(
    string OutputSpeciesId, string ElementPrimary, string Rarity,
    string? NearestPopulatedRung, List<CandidateRef> CandidatePool);

internal record ReconcileInput(
    List<SpeciesRef> EligibleOutputs, List<RecipeRef> DeterministicRecipes, List<DeficitRef> Deficits);
