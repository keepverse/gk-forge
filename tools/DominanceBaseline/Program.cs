using System.Text.Json;
using FusionRpg.Core.Workspace;
using System.Text.RegularExpressions;
using FusionRpg.Core.Balance.Guards;
using FusionRpg.Core.Battle;
using FusionRpg.Core.Combat;
using FusionRpg.Core.Combat.Shield;
using FusionRpg.Core.Effects.Atoms;
using FusionRpg.Core.Power;
using FusionRpg.Core.Stats;
using FusionRpg.Core.Stats.Aptitudes;
using FusionRpg.Core.Stats.Derived;
using FusionRpg.Core.Stats.Derived.Subsystems;
using FusionRpg.Core.Status;

// class-system-todo.md Checkpoint 8's own remaining gap: _baseline-dominance.json's dominanceMatrix and
// dominantCorners fields come from gk-core/tools/CombatSim's `trinity --json`, which reads its own internal,
// still-v1-only tuning copy (P8.5) -- blocked from updating by the same concurrent-edit hazard as
// P3.4/P8.1, and even an override would silently ignore the new AptitudeMitigation dial (P8.3).

// item-todo.md P1.5 / item-plan.md Checkpoint 1 — "the first geared corner run". Opt-in: WITHOUT
// --geared this tool emits byte-for-byte what it always has (DominanceBaselineTests.Run_isDeterministic
// and scripts/regen-class-system-baselines.ps1 both depend on that), and every corner resolves through
// an ActorHub carrying no equipment subsystem at all. WITH it, each corner is additionally equipped
// with the real shipped stat.derived atom corpus and the run is reported alongside the bare one, so
// the delta between them is the evidence that equipment reached the derived snapshot.
var wantGeared = args.Contains("--geared");

var theta = long.Parse(ArgOrDefault(args, "--theta", "100"));
var outPath = ArgOrDefault(args, "--out", "");

// Loads the LIVE shipped config (highest data/tuning/aptitudes.v*.json) -- never a hand-picked version
// literal, matching AptitudeTuningHub.cs's own doc-comment warning about exactly that staleness risk,
// and gk-core/tools/ResidualFitLoop's own established Configure-at-startup pattern.
var repoRoot = FindRepoRoot();
var tuningDir = Path.Combine(KeepverseRoots.Core(), "data", "tuning");
string Read(string domain) => File.ReadAllText(Path.Combine(tuningDir, LatestTuningFileName(tuningDir, domain)));
string ReadPinned(string fileName) => File.ReadAllText(Path.Combine(tuningDir, fileName));

// TerminationGuard.ToActor -> ActorHubBootstrap.CreateDefault touches every one of these hubs (the
// SAME full set gk-core/tools/ResidualFitLoop already configures for the identical reason) -- never a
// hand-picked version literal, matching AptitudeTuningHub.cs's own doc-comment warning about exactly
// that staleness risk; --input overrides ONLY the aptitudes domain (the one this task is measuring).
var tuningFileName = ArgOrDefault(args, "--input", LatestTuningFileName(tuningDir, "aptitudes"));
var tuningPath = Path.IsPathRooted(tuningFileName) ? tuningFileName : Path.Combine(tuningDir, tuningFileName);
AptitudeTuningHub.Configure(AptitudeTuningLoader.Parse(File.ReadAllText(tuningPath)));
CombatPolicy.Configure(CombatTuningLoader.Parse(Read("combat")));
ShieldPolicy.Configure(ShieldTuningLoader.Parse(Read("shield")));
DerivedStatPolicy.Configure(DerivedStatTuningLoader.Parse(Read("derived-stats")));
// ⛔ power-scale is PINNED, not latest-wins. `power-scale.v3.json` is not a newer curve — it is a
// different artifact kind that happens to share the domain prefix: "Pins, not curves. Each row is a
// channel's composed value at the Theta=20 reference", owned by passive-tree-repair, and its own
// _meta says "v2.json frozen". Its channel keys are templates (`combat.power.{variant}`, `arm1Max`)
// with no `atk`/`defense`, so `BattleRuleset.ChannelLadderFor("atk")` throws against it.
PowerTuningHub.Configure(PowerTuningLoader.Parse(ReadPinned("power-scale.v2.json")));
StatusPolicy.Configure(StatusTuningLoader.Parse(Read("status")));
StatsTuningHub.Configure(StatsTuningLoader.Parse(Read("stats")));

// The real roster's own 12 (gk-data/packs/fusion/data/seed/aptitudes/roster.json) and the exact spike/floor corner shape
// BestResponse.DominanceMatrix uses -- verbatim from DominanceGuardTests.cs's own
// Measure_theRealTwelveCornerShape_matchesTheCheckedInBaselinesEmptyDominantCorners (already green
// against the live shipped config) and gk-core/tools/ResidualFitLoop's own identical roster -- kept identical
// across all three rather than re-derived, so a future drift in one is a diff against the other two.
string[] roster =
{
    "Might", "Fortitude", "Vigor", "Onslaught", "Agility", "Composure",
    "Pierce", "Focus", "Bulwark", "Retribution", "Precision", "Ferocity",
};
// Not a balance dial -- BestResponse.DominanceMatrix's own fixed corner-shape constant
// (100/roster.Length/2, per-mille), reproduced verbatim so this tool's corners match trinity's.
const long floor = 4167;
long Spike() => 100_000 - floor * (roster.Length - 1);
AptitudeAllocation Corner(string spikeId) =>
    roster.Aggregate(AptitudeAllocation.Empty, (acc, id) =>
        acc + AptitudeAllocation.Single(AllocationScope.Commander, id, id == spikeId ? Spike() : floor));

var builds = roster.Select(Corner).ToArray();
var report = DominanceGuard.Measure(builds, theta);

// DominanceGuard.Measure names its actors positionally ("corner{i}", read directly from its own
// source: `actors[i] = TerminationGuard.ToActor($"corner{i}", builds[i], theta)`) rather than by the
// aptitude id -- ToActor itself is internal, so this tool cannot build actors with real names directly.
// "corner{i}" maps exactly to builds[i], which is roster[i] by construction (builds = roster.Select
// (Corner)), so parsing the index back out is exact, not a guess about implementation behavior.
static int CornerIndex(string name) => int.Parse(name["corner".Length..]);

// wins[i][j]: attacker i's win share against defender j; diagonal 0.5, matching the existing checked-in
// baseline's own convention (self-vs-self placeholder, never read).
double[][] WinsOf(DominanceReport r)
{
    var w = new double[roster.Length][];
    for (var i = 0; i < roster.Length; i++)
    {
        w[i] = new double[roster.Length];
        for (var j = 0; j < roster.Length; j++) w[i][j] = 0.5;
    }
    foreach (var arrow in r.Matrix)
        w[CornerIndex(arrow.AttackerName)][CornerIndex(arrow.DefenderName)] = arrow.WinShareAttacker;
    return w;
}

// unending[i][j]: the termination invariant per ordered pair, via the SAME public entry point
// (TerminationGuard.Assert) gk-core/tools/ResidualFitLoop already uses for this exact sweep (P8.6/P8.7) --
// a 2-build array per call, try/catch on TerminationViolation, never a re-derivation of the net-
// attrition condition itself.
bool[][] UnendingOf(IReadOnlyList<IReadOnlyList<BoundDerivedAtom>>? gear)
{
    var u = new bool[roster.Length][];
    for (var i = 0; i < roster.Length; i++)
    {
        u[i] = new bool[roster.Length];
        for (var j = 0; j < roster.Length; j++)
        {
            if (i == j) continue;
            // The 2-build slice needs its gear sliced the same way -- Assert requires positional
            // alignment, and passing the full 12-entry gear against a 2-build array would throw.
            var pairGear = gear is null ? null : new[] { gear[i], gear[j] };
            try { TerminationGuard.Assert(new[] { builds[i], builds[j] }, theta, pairGear); }
            catch (TerminationViolation) { u[i][j] = true; }
        }
    }
    return u;
}

var wins = WinsOf(report);
var unending = UnendingOf(null);
var dominantCorners = report.DominantBuildNames.Select(n => roster[CornerIndex(n)]).ToArray();

const string model = "data/tuning/aptitudes (live, via FusionRpg.Core.DominanceGuard/TerminationGuard — not tools/CombatSim)";

object payload = new
{
    model,
    theta,
    dominanceMatrix = new { names = roster, wins, unending },
    dominantCorners,
};

if (wantGeared)
{
    // The equipped payload is REAL SHIPPED CONTENT, read off disk -- never a literal in this file.
    // Everything under gk-data/packs/fusion/data/seed/atoms is collected through the shipped Core-side reader
    // (AtomSeedFile, the same one the importer uses) and filtered to the one kind equipment
    // contributes through, exactly as EquipAtomSource itself filters.
    var atomsRoot = Path.Combine(KeepverseRoots.Content(), "data", "seed", "atoms");
    var seedFiles = Directory.Exists(atomsRoot)
        ? Directory.GetFiles(atomsRoot, "*.json", SearchOption.AllDirectories)
            .OrderBy(f => f, StringComparer.Ordinal)
            .Select(f => (Path: f, Json: File.ReadAllText(f)))
            .ToArray()
        : Array.Empty<(string Path, string Json)>();

    var collected = AtomSeedFile.Collect(seedFiles);
    var equippedRows = collected.Content.Atoms
        .Where(a => string.Equals(a.KindId, "stat.derived", StringComparison.Ordinal))
        .OrderBy(a => a.AtomId, StringComparer.Ordinal)
        .ToArray();

    // Legacy flatten via FromResolver (equip:unknown:{atomId}) — NOT the Server Program.cs path.
    // Production battle uses EquippedBoundAtoms.SourceFromStore → FromEquippedResolver
    // (equip:{role}:{itemRef}). This tool substitutes the store with the shipped corpus and keeps
    // specimen keying / kind filter / param parse as module 5 built it.
    var specimenOf = Enumerable.Range(0, roster.Length)
        .ToDictionary(i => $"specimen-corner-{i}", i => i, StringComparer.Ordinal);
    var equip = EquipAtomSource.FromResolver(specimenId =>
        specimenOf.ContainsKey(specimenId) ? equippedRows : Array.Empty<AtomRow>());

    var gear = Enumerable.Range(0, roster.Length)
        .Select(i => equip.DerivedAtomsFor($"specimen-corner-{i}"))
        .ToArray();

    var gearedReport = DominanceGuard.Measure(builds, theta, gear);
    var gearedWins = WinsOf(gearedReport);
    var gearedUnending = UnendingOf(gear);

    // The falsifying probe. If equipment never reached a channel the predictor reads, every geared
    // win share equals its bare twin and this is exactly 0 -- which would mean the run "executed"
    // while proving nothing. Reported as a number rather than asserted, so the evidence is the
    // output, not a claim about it.
    var maxAbsDelta = 0.0;
    for (var i = 0; i < roster.Length; i++)
    for (var j = 0; j < roster.Length; j++)
        maxAbsDelta = Math.Max(maxAbsDelta, Math.Abs(gearedWins[i][j] - wins[i][j]));

    var terminationGreen = true;
    for (var i = 0; i < roster.Length && terminationGreen; i++)
    for (var j = 0; j < roster.Length; j++)
        if (gearedUnending[i][j]) { terminationGreen = false; break; }

    payload = new
    {
        model,
        theta,
        dominanceMatrix = new { names = roster, wins, unending },
        dominantCorners,
        geared = new
        {
            equippedAtoms = equippedRows.Select(a => new
            {
                atomId = a.AtomId, family = a.FamilyId, tier = a.Tier, @params = a.ParamsJson,
            }).ToArray(),
            equippedAtomCount = equippedRows.Length,
            // What actually reached the predictor, which is NOT the same as what was swept.
            // `EquipAtomSource` skips a row whose `amount` is a ValueSpec object rather than a plain
            // number (`patron-absorption`'s twelve `externalRef` aura atoms, 2026-09-06) — this seam
            // has no ValueSpec resolver. Reported separately so the evidence never reads "13 atoms
            // equipped" when one carried the whole delta.
            contributingAtomCount = gear.Length == 0 ? 0 : gear[0].Count,
            seedFilesRead = seedFiles.Length,
            seedFilesRefused = collected.Errors.Count,
            // Named, not hidden: every stat.derived AFFIX family is refused by E43 today because
            // tier-bands.v1.json authors a sharePermille for the 14 stat.modify primary-channel
            // families only, so gk-data/packs/fusion/data/seed/atoms/generated/ carries no stat.derived row at all. The
            // corpus below is what genuinely ships. When that gap closes, this run gets richer with
            // no code change here.
            corpusNote = "data/seed/items/_tuning/tier-bands.v1.json authors sharePermille for the 14 stat.modify primary-channel families only, so FamilyExpansion (E43) refuses every stat.derived affix family and data/seed/atoms/generated/ holds no stat.derived row. The atoms above are the whole shipped stat.derived corpus.",
            dominanceMatrix = new { names = roster, wins = gearedWins, unending = gearedUnending },
            dominantCorners = gearedReport.DominantBuildNames.Select(n => roster[CornerIndex(n)]).ToArray(),
            terminationGreen,
            matrixMaxAbsDeltaVsBare = maxAbsDelta,
            coverage = new
            {
                elementAxis = gearedReport.Coverage.ElementAxis,
                reservedFamilies = gearedReport.Coverage.ReservedFamilies,
                note = CoverageReport.UpperBoundNote,
            },
        },
    };
}

var json = JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true });
if (string.IsNullOrEmpty(outPath)) Console.WriteLine(json);
else File.WriteAllText(outPath, json);

return 0;

static string ArgOrDefault(string[] a, string flag, string fallback)
{
    var idx = Array.IndexOf(a, flag);
    return idx >= 0 && idx + 1 < a.Length ? a[idx + 1] : fallback;
}

// Mirrors gk-core/tools/tuning/publish.py's own latest_version(domain) / gk-core/tools/ResidualFitLoop's own
// LatestTuningFileName exactly (highest {domain}.v{n}.json in the tuning dir) rather than a hardcoded
// version literal.
static string LatestTuningFileName(string tuningDir, string domain)
{
    var pat = new Regex($@"^{Regex.Escape(domain)}\.v(\d+)\.json$");
    var best = Directory.EnumerateFiles(tuningDir)
        .Select(Path.GetFileName)
        .Select(n => (Name: n!, Match: pat.Match(n!)))
        .Where(x => x.Match.Success)
        .Select(x => (x.Name, Version: int.Parse(x.Match.Groups[1].Value)))
        .OrderByDescending(x => x.Version)
        .FirstOrDefault();
    if (best.Name is null) throw new InvalidOperationException($"no {domain}.v*.json found in {tuningDir}");
    return best.Name;
}

/// Marker: `Directory.Build.props`, the tracked MSBuild root file -- NOT a tool. The marker this
/// used to name, `scripts/guard-class-system.ps1`, was ported to `.py` and no longer exists, so
/// EVERY invocation threw `could not locate repo root`. A marker must be a file no tool migration
/// can delete; the two `FusionRpg.Core.ClassSystem.Tests` files beside this one already used
/// `Directory.Build.props`, and this adopts their convention.
static string FindRepoRoot()
{
    var dir = new DirectoryInfo(AppContext.BaseDirectory);
    while (dir != null)
    {
        if (File.Exists(Path.Combine(dir.FullName, "Directory.Build.props"))) return dir.FullName;
        dir = dir.Parent;
    }
    throw new InvalidOperationException("could not locate repo root above " + AppContext.BaseDirectory);
}
