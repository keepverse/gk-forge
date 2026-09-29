using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Unicode;
using FusionRpg.Core.Creatures;
using FusionRpg.Core.Creatures.Generation;
using FusionRpg.Data;

// Dev-time emitter: CreatureSpeciesCatalog (committed) + almanac_seed + recipes (captured, via the
// DAL — no SQL here) -> gk-data/packs/fusion/data/seed/creatures/*.json, committed. spec-creature-corpus-emit.md.
// Usage: dotnet run --project gk-forge/tools/CreatureCorpusEmit -- <server data dir> [output root]
if (args.Length < 1)
{
    Console.Error.WriteLine("usage: CreatureCorpusEmit <server data dir> [output root, default data/seed/creatures]");
    return 1;
}

var dataDir = Path.GetFullPath(args[0]);
var outputRoot = Path.GetFullPath(args.Length > 1
    ? args[1]
    : Path.Combine(AppContext.BaseDirectory, "..", "..", "..", "..", "..", "data", "seed", "creatures"));

// RpgStore's static ctor builds a DerivedStatRegistry, which reads DerivedStatPolicy — and that
// throws unless Configure has run first (tunables-ssot.md T5). Same fix CreatureCatalogGen needed
// 2026-08-31 after it was found unable to start at all.
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
// T4.7 step 2 / T4.8 (catalog-runtime) — this tool reads CreatureSpeciesCatalog.All directly (line 45),
// which now throws unless Configure has run. Behaviour-preserving: the same compiled roster it
// always walked.
FusionRpg.Core.Creatures.CreatureSpeciesCatalog.ConfigureFromCompiledDefault();

var store = new RpgStore(dataDir);
store.Init();

var species = CreatureSpeciesCatalog.All;

var almanacRows = new List<AlmanacSeedRow>();
foreach (var s in species)
{
    var a = store.GetAlmanacSeed(s.Side, s.GameTypeId);
    if (a is null) continue;
    almanacRows.Add(new AlmanacSeedRow(
        a.Side, a.TypeId, a.FlavorInfo, a.FlavorIntroduce, a.SunCost, a.CooldownSec, a.CostStatus,
        a.Hp, a.Attack, a.Armor, a.ArmorMax, a.StatsObserved));
}

var recipes = store.ListRecipes();

var entries = CreatureCorpusBuilder.Build(species, almanacRows, recipes);

// Partition key: side/rarity (spec §9 Q1, decided 2026-08-31) — rarity lives ONLY on the species
// catalog, never restated on the corpus entry itself (§2.1), so it is looked up here for grouping
// only and never written into the emitted JSON.
var rarityBySpeciesId = species.ToDictionary(s => s.SpeciesId, s => s.BaseRarity.ToId());

var byPartition = entries
    .GroupBy(e => (e.Side, Rarity: rarityBySpeciesId[e.Id]))
    .OrderBy(g => g.Key.Side, StringComparer.Ordinal)
    .ThenBy(g => g.Key.Rarity, StringComparer.Ordinal);

var written = 0;
foreach (var group in byPartition)
{
    var partition = $"{group.Key.Side}/{group.Key.Rarity}";
    var dir = Path.Combine(outputRoot, "creature", group.Key.Side);
    Directory.CreateDirectory(dir);
    var path = Path.Combine(dir, $"{group.Key.Rarity}.json");

    var sortedEntries = group.OrderBy(e => e.Id, StringComparer.Ordinal).ToList();
    File.WriteAllText(path, RenderSeedFile(partition, sortedEntries), new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
    written++;
}

Console.WriteLine($"species: {species.Count}, almanac rows matched: {almanacRows.Count}, " +
    $"recipe rows: {recipes.Count}, entries: {entries.Count}, partitions written: {written}");
Console.WriteLine($"output root: {outputRoot}");
return 0;

// Deterministic, hand-controlled key order — never a default JsonSerializer pass over the record,
// whose property order is an implementation detail rather than a contract (spec §2.5: same inputs
// must produce byte-identical bytes, forever). No timestamp anywhere in the payload.
static string RenderSeedFile(string partition, IReadOnlyList<CreatureCorpusEntry> entries)
{
    using var stream = new MemoryStream();
    // Names are Chinese (spec-family-extract.md §2.2a) — the default encoder escapes every
    // non-ASCII codepoint as \uXXXX, which is valid JSON but makes a committed, diffable corpus
    // unreadable and its diffs meaningless. UnicodeRanges.All keeps names literal without weakening
    // determinism: the bytes are still a pure function of the input, just readable ones.
    var opts = new JsonWriterOptions
    {
        Indented = true,
        SkipValidation = false,
        Encoder = JavaScriptEncoder.Create(UnicodeRanges.All)
    };
    using (var w = new Utf8JsonWriter(stream, opts))
    {
        w.WriteStartObject();
        w.WriteString("kind", "creature");
        w.WriteStartObject("_meta");
        w.WriteString("partition", partition);
        w.WriteEndObject();
        w.WriteStartArray("entries");
        foreach (var e in entries)
        {
            w.WriteStartObject();
            w.WriteString("id", e.Id);
            w.WriteString("nameKey", e.NameKey);
            w.WriteString("name", e.Name);
            w.WriteNumber("gameTypeId", e.GameTypeId);
            w.WriteString("side", e.Side);
            WriteNullableString(w, "flavorInfo", e.FlavorInfo);
            WriteNullableString(w, "flavorIntroduce", e.FlavorIntroduce);
            WriteNullableLong(w, "sunCost", e.SunCost);
            WriteNullableDouble(w, "cooldownSec", e.CooldownSec);
            WriteNullableLong(w, "hp", e.Hp);
            WriteNullableLong(w, "attack", e.Attack);
            WriteNullableLong(w, "armor", e.Armor);
            WriteNullableLong(w, "armorMax", e.ArmorMax);
            w.WriteStartObject("coverage");
            w.WriteString("cost", e.Coverage.Cost);
            w.WriteString("stats", e.Coverage.Stats);
            w.WriteString("flavor", e.Coverage.Flavor);
            w.WriteEndObject();
            w.WriteStartObject("lineage");
            w.WriteStartArray("parents");
            foreach (var p in e.Lineage.Parents) w.WriteNumberValue(p);
            w.WriteEndArray();
            w.WriteStartArray("children");
            foreach (var c in e.Lineage.Children) w.WriteNumberValue(c);
            w.WriteEndArray();
            w.WriteEndObject();
            w.WriteEndObject();
        }
        w.WriteEndArray();
        w.WriteEndObject();
    }
    return Encoding.UTF8.GetString(stream.ToArray());
}

static void WriteNullableString(Utf8JsonWriter w, string name, string? value)
{
    if (value is null) w.WriteNull(name); else w.WriteString(name, value);
}

static void WriteNullableLong(Utf8JsonWriter w, string name, long? value)
{
    if (value is null) w.WriteNull(name); else w.WriteNumber(name, value.Value);
}

static void WriteNullableDouble(Utf8JsonWriter w, string name, double? value)
{
    if (value is null) w.WriteNull(name); else w.WriteNumber(name, value.Value);
}
