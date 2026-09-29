using System.Text.Json.Nodes;
using FusionRpg.Tools.ItemSeedValidator.Model;

namespace FusionRpg.Tools.ItemSeedValidator.Checks;

/// <summary>
/// entry-shapes.md §9's drop-table rules. The section calls `entryKind` a closed enum and states
/// which fields each kind requires, and none of it was enforced — the C# validator checked only
/// the two top-level keys, `sourceAllow` and `groups`, so a typo'd entry kind or an `equipment`
/// row missing its role would have shipped silently.
///
/// That mattered the moment wave R2 added `unique` and `consumable` to the enum: a vocabulary that
/// grows is exactly the kind that drifts, and this corpus has already lost ten references to a
/// spelling nothing checked.
/// </summary>
public static class DropTableCheck
{
    /// <summary>entry-shapes.md §9, extended to ten values by empire-development Task 1.3b
    /// (spec-relic-item-kind.md §Design 4a: `relic`, a rolled, never-equipped item with no base
    /// type, role or frame -- `DropEntryKind.Relic`'s own seed-time gate).</summary>
    static readonly string[] EntryKinds =
    {
        "equipment", "material", "currency", "insert", "charm", "consumable", "unique",
        "relic", "table", "nothing",
    };

    /// <summary>Kinds whose grant is a named thing rather than a category. `relic` names one
    /// specific anchor (a `ref` into `gk-data/packs/fusion/data/seed/items/relics/`), exactly like `unique`/`charm`/
    /// `consumable` already do -- a relic entry without a `ref` grants nothing in particular.
    /// </summary>
    static readonly string[] NeedsRef =
        { "material", "currency", "insert", "charm", "consumable", "unique", "relic", "table" };

    public static void Run(ValidationContext ctx)
    {
        foreach (var entry in ctx.Entries)
        {
            if (!string.Equals(entry.File.Kind, "drop-table", StringComparison.Ordinal)) continue;
            if (entry.File.IsExemplar) continue;

            // ssot-generation.md §4.6 rule 2, the standalone-first rule: a table the web client
            // cannot reach is content that only exists inside the game process.
            var sources = (entry.Node["sourceAllow"] as JsonArray ?? new JsonArray())
                .OfType<JsonValue>()
                .Select(v => v.TryGetValue<string>(out var s) ? s : null)
                .OfType<string>()
                .ToList();
            if (sources.Count > 0 && !sources.Contains("web", StringComparer.Ordinal))
                ctx.Error(entry, "StandaloneRuleViolation", "entry-shapes.md §9",
                    $"sourceAllow is [{string.Join(", ", sources)}] and omits 'web'; every table "
                    + "must be reachable from the standalone client");

            foreach (var group in (entry.Node["groups"] as JsonArray ?? new JsonArray()).OfType<JsonObject>())
            {
                foreach (var row in (group["entries"] as JsonArray ?? new JsonArray()).OfType<JsonObject>())
                {
                    var kind = row["entryKind"]?.GetValue<string>();
                    if (kind is null)
                    {
                        ctx.Error(entry, "DropEntryKindMissing", "entry-shapes.md §9",
                            $"an entry in group '{group["groupKey"]}' declares no entryKind");
                        continue;
                    }

                    if (!EntryKinds.Contains(kind, StringComparer.Ordinal))
                    {
                        ctx.Error(entry, "DropEntryKindUnknown", "entry-shapes.md §9",
                            $"entryKind '{kind}' is not one of {string.Join(", ", EntryKinds)}");
                        continue;
                    }

                    if (kind == "equipment"
                        && (row["role"] is null || row["frame"] is null))
                        ctx.Error(entry, "DropEquipmentSlotMissing", "entry-shapes.md §9",
                            "an 'equipment' entry grants a whole role and frame, so it must name "
                            + "both; without them it grants nothing in particular");

                    if (NeedsRef.Contains(kind, StringComparer.Ordinal) && row["ref"] is null)
                        ctx.Error(entry, "DropRefMissing", "entry-shapes.md §9",
                            $"a '{kind}' entry names one specific thing and carries no ref");
                }
            }
        }
    }
}
