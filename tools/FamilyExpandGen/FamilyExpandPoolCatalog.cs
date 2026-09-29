using System.Text.Json;
using FusionRpg.Core.Effects.Atoms;

namespace FusionRpg.Tools.FamilyExpandGen;

/// <summary>
/// The live E30 pool catalog as seen by the generator.  The catalog is read before expansion and
/// every pool reference emitted by <see cref="Generation.FamilyExpansion"/> is checked against it;
/// a generated row can therefore never point at a pool id that the importer will not find.
/// </summary>
public sealed class FamilyExpandPoolCatalog
{
    readonly IReadOnlyDictionary<string, ChannelPoolRow> _pools;

    FamilyExpandPoolCatalog(
        string path,
        string sha256,
        IReadOnlyDictionary<string, ChannelPoolRow> pools)
    {
        Path = path;
        Sha256 = sha256;
        _pools = pools;
    }

    public string Path { get; }
    public string Sha256 { get; }
    public IReadOnlyList<string> PoolIds => _pools.Keys.OrderBy(id => id, StringComparer.Ordinal).ToArray();

    public static FamilyExpandPoolCatalog Load(string path)
    {
        if (!File.Exists(path))
            throw new FileNotFoundException($"missing channel-pool catalog {path}", path);
        return FromJson(path, File.ReadAllText(path));
    }

    public static FamilyExpandPoolCatalog FromJson(string path, string json)
    {
        var read = ChannelPoolFile.TryParse(json, out var rows);
        if (!read.IsOk)
            throw new FormatException($"{path}: channel-pool catalog refused — {read.Reason}: {read.Detail}");

        var pools = rows.ToDictionary(row => row.PoolId, StringComparer.Ordinal);
        return new FamilyExpandPoolCatalog(path, FamilyExpandHash.Sha256Text(json), pools);
    }

    /// <summary>
    /// Validate the pool-shaped channels in generated rows.  Concrete channels are deliberately
    /// ignored; only an object-form channel can name a pool, and that pool must be in this exact
    /// catalog read for this run.
    /// </summary>
    public IReadOnlyList<string> Validate(IEnumerable<AtomRow> rows)
    {
        var errors = new List<string>();
        foreach (var row in rows)
        {
            JsonDocument document;
            try
            {
                document = JsonDocument.Parse(row.ParamsJson);
            }
            catch (JsonException ex)
            {
                errors.Add($"{row.AtomId}: generated params are not valid JSON — {ex.Message}");
                continue;
            }

            using (document)
            {
                var root = document.RootElement;
                if (!root.TryGetProperty("channel", out var channel) ||
                    channel.ValueKind != JsonValueKind.Object)
                    continue;

                if (!channel.TryGetProperty("pool", out var poolElement) ||
                    poolElement.ValueKind != JsonValueKind.String ||
                    string.IsNullOrWhiteSpace(poolElement.GetString()))
                {
                    errors.Add($"{row.AtomId}: object-form channel has no string pool id");
                    continue;
                }

                var poolId = poolElement.GetString()!;
                if (!_pools.ContainsKey(poolId))
                    errors.Add($"{row.AtomId}: pool '{poolId}' is not present in {Path}");
            }
        }

        return errors;
    }
}
