using System.Text.Json.Nodes;
using FusionRpg.Tools.ItemSeedValidator.Model;

namespace FusionRpg.Tools.ItemSeedValidator.Checks;

/// <summary>
/// Content lints. Every one of these warns and none of them fails a build — they are shapes that
/// are usually a mistake and occasionally deliberate, which is exactly the line between a lint
/// and a rule.
/// </summary>
public static class LintCheck
{
    public static void Run(ValidationContext ctx)
    {
        TierGaps(ctx);
        SingletonPoolGroups(ctx);
        UnreferencedEntries(ctx);
        EmptyClassRungs(ctx);
    }

    /// <summary>A partition whose powerBands skip a tier in the middle of the range it uses.</summary>
    static void TierGaps(ValidationContext ctx)
    {
        var tiers = ctx.Registries.PowerBandTiers;
        if (tiers.Count == 0) return;

        foreach (var group in ctx.Entries
                     .Where(e => e.Partition != Finding.NoPartition && e.AsString("powerBand") is not null)
                     .GroupBy(e => e.Partition, StringComparer.Ordinal))
        {
            var used = group
                .Select(e => tiers.TryGetValue(e.AsString("powerBand")!, out var t) ? t : -1)
                .Where(t => t > 0).Distinct().Order().ToList();
            if (used.Count < 2) continue;

            var missing = Enumerable.Range(used[0], used[^1] - used[0] + 1).Except(used).ToList();
            if (missing.Count == 0) continue;

            var names = missing
                .Select(t => tiers.FirstOrDefault(kv => kv.Value == t).Key ?? $"t{t}")
                .ToList();
            var first = group.First();
            ctx.Warn(first, "TierGap", "lint",
                $"partition {group.Key} uses powerBands t{used[0]}-t{used[^1]} but skips "
                + string.Join(", ", names));
        }
    }

    /// <summary>Field names carrying the role/pool-group vocabulary — "roles" post-rename, plus
    /// the pre-rename "roleGroups" some entries may still carry (seed-contract.md §10).</summary>
    static readonly string[] RoleGroupFields = { "roles", "roleGroups" };

    /// <summary>A pool group with exactly one member is a pool that never chooses anything.</summary>
    static void SingletonPoolGroups(ValidationContext ctx)
    {
        var members = new Dictionary<string, List<SeedEntry>>(StringComparer.Ordinal);
        foreach (var entry in ctx.Entries)
        foreach (var field in RoleGroupFields)
        {
            if (entry.Node[field] is not JsonArray groups) continue;
            foreach (var node in groups)
            {
                if (node is not JsonValue jv || !jv.TryGetValue<string>(out var group)) continue;
                if (!members.TryGetValue(group, out var list)) members[group] = list = new List<SeedEntry>();
                list.Add(entry);
            }
        }

        foreach (var (group, list) in members.OrderBy(kv => kv.Key, StringComparer.Ordinal))
            if (list.Count == 1)
                ctx.Warn(list[0], "PoolGroupSingleton", "lint",
                    $"role group '{group}' has exactly one member; a pool with one row never chooses");
    }

    /// <summary>
    /// Kinds that exist to be referenced, and nothing references them.
    ///
    /// `base-type` is deliberately NOT here. A base type is reachable by rolling, not by being
    /// pointed at: 637 of 740 are referenced by nothing and every one of them is correct content.
    /// Warning on each buried the roughly twenty findings that meant something under noise that
    /// could never be actioned.
    /// </summary>
    /// Nor is `gem`, for the same reason once you read entry-shapes.md §2: a socket word names its
    /// ingredients by atom FAMILY and `minPowerBand`, never by gem id, so a gem is found and
    /// socketed rather than pointed at. Nor `curve` — a curve is resolved by the generator through
    /// `bands.v1.json`, not named by any seed row.
    ///
    /// What is left genuinely exists to be referenced: an affix family nothing grants, and a
    /// material no recipe spends, are both real findings.
    static readonly string[] ReferencedKinds = { "affix-family", "material" };

    /// <summary>
    /// Five kinds carry a runtime-facing id beside their allocated tracking id (entry-shapes.md §0),
    /// and a consumer naturally references the runtime one — a recipe spends
    /// `substrate.humanoid.crude`, not `material.017`. Matching only the tracking id reports a live,
    /// referenced row as an orphan. This is the same tracking-vs-runtime confusion that made the
    /// validator demand an enhancement milestone resolve its own minted family.
    /// </summary>
    static readonly string[] RuntimeIdFields = { "runtimeId", "runtimeFamily", "containerId" };

    static void UnreferencedEntries(ValidationContext ctx)
    {
        var referenced = new HashSet<string>(StringComparer.Ordinal);
        foreach (var entry in ctx.Entries)
            foreach (var (_, key, value) in ValidationContext.Walk(entry.Node))
            {
                if (key is "id" || key.EndsWith("Key", StringComparison.Ordinal)) continue;
                if (value is JsonValue jv && jv.TryGetValue<string>(out var text)) referenced.Add(text);
            }

        foreach (var entry in ctx.Entries)
        {
            if (entry.Id is not { } id) continue;
            // An exemplar is a pattern, not corpus content. Nothing referencing it is correct.
            if (entry.File.IsExemplar) continue;
            if (!ReferencedKinds.Contains(entry.File.Kind ?? "", StringComparer.Ordinal)) continue;
            if (referenced.Contains(id)) continue;
            if (RuntimeIdFields.Select(entry.AsString).OfType<string>().Any(referenced.Contains)) continue;
            ctx.Warn(entry, "Unreferenced", "lint",
                $"nothing in the corpus references '{id}'");
        }
    }

    /// <summary>A class rung no base type ever uses is a rung that ships empty.</summary>
    static void EmptyClassRungs(ValidationContext ctx)
    {
        var hasBaseTypes = ctx.Files.Any(f => f.Kind == "base-type" && f.Entries.Count > 0);
        if (!hasBaseTypes) return;

        var used = ctx.Entries
            .Where(e => e.File.Kind == "base-type")
            .Select(e => e.AsString("class"))
            .OfType<string>()
            .ToHashSet(StringComparer.Ordinal);

        foreach (var classId in ctx.Registries.ClassIds)
        {
            if (used.Contains(classId)) continue;
            var (ladder, frame, rung) = ctx.Registries.ClassRungs[classId];
            ctx.CorpusWarn("ClassRungEmpty", "lint",
                $"class '{classId}' ({ladder}/{frame} rung {rung}) has no base types");
        }
    }
}
