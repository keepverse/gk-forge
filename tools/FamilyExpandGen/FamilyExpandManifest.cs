using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using FusionRpg.Core.Effects.Atoms.Generation;

namespace FusionRpg.Tools.FamilyExpandGen;

public sealed record FamilyExpandInputDescriptor(
    string Path,
    int? Version,
    string? Sha256,
    bool Present,
    string? Note);

public sealed record FamilyExpandOutputDescriptor(
    string Path,
    string Sha256,
    int RowCount);

public enum FamilyExpandManifestReconciliationStatus
{
    Clean,
    Missing,
    Invalid,
    Drifted,
}

public sealed record FamilyExpandManifestReconciliation(
    FamilyExpandManifestReconciliationStatus Status,
    string Detail)
{
    public bool IsClean => Status == FamilyExpandManifestReconciliationStatus.Clean;
}

/// <summary>
/// The durable sidecar written beside the generated atom files.  It is deliberately named with a
/// leading underscore: <c>SeedScanner</c> deliberately ignores underscore-prefixed files, so the
/// manifest can record refusals and provenance without becoming an importable atom seed.
/// </summary>
public sealed record FamilyExpandManifest(
    IReadOnlyList<FamilyExpandInputDescriptor> Inputs,
    IReadOnlyList<FamilyExpandOutputDescriptor> Outputs,
    IReadOnlyList<FamilyRefusal> Refusals)
{
    public const int SchemaVersion = 1;
    public const int GeneratorVersion = 1;
    public const string GeneratorName = "FamilyExpandGen";
    public const string RefusalPolicy = "reconcile-on-check";

    // The manifest lives below gk-data/packs/fusion/data/seed/atoms, and several content tests deliberately feed every
    // *.json below that root through AtomSeedFile instead of first applying SeedScanner's underscore
    // exclusion. Give those existing closed-kind readers a valid, deliberately empty seed envelope:
    // `affix` is the nearest shipped table because this generator expands authored affix families,
    // while the custom inputs/outputs/refusals arrays below retain the manifest's real meaning. An
    // empty `entries` array is load-bearing — putting refusal rows there would manufacture content.
    public const string SeedReaderKind = "affix";

    public string InputHash => FamilyExpandHash.Sha256Json(InputsJson());
    public string OutputHash => FamilyExpandHash.Sha256Json(OutputsJson());

    public static FamilyExpandManifest Create(
        IEnumerable<FamilyExpandInputDescriptor> inputs,
        IEnumerable<FamilyExpandOutputDescriptor> outputs,
        IEnumerable<FamilyRefusal> refusals) =>
        new(
            inputs.OrderBy(input => input.Path, StringComparer.Ordinal).ToArray(),
            outputs.OrderBy(output => output.Path, StringComparer.Ordinal).ToArray(),
            refusals.OrderBy(refusal => refusal.FamilyId, StringComparer.Ordinal).ToArray());

    public string ToCanonicalJson()
    {
        var root = new JsonObject
        {
            ["schemaVersion"] = SchemaVersion,
            ["kind"] = SeedReaderKind,
            ["generator"] = GeneratorName,
            ["generatorVersion"] = GeneratorVersion,
            ["refusalPolicy"] = RefusalPolicy,
            ["inputHash"] = InputHash,
            ["outputHash"] = OutputHash,
            ["inputs"] = InputsJson(),
            ["outputs"] = OutputsJson(),
            ["refusals"] = RefusalsJson(),
            ["entries"] = new JsonArray(),
        };

        return FamilyExpandHash.Canonicalize(
            root.ToJsonString(new JsonSerializerOptions { WriteIndented = true })) + "\n";
    }

    public static FamilyExpandManifest Parse(string json)
    {
        JsonNode? parsed;
        try
        {
            parsed = JsonNode.Parse(json);
        }
        catch (JsonException ex)
        {
            throw new FormatException($"family-expand manifest is not valid JSON — {ex.Message}", ex);
        }

        if (parsed is not JsonObject root)
            throw new FormatException("family-expand manifest must be a JSON object");

        var schemaVersion = Int(root, "schemaVersion");
        if (schemaVersion != SchemaVersion)
            throw new FormatException($"family-expand manifest schemaVersion {schemaVersion} — this generator reads {SchemaVersion}");

        var seedReaderKind = String(root, "kind");
        if (!string.Equals(seedReaderKind, SeedReaderKind, StringComparison.Ordinal))
            throw new FormatException(
                $"family-expand manifest seed-reader kind '{seedReaderKind}' — expected '{SeedReaderKind}'");
        if (Array(root, "entries").Count != 0)
            throw new FormatException("family-expand manifest seed-reader entries must be empty");

        var generator = String(root, "generator");
        if (!string.Equals(generator, GeneratorName, StringComparison.Ordinal))
            throw new FormatException($"family-expand manifest generator '{generator}' — expected '{GeneratorName}'");

        var generatorVersion = Int(root, "generatorVersion");
        if (generatorVersion != GeneratorVersion)
            throw new FormatException($"family-expand manifest generatorVersion {generatorVersion} — this generator writes {GeneratorVersion}");

        var refusalPolicy = String(root, "refusalPolicy");
        if (!string.Equals(refusalPolicy, RefusalPolicy, StringComparison.Ordinal))
            throw new FormatException($"family-expand manifest refusalPolicy '{refusalPolicy}' — expected '{RefusalPolicy}'");

        var inputs = ReadInputs(root);
        var outputs = ReadOutputs(root);
        var refusals = ReadRefusals(root);
        var manifest = Create(inputs, outputs, refusals);

        var declaredInputHash = String(root, "inputHash");
        if (!string.Equals(declaredInputHash, manifest.InputHash, StringComparison.Ordinal))
            throw new FormatException("family-expand manifest inputHash does not match its inputs");
        var declaredOutputHash = String(root, "outputHash");
        if (!string.Equals(declaredOutputHash, manifest.OutputHash, StringComparison.Ordinal))
            throw new FormatException("family-expand manifest outputHash does not match its outputs");

        return manifest;
    }

    public static FamilyExpandManifestReconciliation Reconcile(string? existingJson, FamilyExpandManifest expected)
    {
        if (string.IsNullOrWhiteSpace(existingJson))
            return new FamilyExpandManifestReconciliation(
                FamilyExpandManifestReconciliationStatus.Missing,
                "refusal/provenance manifest is missing; run FamilyExpandGen");

        FamilyExpandManifest actual;
        try
        {
            actual = Parse(existingJson);
        }
        catch (FormatException ex)
        {
            return new FamilyExpandManifestReconciliation(
                FamilyExpandManifestReconciliationStatus.Invalid,
                $"refusal/provenance manifest is invalid: {ex.Message}");
        }

        if (string.Equals(
                FamilyExpandHash.Canonicalize(existingJson),
                expected.ToCanonicalJson(),
                StringComparison.Ordinal))
            return new FamilyExpandManifestReconciliation(
                FamilyExpandManifestReconciliationStatus.Clean,
                "refusal/provenance manifest matches the current generator inputs");

        var detail = new List<string> { "refusal/provenance manifest drifted" };
        if (!string.Equals(actual.InputHash, expected.InputHash, StringComparison.Ordinal))
            detail.Add("input hash changed");
        if (!string.Equals(actual.OutputHash, expected.OutputHash, StringComparison.Ordinal))
            detail.Add("output hash changed");
        if (actual.Refusals.Count != expected.Refusals.Count ||
            !actual.Refusals.SequenceEqual(expected.Refusals))
            detail.Add("refusal baseline changed");
        if (actual.Inputs.Count != expected.Inputs.Count ||
            !actual.Inputs.SequenceEqual(expected.Inputs))
            detail.Add("input inventory changed");
        if (actual.Outputs.Count != expected.Outputs.Count ||
            !actual.Outputs.SequenceEqual(expected.Outputs))
            detail.Add("output inventory changed");

        return new FamilyExpandManifestReconciliation(
            FamilyExpandManifestReconciliationStatus.Drifted,
            string.Join("; ", detail));
    }

    public static FamilyExpandInputDescriptor DescribeFile(
        string repoRoot,
        string path,
        int? version = null,
        string? note = null)
    {
        var fullPath = Path.GetFullPath(path);
        if (!File.Exists(fullPath))
            throw new FileNotFoundException($"missing FamilyExpandGen input {fullPath}", fullPath);
        return new FamilyExpandInputDescriptor(
            RelativePath(repoRoot, fullPath),
            version,
            FamilyExpandHash.Sha256Text(File.ReadAllText(fullPath)),
            Present: true,
            note);
    }

    public static FamilyExpandInputDescriptor DescribeMissing(
        string repoRoot,
        string path,
        string? note = null) =>
        new(RelativePath(repoRoot, Path.GetFullPath(path)), null, null, Present: false, note);

    static string RelativePath(string repoRoot, string path) =>
        Path.GetRelativePath(Path.GetFullPath(repoRoot), path).Replace('\\', '/');

    JsonArray InputsJson()
    {
        var array = new JsonArray();
        foreach (var input in Inputs.OrderBy(item => item.Path, StringComparer.Ordinal))
        {
            var item = new JsonObject
            {
                ["path"] = input.Path,
                ["present"] = input.Present,
            };
            if (input.Version.HasValue) item["version"] = input.Version.Value;
            if (input.Present) item["sha256"] = RequireHash(input.Sha256, $"input '{input.Path}'");
            if (!string.IsNullOrWhiteSpace(input.Note)) item["note"] = input.Note;
            array.Add(item);
        }

        return array;
    }

    JsonArray OutputsJson()
    {
        var array = new JsonArray();
        foreach (var output in Outputs.OrderBy(item => item.Path, StringComparer.Ordinal))
        {
            array.Add(new JsonObject
            {
                ["path"] = output.Path,
                ["sha256"] = RequireHash(output.Sha256, $"output '{output.Path}'"),
                ["rowCount"] = output.RowCount,
            });
        }

        return array;
    }

    JsonArray RefusalsJson()
    {
        var array = new JsonArray();
        foreach (var refusal in Refusals.OrderBy(item => item.FamilyId, StringComparer.Ordinal))
        {
            array.Add(new JsonObject
            {
                ["familyId"] = refusal.FamilyId,
                ["reason"] = refusal.Reason,
            });
        }

        return array;
    }

    static IReadOnlyList<FamilyExpandInputDescriptor> ReadInputs(JsonObject root)
    {
        var result = new List<FamilyExpandInputDescriptor>();
        foreach (var node in Array(root, "inputs"))
        {
            if (node is not JsonObject item) throw new FormatException("family-expand manifest inputs must contain objects");
            var path = String(item, "path");
            var present = Bool(item, "present");
            var version = OptionalInt(item, "version");
            var hash = OptionalString(item, "sha256");
            var note = OptionalString(item, "note");
            if (present && hash is null)
                throw new FormatException($"family-expand manifest input '{path}' is present without sha256");
            if (!present && hash is not null)
                throw new FormatException($"family-expand manifest input '{path}' is absent but carries sha256");
            if (present) _ = RequireHash(hash, $"input '{path}'");
            result.Add(new FamilyExpandInputDescriptor(path, version, hash, present, note));
        }

        return result;
    }

    static IReadOnlyList<FamilyExpandOutputDescriptor> ReadOutputs(JsonObject root)
    {
        var result = new List<FamilyExpandOutputDescriptor>();
        foreach (var node in Array(root, "outputs"))
        {
            if (node is not JsonObject item) throw new FormatException("family-expand manifest outputs must contain objects");
            var path = String(item, "path");
            var hash = RequireHash(OptionalString(item, "sha256"), $"output '{path}'");
            var rowCount = Int(item, "rowCount");
            if (rowCount < 0) throw new FormatException($"family-expand manifest output '{path}' has negative rowCount");
            result.Add(new FamilyExpandOutputDescriptor(path, hash, rowCount));
        }

        return result;
    }

    static IReadOnlyList<FamilyRefusal> ReadRefusals(JsonObject root)
    {
        var result = new List<FamilyRefusal>();
        foreach (var node in Array(root, "refusals"))
        {
            if (node is not JsonObject item) throw new FormatException("family-expand manifest refusals must contain objects");
            var familyId = String(item, "familyId");
            var reason = String(item, "reason");
            if (result.Any(existing => string.Equals(existing.FamilyId, familyId, StringComparison.Ordinal)))
                throw new FormatException($"family-expand manifest repeats refusal family '{familyId}'");
            result.Add(new FamilyRefusal(familyId, reason));
        }

        return result;
    }

    static JsonArray Array(JsonObject root, string name)
    {
        if (!root.TryGetPropertyValue(name, out var node) || node is not JsonArray array)
            throw new FormatException($"family-expand manifest missing array '{name}'");
        return array;
    }

    static string String(JsonObject root, string name)
    {
        if (!root.TryGetPropertyValue(name, out var node) || node is not JsonValue value ||
            !value.TryGetValue<string>(out var text) || string.IsNullOrWhiteSpace(text))
            throw new FormatException($"family-expand manifest missing string '{name}'");
        return text;
    }

    static string? OptionalString(JsonObject root, string name)
    {
        if (!root.TryGetPropertyValue(name, out var node) || node is null) return null;
        if (node is not JsonValue value || !value.TryGetValue<string>(out var text))
            throw new FormatException($"family-expand manifest field '{name}' must be a string");
        return text;
    }

    static int Int(JsonObject root, string name)
    {
        if (!root.TryGetPropertyValue(name, out var node) || node is not JsonValue value ||
            !value.TryGetValue<int>(out var number))
            throw new FormatException($"family-expand manifest missing integer '{name}'");
        return number;
    }

    static int? OptionalInt(JsonObject root, string name)
    {
        if (!root.TryGetPropertyValue(name, out var node) || node is null) return null;
        if (node is not JsonValue value || !value.TryGetValue<int>(out var number))
            throw new FormatException($"family-expand manifest field '{name}' must be an integer");
        return number;
    }

    static bool Bool(JsonObject root, string name)
    {
        if (!root.TryGetPropertyValue(name, out var node) || node is not JsonValue value ||
            !value.TryGetValue<bool>(out var result))
            throw new FormatException($"family-expand manifest missing boolean '{name}'");
        return result;
    }

    static string RequireHash(string? hash, string owner)
    {
        if (string.IsNullOrWhiteSpace(hash) || hash.Length != 64 ||
            hash.Any(character => !Uri.IsHexDigit(character)))
            throw new FormatException($"{owner} needs a 64-character SHA-256 hex hash");
        return hash.ToLowerInvariant();
    }
}

public static class FamilyExpandHash
{
    public static string Canonicalize(string text) => text.Replace("\r\n", "\n");

    public static string Sha256Text(string text) =>
        Sha256Bytes(Encoding.UTF8.GetBytes(Canonicalize(text)));

    public static string Sha256Json(JsonNode node) => Sha256Text(node.ToJsonString());

    static string Sha256Bytes(byte[] bytes)
    {
        var hash = SHA256.HashData(bytes);
        return Convert.ToHexString(hash).ToLowerInvariant();
    }
}
