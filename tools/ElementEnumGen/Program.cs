using FusionRpg.Core.Effects.Atoms;
using FusionRpg.Tools.ElementEnumGen;

// E23 content-codegen checks (completeness-audit.md B2): do the hand-written pieces that mirror
// gk-data/packs/fusion/data/seed/** still agree with it?
//
// Usage: dotnet run --project gk-forge/tools/ElementEnumGen -- [--check|--emit <path>|--trait-check|--trait-emit <path>] [seed root]
//        --check        (default) ElementTypeId + its three companion switches vs roster.json
//        --emit <path>  write the generated ActorElementTypes source instead of checking
//        --trait-check  TraitAtomSource.Shipped() vs the migrated trait containers
//        --trait-emit   write the generated Shipped() body instead of checking
//        --effect-emit <path>   write EffectAtomCatalog.Generated.cs from data/seed/atoms/fx-*.json
//        --effect-check <path>  fail (exit 1) when the checked-in catalog is stale vs the seed
//
// Exit codes: 0 clean, 1 mismatch found, 2 could not start.

// The shipped fx-*.json atom seed files, named explicitly (E43, spec-family-expand.md §3.3) — the
// AllDirectories glob this replaces enforced nothing, it just happened to match only these three.
var ShippedFxFiles = new[] { "fx-board.json", "fx-core.json", "fx-status.json" };

var mode = "check";
string? emitPath = null;
var positional = new List<string>();

for (var i = 0; i < args.Length; i++)
{
    if (args[i] == "--check") { mode = "check"; continue; }
    if (args[i] == "--trait-check") { mode = "trait-check"; continue; }
    if (args[i] == "--emit" && i + 1 < args.Length) { mode = "emit"; emitPath = args[++i]; continue; }
    if (args[i] == "--trait-emit" && i + 1 < args.Length) { mode = "trait-emit"; emitPath = args[++i]; continue; }
    if (args[i] == "--effect-emit" && i + 1 < args.Length) { mode = "effect-emit"; emitPath = args[++i]; continue; }
    if (args[i] == "--effect-check" && i + 1 < args.Length) { mode = "effect-check"; emitPath = args[++i]; continue; }
    positional.Add(args[i]);
}

var seedRoot = positional.Count > 0 ? Path.GetFullPath(positional[0]) : FindUp("data", "seed");
if (seedRoot is null || !Directory.Exists(seedRoot))
{
    Console.Error.WriteLine("could not locate data/seed; pass the seed root explicitly");
    return 2;
}

if (mode is "effect-emit" or "effect-check")
{
    var gen = EffectCatalogGen.GenerateFromSeed(seedRoot, ShippedFxFiles);
    if (gen.Code != 0)
    {
        Console.Error.WriteLine(gen.Message);
        return gen.Code;
    }

    if (mode == "effect-check")
    {
        var checkedIn = File.Exists(emitPath!) ? File.ReadAllText(emitPath!) : "";
        if (!EffectCatalogGen.Matches(gen.Source!, checkedIn))
        {
            Console.Error.WriteLine($"{emitPath} is stale vs data/seed/atoms — run --effect-emit and commit the diff");
            return 1;
        }
        Console.WriteLine($"{emitPath} matches data/seed/atoms");
        return 0;
    }

    File.WriteAllText(emitPath!, gen.Source!);
    Console.WriteLine($"wrote {emitPath} ({gen.Message})");
    return 0;
}

if (mode is "trait-check" or "trait-emit")
{
    var files = new[] { "atoms", "containers" }
        .Select(d => Path.Combine(seedRoot, d))
        .Where(Directory.Exists)
        .SelectMany(d => Directory.GetFiles(d, "*.json", SearchOption.AllDirectories))
        .OrderBy(f => f, StringComparer.Ordinal)
        .Select(f => (f, File.ReadAllText(f)))
        .ToArray();

    var collected = AtomSeedFile.Collect(files);
    if (!collected.IsOk)
    {
        Console.Error.WriteLine("data/seed/{atoms,containers} did not parse:");
        foreach (var e in collected.Errors) Console.Error.WriteLine("  " + e);
        return 2;
    }

    if (mode == "trait-emit")
    {
        var source = TraitSourceCheck.GenerateSource(collected.Content);
        File.WriteAllText(emitPath!, source);
        Console.WriteLine($"wrote {emitPath}");
        return 0;
    }

    var traitReport = TraitSourceCheck.Run(collected.Content);
    if (traitReport.IsOk)
    {
        Console.WriteLine("TraitAtomSource.Shipped() agrees with the migrated trait containers.");
        return 0;
    }

    Console.Error.WriteLine($"{traitReport.Mismatches.Count} disagreement(s):");
    foreach (var m in traitReport.Mismatches) Console.Error.WriteLine("  " + m);
    return 1;
}

var rosterFile = Path.Combine(seedRoot, "elements", "roster.json");
if (!File.Exists(rosterFile))
{
    Console.Error.WriteLine($"missing {rosterFile}");
    return 2;
}

var rosterCollected = AtomSeedFile.Collect(new[] { (rosterFile, File.ReadAllText(rosterFile)) });
if (!rosterCollected.IsOk)
{
    Console.Error.WriteLine($"{rosterFile} did not parse:");
    foreach (var e in rosterCollected.Errors) Console.Error.WriteLine("  " + e);
    return 2;
}

if (mode == "emit")
{
    var source = ElementEnumCheck.GenerateSource(rosterCollected.Content.Elements);
    File.WriteAllText(emitPath!, source);
    Console.WriteLine($"wrote {emitPath} ({rosterCollected.Content.Elements.Count} element(s))");
    return 0;
}

var report = ElementEnumCheck.Run(rosterCollected.Content.Elements);
if (report.IsOk)
{
    Console.WriteLine($"ElementTypeId and its three companion switches agree with the roster " +
                       $"({rosterCollected.Content.Elements.Count} element(s)).");
    return 0;
}

Console.Error.WriteLine($"{report.Mismatches.Count} disagreement(s):");
foreach (var m in report.Mismatches) Console.Error.WriteLine("  " + m);
return 1;

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
