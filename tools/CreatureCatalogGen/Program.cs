using FusionRpg.Core.Creatures;
using FusionRpg.Core.Creatures.Generation;
using FusionRpg.Data;

// Dev-time generator: captured types (via the DAL — no SQL here) → committed species roster.
// Usage: dotnet run --project gk-forge/tools/CreatureCatalogGen -- <server data dir> [output .cs path]
if (args.Length < 1)
{
    Console.Error.WriteLine("usage: CreatureCatalogGen <server data dir> [output .cs]");
    return 1;
}

var dataDir = Path.GetFullPath(args[0]);
var output = Path.GetFullPath(args.Length > 1
    ? args[1]
    : Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..",
        "src", "FusionRpg.Core", "Creatures", "CreatureSpeciesCatalog.Generated.cs"));

// RpgStore's static ctor builds a DerivedStatRegistry, which reads DerivedStatPolicy — and that
// policy throws unless Configure has run (tunables-ssot.md T5: no built-in defaults). Without this
// the tool cannot start at all, which is why the catalog had quietly stopped being regenerable.
// Tuning sits beside the data dir in a deployed layout, and at gk-core/data/tuning in the repo.
var tuningDir = new[]
    {
        Path.Combine(dataDir, "tuning"),
        Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "data", "tuning")
    }
    .Select(Path.GetFullPath)
    .FirstOrDefault(d => File.Exists(Path.Combine(d, "derived-stats.v2.json")));
if (tuningDir is null)
{
    Console.Error.WriteLine($"no tuning dir found (looked in {Path.Combine(dataDir, "tuning")} and data/tuning)");
    return 1;
}
FusionRpg.Core.Stats.Derived.DerivedStatPolicy.Configure(
    FusionRpg.Core.Stats.Derived.DerivedStatTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "derived-stats.v2.json"))));

var store = new RpgStore(dataDir);
store.Init();
// Deterministic tie order: (side, type, game) — `types` can carry the same (side, type) under
// multiple game ids and SQLite's duplicate order is unspecified; the generator dedupes by First().
var seeds = store.ListTypes()
    .OrderBy(t => t.Side, StringComparer.Ordinal)
    .ThenBy(t => t.Type)
    .ThenBy(t => t.Game, StringComparer.Ordinal)
    .Select(t => new CapturedTypeSeed(t.Side, t.Type, t.TypeName, t.DisplayName, t.HpBase ?? 0L))
    .ToList();
Console.WriteLine($"captured type rows: {seeds.Count} (zombie {seeds.Count(s => s.Side == "zombie")}, plant {seeds.Count(s => s.Side == "plant")})");

var species = CreatureSpeciesGenerator.Generate(seeds);
CreatureSpeciesCatalog.Validate(species);
File.WriteAllText(output, CreatureSpeciesGenerator.EmitCSharp(species));

Console.WriteLine($"species: {species.Count} " +
    $"(sunwoven {species.Count(s => s.BaseRarity == CreatureRarity.Sunwoven)}, " +
    $"heirloom {species.Count(s => s.BaseRarity == CreatureRarity.Heirloom)}, " +
    $"cultivated {species.Count(s => s.BaseRarity == CreatureRarity.Cultivated)}, " +
    $"chaff {species.Count(s => s.BaseRarity == CreatureRarity.Chaff)}; " +
    $"light {species.Count(s => s.ElementPrimary == FusionRpg.Core.Stats.Derived.ElementTypeId.Light)}, " +
    $"dark {species.Count(s => s.ElementPrimary == FusionRpg.Core.Stats.Derived.ElementTypeId.Dark)}, " +
    $"hypno {species.Count(s => s.DeployMode == CreatureDeployMode.HypnoAlly)}, " +
    $"captureOnly {species.Count(s => s.Acquisition == CreatureAcquisition.CaptureOnly)})");
Console.WriteLine($"wrote {output}");
return 0;
