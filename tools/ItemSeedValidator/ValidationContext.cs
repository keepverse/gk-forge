using System.Text.Json.Nodes;
using FusionRpg.Tools.ItemSeedValidator.Model;
using FusionRpg.Tools.ItemSeedValidator.Naming;
using FusionRpg.Tools.ItemSeedValidator.Registries;

namespace FusionRpg.Tools.ItemSeedValidator;

/// <summary>Everything a check needs, plus the one place findings are collected.</summary>
public sealed class ValidationContext
{
    public required RegistrySet Registries { get; init; }
    public required NamespaceAllocation Allocation { get; init; }
    public required IReadOnlyList<SeedFile> Files { get; init; }
    public required NameNormalizer Normalizer { get; init; }

    public List<Finding> Findings { get; } = new();

    /// <summary>Every authored entry across every file, in scan order.</summary>
    public IEnumerable<SeedEntry> Entries => Files.SelectMany(f => f.Entries);

    /// <summary>id to the first entry that claimed it. Built by the identity check.</summary>
    public Dictionary<string, SeedEntry> ById { get; } = new(StringComparer.Ordinal);

    /// <summary>
    /// Runtime ids an entry MINTS rather than an allocation handing it out — a milestone's
    /// `atom.enhance-*`, a socket word's `gem.word-*`. They are legitimate reference targets that
    /// `ById` can never contain, so the resolver consults this too. Populated by ReferenceCheck.
    /// </summary>
    public HashSet<string> MintedRuntime { get; set; } = new(StringComparer.Ordinal);

    /// <summary>Ids retired by a disabled entry in this corpus, on top of the ledger.</summary>
    public HashSet<string> RetiredHere { get; } = new(StringComparer.Ordinal);

    public void Error(SeedEntry entry, string code, string rule, string message) =>
        Findings.Add(Finding.Error(code, entry.File.RelativePath, entry.Label, rule, message, entry.Partition));

    public void Warn(SeedEntry entry, string code, string rule, string message) =>
        Findings.Add(Finding.Warn(code, entry.File.RelativePath, entry.Label, rule, message, entry.Partition));

    public void FileError(SeedFile file, string code, string rule, string message) =>
        Findings.Add(Finding.Error(code, file.RelativePath, null, rule, message, FilePartition(file)));

    public void FileWarn(SeedFile file, string code, string rule, string message) =>
        Findings.Add(Finding.Warn(code, file.RelativePath, null, rule, message, FilePartition(file)));

    public void CorpusError(string code, string rule, string message) =>
        Findings.Add(Finding.Error(code, "(corpus)", null, rule, message));

    public void CorpusWarn(string code, string rule, string message) =>
        Findings.Add(Finding.Warn(code, "(corpus)", null, rule, message));

    /// <summary>The partition a whole file belongs to, if its entries agree on one.</summary>
    public static string FilePartition(SeedFile file)
    {
        var partitions = file.Entries.Select(e => e.Partition)
            .Where(p => p != Finding.NoPartition).Distinct().ToList();
        return partitions.Count == 1 ? partitions[0] : Finding.NoPartition;
    }

    /// <summary>Walks every (path, key, value) pair under a node, arrays included.</summary>
    public static IEnumerable<(string Path, string Key, JsonNode? Value)> Walk(JsonObject root)
    {
        var stack = new Stack<(string Path, JsonObject Node)>();
        stack.Push(("", root));
        while (stack.Count > 0)
        {
            var (path, node) = stack.Pop();
            foreach (var (key, value) in node)
            {
                var childPath = path.Length == 0 ? key : $"{path}.{key}";
                yield return (childPath, key, value);
                switch (value)
                {
                    case JsonObject obj:
                        stack.Push((childPath, obj));
                        break;
                    case JsonArray arr:
                        for (var i = 0; i < arr.Count; i++)
                        {
                            var itemPath = $"{childPath}[{i}]";
                            yield return (itemPath, key, arr[i]);
                            if (arr[i] is JsonObject itemObj) stack.Push((itemPath, itemObj));
                        }
                        break;
                }
            }
        }
    }
}
