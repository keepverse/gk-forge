using System.Text.Json;
using FusionRpg.Core.Creatures;
using FusionRpg.Core.Creatures.Generation;
using FusionRpg.Core.Power;
using FusionRpg.Core.Stats.Aptitudes;
using FusionRpg.Core.Stats.Derived;
using FusionRpg.Core.Workspace;

// species-generator's own CLI (T4.5, spec-species-generator.md §7-8). Reads every real classified
// anchor under the seed root, expands each into a ConcreteSpecies, and writes the committed,
// canonically-serialised generated tree.
//
// Usage: dotnet run --project gk-forge/tools/CreatureSpeciesGen -- [--seed <dir>] [--out <dir>] [--check]
//                                                       [--explain <speciesId>]
//                                                       [--export-legacy <path>]
//        --seed     default: gk-data/packs/fusion/data/seed/creatures/species, found by walking up from the working directory
//        --out      default: gk-data/packs/fusion/data/generated/creatures
//        --check    compare against what is on disk; write nothing; exit 1 if anything differs
//        --explain  print the full derivation chain for one species; write nothing
//        --export-legacy   write the SHIPPED, COMPILED 84-species catalog's own
//                          elementPrimary/deployMode/acquisition/variants as plain JSON, in the
//                          exact shape `legacy_diff.py`'s `diff_legacy(new_anchors, legacy_entries)`
//                          expects — closes the "a small future export step" gap that module's own
//                          docstring named (T2.7, spec-anchor-emit.md §6). Independent of every
//                          other flag; writes nothing else and exits immediately after.
//
// Exit codes: 0 clean/written, 1 stale (--check) or species not found (--explain), 2 could not start.

var args2 = args.ToList();
string? exportLegacyPath = TakeOption("--export-legacy");
if (exportLegacyPath is not null)
    return ExportLegacy(exportLegacyPath);

string? seedOverride = TakeOption("--seed");
string? outOverride = TakeOption("--out");
var check = args2.Remove("--check");
string? explainSpeciesId = TakeOption("--explain");

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

        // Derived from seedRoot, NOT from the tuning root, and that is the whole point of the change.
        // Tuning and the generated corpus were siblings under one data/ in the monorepo, so deriving one
        // from the other worked. After the Keepverse split gk-core/data/tuning is in gk-core while the generated
        // corpus is in the gk-data pack, and deriving the output from tuning made this compare every species
        // against a gk-core/data/generated/creatures that does not exist - 904 of them reported stale, which
        // is an artefact of the wrong root and not drift. Walking up from seedRoot gives <content>/data in
        // BOTH layouts, because seedRoot is <content>/data/seed/creatures/species in each, so a monorepo
        // checkout resolves byte-for-byte what it always did and the split resolves the real corpus.
        var contentDataDir = Path.GetFullPath(Path.Combine(seedRoot, "..", "..", ".."));
        var outRoot = outOverride ?? Path.Combine(contentDataDir, "generated", "creatures");

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

var anchors = new List<AnchorRow>();
foreach (var file in Directory.GetFiles(seedRoot, "*.json", SearchOption.AllDirectories).OrderBy(f => f, StringComparer.Ordinal))
{
    if (Path.GetFileName(file).StartsWith('_')) continue; // notes/exemplars, matching AtomImporter's own convention
    try { anchors.AddRange(AnchorRowReader.ReadAll(File.ReadAllText(file))); }
    catch (AnchorRowRejection ex) { Console.Error.WriteLine($"{file}: {ex.Message}"); return 1; }
}

if (explainSpeciesId is not null)
{
    var anchor = anchors.FirstOrDefault(a => string.Equals(a.SpeciesId, explainSpeciesId, StringComparison.Ordinal));
    if (anchor is null)
    {
        Console.Error.WriteLine($"'{explainSpeciesId}' not found under {seedRoot}");
        return 1;
    }
    Explain(anchor, aptitudeTuning, powerTuning, shapeTuning, threatTuning);
    return 0;
}

var stale = new List<string>();
var skipped = new List<string>();
var written = 0;
foreach (var anchor in anchors)
{
    var unresolvedFields = SpeciesExpander.UnresolvedFields(anchor);
    if (unresolvedFields.Count > 0)
    {
        skipped.Add($"{anchor.SpeciesId} ({string.Join(", ", unresolvedFields)})");
        continue;
    }

    ConcreteSpecies species;
    try { species = SpeciesExpander.Expand(anchor, aptitudeTuning, powerTuning, shapeTuning, threatTuning); }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"'{anchor.SpeciesId}': {ex.Message}");
        return 1;
    }

    var json = ConcreteSpeciesSerializer.Canonical(species);
    var outPath = Path.Combine(outRoot, anchor.SpeciesId + ".json");

    if (check)
    {
        // Normalise the read-back: a working tree that still holds the old CRLF output must not read as
        // stale when its content is identical (CanonicalEol).
        var existing = File.Exists(outPath) ? File.ReadAllText(outPath).ToLf() : null;
        if (existing != json) stale.Add(anchor.SpeciesId);
        continue;
    }

    Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
    if (!File.Exists(outPath) || File.ReadAllText(outPath).ToLf() != json)
    {
        File.WriteAllText(outPath, json);
        written++;
    }
}

if (skipped.Count > 0)
{
    Console.WriteLine(
        $"{skipped.Count} species skipped — still unresolved on at least one voted field, not " +
        $"generated: {string.Join("; ", skipped)}");
}

if (check)
{
    if (stale.Count > 0)
    {
        Console.Error.WriteLine($"{stale.Count} species stale against {outRoot}: {string.Join(", ", stale)}");
        return 1;
    }
    Console.WriteLine($"--check: clean, {anchors.Count - skipped.Count} species match {outRoot}");
    return 0;
}

Console.WriteLine($"{anchors.Count - skipped.Count} species expanded, {written} file(s) written to {outRoot}");
return 0;

static void Explain(
    AnchorRow anchor, AptitudeTuning aptitudeTuning, PowerTuning powerTuning,
    CreatureShapeTuning shapeTuning, CreatureThreatTuning threatTuning)
{
    var species = SpeciesExpander.Expand(anchor, aptitudeTuning, powerTuning, shapeTuning, threatTuning);

    Console.WriteLine($"speciesId       = {anchor.SpeciesId}");
    Console.WriteLine($"rarity          = {anchor.Rarity}  -> ConcreteSpecies.Rarity = {species.Rarity}");
    Console.WriteLine($"threatBand      = {anchor.ThreatBand ?? "(absent, using creature-threat.v1.json's own inferredDefaultRung " + threatTuning.InferredDefaultRung + ")"}");
    Console.WriteLine($"  thetaOffset   = {threatTuning.OffsetFor(anchor.ThreatBand)} (creature-threat.v1.json)");
    Console.WriteLine($"  speciesBaseTheta = {shapeTuning.SpeciesBaseTheta} (creature-shape.v1.json)");
    Console.WriteLine($"theta           = {species.Theta}  (base + offset)");
    Console.WriteLine($"pTheta          = {species.PTheta}  (PowerLadder(power-scale.v2.json).Value(theta))");
    Console.WriteLine($"aptitudePrimary = {anchor.AptitudePrimary}, pure = {anchor.Pure}");
    Console.WriteLine($"aptitudeSecondary = {anchor.AptitudeSecondary ?? "(none)"}");
    Console.WriteLine($"attackTempo     = {anchor.AttackTempo} -> attackIntervalMs = {species.AttackIntervalMs} ({species.AttackIntervalSource})");
    Console.WriteLine($"reach           = {anchor.Reach} -> rangeCells = {species.RangeCells}");
    Console.WriteLine($"variants        = [{string.Join(", ", anchor.Variants)}] -> variantCount = {species.VariantCount}");
    Console.WriteLine($"magnitudes ({species.Magnitudes.Count} channel(s)):");
    foreach (var (channel, value) in species.Magnitudes.OrderBy(kv => kv.Key, StringComparer.Ordinal))
    {
        var edge = aptitudeTuning.Edges.First(e => e.Channel == channel &&
            (e.Source == anchor.AptitudePrimary || e.Source == anchor.AptitudeSecondary));
        Console.WriteLine($"  {channel,-40} = {value,12}  (source={edge.Source} kMilli={edge.KMilli})");
    }
}

/// <summary>Find a directory ending in <paramref name="segments"/>, trying the detected workspace
/// roots before walking up from the working directory.
///
/// <para><b>Why the roots come first.</b> Before the Keepverse split the walk alone was a complete
/// answer, because <c>gk-core/data/tuning</c> and <c>gk-data/packs/fusion/data/seed</c> sat beside this tool. After the split
/// <c>gk-core/data/tuning</c> is in gk-core and <c>gk-data/packs/fusion/data/seed</c> is in a gk-data pack, both siblings of
/// gk-forge, so the walk from here reaches the workspace root and finds neither. That is why these
/// generators exit 2 with "could not locate gk-core/data/tuning" in the split layout while the corpus they
/// read is present and correct. <see cref="KeepverseRoots.Roots"/> is the single place that knows
/// where the roots are, and consulting it here is what keeps ONE resolver instead of a private copy
/// per tool - the same duplication that left ~175 hand-rolled walkers behind.
///
/// <para>The walk is kept, not replaced: it still answers in a legacy checkout, where the roots
/// collapse to the repository root and this returns exactly what it always did, and it still
/// answers for a path outside both roots. Returns <see langword="null"/> rather than throwing, so
/// each caller's own "could not locate X; pass --Y" message is unchanged.
/// </para></summary>
static string? FindUp(params string[] segments)
{
    foreach (var root in KeepverseRoots.Roots(Directory.GetCurrentDirectory()))
    {
        var candidate = Path.Combine(new[] { root }.Concat(segments).ToArray());
        if (Directory.Exists(candidate)) return candidate;
    }

    var dir = new DirectoryInfo(Directory.GetCurrentDirectory());
    while (dir is not null)
    {
        var candidate = Path.Combine(new[] { dir.FullName }.Concat(segments).ToArray());
        if (Directory.Exists(candidate)) return candidate;
        dir = dir.Parent;
    }
    return null;
}


/// <summary>
/// The shipped, compiled 84-species catalog's own comparable fields, in `legacy_diff.py`'s exact
/// expected shape: a flat JSON array of `{id, elementPrimary, deployMode, acquisition, variants}`.
/// `id` matches `diff_legacy`'s own default `legacy_id_key="id"`. Field VALUES match the real
/// anchor's own literal conventions exactly — `elementPrimary` lowercase via the same
/// `ToElementId()` extension the live `/api/creatures/catalog` endpoint already uses, `deployMode` as
/// the enum's own raw name (anchors write `"PlantAvatar"`, never a display-cased variant),
/// `acquisition` as an array of the flag's own set member names (an anchor's own `acquisition` is
/// always an array, even for one flag) — verified against a real anchor
/// (`data/seed/creatures/species/plant/cherry.json`) before writing this, not assumed from the enum
/// alone.
/// </summary>
static int ExportLegacy(string path)
{
    CreatureSpeciesCatalog.ConfigureFromCompiledDefault();

    var rows = CreatureSpeciesCatalog.All
        .OrderBy(s => s.SpeciesId, StringComparer.Ordinal)
        .Select(s => new
        {
            id = s.SpeciesId,
            elementPrimary = s.ElementPrimary.ToElementId(),
            deployMode = s.DeployMode.ToString(),
            acquisition = Enum.GetValues<CreatureAcquisition>()
                .Where(f => f != CreatureAcquisition.None && s.Acquisition.HasFlag(f))
                .Select(f => f.ToString())
                .ToList(),
            variants = s.Variants.ToList(),
        })
        .ToList();

    var json = JsonSerializer.Serialize(rows, new JsonSerializerOptions { WriteIndented = true });
    Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
    File.WriteAllText(path, json);
    Console.WriteLine($"{rows.Count} legacy species exported to {path}");
    return 0;
}
