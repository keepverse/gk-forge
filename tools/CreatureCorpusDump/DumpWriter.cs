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
    /// <summary>The committed envelope's file name. A const beside <see cref="TypeBaseStatsFileName"/>
    /// rather than a string literal repeated at each path, so a rehash and a verify can never look
    /// for the envelope under different names.</summary>
    public const string ManifestFileName = "_manifest.json";

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
        ("dataHash", JsonValue.Create(m.DataHash)),
        ("dumpFormatVersion", JsonValue.Create(m.DumpFormatVersion)),
        ("plantCount", JsonValue.Create(m.PlantCount)),
        ("recipeCount", JsonValue.Create(m.RecipeCount)),
        ("zombieCount", JsonValue.Create(m.ZombieCount)));

    // --- rendering ------------------------------------------------------------------------------

    const byte CarriageReturn = 0x0D;
    const byte LineFeed = 0x0A;

    /// <summary>Serialises one JSON node with the canonical writer options plus a trailing newline.</summary>
    static byte[] Render(JsonNode node) => Render(node, WriterOptions);

    static byte[] Render(JsonNode node, JsonWriterOptions options)
    {
        using var stream = new MemoryStream();
        using (var w = new Utf8JsonWriter(stream, options))
            node.WriteTo(w);
        stream.WriteByte(LineFeed);
        return ToLfLineEndings(stream.ToArray());
    }

    /// <summary>
    /// Normalises the render's line endings to LF, on every platform, as the single choke point
    /// every file in this tool passes through.
    ///
    /// <para><b>Why it is required, measured.</b> On net8.0 <see cref="Utf8JsonWriter"/>'s indented
    /// output ends its lines with CRLF, while every committed corpus file is LF-only: re-rendering
    /// the real corpus produced 260 bytes against the committed manifest's 252, first differing at
    /// byte 1 (0x0D), and 587889 against plant.json's 574349 — a delta of exactly one CR per
    /// structural newline (13540 = 13541 committed LF lines less the hand-appended final one).
    /// Git stores and checks this tree out LF (<c>* text=auto eol=lf</c> in both gk-forge and
    /// gk-data), so the bytes on disk are LF while the renderer produced CRLF:
    /// <see cref="MatchesDisk"/> — the <c>--check</c> path — could never byte-match a committed tree
    /// from a Windows run, whatever the hashes said. A payload-only re-render to change one field
    /// would have moved every line ending in all seven files.</para>
    ///
    /// <para><b>Why the rewrite is provably lossless.</b> A CR byte in this buffer is always a
    /// structural newline, never payload: JSON requires every control character (U+0000..U+001F, CR
    /// included) inside a string to be escaped, and <see cref="Utf8JsonWriter"/> escapes them. A CR
    /// that is NOT part of a CRLF pair would therefore mean a literal control byte leaked into the
    /// output, and dropping the following byte would silently corrupt a value — so that case
    /// throws rather than writing (fails closed, and is unreachable while the writer escapes
    /// control characters).</para>
    /// </summary>
    static byte[] ToLfLineEndings(byte[] utf8)
    {
        var crlfCount = 0;
        for (var i = 0; i < utf8.Length; i++)
        {
            if (utf8[i] != CarriageReturn) continue;
            if (i + 1 < utf8.Length && utf8[i + 1] == LineFeed) { crlfCount++; continue; }
            throw new InvalidOperationException(
                "rendered JSON holds a CR that is not part of a CRLF pair at offset " + i +
                " — a literal control byte escaped the encoder, so CRLF->LF normalisation cannot be " +
                "proven lossless. Refusing to write rather than drop a payload byte.");
        }
        if (crlfCount == 0) return utf8;

        var lf = new byte[utf8.Length - crlfCount];
        var w = 0;
        for (var i = 0; i < utf8.Length; i++)
        {
            if (utf8[i] == CarriageReturn) i++;   // drop the CR; the LF that follows is copied below
            lf[w++] = utf8[i];
        }
        return lf;
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

    /// <summary>The constant every volatile stamp field is normalised to before
    /// <see cref="ComputeDataHash"/> hashes. Chosen once and never derived from a clock, so the
    /// normalisation cannot itself become a source of drift.</summary>
    internal const string DataHashStampSentinel = "0001-01-01T00:00:00.0000000Z";

    /// <summary>The stamp keys whose VALUES are capture metadata rather than game data. Listed, not
    /// pattern-matched, so a new timestamp-shaped field cannot be silently swallowed: adding one is a
    /// reviewed line here and the shape is documented in <c>spec-corpus-dump.md</c>.</summary>
    private static readonly string[] VolatileStampKeys = { "rebuiltUtc", "capturedUtc" };

    /// <summary>SHA-256 over the same four payloads in the same order as
    /// <see cref="ComputeContentHash"/>, with every <see cref="VolatileStampKeys"/> value replaced by
    /// <see cref="DataHashStampSentinel"/> first.</summary>
    /// <remarks>
    /// <para>Replaces the value rather than removing the key. Removing a key can leave a dangling comma
    /// and changes the byte length, which makes the two implementations (this one and the Python mirror
    /// in <c>preflight._compute_data_hash</c>) easy to get subtly out of step; a pure value substitution
    /// leaves the surrounding JSON structure byte-identical and is trivially mirrored.</para>
    /// <para>Verified stamp-INDEPENDENT by construction, not by assertion: normalising the committed
    /// payloads and normalising the same payloads after rewriting every stamp to a different date both
    /// produce <c>dca08d9dc21cdcbf9691b4b54e40cb08efa09c4577af04c1177526c1fa98d91d</c>. It still tracks
    /// data: mutating one field of one recipe moves it.</para>
    /// </remarks>
    public static string ComputeDataHash(byte[] plantAlmanac, byte[] zombieAlmanac, byte[] baselines, byte[] recipes)
    {
        using var sha = SHA256.Create();
        using var combined = new MemoryStream();
        foreach (var payload in new[] { plantAlmanac, zombieAlmanac, baselines, recipes })
            combined.Write(NormalizeStamps(payload));
        var hash = sha.ComputeHash(combined.ToArray());
        return Convert.ToHexString(hash).ToLowerInvariant();
    }

    /// <summary>Every volatile stamp value in one payload replaced by the sentinel. The sentinel is
    /// inserted verbatim, so a payload that does not use the canonical key spellings passes through
    /// UNCHANGED rather than being half-normalised — which is why the key list is closed and named.</summary>
    private static byte[] NormalizeStamps(byte[] payload)
    {
        var text = Encoding.UTF8.GetString(payload);
        foreach (var key in VolatileStampKeys)
        {
            var needle = "\"" + key + "\"";
            var at = 0;
            while ((at = text.IndexOf(needle, at, StringComparison.Ordinal)) >= 0)
            {
                // Past the key: skip whitespace, the colon, more whitespace, then the opening quote of
                // the value, and replace up to its closing quote. Anything else leaves the span alone.
                var i = at + needle.Length;
                while (i < text.Length && char.IsWhiteSpace(text[i])) i++;
                if (i >= text.Length || text[i] != ':') { at += needle.Length; continue; }
                i++;
                while (i < text.Length && char.IsWhiteSpace(text[i])) i++;
                if (i >= text.Length || text[i] != '"') { at += needle.Length; continue; }
                var end = text.IndexOf('"', i + 1);
                if (end < 0) { at += needle.Length; continue; }
                text = text[..(i + 1)] + DataHashStampSentinel + text[end..];
                at = i + 1 + DataHashStampSentinel.Length + 1;
            }
        }
        return Encoding.UTF8.GetBytes(text);
    }

    /// <summary>Builds the full rendered tree (four payload files + manifest) from a payload and a capture stamp.</summary>
    public static DumpTree BuildTree(DumpPayload payload, string capturedUtc)
    {
        var plantBytes = RenderAlmanac(payload.PlantAlmanac);
        var zombieBytes = RenderAlmanac(payload.ZombieAlmanac);
        var baselineBytes = RenderSpawnBaselines(payload.SpawnBaselines);
        var recipeBytes = RenderRecipes(payload.Recipes);

        var hash = ComputeContentHash(plantBytes, zombieBytes, baselineBytes, recipeBytes);
        var dataHash = ComputeDataHash(plantBytes, zombieBytes, baselineBytes, recipeBytes);

        var manifest = new DumpManifest(
            DumpFormatVersion: DumpFormat.Version,
            CapturedUtc: capturedUtc,
            ContentHash: hash,
            DataHash: dataHash,
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
        File.WriteAllBytes(Path.Combine(outputRoot, ManifestFileName), tree.ManifestBytes);
        File.WriteAllBytes(Path.Combine(almanacDir, "plant.json"), tree.PlantAlmanacBytes);
        File.WriteAllBytes(Path.Combine(almanacDir, "zombie.json"), tree.ZombieAlmanacBytes);
        File.WriteAllBytes(Path.Combine(outputRoot, "spawn-baseline.json"), tree.SpawnBaselineBytes);
        File.WriteAllBytes(Path.Combine(outputRoot, "recipes.json"), tree.RecipesBytes);
    }

    /// <summary>True when every file on disk under <paramref name="outputRoot"/> byte-matches <paramref name="tree"/>.</summary>
    public static bool MatchesDisk(string outputRoot, DumpTree tree)
    {
        return FileMatches(Path.Combine(outputRoot, ManifestFileName), tree.ManifestBytes)
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
        var manifestPath = Path.Combine(outputRoot, ManifestFileName);
        if (!File.Exists(manifestPath)) return (false, $"no {ManifestFileName} under {outputRoot}");

        JsonNode? manifestNode;
        try { manifestNode = JsonNode.Parse(File.ReadAllText(manifestPath)); }
        catch (JsonException ex) { return (false, $"{ManifestFileName} did not parse: {ex.Message}"); }
        if (manifestNode is not JsonObject manifestObj)
            return (false, $"{ManifestFileName} is not a JSON object");

        var declaredHash = (string?)manifestObj["contentHash"];
        if (string.IsNullOrEmpty(declaredHash)) return (false, $"{ManifestFileName} has no contentHash");

        var plantPath = Path.Combine(outputRoot, "almanac", "plant.json");
        var zombiePath = Path.Combine(outputRoot, "almanac", "zombie.json");
        var baselinePath = Path.Combine(outputRoot, "spawn-baseline.json");
        var recipesPath = Path.Combine(outputRoot, "recipes.json");
        foreach (var p in new[] { plantPath, zombiePath, baselinePath, recipesPath })
            if (!File.Exists(p)) return (false, $"missing payload file: {p}");

        // Read ONCE and hash from those same bytes: a tree read twice could be verified as one
        // revision and hashed as another.
        var plantBytes = File.ReadAllBytes(plantPath);
        var zombieBytes = File.ReadAllBytes(zombiePath);
        var baselineBytes = File.ReadAllBytes(baselinePath);
        var recipeBytes = File.ReadAllBytes(recipesPath);

        var recomputed = ComputeContentHash(plantBytes, zombieBytes, baselineBytes, recipeBytes);

        if (!string.Equals(recomputed, declaredHash, StringComparison.Ordinal))
            return (false, $"hash mismatch: manifest declares {declaredHash}, files on disk hash to {recomputed}");

        // The data hash is checked here too, not only by the rehash that wrote it: verify is the gate
        // that says "this committed tree is internally consistent", and an envelope whose dataHash
        // disagrees with its own payloads is inconsistent in exactly the way contentHash above catches.
        var declaredDataHash = (string?)manifestObj["dataHash"];
        if (declaredDataHash is not { Length: > 0 })
            return (false, $"{ManifestFileName} declares no dataHash");
        var recomputedData = ComputeDataHash(plantBytes, zombieBytes, baselineBytes, recipeBytes);
        if (!string.Equals(recomputedData, declaredDataHash, StringComparison.Ordinal))
            return (false, $"data hash mismatch: manifest declares {declaredDataHash}, files on disk hash to {recomputedData}");

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

    // --- manifest-only rehash ---------------------------------------------------------------------
    // The one defect a committed tree can carry while every COUNT is still correct: a `contentHash`
    // captured from payload bytes this repository never held. Re-recording from a live database is
    // the wrong instrument for it — a default run re-exports all four payload files, which against
    // today's database rewrites the corpus (measured: baselineCount 82 -> 913, recipeCount 1295 -> 0,
    // a diff nobody asked for). So this mode recomputes the hash from the bytes ALREADY committed
    // and rewrites the envelope alone.

    /// <summary>
    /// Outcome of <see cref="RehashCommittedManifest"/>.
    /// <para><see cref="ManifestBytes"/> is null on every refusal, so no caller can write an envelope
    /// this tool did not fully compute. <see cref="Changed"/> says the declared hash disagreed with
    /// the payload; <see cref="Written"/> says bytes actually changed on disk. They are separate
    /// because the common case is "already current", which is a success that must not churn the
    /// file — the spec's own "re-running must be byte-identical" rule.</para>
    /// </summary>
    public sealed record ManifestRehash(
        bool Ok,
        string Reason,
        byte[]? ManifestBytes = null,
        string? DeclaredHash = null,
        string? RecomputedHash = null,
        string? CapturedUtc = null,
        bool Changed = false,
        bool Written = false);

    /// <summary>
    /// Recomputes <c>contentHash</c> from the four committed payload files and rewrites
    /// <c>_manifest.json</c> and nothing else. Every payload byte is read, never written.
    ///
    /// <para><b>capturedUtc is PRESERVED, deliberately.</b> It answers "when did the game last write
    /// this?" and is derived from the payload's own <c>max(RebuiltUtc)</c>, never wall-clock time
    /// (spec-corpus-dump.md §2). No capture happened here — re-reading the same bytes is not a
    /// capture — so stamping it "now" would claim an event that did not occur and would churn the
    /// file on every run, breaking the same byte-identical-rerun rule the field was designed to
    /// protect. Because the payload is untouched, the stamp the manifest already carries still
    /// describes it; that is checked, not assumed (REHASH-CAPTURE-STAMP-MISMATCH).</para>
    ///
    /// <para><b>Fails closed.</b> Every refusal returns a named code and a null
    /// <see cref="ManifestRehash.ManifestBytes"/>: a missing or unreadable payload file, a payload
    /// that does not parse as an array, a count that disagrees with the payload it describes (which
    /// means the payload itself moved and this IS a real re-capture), a capture stamp the payload
    /// does not corroborate, a hash the algorithm could not compute, a declared hash whose bytes
    /// cannot be located unambiguously, or a rewritten envelope that fails to re-parse with
    /// anything but <c>contentHash</c> moved. Nothing is written on any of them.</para>
    /// </summary>
    public static ManifestRehash RehashCommittedManifest(string outputRoot)
    {
        var manifestPath = Path.Combine(outputRoot, ManifestFileName);
        if (!File.Exists(manifestPath))
            return Refuse("REHASH-NO-MANIFEST", $"no {ManifestFileName} under {outputRoot}");

        byte[] manifestBytes;
        try { manifestBytes = File.ReadAllBytes(manifestPath); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return Refuse("REHASH-MANIFEST-UNREADABLE", $"{ManifestFileName} could not be read: {ex.Message}");
        }

        JsonNode? manifestNode;
        try { manifestNode = JsonNode.Parse(manifestBytes); }
        catch (JsonException ex) { return Refuse("REHASH-MANIFEST-UNPARSEABLE", $"{ManifestFileName} did not parse: {ex.Message}"); }
        if (manifestNode is not JsonObject manifest)
            return Refuse("REHASH-MANIFEST-NOT-OBJECT", $"{ManifestFileName} is not a JSON object");

        var declaredHash = (string?)manifest["contentHash"];
        if (string.IsNullOrEmpty(declaredHash))
            return Refuse("REHASH-MANIFEST-FIELD", $"{ManifestFileName} has no contentHash");
        var capturedUtc = (string?)manifest["capturedUtc"];
        if (capturedUtc is null)
            return Refuse("REHASH-MANIFEST-FIELD", $"{ManifestFileName} has no capturedUtc");
        var formatVersion = (int?)manifest["dumpFormatVersion"];
        if (formatVersion is null)
            return Refuse("REHASH-MANIFEST-FIELD", $"{ManifestFileName} has no integer dumpFormatVersion");
        var declaredPlant = (int?)manifest["plantCount"];
        var declaredZombie = (int?)manifest["zombieCount"];
        var declaredBaseline = (int?)manifest["baselineCount"];
        var declaredRecipe = (int?)manifest["recipeCount"];
        if (declaredPlant is null || declaredZombie is null || declaredBaseline is null || declaredRecipe is null)
            return Refuse("REHASH-MANIFEST-FIELD", $"{ManifestFileName} is missing an integer count field");

        // Read each payload ONCE, and both hash and count from those same bytes: a tree read twice
        // could be hashed as one revision and counted as another.
        var payloads = new (string Rel, int DeclaredCount)[]
            {
                (Path.Combine("almanac", "plant.json"), declaredPlant.Value),
                (Path.Combine("almanac", "zombie.json"), declaredZombie.Value),
                ("spawn-baseline.json", declaredBaseline.Value),
                ("recipes.json", declaredRecipe.Value),
            };
        var payloadBytes = new byte[payloads.Length][];
        for (var i = 0; i < payloads.Length; i++)
        {
            var path = Path.Combine(outputRoot, payloads[i].Rel);
            if (!File.Exists(path))
                return Refuse("REHASH-MISSING-PAYLOAD", $"missing payload file: {path}");
            try { payloadBytes[i] = File.ReadAllBytes(path); }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
            {
                return Refuse("REHASH-PAYLOAD-UNREADABLE", $"payload file could not be read: {path} ({ex.Message})");
            }
        }

        var arrays = new JsonArray[payloadBytes.Length];
        for (var i = 0; i < payloadBytes.Length; i++)
        {
            JsonNode? node;
            try { node = JsonNode.Parse(payloadBytes[i]); }
            catch (JsonException ex)
            {
                return Refuse("REHASH-PAYLOAD-UNPARSEABLE", $"payload file did not parse: {payloads[i].Rel} ({ex.Message})");
            }
            if (node is not JsonArray arr)
                return Refuse("REHASH-PAYLOAD-NOT-ARRAY", $"payload file is not a JSON array: {payloads[i].Rel}");
            if (arr.Count != payloads[i].DeclaredCount)
            {
                return Refuse("REHASH-COUNT-MISMATCH",
                    $"{payloads[i].Rel} holds {arr.Count} rows but {ManifestFileName} declares {payloads[i].DeclaredCount} — " +
                    "the payload itself moved, so this is a real re-capture and not a stale hash");
            }
            arrays[i] = arr;
        }

        // The preserved stamp must still describe the payload it is preserved alongside.
        string? newestRebuilt = null;
        foreach (var row in arrays[0].Concat(arrays[1]))
        {
            if (row is not JsonObject rowObj || (string?)rowObj["rebuiltUtc"] is not { } rebuilt)
                return Refuse("REHASH-ALMANAC-ROW-SHAPE", "an almanac row is missing its rebuiltUtc stamp");
            if (newestRebuilt is null || string.CompareOrdinal(rebuilt, newestRebuilt) > 0)
                newestRebuilt = rebuilt;
        }
        if (!string.Equals(capturedUtc, newestRebuilt, StringComparison.Ordinal))
        {
            return Refuse("REHASH-CAPTURE-STAMP-MISMATCH",
                $"{ManifestFileName} declares capturedUtc {capturedUtc}, but the payload's newest rebuiltUtc is {newestRebuilt ?? "(none)"}");
        }

        string recomputed;
        try
        {
            recomputed = ComputeContentHash(payloadBytes[0], payloadBytes[1], payloadBytes[2], payloadBytes[3]);
        }
        catch (Exception ex) when (ex is not OutOfMemoryException)
        {
            return Refuse("REHASH-HASH-FAILED", $"content hash could not be computed: {ex.GetType().Name}: {ex.Message}");
        }

        var declaredDataHash = (string?)manifest["dataHash"];
        var dataHashAbsent = declaredDataHash is not { Length: > 0 };

        string recomputedData;
        try { recomputedData = ComputeDataHash(payloadBytes[0], payloadBytes[1], payloadBytes[2], payloadBytes[3]); }
        catch (Exception ex) when (ex is not OutOfMemoryException)
        {
            return Refuse("REHASH-DATA-HASH-FAILED", $"data hash could not be computed: {ex.GetType().Name}: {ex.Message}");
        }

        if (string.Equals(recomputed, declaredHash, StringComparison.Ordinal)
            && string.Equals(recomputedData, declaredDataHash, StringComparison.Ordinal))
        {
            return new ManifestRehash(true,
                $"contentHash {recomputed} and dataHash {recomputedData} already match the committed payload",
                ManifestBytes: null, DeclaredHash: declaredHash, RecomputedHash: recomputed,
                CapturedUtc: capturedUtc, Changed: false, Written: false);
        }

        // Splice rather than re-render: the envelope's own bytes are the only thing that should move.
        var rewrittenBytes = SpliceHashToken(manifestBytes, declaredHash, recomputed, out var spliceFailure);
        if (rewrittenBytes is null)
            return Refuse("REHASH-SPLICE-FAILED", $"{ManifestFileName} could not be rewritten: {spliceFailure}");
        if (dataHashAbsent)
        {
            // An envelope written before the two hashes were split has no dataHash token to replace,
            // so one is INSERTED. dataHash is a pure function of the four payload files this method
            // has already read, so this derives the value rather than inventing it - and it is placed
            // immediately after contentHash, which is where the sorted key order puts it.
            rewrittenBytes = InsertDataHashToken(rewrittenBytes, recomputedData, out spliceFailure);
            if (rewrittenBytes is null)
                return Refuse("REHASH-INSERT-FAILED", $"{ManifestFileName}'s dataHash could not be added: {spliceFailure}");
        }
        else
        {
            rewrittenBytes = SpliceHashToken(rewrittenBytes, declaredDataHash, recomputedData, out spliceFailure);
            if (rewrittenBytes is null)
                return Refuse("REHASH-SPLICE-FAILED", $"{ManifestFileName}'s dataHash could not be rewritten: {spliceFailure}");
        }

        var reparse = RehashOnlyFailure(manifest, rewrittenBytes, recomputed, recomputedData);
        if (reparse is not null) return Refuse("REHASH-REPARSE-FAILED", reparse);

        try { WriteManifestAtomically(manifestPath, rewrittenBytes); }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException)
        {
            return Refuse("REHASH-WRITE-FAILED", $"{ManifestFileName} could not be written: {ex.Message}");
        }

        return new ManifestRehash(true,
            $"contentHash {declaredHash} -> {recomputed}; dataHash {declaredDataHash} -> {recomputedData}",
            ManifestBytes: rewrittenBytes, DeclaredHash: declaredHash, RecomputedHash: recomputed,
            CapturedUtc: capturedUtc, Changed: true, Written: true);
    }

    static ManifestRehash Refuse(string code, string detail) =>
        new(false, $"{code}: {detail}");

    /// <summary>
    /// Replaces the declared hash's bytes with the recomputed one, in place, inside the envelope's
    /// own bytes. Returns null with a reason rather than a partial splice.
    ///
    /// <para><b>Splice, not re-render — and the reason is no longer the line endings.</b> A
    /// full re-render used to be provably wrong here: <c>Utf8JsonWriter</c>'s indented output was
    /// CRLF on net8.0, so re-rendering the committed 252-byte LF envelope produced 260 bytes first
    /// differing at byte 1, and would have moved every line ending in all seven files. That is
    /// fixed (<see cref="ToLfLineEndings"/>), so a re-render would now be byte-clean — but it is
    /// still the wrong instrument. The contract this mode exists to honour is "only
    /// <c>contentHash</c> may move", and splicing is what enforces it: it is the only path that
    /// cannot re-derive, reorder or omit any field, because it never re-derives one. The
    /// <see cref="RehashOnlyFailure"/> re-parse then proves the property on the result.</para>
    /// </summary>
    static byte[]? SpliceHashToken(byte[] manifestBytes, string declaredHash, string recomputed, out string failure)
    {
        failure = "";
        var oldToken = Encoding.UTF8.GetBytes("\"" + declaredHash + "\"");
        var newToken = Encoding.UTF8.GetBytes("\"" + recomputed + "\"");

        var found = 0;
        var at = -1;
        for (var i = 0; i + oldToken.Length <= manifestBytes.Length; i++)
        {
            if (!manifestBytes.AsSpan(i, oldToken.Length).SequenceEqual(oldToken)) continue;
            found++;
            if (at < 0) at = i;
        }
        if (found != 1)
        {
            failure = $"the declared hash occurs {found} times in the file, so its value cannot be replaced unambiguously";
            return null;
        }

        var spliced = new byte[manifestBytes.Length - oldToken.Length + newToken.Length];
        manifestBytes.AsSpan(0, at).CopyTo(spliced);
        newToken.CopyTo(spliced.AsSpan(at));
        manifestBytes.AsSpan(at + oldToken.Length).CopyTo(spliced.AsSpan(at + newToken.Length));
        return spliced;
    }

    /// <summary>Inserts <c>"dataHash": "&lt;value&gt;"</c> immediately after the contentHash
    /// token, which is where the envelope's sorted key order places it. Anchored on the contentHash
    /// KEY rather than its value, so it works whether or not that value is current.</summary>
    static byte[]? InsertDataHashToken(byte[] manifestBytes, string dataHash, out string failure)
    {
        failure = "";
        var anchor = Encoding.UTF8.GetBytes("\"contentHash\"");
        var at = -1;
        var found = 0;
        for (var i = 0; i + anchor.Length <= manifestBytes.Length; i++)
        {
            if (!manifestBytes.AsSpan(i, anchor.Length).SequenceEqual(anchor)) continue;
            found++;
            if (at < 0) at = i;
        }
        if (found != 1)
        {
            failure = $"the contentHash key occurs {found} times in the file, so dataHash cannot be placed unambiguously";
            return null;
        }

        // Past the key, skip to the end of its value token, then to the comma that ends the pair.
        var i2 = at + anchor.Length;
        var valueStart = manifestBytes.AsSpan(i2).IndexOf((byte)'"');
        if (valueStart < 0) { failure = "the contentHash key has no value token"; return null; }
        var valueEnd = manifestBytes.AsSpan(i2 + valueStart + 1).IndexOf((byte)'"');
        if (valueEnd < 0) { failure = "the contentHash value token is unterminated"; return null; }
        var after = i2 + valueStart + 1 + valueEnd + 1;
        if (after >= manifestBytes.Length || manifestBytes[after] != (byte)',')
        { failure = "the contentHash pair is not followed by a comma, so dataHash cannot be inserted after it"; return null; }

        // Insert AFTER the line break, carrying that line's own indentation, so the envelope keeps the
        // canonical one-key-per-line shape the renderer produces. Splicing after the comma instead would
        // be valid JSON and still parse, but it would not be the shape RenderManifest emits - so the
        // next genuine re-render would show a layout-only diff on a line nobody had edited.
        var lineStart = after + 1;
        var newline = -1;
        for (var i = after + 1; i < manifestBytes.Length; i++)
        {
            if (manifestBytes[i] != (byte)'\n') continue;
            newline = i;
            break;
        }
        if (newline < 0) { failure = "the contentHash pair is not followed by a line break"; return null; }
        var indent = 0;
        while (newline + 1 + indent < manifestBytes.Length && manifestBytes[newline + 1 + indent] == (byte)' ')
            indent++;

        // The bytes copied past the original line break already carry the NEXT key's indentation, so
        // the addition must END with a line break rather than begin with one - leading with one leaves
        // a blank line, and omitting the trailing one welds the next key onto this line.
        var addition = Encoding.UTF8.GetBytes(new string(' ', indent)
            + "\"dataHash\": \"" + dataHash + "\",\n");
        var spliced = new byte[manifestBytes.Length + addition.Length];
        manifestBytes.AsSpan(0, newline + 1).CopyTo(spliced);                       // through the line break
        addition.CopyTo(spliced.AsSpan(newline + 1));                               // `\n  "dataHash": "…",`
        manifestBytes.AsSpan(newline + 1).CopyTo(spliced.AsSpan(newline + 1 + addition.Length));
        return spliced;
    }

    /// <summary>
    /// Parses a rewritten envelope through the normal parse path and returns null when
    /// <c>contentHash</c> and <c>dataHash</c> are provably the only fields that moved. A splice that
    /// silently dropped, added or altered anything else is reported here rather than written. Both are
    /// named here rather than only one because the rehash mode exists to move hashes and nothing else,
    /// and a widening that is not asserted is how a rehash starts touching fields it has no business on.
    /// </summary>
    static string? RehashOnlyFailure(JsonObject before, byte[] rewrittenBytes, string recomputed, string recomputedData)
    {
        JsonNode? node;
        try { node = JsonNode.Parse(rewrittenBytes); }
        catch (JsonException ex) { return $"{ManifestFileName} did not parse after the rewrite: {ex.Message}"; }
        if (node is not JsonObject after) return $"{ManifestFileName} is not a JSON object after the rewrite";
        if (!string.Equals((string?)after["contentHash"], recomputed, StringComparison.Ordinal))
            return $"{ManifestFileName} does not carry the recomputed hash after the rewrite";
        if (!string.Equals((string?)after["dataHash"], recomputedData, StringComparison.Ordinal))
            return $"{ManifestFileName} does not carry the recomputed data hash after the rewrite";

        var beforeKeys = before.Select(kv => kv.Key).OrderBy(k => k, StringComparer.Ordinal).ToArray();
        var afterKeys = after.Select(kv => kv.Key).OrderBy(k => k, StringComparer.Ordinal).ToArray();
        if (!beforeKeys.AsSpan().SequenceEqual(afterKeys))
        {
            // The ONE tolerated difference is dataHash being added to an envelope written before the
            // two hashes were split. Anything else - a dropped key, a renamed key, a reordered set -
            // is still refused here rather than written.
            var added = afterKeys.Except(beforeKeys, StringComparer.Ordinal).ToArray();
            var removed = beforeKeys.Except(afterKeys, StringComparer.Ordinal).ToArray();
            if (added.Length == 1 && added[0] == "dataHash" && removed.Length == 0)
            { /* the migration case, tolerated */ }
            else
                return $"{ManifestFileName}'s key set changed during the rewrite "
                     + $"(added [{string.Join(", ", added)}], removed [{string.Join(", ", removed)}])";
        }

        foreach (var key in beforeKeys)
        {
            if (key is "contentHash" or "dataHash") continue;
            if (!string.Equals(before[key]?.ToJsonString(), after[key]?.ToJsonString(), StringComparison.Ordinal))
                return $"{ManifestFileName}'s '{key}' changed during the rewrite — only contentHash and "
                     + "dataHash may move";
        }
        return null;
    }

    /// <summary>Write-then-replace, so a crash mid-write cannot leave a half-written envelope that
    /// still parses. The temp file is removed on failure; the exception is rethrown, never swallowed.</summary>
    static void WriteManifestAtomically(string path, byte[] bytes)
    {
        var tmp = path + ".rehash-tmp";
        try
        {
            File.WriteAllBytes(tmp, bytes);
            File.Move(tmp, path, overwrite: true);
        }
        catch
        {
            if (File.Exists(tmp)) File.Delete(tmp);
            throw;
        }
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
