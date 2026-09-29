using System.Text.Json;
using System.Text.Json.Nodes;
using FusionRpg.Core.Items.Sockets;
using FusionRpg.Tools.ItemSeedValidator.Model;

namespace FusionRpg.Tools.ItemSeedValidator.Checks;

/// <summary>
/// `socketMax` (spec-base-types.md, item module 6): every live base type carries an explicit value
/// (an omitted field is not a zero), and no entry may exceed its role's ceiling
/// (`SocketTuningFiles.Current`; module 16 owns the ceiling table and this check reads it, never
/// re-states it).
/// </summary>
public static class SocketMaxCheck
{
    public static void Run(ValidationContext ctx)
    {
        var ceilings = LoadCeilings(ctx.Registries.RegistryDir);
        if (ceilings is null)
        {
            ctx.CorpusWarn("SocketCeilingTableAbsent", $"data/tuning/{SocketTuningFiles.Current}",
                "the per-role socket ceiling table could not be loaded; socketMax bounds were not checked");
            return;
        }

        foreach (var entry in ctx.Entries)
        {
            if (entry.File.Kind != "base-type") continue;
            if (entry.File.IsExemplar) continue; // a pattern, not corpus content
            if (entry.Node["enabled"] is JsonValue en && en.TryGetValue<bool>(out var enabled) && !enabled) continue;

            var role = entry.AsString("role");
            if (role is null) continue;

            if (entry.Node["socketMax"] is not JsonValue smNode || !smNode.TryGetValue<int>(out var socketMax))
            {
                ctx.Error(entry, "SocketMaxMissing", "spec-base-types.md",
                    $"'{entry.Label}': socketMax is absent — an omitted field is not a zero, it is an undefined socket count");
                continue;
            }

            if (!ceilings.TryGetValue(role, out var ceiling)) continue; // no ceiling row for this role (e.g. commander standard)

            if (socketMax > ceiling)
                ctx.Error(entry, "SocketMaxExceedsRoleCeiling", $"data/tuning/{SocketTuningFiles.Current}",
                    $"'{entry.Label}': socketMax {socketMax} exceeds role '{role}''s ceiling of {ceiling}");
        }
    }

    static Dictionary<string, int>? LoadCeilings(string registryDir)
    {
        // registryDir is .../data/seed/items/_registry -- the tuning file is a sibling of gk-data/packs/fusion/data/seed.
        var path = Path.GetFullPath(Path.Combine(registryDir, "..", "..", "..", "tuning", SocketTuningFiles.Current));
        if (!File.Exists(path)) return null;

        using var doc = JsonDocument.Parse(File.ReadAllText(path));
        if (!doc.RootElement.TryGetProperty("socketCeiling", out var el) || el.ValueKind != JsonValueKind.Object)
            return null;

        var result = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var prop in el.EnumerateObject())
            result[prop.Name] = prop.Value.GetInt32();
        return result;
    }
}
