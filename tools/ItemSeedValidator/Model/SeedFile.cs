using System.Text.Json;
using System.Text.Json.Nodes;

namespace FusionRpg.Tools.ItemSeedValidator.Model;

/// <summary>One authored entry inside a seed file, plus where it came from.</summary>
public sealed class SeedEntry
{
    public required SeedFile File { get; init; }
    public required int Index { get; init; }
    public required JsonObject Node { get; init; }

    /// <summary>The authored id, or null when the entry omits it (which is itself an error).</summary>
    public string? Id => Node["id"]?.GetValue<string>();

    public string? NameKey => AsString("nameKey");
    public string? Name => AsString("name");

    /// <summary>Filled in by the identity check once the id resolves to an allocated namespace.</summary>
    public string Partition { get; set; } = Finding.NoPartition;

    /// <summary>Wave stage of the owning partition: "1a", "1b", or "" when unresolved.</summary>
    public string Stage { get; set; } = "";

    /// <summary>The allocated namespace this id matched, once the identity check has run.</summary>
    public Registries.AllocatedNamespace? Allocation { get; set; }

    /// <summary>Best label for a message when the id is missing.</summary>
    public string Label => Id ?? $"(entry #{Index})";

    public string? AsString(string key) =>
        Node[key] is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;
}

/// <summary>A parsed seed file. Parse failures produce a file with <see cref="Root"/> null.</summary>
public sealed class SeedFile
{
    public required string RelativePath { get; init; }
    public required string AbsolutePath { get; init; }

    /// <summary>First path segment under the seed root — what <c>kind</c> must agree with.</summary>
    public required string Directory { get; init; }

    /// <summary>
    /// A worked exemplar rather than corpus content. Exemplars validate exactly like real files —
    /// that is what makes them trustworthy as the pattern 124 agents copy — but they sit in
    /// <c>_exemplars/</c> rather than a kind directory, and nothing references them, so the
    /// directory rule and the corpus-level "unreferenced" lint do not apply.
    /// </summary>
    public bool IsExemplar => Directory.Equals("_exemplars", StringComparison.Ordinal);

    public JsonObject? Root { get; init; }
    public string? ParseError { get; init; }
    public IReadOnlyList<string> DuplicateKeyPaths { get; init; } = Array.Empty<string>();

    public JsonObject? Meta => Root?["_meta"] as JsonObject;
    public string? Kind => Root?["kind"] is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;

    public List<SeedEntry> Entries { get; } = new();

    public static SeedFile Load(string absolutePath, string relativePath, string directory)
    {
        string text;
        try
        {
            text = System.IO.File.ReadAllText(absolutePath);
        }
        catch (Exception ex)
        {
            return new SeedFile
            {
                AbsolutePath = absolutePath, RelativePath = relativePath, Directory = directory,
                ParseError = $"unreadable: {ex.Message}",
            };
        }

        return Parse(text, relativePath, directory, absolutePath);
    }

    /// <summary>Parse from text. The test seam, and what <see cref="Load"/> delegates to.</summary>
    public static SeedFile Parse(string text, string relativePath, string directory, string? absolutePath = null)
    {
        absolutePath ??= relativePath;

        JsonObject? root;
        try
        {
            // Comments and trailing commas stay disallowed: a seed file is machine input, and a
            // parser that accepts more than the contract does is a parser that hides a defect.
            var node = JsonNode.Parse(text, documentOptions: new JsonDocumentOptions
            {
                CommentHandling = JsonCommentHandling.Disallow,
                AllowTrailingCommas = false,
            });
            root = node as JsonObject;
            if (root is null)
                return new SeedFile
                {
                    AbsolutePath = absolutePath, RelativePath = relativePath, Directory = directory,
                    ParseError = "top level is not a JSON object",
                };
        }
        catch (JsonException ex)
        {
            return new SeedFile
            {
                AbsolutePath = absolutePath, RelativePath = relativePath, Directory = directory,
                ParseError = ex.Message,
            };
        }

        var file = new SeedFile
        {
            AbsolutePath = absolutePath, RelativePath = relativePath, Directory = directory,
            Root = root,
            // System.Text.Json keeps the LAST duplicate key silently. A duplicated key in a seed
            // file means one of the two values was never validated, so find them ourselves.
            DuplicateKeyPaths = DuplicateKeyScanner.Scan(text),
        };

        if (root["entries"] is JsonArray entries)
        {
            for (var i = 0; i < entries.Count; i++)
                if (entries[i] is JsonObject entry)
                    file.Entries.Add(new SeedEntry { File = file, Index = i, Node = entry });
        }

        return file;
    }
}
