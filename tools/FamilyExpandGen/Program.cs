using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using FusionRpg.Core.Battle;
using FusionRpg.Core.Effects.Atoms;
using FusionRpg.Core.Effects.Atoms.Generation;
using FusionRpg.Core.Power;
using FusionRpg.Tools.FamilyExpandGen;
using FusionRpg.Core.Workspace;

// E43 family-expand generator (spec-family-expand.md §3.1, decided 2026-09-03 — the CreatureSpeciesGen
// --check pattern). Reads every authored affix-family definition
// (gk-data/packs/fusion/data/seed/items/affix-families/*.json) and the tier-bands balance surface
// (data/seed/items/_tuning/tier-bands.v{n}.json, LATEST version — TierBandsFile.FindLatestPath, fixed
// 2026-09-08 after this literally hardcoded "v1.json" and silently ignored two real, already-published
// later versions), and writes one atom seed file PER SOURCE FAMILY FILE under gk-data/packs/fusion/data/seed/atoms/generated/
// — a directory already inside AtomImporter's SeedScanner.OwnedFolders "atoms" root, so the importer
// sweeps the GENERATED rows and never parses a family file itself. The definitions stay exactly where
// the item program put them and never move.
//
// Usage: dotnet run --project gk-forge/tools/FamilyExpandGen -- [--seed <dir>] [--out <dir>] [--check]
//        --seed   default: gk-data/packs/fusion/data/seed/items, found by walking up from the working directory
//        --out    default: gk-data/packs/fusion/data/seed/atoms/generated
//        --check  regenerate in memory, diff byte-for-byte against what's on disk, and reconcile the
//                 underscore-prefixed refusal/provenance manifest; write nothing; exit 1 on any
//                 generated output, refusal baseline, input hash, or provenance drift
//
// Exit codes: 0 clean/written, 1 stale output/refusal/provenance (--check), 2 could not start. A
// refused family (no authored share, no reference-base curve, no matching pool) is expected and is
// recorded in the manifest; a refusal inventory change is not silently green on --check.

var args2 = args.ToList();
string? seedOverride = TakeOption("--seed");
string? outOverride = TakeOption("--out");
var check = args2.Remove("--check");

string? TakeOption(string flag)
{
    var i = args2.IndexOf(flag);
    if (i < 0 || i + 1 >= args2.Count) return null;
    var value = args2[i + 1];
    args2.RemoveRange(i, 2);
    return value;
}

var itemsRoot = seedOverride ?? FindUp("data", "seed", "items");
if (itemsRoot is null || !Directory.Exists(itemsRoot))
{
    Console.Error.WriteLine("could not locate data/seed/items; pass --seed <dir>");
    return 2;
}

var repoRoot = Path.GetFullPath(Path.Combine(itemsRoot, "..", "..", ".."));
var provenanceInputs = new List<FamilyExpandInputDescriptor>();

var familiesDir = Path.Combine(itemsRoot, "affix-families");
if (!Directory.Exists(familiesDir))
{
    Console.Error.WriteLine($"missing {familiesDir}");
    return 2;
}

// species-gear-chain T12: the milestone partition reads through the same expansion —
// `MilestoneFamilyFile` (runtimeFamily as the family id, never the ledger id) — and lands in
// `family-expand.milestones.json`, grouped by its own source file like every other input. The
// milestone corpus stays generated and ledger-owned; this widens the generator's INPUT SET, never
// hand-writes a row.
var milestonesPath = Path.Combine(itemsRoot, "enhancement-milestones", "milestones.json");
if (!File.Exists(milestonesPath))
{
    Console.Error.WriteLine($"missing {milestonesPath}");
    return 2;
}
provenanceInputs.Add(FamilyExpandManifest.DescribeFile(repoRoot, milestonesPath, note: "enhancement milestone families"));

// The E30 pool catalog is a generator input, not a comment in FamilyExpansion.cs.  Read it before
// expansion and validate every emitted pool reference against this exact file; the importer sees
// the same catalog and must never receive a row naming an id it cannot resolve.
var poolPath = Path.GetFullPath(Path.Combine(itemsRoot, "..", "channel-pools", "pools.v1.json"));
FamilyExpandPoolCatalog poolCatalog;
try
{
    poolCatalog = FamilyExpandPoolCatalog.Load(poolPath);
    provenanceInputs.Add(FamilyExpandManifest.DescribeFile(repoRoot, poolPath, 1, note: "E30 channel-pool catalog"));
}
catch (Exception ex)
{
    Console.Error.WriteLine($"{poolPath}: {ex.Message}");
    return 2;
}

// Real bug fixed 2026-09-08 (atom-family-expansion, tier-bands-coverage): this used to hardcode
// literal "tier-bands.v1.json", so `seedsmith numerics rebalance --publish` (which writes
// tier-bands.v{n+1}.json) had zero effect on this generator -- confirmed live, two real published
// versions (v2/v3) already existed on disk, unread by anything. TierBandsFile.FindLatestPath
// mirrors seedsmith.numerics.tier_bands_io.load("latest")'s own resolution exactly.
var tuningDir = Path.Combine(itemsRoot, "_tuning");
string tierBandsPath;
try
{
    tierBandsPath = TierBandsFile.FindLatestPath(tuningDir);
}
catch (FileNotFoundException)
{
    Console.Error.WriteLine($"missing tier-bands.v*.json under {tuningDir}");
    return 2;
}
provenanceInputs.Add(FamilyExpandManifest.DescribeFile(
    repoRoot,
    tierBandsPath,
    VersionedInputFile.VersionOf(tierBandsPath, "tier-bands"),
    note: "latest tier-bands tuning"));

var tuningRoot = FindUp("data", "tuning");
if (tuningRoot is null)
{
    Console.Error.WriteLine("could not locate data/tuning; needed to load the shipped power-scale curve");
    return 2;
}

var powerScalePath = Path.Combine(tuningRoot, "power-scale.v2.json");
if (!File.Exists(powerScalePath))
{
    Console.Error.WriteLine($"missing {powerScalePath}");
    return 2;
}
provenanceInputs.Add(FamilyExpandManifest.DescribeFile(repoRoot, powerScalePath, 2, "base power-scale tuning"));

PowerTuning baseTuning;
try
{
    baseTuning = PowerTuningLoader.Parse(File.ReadAllText(powerScalePath));
}
catch (Exception ex)
{
    Console.Error.WriteLine($"could not load {powerScalePath}: {ex.Message}");
    return 2;
}

// power-scale.v3.json contributes channel pins only — same curve dial, never a fork. v3 keys
// are disjoint from v2's (atk/defense) by design; a collision is a publish error, not a merge.
var v3Path = Path.Combine(tuningRoot, "power-scale.v3.json");
if (File.Exists(v3Path))
    provenanceInputs.Add(FamilyExpandManifest.DescribeFile(repoRoot, v3Path, 3, "additive power-scale channel pins"));
else
    provenanceInputs.Add(FamilyExpandManifest.DescribeMissing(repoRoot, v3Path, "optional additive power-scale pins"));
if (File.Exists(v3Path))
{
    PowerTuning v3;
    try
    {
        v3 = PowerTuningLoader.Parse(File.ReadAllText(v3Path));
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"could not load {v3Path}: {ex.Message}");
        return 2;
    }

    var merged = new Dictionary<string, PowerChannelTuning>(baseTuning.ChannelsOrEmpty, StringComparer.Ordinal);
    foreach (var (name, ch) in v3.ChannelsOrEmpty)
    {
        if (merged.ContainsKey(name))
        {
            Console.Error.WriteLine($"{v3Path}: channel '{name}' collides with v2 — pins are additive across versions, never overlapping");
            return 2;
        }

        merged[name] = ch;
    }

    baseTuning = baseTuning with { Channels = merged };
}

PowerTuningHub.Configure(baseTuning);

// gk-data/packs/fusion/data/seed/items/.. -> gk-data/packs/fusion/data/seed, then atoms/generated — the shipped "atoms" root SeedScanner
// already sweeps (SeedScanner.cs OwnedFolders), never a second, unswept location.
var outRoot = outOverride ?? Path.GetFullPath(Path.Combine(itemsRoot, "..", "atoms", "generated"));

TierBandsInput tierBands;
try
{
    tierBands = TierBandsFile.Read(File.ReadAllText(tierBandsPath));
}
catch (Exception ex)
{
    Console.Error.WriteLine($"{tierBandsPath}: {ex.Message}");
    return 2;
}

var families = new List<FamilyEntryInput>();
var sourceFiles = Directory.GetFiles(familiesDir, "*.json", SearchOption.TopDirectoryOnly)
    .Where(f => !Path.GetFileName(f).StartsWith('_'))
    .OrderBy(f => f, StringComparer.Ordinal)
    .ToArray();

foreach (var file in sourceFiles)
{
    var name = Path.GetFileName(file);
    provenanceInputs.Add(FamilyExpandManifest.DescribeFile(repoRoot, file, note: "authored affix family"));
    try { families.AddRange(AffixFamilyFile.Read(name, File.ReadAllText(file))); }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"{file}: {ex.Message}");
        return 2;
    }
}

// species-gear-chain: enhancement milestones join the same family list the affix files above feed.
// Merged 2026-09-16 — this and the status-anchor/interval-reference block below were added to the
// same region by two branches and are independent, so both stay; this one moves up beside the
// other `families.AddRange` call it belongs with.
try { families.AddRange(MilestoneFamilyFile.Read("milestones.json", File.ReadAllText(milestonesPath))); }
catch (Exception ex)
{
    Console.Error.WriteLine($"{milestonesPath}: {ex.Message}");
    return 2;
}

// status-anchor.v{n}.json (passive-tree-repair SA-1): chance/duration t1 bases plus the
// family-to-status mapping (authored in atom-family-library.md SS3.4, quoted in the file, never
// inferred). Latest version wins, same convention as tier-bands. Absent = status.apply families
// refuse naming the missing anchor row (E43's own message), never a default.
IReadOnlyDictionary<string, StatusAnchorRow>? statusAnchor = null;
var registryDir = Path.Combine(itemsRoot, "_registry");
// Numeric version selection is shared with the tier-bands rule: v10 must beat v9, not lose to
// it because the filenames sort lexicographically.
var anchorPath = VersionedInputFile.FindLatestPath(registryDir, "status-anchor");
if (anchorPath is not null)
    provenanceInputs.Add(FamilyExpandManifest.DescribeFile(
        repoRoot,
        anchorPath,
        VersionedInputFile.VersionOf(anchorPath, "status-anchor"),
        note: "latest status-anchor registry"));
else
    provenanceInputs.Add(FamilyExpandManifest.DescribeMissing(
        repoRoot,
        Path.Combine(registryDir, "status-anchor.v*.json"),
        "optional status-anchor registry; status.apply families refuse without it"));
if (anchorPath is not null)
{
    try { statusAnchor = StatusAnchorFile.Read(File.ReadAllText(anchorPath)); }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"{anchorPath}: {ex.Message}");
        return 2;
    }
}

StatusAnchorRow? AnchorFor(string familyId) =>
    statusAnchor is not null && statusAnchor.TryGetValue(familyId, out var row) ? row : null;

// channel-policy/defaults.json (passive-tree-repair IL-1): referenceMs for interval channels.
// Data lookup, same class as the v3 pins — direction (LowerIsBetter) stays downstream's job.
var intervalPolicyPath = Path.Combine(itemsRoot, "..", "channel-policy", "defaults.json");
if (File.Exists(intervalPolicyPath))
    provenanceInputs.Add(FamilyExpandManifest.DescribeFile(
        repoRoot, intervalPolicyPath, note: "interval channel reference policy"));
else
    provenanceInputs.Add(FamilyExpandManifest.DescribeMissing(
        repoRoot, intervalPolicyPath, "optional interval channel reference policy"));

IReadOnlyDictionary<string, long> intervalReferenceMs = LoadIntervalReferenceMs();
IReadOnlyDictionary<string, long> LoadIntervalReferenceMs()
{
    var policyPath = intervalPolicyPath;
    if (!File.Exists(policyPath)) return new Dictionary<string, long>(StringComparer.Ordinal);
    try
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(policyPath));
        var d = new Dictionary<string, long>(StringComparer.Ordinal);
        foreach (var e in doc.RootElement.GetProperty("entries").EnumerateArray())
        {
            if (e.TryGetProperty("referenceMs", out var ms) && ms.TryGetInt64(out var v))
                d[e.GetProperty("channel").GetString()!] = v;
        }
        return d;
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"{policyPath}: {ex.Message}");
        Environment.Exit(2);
        throw new InvalidOperationException("unreachable");
    }
}

// Flat op only — Increased/More read the identity ratio and never touch a game curve
// (FamilyExpansion.TryReferenceBaseM1's own doc). "hp" reuses BaseHp's curve deliberately: it is the
// same hit-point unit space as "maxHp" and there is no separate current-hp curve anywhere in the
// tuning surface. Channels with no pin anywhere (attackInterval/produceInterval/zombieSpeed/'' —
// owned by interval-ledger, battle-tempo, or the status anchor path) return null and their families
// are refused, honestly, rather than inventing a base. power-scale.v3.json pins (passive-tree-repair
// V3-1) extend this map without touching the v2 curve.
long? FlatReferenceBase(string channel)
{
    // Shipped curve reads stay first (same values the game uses at runtime).
    long? direct = channel switch
    {
        "maxHp" or "hp" => BattleRuleset.BaseHp(FamilyExpansion.ReferenceLevel),
        "atk" => BattleRuleset.BaseAtk(FamilyExpansion.ReferenceLevel),
        "defense" => BattleRuleset.BaseDefense(FamilyExpansion.ReferenceLevel),
        _ => null,
    };
    if (direct is not null) return direct;

    // v3 pins: a channel's composed value at the Theta=20 reference, zero contributions.
    // PinValue only — growth stays on the tier ladder, never on a second curve.
    if (PowerTuningHub.Tuning.ChannelsOrEmpty.TryGetValue(channel, out var tuning))
        return tuning.PinValue;

    // Interval references (IL-1): ms baselines from channel-policy. Direction stays downstream.
    if (intervalReferenceMs.TryGetValue(channel, out var referenceMs))
        return referenceMs;

    return null;
}

var result = FamilyExpansion.Expand(families, tierBands, FlatReferenceBase, AnchorFor);
var poolErrors = poolCatalog.Validate(result.Rows);
if (poolErrors.Count > 0)
{
    Console.Error.WriteLine($"{poolErrors.Count} generated pool reference(s) do not close against {poolPath}:");
    foreach (var error in poolErrors) Console.Error.WriteLine("  " + error);
    return 2;
}

var familySource = families.ToDictionary(f => f.Id, f => f.SourceFile, StringComparer.Ordinal);
var bySource = result.Rows
    .GroupBy(r => familySource[r.FamilyId])
    .OrderBy(g => g.Key, StringComparer.Ordinal)
    .ToDictionary(g => g.Key, g => g.OrderBy(r => r.AtomId, StringComparer.Ordinal).ToList());

var wantedFiles = new Dictionary<string, string>(StringComparer.Ordinal); // absolute out path -> json text
foreach (var (sourceFile, rows) in bySource)
{
    var stem = Path.GetFileNameWithoutExtension(sourceFile);
    var outName = $"family-expand.{stem}.json";
    if (outName.StartsWith("fx-", StringComparison.OrdinalIgnoreCase))
    {
        // Mechanical, not just documented — spec-family-expand.md §3.3/§4: this generator's own
        // output must never collide with ElementEnumGen's fx-*.json sweep or with
        // EffectAtomCatalogGeneratedTests' frozen-catalog id set.
        Console.Error.WriteLine($"refusing to name generated output '{outName}' — fx-* is reserved");
        return 2;
    }

    wantedFiles[Path.GetFullPath(Path.Combine(outRoot, outName))] = FamilyExpansionSeedFile.ToCanonicalJson(rows);
}

var totalRows = bySource.Values.Sum(r => r.Count);
Console.WriteLine(
    $"{families.Count} families read, {totalRows} row(s) emitted across {bySource.Count} family file(s), " +
    $"{result.Refusals.Count} family(ies) refused:");
foreach (var r in result.Refusals.OrderBy(r => r.FamilyId, StringComparer.Ordinal))
    Console.WriteLine($"  {r.FamilyId} — {r.Reason}");

// The manifest is the durable refusal/provenance closure.  It is a sidecar, not an atom seed:
// the leading underscore is the SeedScanner convention for notes/exemplars.  Its expected form is
// computed from this run's inputs, outputs, and refusals, so --check can distinguish an intentional
// refusal baseline from a newly introduced or silently dropped refusal.
var outputDescriptors = wantedFiles.Select(pair =>
{
    using var document = JsonDocument.Parse(pair.Value);
    var rowCount = document.RootElement.GetProperty("entries").GetArrayLength();
    var relativePath = Path.GetRelativePath(repoRoot, pair.Key).Replace('\\', '/');
    return new FamilyExpandOutputDescriptor(
        relativePath,
        FamilyExpandHash.Sha256Text(pair.Value),
        rowCount);
}).ToArray();
var expectedManifest = FamilyExpandManifest.Create(
    provenanceInputs,
    outputDescriptors,
    result.Refusals);
var manifestPath = Path.Combine(outRoot, "_family-expand.manifest.json");

var existingGenerated = Directory.Exists(outRoot)
    ? Directory.GetFiles(outRoot, "family-expand.*.json").Select(Path.GetFullPath).ToArray()
    : Array.Empty<string>();

if (check)
{
    var stale = new List<string>();
    var existingManifest = File.Exists(manifestPath) ? File.ReadAllText(manifestPath) : null;
    var manifestReconciliation = FamilyExpandManifest.Reconcile(existingManifest, expectedManifest);
    if (!manifestReconciliation.IsClean)
        stale.Add($"{manifestPath} — {manifestReconciliation.Detail}");

    foreach (var (outPath, json) in wantedFiles)
    {
        var existing = File.Exists(outPath)
            ? FamilyExpansionSeedFile.Canonicalize(File.ReadAllText(outPath))
            : null;
        if (existing != json) stale.Add(outPath);
    }

    // A committed generated file with no corresponding source family any more is stale output —
    // §3.1's own "a stale generation fails CI" acceptance criterion, not just a diff on files that
    // still exist.
    foreach (var existingFile in existingGenerated)
        if (!wantedFiles.ContainsKey(existingFile))
            stale.Add(existingFile);

    if (stale.Count > 0)
    {
        Console.Error.WriteLine($"{stale.Count} generated output/provenance item(s) stale against {outRoot}:");
        foreach (var s in stale.OrderBy(x => x, StringComparer.Ordinal)) Console.Error.WriteLine("  " + s);
        return 1;
    }

    Console.WriteLine(
        $"--check: clean, {wantedFiles.Count} generated file(s), {result.Refusals.Count} recorded refusal(s), " +
        $"and provenance manifest match {outRoot}");
    return 0;
}

Directory.CreateDirectory(outRoot);
var written = 0;
foreach (var (outPath, json) in wantedFiles)
{
    if (!File.Exists(outPath) || FamilyExpansionSeedFile.Canonicalize(File.ReadAllText(outPath)) != json)
    {
        FamilyExpansionSeedFile.WriteCanonical(outPath, json);
        written++;
    }
}

var removed = 0;
foreach (var existingFile in existingGenerated)
{
    if (wantedFiles.ContainsKey(existingFile)) continue;
    File.Delete(existingFile);
    removed++;
}

FamilyExpansionSeedFile.WriteCanonical(manifestPath, expectedManifest.ToCanonicalJson());

Console.WriteLine(
    $"{written} file(s) written, {removed} stale file(s) removed, " +
    $"{result.Refusals.Count} refusal(s) reconciled, under {outRoot}");
return 0;

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

