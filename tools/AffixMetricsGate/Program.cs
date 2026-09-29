using System.Text.Json;
using FusionRpg.Core.Effects.Atoms;
using FusionRpg.Core.Effects.Atoms.Power;
using FusionRpg.Data.Seed;

// `affix-metrics` (T3.8, effect-pipeline) "register with declared targets" — a report, and (with
// --gate) a CI-safe gate, over the real committed gk-data/packs/fusion/data/seed/** tree. Never re-derives the metrics
// themselves (ContentMetrics.FamilyCoverageOf/ContainerFillRatesOf, already built and tested) and
// never re-implements collecting a seed tree (SeedImportRunner, the same member AtomImporter and the
// server's own self-healing startup import both call) — this file is argument parsing and a report,
// matching AtomImporter's/CreatureRecipeDistributionIndex's own division of labour exactly.
//
// Usage: dotnet run --project gk-forge/tools/AffixMetricsGate -- [--seed <dir>] [--gate]
//        --seed   default: gk-data/packs/fusion/data/seed, found by walking up from the working directory
//        --tuning default: gk-core/data/tuning, found the same way
//        --gate   exit 1 only if a finding's OWN gate is armed in affix-metrics.v{n}.json — the
//                 same "measure vs. gate" split creatures metrics --gate already established
//
// Exit codes: 0 clean (or --gate not passed), 1 a gated finding fired, 2 could not start.

var args2 = args.ToList();
var gate = args2.Remove("--gate");
string? seedOverride = TakeOption("--seed");
string? tuningOverride = TakeOption("--tuning");

string? TakeOption(string flag)
{
    var i = args2.IndexOf(flag);
    if (i < 0 || i + 1 >= args2.Count) return null;
    var value = args2[i + 1];
    args2.RemoveRange(i, 2);
    return value;
}

var seedRoot = seedOverride ?? FindUp("data", "seed");
if (seedRoot is null || !Directory.Exists(seedRoot))
{
    Console.Error.WriteLine("could not locate data/seed; pass --seed <dir>");
    return 2;
}

var tuningDir = tuningOverride ?? FindUp("data", "tuning");
if (tuningDir is null)
{
    Console.Error.WriteLine("could not locate data/tuning; pass --tuning <dir>");
    return 2;
}

var roots = SeedImportRunner.Roots(seedRoot, explicitRoot: seedOverride is not null);
var files = SeedImportRunner.Files(roots);
if (files.Count == 0)
{
    Console.Error.WriteLine($"no *.json under {seedRoot} — nothing to measure");
    return 2;
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
    Console.Error.WriteLine($"{collected.Errors.Count} file(s) refused — fix them before measuring:");
    foreach (var e in collected.Errors)
        Console.Error.WriteLine($"  {e.SourcePath}: {e.EntryId} — {e.Reason} ({e.Detail})");
    return 2;
}

var targetsPath = FindTuningFile(tuningDir, "affix-metrics");
var targets = targetsPath is null
    ? AffixMetricsTargets.MeasureOnly
    : ParseTargets(File.ReadAllText(targetsPath));

var coverage = ContentMetrics.FamilyCoverageOf(collected.Content.Atoms, collected.Content.Affixes);
var fillRates = ContentMetrics.ContainerFillRatesOf(collected.Content.Containers, collected.Content.Affixes);
var findings = AffixMetricsGateEvaluator.Evaluate(coverage, fillRates, targets);

Console.WriteLine(
    $"{collected.Content.Atoms.Count} atom(s), {collected.Content.Containers.Count} container(s), " +
    $"{collected.Content.Affixes.Count} affix(es) — {coverage.Count} family row(s), " +
    $"{fillRates.Count} container(s) with a pool budget");
Console.WriteLine(
    $"targets: familyCoverageGates={targets.FamilyCoverageGates}, " +
    $"containerFillRateGates={targets.ContainerFillRateGates}" +
    (targetsPath is null ? " (no affix-metrics.v*.json found — measure-only default)" : $" ({Path.GetFileName(targetsPath)})"));

if (findings.Count == 0)
{
    Console.WriteLine("no findings");
    return 0;
}

foreach (var f in findings.OrderBy(f => f.Kind, StringComparer.Ordinal).ThenBy(f => f.Id, StringComparer.Ordinal))
    Console.WriteLine($"[{(f.Gates ? "GATE" : "info")}] {f.Kind} {f.Id}: {f.Detail}");

var gating = AffixMetricsGateEvaluator.AnyGatingFinding(findings);
Console.WriteLine($"{findings.Count} finding(s), {findings.Count(f => f.Gates)} gating");

return gate && gating ? 1 : 0;

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

// gk-core/data/tuning/<domain>.v{n}.json — the highest N wins, matching every other tuning loader's own
// "latest version on disk" convention (never hand-picking a version number here).
static string? FindTuningFile(string tuningDir, string domain)
{
    return Directory.EnumerateFiles(tuningDir, $"{domain}.v*.json")
        .OrderByDescending(p => VersionOf(p))
        .FirstOrDefault();

    static int VersionOf(string path)
    {
        var name = Path.GetFileNameWithoutExtension(path); // "affix-metrics.v1"
        var vIdx = name.LastIndexOf(".v", StringComparison.Ordinal);
        return vIdx >= 0 && int.TryParse(name[(vIdx + 2)..], out var v) ? v : 0;
    }
}

static AffixMetricsTargets ParseTargets(string json)
{
    var doc = JsonDocument.Parse(json);
    var root = doc.RootElement;
    var familyGates = root.TryGetProperty("familyCoverageGates", out var fg) && fg.GetBoolean();
    var containerGates = root.TryGetProperty("containerFillRateGates", out var cg) && cg.GetBoolean();
    return new AffixMetricsTargets(familyGates, containerGates);
}
