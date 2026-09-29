using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Unicode;
using FusionRpg.Core.Creatures.Generation;

namespace FusionRpg.Tools.CreatureCorpusDump;

/// <summary>
/// Canonical serialisation + content hash for `creature-seed` module 1 (spec-corpus-dump.md §3/§4).
/// Every render function here is a pure function of its input — no timestamp, no machine state —
/// so the same database produces byte-identical output on every run.
/// </summary>
public static class DumpWriter
{
    static readonly JsonWriterOptions WriterOptions = new()
    {
        Indented = true,
        SkipValidation = false,
        // Names are Chinese. The default encoder escapes every non-ASCII codepoint as \uXXXX,
        // which is valid JSON but makes a committed, diffable corpus unreadable and its diffs
        // meaningless — same choice CreatureCorpusEmit/Program.cs already makes.
        Encoder = JavaScriptEncoder.Create(UnicodeRanges.All)
    };

    public static readonly UTF8Encoding Utf8NoBom = new(encoderShouldEmitUTF8Identifier: false);

    // --- key ordering -------------------------------------------------------------------------
    // "keys sorted ordinal" (spec §3) is enforced mechanically here, not by hand-ordering each
    // WriteString call — a field added later in the wrong place in code still lands in the right
    // place in the file, because the sort runs at render time, not at authoring time.
    static JsonObject SortedObj(params (string Key, JsonNode? Value)[] fields)
    {
        var obj = new JsonObject();
        foreach (var f in fields.OrderBy(f => f.Key, StringComparer.Ordinal))
            obj[f.Key] = f.Value;
        return obj;
    }

    static JsonNode? Str(string? s) => s is null ? null : JsonValue.Create(s);
    static JsonNode? IntOrNull(int? i) => i is null ? null : JsonValue.Create(i.Value);
    // Magnitudes are long (overflow re-triage, 2026-09-18). JSON renders a long with the same digits
    // as an int, so the committed dump and its content hash are unchanged for every value that fits.
    static JsonNode? LongOrNull(long? i) => i is null ? null : JsonValue.Create(i.Value);
    static JsonNode? DblOrNull(double? d) => d is null ? null : JsonValue.Create(d.Value);

    // --- node builders --------------------------------------------------------------------------

    static JsonObject EnrichmentNode(DumpEnrichment e) => SortedObj(
        ("damageVsText", Str(e.DamageVsText)),
        ("description", Str(e.Description)),
        ("qualities", e.Qualities is null
            ? null
            : new JsonArray(e.Qualities.Select(q => (JsonNode?)JsonValue.Create(q)).ToArray())),
        ("source", JsonValue.Create(e.Source)),
        ("typeClass", Str(e.TypeClass)),
        ("unlockCondition", Str(e.UnlockCondition)),
        ("weaknessesText", Str(e.WeaknessesText)));

    static JsonObject AlmanacRowNode(DumpAlmanacRow r) => SortedObj(
        ("armor", LongOrNull(r.Armor)),
        ("armorMax", LongOrNull(r.ArmorMax)),
        ("attack", LongOrNull(r.Attack)),
        ("contractVersion", JsonValue.Create(r.ContractVersion)),
        ("cooldownSec", DblOrNull(r.CooldownSec)),
        ("costStatus", JsonValue.Create(r.CostStatus)),
        ("displayName", Str(r.DisplayName)),
        ("enrichment", r.Enrichment is null ? null : EnrichmentNode(r.Enrichment)),
        ("flavorInfo", Str(r.FlavorInfo)),
        ("flavorIntroduce", Str(r.FlavorIntroduce)),
        ("hp", LongOrNull(r.Hp)),
        ("rebuiltUtc", JsonValue.Create(r.RebuiltUtc)),
        ("side", JsonValue.Create(r.Side)),
        ("statsObserved", JsonValue.Create(r.StatsObserved)),
        ("sunCost", IntOrNull(r.SunCost)),
        ("typeId", JsonValue.Create(r.TypeId)),
        ("typeName", Str(r.TypeName)));

    static JsonObject BaselineNode(DumpSpawnBaseline b) => SortedObj(
        ("capturedUtc", JsonValue.Create(b.CapturedUtc)),
        ("side", JsonValue.Create(b.Side)),
        ("statsJson", JsonValue.Create(b.StatsJson)),
        ("typeId", JsonValue.Create(b.TypeId)));

    static JsonObject RecipeNode(DumpRecipe r) => SortedObj(
        ("parentA", JsonValue.Create(r.ParentA)),
        ("parentAName", Str(r.ParentAName)),
        ("parentB", JsonValue.Create(r.ParentB)),
        ("parentBName", Str(r.ParentBName)),
        ("result", JsonValue.Create(r.Result)),
        ("resultName", Str(r.ResultName)));

    static JsonObject ManifestNode(DumpManifest m) => SortedObj(
        ("baselineCount", JsonValue.Create(m.BaselineCount)),
        ("capturedUtc", JsonValue.Create(m.CapturedUtc)),
        ("contentHash", JsonValue.Create(m.ContentHash)),
        ("dumpFormatVersion", JsonValue.Create(m.DumpFormatVersion)),
        ("plantCount", JsonValue.Create(m.PlantCount)),
        ("recipeCount", JsonValue.Create(m.RecipeCount)),
        ("zombieCount", JsonValue.Create(m.ZombieCount)));

    // --- rendering ------------------------------------------------------------------------------

    /// <summary>Serialises one JSON node with the canonical writer options plus a trailing newline.</summary>
    static byte[] Render(JsonNode node) => Render(node, WriterOptions);

    static byte[] Render(JsonNode node, JsonWriterOptions options)
    {
        using var stream = new MemoryStream();
        using (var w = new Utf8JsonWriter(stream, options))
            node.WriteTo(w);
        stream.WriteByte((byte)'\n');
        return stream.ToArray();
    }

    public static byte[] RenderAlmanac(IReadOnlyList<DumpAlmanacRow> rows)
    {
        var arr = new JsonArray(rows.OrderBy(r => r.TypeId).Select(r => (JsonNode?)AlmanacRowNode(r)).ToArray());
        return Render(arr);
    }

    public static byte[] RenderSpawnBaselines(IReadOnlyList<DumpSpawnBaseline> rows)
    {
        var arr = new JsonArray(rows
            .OrderBy(r => r.Side, StringComparer.Ordinal).ThenBy(r => r.TypeId)
            .Select(r => (JsonNode?)BaselineNode(r)).ToArray());
        return Render(arr);
    }

    public static byte[] RenderRecipes(IReadOnlyList<DumpRecipe> rows)
    {
        var arr = new JsonArray(rows
            .OrderBy(r => r.ParentA).ThenBy(r => r.ParentB).ThenBy(r => r.Result)
            .Select(r => (JsonNode?)RecipeNode(r)).ToArray());
        return Render(arr);
    }

    public static byte[] RenderManifest(DumpManifest manifest) => Render(ManifestNode(manifest));

    /// <summary>SHA-256 over the four payload files' canonical bytes, in a fixed order. Excludes the manifest itself.</summary>
    public static string ComputeContentHash(byte[] plantAlmanac, byte[] zombieAlmanac, byte[] baselines, byte[] recipes)
    {
        using var sha = SHA256.Create();
        using var combined = new MemoryStream();
        combined.Write(plantAlmanac);
        combined.Write(zombieAlmanac);
        combined.Write(baselines);
        combined.Write(recipes);
        var hash = sha.ComputeHash(combined.ToArray());
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    /// <summary>Builds the full rendered tree (four payload files + manifest) from a payload and a capture stamp.</summary>
    public static DumpTree BuildTree(DumpPayload payload, string capturedUtc)
    {
        var plantBytes = RenderAlmanac(payload.PlantAlmanac);
        var zombieBytes = RenderAlmanac(payload.ZombieAlmanac);
        var baselineBytes = RenderSpawnBaselines(payload.SpawnBaselines);
        var recipeBytes = RenderRecipes(payload.Recipes);

        var hash = ComputeContentHash(plantBytes, zombieBytes, baselineBytes, recipeBytes);

        var manifest = new DumpManifest(
            DumpFormatVersion: DumpFormat.Version,
            CapturedUtc: capturedUtc,
            ContentHash: hash,
            PlantCount: payload.PlantAlmanac.Count,
            ZombieCount: payload.ZombieAlmanac.Count,
            BaselineCount: payload.SpawnBaselines.Count,
            RecipeCount: payload.Recipes.Count);

        return new DumpTree(
            ManifestBytes: RenderManifest(manifest),
            PlantAlmanacBytes: plantBytes,
            ZombieAlmanacBytes: zombieBytes,
            SpawnBaselineBytes: baselineBytes,
            RecipesBytes: recipeBytes,
            Manifest: manifest);
    }

    public static void WriteToDisk(string outputRoot, DumpTree tree)
    {
        var almanacDir = Path.Combine(outputRoot, "almanac");
        Directory.CreateDirectory(almanacDir);
        File.WriteAllBytes(Path.Combine(outputRoot, "_manifest.json"), tree.ManifestBytes);
        File.WriteAllBytes(Path.Combine(almanacDir, "plant.json"), tree.PlantAlmanacBytes);
        File.WriteAllBytes(Path.Combine(almanacDir, "zombie.json"), tree.ZombieAlmanacBytes);
        File.WriteAllBytes(Path.Combine(outputRoot, "spawn-baseline.json"), tree.SpawnBaselineBytes);
        File.WriteAllBytes(Path.Combine(outputRoot, "recipes.json"), tree.RecipesBytes);
    }

    /// <summary>True when every file on disk under <paramref name="outputRoot"/> byte-matches <paramref name="tree"/>.</summary>
    public static bool MatchesDisk(string outputRoot, DumpTree tree)
    {
        return FileMatches(Path.Combine(outputRoot, "_manifest.json"), tree.ManifestBytes)
            && FileMatches(Path.Combine(outputRoot, "almanac", "plant.json"), tree.PlantAlmanacBytes)
            && FileMatches(Path.Combine(outputRoot, "almanac", "zombie.json"), tree.ZombieAlmanacBytes)
            && FileMatches(Path.Combine(outputRoot, "spawn-baseline.json"), tree.SpawnBaselineBytes)
            && FileMatches(Path.Combine(outputRoot, "recipes.json"), tree.RecipesBytes);
    }

    static bool FileMatches(string path, byte[] expected)
        => File.Exists(path) && File.ReadAllBytes(path).AsSpan().SequenceEqual(expected);

    /// <summary>
    /// A DB-free self-consistency check: re-hashes the four payload files already on disk and
    /// compares against what <c>_manifest.json</c> declares. This is what CI runs instead of
    /// <see cref="MatchesDisk"/>'s full <c>--check</c> — decisions.md rules out a real game/Harmony
    /// (and therefore a populated <c>hot.sqlite</c>) in CI, so there is no live database to
    /// regenerate against there. This does not prove the committed dump still matches the game —
    /// only that nobody hand-edited or partially merged it since the last real run. Proving it
    /// matches the game is a local, owner-run step (spec-corpus-dump.md's own `--check`).
    /// </summary>
    public static (bool Ok, string Reason) VerifyCommittedTree(string outputRoot)
    {
        var manifestPath = Path.Combine(outputRoot, "_manifest.json");
        if (!File.Exists(manifestPath)) return (false, $"no _manifest.json under {outputRoot}");

        JsonNode? manifestNode;
        try { manifestNode = JsonNode.Parse(File.ReadAllText(manifestPath)); }
        catch (JsonException ex) { return (false, $"_manifest.json did not parse: {ex.Message}"); }
        if (manifestNode is not JsonObject manifestObj)
            return (false, "_manifest.json is not a JSON object");

        var declaredHash = (string?)manifestObj["contentHash"];
        if (string.IsNullOrEmpty(declaredHash)) return (false, "_manifest.json has no contentHash");

        var plantPath = Path.Combine(outputRoot, "almanac", "plant.json");
        var zombiePath = Path.Combine(outputRoot, "almanac", "zombie.json");
        var baselinePath = Path.Combine(outputRoot, "spawn-baseline.json");
        var recipesPath = Path.Combine(outputRoot, "recipes.json");
        foreach (var p in new[] { plantPath, zombiePath, baselinePath, recipesPath })
            if (!File.Exists(p)) return (false, $"missing payload file: {p}");

        var recomputed = ComputeContentHash(
            File.ReadAllBytes(plantPath), File.ReadAllBytes(zombiePath),
            File.ReadAllBytes(baselinePath), File.ReadAllBytes(recipesPath));

        if (!string.Equals(recomputed, declaredHash, StringComparison.Ordinal))
            return (false, $"hash mismatch: manifest declares {declaredHash}, files on disk hash to {recomputed}");

        int CountArray(string path)
        {
            var node = JsonNode.Parse(File.ReadAllText(path));
            return node is JsonArray arr ? arr.Count : -1;
        }

        var declaredPlant = (int?)manifestObj["plantCount"] ?? -1;
        var declaredZombie = (int?)manifestObj["zombieCount"] ?? -1;
        var declaredBaseline = (int?)manifestObj["baselineCount"] ?? -1;
        var declaredRecipe = (int?)manifestObj["recipeCount"] ?? -1;

        if (CountArray(plantPath) != declaredPlant) return (false, "plantCount does not match almanac/plant.json's array length");
        if (CountArray(zombiePath) != declaredZombie) return (false, "zombieCount does not match almanac/zombie.json's array length");
        if (CountArray(baselinePath) != declaredBaseline) return (false, "baselineCount does not match spawn-baseline.json's array length");
        if (CountArray(recipesPath) != declaredRecipe) return (false, "recipeCount does not match recipes.json's array length");

        return (true, $"hash {declaredHash} — plant={declaredPlant} zombie={declaredZombie} baselines={declaredBaseline} recipes={declaredRecipe}");
    }

    // --- type_base_stats: the game's own static table, committed so a generator never reads a DB ---
    // creature-seed R-CS1's own unnamed precondition: the measured stats live only in the local,
    // uncommitted dist/FusionRpg.Server/data/rpg-hot.sqlite, while gk-data/packs/fusion/data/generated/creatures/** is
    // committed and CI byte-compares it. A generator reading the live DB would make a committed
    // artifact depend on uncommitted local state. This is the same committed-capture pattern the
    // four payload files above already established, kept in its OWN file with its OWN hash — see
    // DumpTypeBaseStatsFile's doc comment for why it is not folded into the manifest hash.

    public const string TypeBaseStatsFileName = "type-base-stats.json";

    /// <summary>
    /// This one file's rows carry an embedded JSON document as a STRING (`statsJson`), so every
    /// quote inside it is escaped. The shared <see cref="WriterOptions"/> encoder renders those as
    /// <c>"</c>, which turns a 400 KB committed, diffable capture into noise; the relaxed
    /// encoder renders the standard <c>\"</c>. Same reason the shared options unescape CJK — this
    /// tree is read by people reviewing diffs, not only by parsers. Deterministic either way, and
    /// the choice is local to this file, never applied to the four payload files whose committed
    /// bytes (and hash) must not move.
    /// </summary>
    static readonly JsonWriterOptions TypeBaseStatsWriterOptions = new()
    {
        Indented = true,
        SkipValidation = false,
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    static JsonObject TypeBaseStatsNode(DumpTypeBaseStats r) => SortedObj(
        ("capturedUtc", JsonValue.Create(r.CapturedUtc)),
        ("side", JsonValue.Create(r.Side)),
        ("statsJson", JsonValue.Create(r.StatsJson)),
        ("typeId", JsonValue.Create(r.TypeId)),
        ("typeName", Str(r.TypeName)));

    /// <summary>The entries array alone, canonically ordered by (side ordinal, typeId) — the same
    /// order <c>RpgStore.ListTypeBaseStats</c> already returns, restated here so the rendering does
    /// not depend on the caller having preserved it.</summary>
    public static byte[] RenderTypeBaseStatsEntries(IReadOnlyList<DumpTypeBaseStats> rows)
    {
        var arr = new JsonArray(rows
            .OrderBy(r => r.Side, StringComparer.Ordinal).ThenBy(r => r.TypeId)
            .Select(r => (JsonNode?)TypeBaseStatsNode(r)).ToArray());
        return Render(arr, TypeBaseStatsWriterOptions);
    }

    /// <summary>SHA-256 over the canonical entries rendering. Excludes the envelope, exactly as
    /// <see cref="ComputeContentHash"/> excludes the manifest.</summary>
    public static string ComputeTypeBaseStatsHash(byte[] entries)
    {
        using var sha = SHA256.Create();
        return Convert.ToHexString(sha.ComputeHash(entries)).ToLowerInvariant();
    }

    /// <summary>
    /// Builds the full self-describing file. <paramref name="rows"/>' own <c>CapturedUtc</c> is the
    /// only source for the envelope stamp — the MAXIMUM over the rows, never wall-clock time, the
    /// same rule <c>CorpusReader.CapturedUtc</c> holds for the almanac tree. A sweep writes the
    /// stamp per row, so a partial re-capture is visible as a mixed set rather than hidden behind a
    /// fresh "now".
    /// </summary>
    public static DumpTypeBaseStatsFile BuildTypeBaseStatsFile(IReadOnlyList<DumpTypeBaseStats> rows)
    {
        var ordered = rows
            .OrderBy(r => r.Side, StringComparer.Ordinal).ThenBy(r => r.TypeId)
            .ToList();
        var entries = RenderTypeBaseStatsEntries(ordered);
        return new DumpTypeBaseStatsFile(
            DumpFormatVersion: DumpFormat.Version,
            CapturedUtc: ordered.Select(r => r.CapturedUtc).DefaultIfEmpty("").Max(StringComparer.Ordinal)!,
            ContentHash: ComputeTypeBaseStatsHash(entries),
            PlantCount: ordered.Count(r => r.Side == "plant"),
            ZombieCount: ordered.Count(r => r.Side == "zombie"),
            Entries: ordered);
    }

    public static byte[] RenderTypeBaseStatsFile(DumpTypeBaseStatsFile file)
    {
        var entriesNode = JsonNode.Parse(RenderTypeBaseStatsEntries(file.Entries))!;
        return Render(SortedObj(
            ("capturedUtc", JsonValue.Create(file.CapturedUtc)),
            ("contentHash", JsonValue.Create(file.ContentHash)),
            ("dumpFormatVersion", JsonValue.Create(file.DumpFormatVersion)),
            ("entries", entriesNode),
            ("plantCount", JsonValue.Create(file.PlantCount)),
            ("zombieCount", JsonValue.Create(file.ZombieCount))), TypeBaseStatsWriterOptions);
    }

    public static void WriteTypeBaseStats(string outputRoot, byte[] rendered)
    {
        Directory.CreateDirectory(outputRoot);
        File.WriteAllBytes(Path.Combine(outputRoot, TypeBaseStatsFileName), rendered);
    }

    public static bool TypeBaseStatsMatchesDisk(string outputRoot, byte[] rendered)
        => FileMatches(Path.Combine(outputRoot, TypeBaseStatsFileName), rendered);

    /// <summary>
    /// DB-free self-consistency for <c>type-base-stats.json</c>, the twin of
    /// <see cref="VerifyCommittedTree"/>: re-render the entries the file itself carries, re-hash
    /// them, and compare against the hash and counts the file declares. Proves nobody hand-edited
    /// or partially merged it; proving it still matches the GAME is the local, owner-run capture.
    /// Kept a separate entry point rather than folded into <see cref="VerifyCommittedTree"/> so a
    /// caller holding only the four-file tree (every existing test) is unaffected.
    /// </summary>
    public static (bool Ok, string Reason) VerifyCommittedTypeBaseStats(string outputRoot)
    {
        var path = Path.Combine(outputRoot, TypeBaseStatsFileName);
        if (!File.Exists(path)) return (false, $"no {TypeBaseStatsFileName} under {outputRoot}");

        JsonNode? node;
        try { node = JsonNode.Parse(File.ReadAllText(path)); }
        catch (JsonException ex) { return (false, $"{TypeBaseStatsFileName} did not parse: {ex.Message}"); }
        if (node is not JsonObject obj) return (false, $"{TypeBaseStatsFileName} is not a JSON object");

        var declaredHash = (string?)obj["contentHash"];
        if (string.IsNullOrEmpty(declaredHash)) return (false, $"{TypeBaseStatsFileName} has no contentHash");
        if (obj["entries"] is not JsonArray entriesArr)
            return (false, $"{TypeBaseStatsFileName} has no 'entries' array");

        var rows = new List<DumpTypeBaseStats>(entriesArr.Count);
        foreach (var e in entriesArr)
        {
            if (e is not JsonObject row) return (false, "an entry is not a JSON object");
            var side = (string?)row["side"];
            var statsJson = (string?)row["statsJson"];
            var capturedUtc = (string?)row["capturedUtc"];
            if (side is null || statsJson is null || capturedUtc is null || row["typeId"] is null)
                return (false, "an entry is missing one of side/typeId/statsJson/capturedUtc");
            rows.Add(new DumpTypeBaseStats(side, (int)row["typeId"]!, (string?)row["typeName"], statsJson, capturedUtc));
        }

        var recomputed = ComputeTypeBaseStatsHash(RenderTypeBaseStatsEntries(rows));
        if (!string.Equals(recomputed, declaredHash, StringComparison.Ordinal))
            return (false, $"hash mismatch: file declares {declaredHash}, its own entries hash to {recomputed}");

        var declaredPlant = (int?)obj["plantCount"] ?? -1;
        var declaredZombie = (int?)obj["zombieCount"] ?? -1;
        if (rows.Count(r => r.Side == "plant") != declaredPlant)
            return (false, "plantCount does not match the number of plant entries");
        if (rows.Count(r => r.Side == "zombie") != declaredZombie)
            return (false, "zombieCount does not match the number of zombie entries");
        if (rows.Select(r => (r.Side, r.TypeId)).Distinct().Count() != rows.Count)
            return (false, "(side, typeId) is not unique across entries");

        return (true, $"hash {declaredHash} — plant={declaredPlant} zombie={declaredZombie}");
    }
}

public sealed record DumpTree(
    byte[] ManifestBytes,
    byte[] PlantAlmanacBytes,
    byte[] ZombieAlmanacBytes,
    byte[] SpawnBaselineBytes,
    byte[] RecipesBytes,
    DumpManifest Manifest);
