using System.Text.Json;
using FusionRpg.Core.Creatures;
using FusionRpg.Core.Creatures.Generation;
using FusionRpg.Core.Power;
using FusionRpg.Core.Stats.Derived;
using FusionRpg.Tools.CombatSim;
using AptitudeTuning = FusionRpg.Core.Stats.Aptitudes.AptitudeTuning;
using AptitudeTuningLoader = FusionRpg.Core.Stats.Aptitudes.AptitudeTuningLoader;

// creature-quality-report: a reusable scan over the WHOLE classified corpus, covering three things no
// single existing tool covers together — `creatures metrics` (seedsmith) reports classification
// quality only, `CreatureSpeciesGen` reports generation staleness only, and balance has never had a
// tool at all before this (only one-off scratch analysis). Re-run any time after a classification
// batch, a rebalance, or a tuning change; nothing here writes to the seed tree, the generated tree,
// or any database — read-only end to end.
//
// Usage: dotnet run --project gk-forge/tools/CreatureQualityReport -- [--seed <dir>] [--trials N] [--json <path>]
//        --seed    default: gk-data/packs/fusion/data/seed/creatures/species, found by walking up from the working directory
//        --trials  duels per species-vs-baseline fight (default 300 — enough to separate a real
//                   stomp from noise without the tool taking minutes on a 900-species corpus)
//        --json    also write the full report as machine-readable JSON, for diffing between runs
//
// Exit code: always 0 on a successful scan (this tool REPORTS, it does not gate — `creatures metrics
// --gate` and CreatureSpeciesGen --check own that job). Non-zero only on a real inability to run
// (missing seed tree, missing tuning).

var args2 = args.ToList();
string? seedOverride = TakeOption("--seed");
string? jsonOut = TakeOption("--json");
var trials = int.TryParse(TakeOption("--trials"), out var t) ? t : 300;

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

var repoRoot = FindUp("data", "tuning");
if (repoRoot is null)
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
    aptitudeTuning = AptitudeTuningLoader.Parse(File.ReadAllText(Path.Combine(repoRoot, "aptitudes.v2.json")));
    powerTuning = PowerTuningLoader.Parse(File.ReadAllText(Path.Combine(repoRoot, "power-scale.v2.json")));
    shapeTuning = CreatureShapeTuningLoader.Parse(File.ReadAllText(Path.Combine(repoRoot, "creature-shape.v1.json")));
    threatTuning = CreatureThreatTuningLoader.Parse(File.ReadAllText(Path.Combine(repoRoot, "creature-threat.v1.json")));
}
catch (Exception ex)
{
    Console.Error.WriteLine($"could not load the balance surface: {ex.Message}");
    return 2;
}

// ---- 1. load every anchor entry, tracking which FILE each came from -----------------------------

var entriesByFile = new List<(string File, AnchorRow Row)>();
foreach (var file in Directory.GetFiles(seedRoot, "*.json", SearchOption.AllDirectories).OrderBy(f => f, StringComparer.Ordinal))
{
    if (Path.GetFileName(file).StartsWith('_')) continue; // notes/exemplars, matching AtomImporter's own convention
    try
    {
        foreach (var row in AnchorRowReader.ReadAll(File.ReadAllText(file)))
            entriesByFile.Add((file, row));
    }
    catch (AnchorRowRejection ex)
    {
        Console.Error.WriteLine($"{file}: {ex.Message}");
    }
}

var indexPath = Path.Combine(seedRoot, "_index.json");
var index = File.Exists(indexPath)
    ? JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(indexPath)) ?? new()
    : new Dictionary<string, string>();

// ---- 2. classification quality: duplicates/orphans, unresolved rates, distribution --------------

var bySpecies = entriesByFile.GroupBy(e => e.Row.SpeciesId).ToDictionary(g => g.Key, g => g.ToList());
var duplicates = bySpecies.Where(kv => kv.Value.Count > 1).ToList();
var indexedNotOnDisk = index.Keys.Where(id => !bySpecies.ContainsKey(id)).ToList();
var onDiskNotIndexed = bySpecies.Keys.Where(id => !index.ContainsKey(id)).ToList();

Console.WriteLine("=== 1. Classification integrity ===");
Console.WriteLine($"  {entriesByFile.Count} anchor entries on disk, {bySpecies.Count} distinct species ids, {index.Count} indexed");
if (duplicates.Count > 0)
{
    Console.WriteLine($"  ⚠ {duplicates.Count} species have MORE THAN ONE anchor entry (a stale file left behind by a");
    Console.WriteLine($"    reclassification that changed family bucket — the same class of bug found and fixed for");
    Console.WriteLine($"    2 species 2026-09-03; this corpus has it at scale). First 10:");
    foreach (var (id, rows) in duplicates.Take(10))
        Console.WriteLine($"    {id}: {string.Join(", ", rows.Select(r => Path.GetRelativePath(seedRoot, r.File)))}");
}
if (onDiskNotIndexed.Count > 0)
    Console.WriteLine($"  ⚠ {onDiskNotIndexed.Count} species exist on disk but _index.json does not point at them.");
if (indexedNotOnDisk.Count > 0)
    Console.WriteLine($"  ⚠ {indexedNotOnDisk.Count} species are indexed but no anchor entry was found for them.");
if (duplicates.Count == 0 && onDiskNotIndexed.Count == 0 && indexedNotOnDisk.Count == 0)
    Console.WriteLine("  clean — every anchor entry is unique and the index matches the tree exactly.");

// The index is authoritative for "where does this species really live" (same convention
// run-control's own emit.py uses) — pick the entry the index actually resolves to; a duplicate's
// OTHER copies are already reported above, never silently re-analyzed as if they were both real.
var anchors = new List<AnchorRow>();
foreach (var (speciesId, rel) in index)
{
    var candidates = bySpecies.GetValueOrDefault(speciesId);
    if (candidates is null) continue; // already reported above (indexedNotOnDisk)
    var match = candidates.FirstOrDefault(c => string.Equals(
        Path.GetRelativePath(seedRoot, c.File).Replace('\\', '/'), rel, StringComparison.Ordinal));
    anchors.Add((match.Row is not null ? match : candidates[0]).Row);
}

var votedFields = new[] { "elementPrimary", "aptitudePrimary", "aptitudeSecondary", "rarity", "threatBand", "deployMode" };
Console.WriteLine();
Console.WriteLine("  Unresolved rate per voted field:");
foreach (var field in votedFields)
{
    var unresolved = anchors.Count(a => FieldValue(a, field) == "unresolved");
    if (unresolved == 0) continue;
    var permille = anchors.Count == 0 ? 0 : unresolved * 1000 / anchors.Count;
    Console.WriteLine($"    {field,-18} {unresolved,4}/{anchors.Count} ({permille}‰)");
}
// spec-species-rank.md §7: rank is DERIVED (not voted), so it is not one of the fields above —
// it gets its own coverage line: how many anchors carry the table's rank vs skipped it (an
// unresolved threatBand/rarity, or a pre-rank anchor). Reports-only, never gating.
var ranked = anchors.Count(a => a.Rank is not null);
var rankPermille = anchors.Count == 0 ? 0 : ranked * 1000 / anchors.Count;
Console.WriteLine($"  Rank coverage (DERIVED anchor field): {ranked}/{anchors.Count} ({rankPermille}‰) carry the table's rank, {anchors.Count - ranked} skipped");

Console.WriteLine();
Console.WriteLine("  Element distribution (elementPrimary):");
PrintDistribution(anchors.Select(a => a.ElementPrimary));
Console.WriteLine("  Rarity distribution:");
PrintDistribution(anchors.Select(a => a.Rarity));
Console.WriteLine("  Side distribution:");
PrintDistribution(anchors.Select(a => a.Side));

// ---- 2. catalog diversity: every closed-vocabulary attribute, not just the three above ----------
//
// "Unresolved" entries are excluded from every field below — that is a classification FAILURE
// (already reported above, per field, in "Unresolved rate"), not a real value the vocabulary
// expresses; mixing it in would muddy "is the corpus actually using the vocabulary" with "is
// classification working." A value's closed set always comes from the SAME real source
// species-generator itself reads (the enum, or the tuning file) — never a hand-typed list that
// could silently drift from what the game actually recognises.

Console.WriteLine();
Console.WriteLine("=== 2. Catalog diversity (closed-vocabulary attributes) ===");
Console.WriteLine($"  {"field",-18} {"used/possible",-14} {"entropy",8}  unused values");

var aptitudeFamilies = aptitudeTuning.Edges.Select(e => e.Source).Distinct(StringComparer.Ordinal).ToList();
ReportDiversity("elementPrimary", ElementRoster.Concrete.Select(e => e.ToString().ToLowerInvariant()),
    anchors.Select(a => a.ElementPrimary));
ReportDiversity("elementSecondary", ElementRoster.Concrete.Select(e => e.ToString().ToLowerInvariant()),
    anchors.Select(a => a.ElementSecondary).Where(v => v is not null)!);
ReportDiversity("aptitudePrimary", aptitudeFamilies, anchors.Select(a => a.AptitudePrimary));
ReportDiversity("aptitudeSecondary", aptitudeFamilies,
    anchors.Select(a => a.AptitudeSecondary).Where(v => v is not null)!);
ReportDiversity("rarity", Enum.GetValues<CreatureRarity>().Select(r => r.ToString().ToLowerInvariant()),
    anchors.Select(a => a.Rarity));
// spec-species-rank.md §7 (GAP-5): the diversity section is an explicit call list, never
// reflection over the anchor record — so rank needs its own dimension or it is invisible here.
// Possible set from the declaring enum (the SAME source the generator reads); observed off the
// anchors' own derived field. Skipped ranks (null) are filtered — the coverage line above owns
// that count, and ReportDiversity already excludes "unresolved" the same way.
ReportDiversity("rank", CreatureRankLadder.All.Select(r => r.ToId()),
    anchors.Select(a => a.Rank).Where(v => v is not null)!);
ReportDiversity("threatBand", threatTuning.Thresholds.Select(t => t.Id),
    anchors.Select(a => a.ThreatBand).Where(v => v is not null)!);
// threat-band-fill T3: a rung's occupancy is only half the story — the stamp says HOW it got
// there. scored = the scorer computed it from the dump; default = the sanctioned fallback;
// high/split = a real classification vote; deterministic-fallback = a pre-fill fix; unstamped =
// classified before the fill ever stamped anything.
var threatProv = anchors.Where(a => a.ThreatBand != "unresolved").ToList();
if (threatProv.Count > 0)
{
    Console.WriteLine("  threatBand provenance (how each rung was chosen):");
    foreach (var g in threatProv.GroupBy(a => a.ThreatBandConfidence ?? "unstamped").OrderByDescending(g => g.Count()))
        Console.WriteLine($"    {g.Key,-22} {g.Count(),4}/{threatProv.Count}");
}
ReportDiversity("deployMode", Enum.GetValues<CreatureDeployMode>().Select(d => d.ToString()),
    anchors.Select(a => a.DeployMode));
ReportDiversity("attackTempo", shapeTuning.AttackTempoIntervalMs.Keys, anchors.Select(a => a.AttackTempo));
ReportDiversity("reach", shapeTuning.ReachRangeCells.Keys, anchors.Select(a => a.Reach));
ReportDiversity("side", new[] { "plant", "zombie" }, anchors.Select(a => a.Side));

Console.WriteLine();
Console.WriteLine("  acquisition (multi-valued — % of species carrying each flag, not a single distribution):");
var acquisitionFlags = Enum.GetValues<CreatureAcquisition>().Where(f => f != CreatureAcquisition.None).ToList();
foreach (var flag in acquisitionFlags)
{
    var carrying = anchors.Count(a => a.Acquisition.Contains(flag.ToString(), StringComparer.Ordinal));
    var permille = anchors.Count == 0 ? 0 : carrying * 1000 / anchors.Count;
    Console.WriteLine($"    {flag,-18} {carrying,4}/{anchors.Count} ({permille / 10.0:F1}%)");
}
var noAcquisition = anchors.Count(a => a.Acquisition.Count == 0);
if (noAcquisition > 0)
    Console.WriteLine($"  ⚠ {noAcquisition} species carry NO acquisition flag at all — a catalog error " +
                       "(CreatureAcquisition.None), would refuse at import.");

void ReportDiversity(string field, IEnumerable<string> possible, IEnumerable<string> observedRaw)
{
    var possibleList = possible.Distinct(StringComparer.Ordinal).ToList();
    var observed = observedRaw.Where(v => v != "unresolved").ToList();
    var counts = observed
        .GroupBy(v => v, StringComparer.Ordinal)
        .ToDictionary(g => g.Key, g => g.Count(), StringComparer.Ordinal);
    var used = possibleList.Count(v => counts.GetValueOrDefault(v) > 0);
    var entropy = NormalizedEntropy(counts, possibleList, observed.Count);
    var unused = possibleList.Where(v => counts.GetValueOrDefault(v) == 0).ToList();
    var unusedText = unused.Count == 0 ? "(none)"
        : unused.Count <= 6 ? string.Join(", ", unused)
        : string.Join(", ", unused.Take(6)) + $", +{unused.Count - 6} more";
    Console.WriteLine($"  {field,-18} {used + "/" + possibleList.Count,-14} {entropy,8:F2}  {unusedText}");
}

// ---- 3. generation quality: expand every resolvable anchor, catch and count the rest ------------

Console.WriteLine();
Console.WriteLine("=== 3. Generation quality ===");
var generated = new List<ConcreteSpecies>();
var generationFailures = new List<(string SpeciesId, string Reason)>();
foreach (var anchor in anchors)
{
    try { generated.Add(SpeciesExpander.Expand(anchor, aptitudeTuning, powerTuning, shapeTuning, threatTuning)); }
    catch (Exception ex) { generationFailures.Add((anchor.SpeciesId, ex.Message)); }
}

Console.WriteLine($"  {generated.Count}/{anchors.Count} species generate cleanly, {generationFailures.Count} refuse to generate");
if (generationFailures.Count > 0)
{
    var byReason = generationFailures
        .GroupBy(f => f.Reason.Contains("aptitudePrimary") ? "unresolved/unknown aptitudePrimary"
                    : f.Reason.Contains("aptitudeSecondary") ? "unresolved/unknown aptitudeSecondary"
                    : f.Reason.Contains("rarity") ? "unknown rarity"
                    : f.Reason.Contains("elementPrimary") || f.Reason.Contains("elementSecondary") ? "unknown element"
                    : f.Reason.Contains("deployMode") ? "unknown deployMode"
                    : "other")
        .OrderByDescending(g => g.Count());
    foreach (var g in byReason)
        Console.WriteLine($"    {g.Count(),4}  {g.Key}");
}

var zeroMagnitude = generated.Where(s => s.Magnitudes.Count == 0).ToList();
var channelCounts = generated.Select(s => s.Magnitudes.Count).OrderBy(c => c).ToList();
Console.WriteLine();
if (zeroMagnitude.Count > 0)
{
    Console.WriteLine($"  ⚠ {zeroMagnitude.Count} generated species have ZERO magnitude channels (a real quality defect —");
    Console.WriteLine($"    every stat comes from an aptitude edge; zero channels means a silently stat-less creature).");
    Console.WriteLine($"    First 10: {string.Join(", ", zeroMagnitude.Take(10).Select(s => s.SpeciesId))}");
}
if (channelCounts.Count > 0)
    Console.WriteLine($"  magnitude channels per species: min={channelCounts[0]} median={Median(channelCounts.Select(c => (double)c).ToList()):F0} max={channelCounts[^1]}");

// ---- 4. balance: every species vs one self-calibrated baseline, through the REAL combat pipeline ----

Console.WriteLine();
Console.WriteLine("=== 4. Balance (real simulated combat, not a stat-sum estimate) ===");
var fightable = generated.Where(s => s.Magnitudes.Count > 0).ToList();
if (fightable.Count < 2)
{
    Console.WriteLine("  fewer than 2 generatable species — nothing to compare.");
}
else
{
    var baseline = BuildBaseline(fightable);
    Console.WriteLine($"  baseline archetype: self-calibrated median across {fightable.Count} species");
    Console.WriteLine($"    hp={baseline.Hp.Min:F0}  baseDamage={baseline.BaseDamage.Min:F0} (fixed, isolates each");
    Console.WriteLine($"    species' own derived stats as the thing under test — see BuildBaseline)");
    Console.WriteLine($"  running {fightable.Count} duels, {trials} trials each...");

    // Same bootstrap CombatSim's own Program.cs runs before any duel — Simulator.Duel goes through
    // the REAL combat pipeline (ShieldPolicy, CombatPolicy, etc.), and those are static singletons
    // that throw until configured. Never touched, never patched — this tool measures what the game
    // actually ships (gk-core/data/tuning/*.json), same as every other CombatSim-based reading this session.
    TuningBootstrap.Load(Array.Empty<string>());

    var results = new List<(ConcreteSpecies Species, DuelSummary Duel)>();
    var seed = 42;
    foreach (var species in fightable)
    {
        var archetype = ToArchetype(species, "test-subject");
        var duel = Simulator.Duel(archetype, baseline, trials, seed, maxRounds: 2000);
        results.Add((species, duel));
    }

    var stomps = results.Where(r => r.Duel.AWinShare is 1.0 or 0.0).ToList();
    var stalemates = results.Where(r => r.Duel.Stalemates > 0).ToList();
    Console.WriteLine($"  {stomps.Count}/{results.Count} ({stomps.Count * 100 / results.Count}%) are complete stomps (100%-0% vs baseline)");
    if (stalemates.Count > 0)
    {
        Console.WriteLine($"  ⚠ {stalemates.Count} species never resolve against the baseline within the round cap (a real");
        Console.WriteLine($"    'fight never ends' defect, not a balance nuance).");
    }

    Console.WriteLine();
    Console.WriteLine("  Win share vs baseline, by rarity (0.50 = evenly matched with the corpus median):");
    var byRarity = results.GroupBy(r => r.Species.Rarity.ToString()).OrderBy(g => g.Key);
    foreach (var g in byRarity)
    {
        var shares = g.Select(r => r.Duel.AWinShare).OrderBy(x => x).ToList();
        Console.WriteLine($"    {g.Key,-12} n={shares.Count,4}  mean={shares.Average():P0}  median={Median(shares):P0}");
    }

    if (jsonOut is not null)
    {
        var payload = new
        {
            generatedUtc = DateTime.UtcNow.ToString("O"),
            totalAnchors = anchors.Count,
            duplicateSpeciesCount = duplicates.Count,
            onDiskNotIndexedCount = onDiskNotIndexed.Count,
            indexedNotOnDiskCount = indexedNotOnDisk.Count,
            generatedCount = generated.Count,
            generationFailureCount = generationFailures.Count,
            zeroMagnitudeCount = zeroMagnitude.Count,
            species = results.Select(r => new
            {
                speciesId = r.Species.SpeciesId,
                rarity = r.Species.Rarity.ToString(),
                side = r.Species.Side,
                magnitudeChannels = r.Species.Magnitudes.Count,
                winShareVsBaseline = r.Duel.AWinShare,
                stalemate = r.Duel.Stalemates > 0,
            }).ToList(),
        };
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(jsonOut))!);
        File.WriteAllText(jsonOut, JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true }).ToLf());
        Console.WriteLine();
        Console.WriteLine($"  wrote {jsonOut}");
    }
}

return 0;

// ---- helpers --------------------------------------------------------------------------------------

static string? FieldValue(AnchorRow a, string field) => field switch
{
    "elementPrimary" => a.ElementPrimary,
    "aptitudePrimary" => a.AptitudePrimary,
    "aptitudeSecondary" => a.AptitudeSecondary,
    "rarity" => a.Rarity,
    "threatBand" => a.ThreatBand,
    "deployMode" => a.DeployMode,
    _ => null,
};

static void PrintDistribution(IEnumerable<string> values)
{
    var counts = values.GroupBy(v => v).OrderByDescending(g => g.Count()).ToList();
    var total = counts.Sum(g => g.Count());
    if (total == 0) { Console.WriteLine("    (none)"); return; }
    foreach (var g in counts)
        Console.WriteLine($"    {g.Key,-14} {g.Count(),4}  ({g.Count() * 100 / total}%)");
}

static double Median(IReadOnlyList<double> sorted)
{
    if (sorted.Count == 0) return 0;
    var mid = sorted.Count / 2;
    return sorted.Count % 2 == 1 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2.0;
}

/// <summary>
/// Shannon entropy, normalised to [0, 1] against the FULL possible set (not just the values that
/// happened to appear) — the standard diversity index (same shape ecology's own Shannon index
/// uses). 1.0 means every possible value is used equally often; a low score can come from either
/// skew (a few values dominate) or dead coverage (some values never appear at all) — dividing by
/// `log2(possibleCount)` rather than `log2(usedCount)` is what makes a completely unused value
/// lower the score, exactly the signal a coverage gap needs to show up as.
/// </summary>
static double NormalizedEntropy(IReadOnlyDictionary<string, int> counts, IReadOnlyList<string> possible, int total)
{
    if (total == 0 || possible.Count <= 1) return 0;
    var h = 0.0;
    foreach (var value in possible)
    {
        var c = counts.GetValueOrDefault(value);
        if (c == 0) continue;
        var p = (double)c / total;
        h -= p * Math.Log2(p);
    }
    return h / Math.Log2(possible.Count);
}

/// <summary>
/// A self-calibrated baseline, not a hand-picked number: the median of every creature-species magnitude
/// channel actually observed across the corpus. Rebuilding it from THIS run's own data (rather than
/// a fixed reference file) is what makes the tool re-runnable as the corpus grows or gets rebalanced
/// — the baseline always represents "the field average today," never a stale snapshot.
///
/// `BaseDamage` is fixed at 1000 for every species (baseline included) — a deliberate modeling
/// choice, not a real per-species value: it isolates each species' OWN derived stat profile
/// (power/defense/block/parry/shield) as the thing this report measures, matching the same choice
/// made in the one-off analysis this tool replaces (2026-09-03, rarity-scaling finding).
/// </summary>
static Archetype BuildBaseline(IReadOnlyList<ConcreteSpecies> species)
{
    var channels = species.SelectMany(s => s.Magnitudes.Keys).Distinct().ToList();
    var stats = new Dictionary<string, StatRange>(StringComparer.Ordinal);
    foreach (var channel in channels)
    {
        if (channel == "resource.max.hp") continue; // becomes Hp, not a Stats entry — same as ToArchetype
        var values = species.Where(s => s.Magnitudes.ContainsKey(channel))
            .Select(s => (double)s.Magnitudes[channel]).OrderBy(v => v).ToList();
        stats[channel] = StatRange.Fixed(Median(values));
    }
    var hpValues = species.Where(s => s.Magnitudes.ContainsKey("resource.max.hp"))
        .Select(s => (double)s.Magnitudes["resource.max.hp"]).OrderBy(v => v).ToList();
    return new Archetype
    {
        Name = "field-average", Hp = StatRange.Fixed(Median(hpValues)), BaseDamage = StatRange.Fixed(1000),
        ShieldHp = StatRange.Fixed(0), Stats = stats,
    };
}

static Archetype ToArchetype(ConcreteSpecies species, string name)
{
    var stats = species.Magnitudes
        .Where(kv => kv.Key != "resource.max.hp")
        .ToDictionary(kv => kv.Key, kv => StatRange.Fixed(kv.Value), StringComparer.Ordinal);
    var hp = species.Magnitudes.GetValueOrDefault("resource.max.hp", 0);
    return new Archetype
    {
        Name = name, Hp = StatRange.Fixed(hp), BaseDamage = StatRange.Fixed(1000),
        ShieldHp = StatRange.Fixed(species.Magnitudes.GetValueOrDefault("combat.shield.capacity.omni", 0)),
        Stats = stats,
    };
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
