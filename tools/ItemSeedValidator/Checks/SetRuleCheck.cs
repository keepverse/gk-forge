using System.Text.Json.Nodes;
using FusionRpg.Tools.ItemSeedValidator.Model;

namespace FusionRpg.Tools.ItemSeedValidator.Checks;

/// <summary>
/// ssot-sets.md §3.4's hard rules. Like the unique rules next door, these live only in a lane
/// document, so nothing mechanical held them and each agent had to find them by reading.
///
/// The 6-role cap and the uniques' 8-role quota are one rule read twice: ssot-uniques.md §3.7 notes
/// that 8 + 6 > 15, so the two lanes are competing for the same fifteen slots and cannot each be
/// checked in isolation. That interaction is why both checks landed in the same pass.
/// </summary>
public static class SetRuleCheck
{
    /// <summary>ssot-sets.md §3.4: "at least 9 slots on a pure frame are always rare or unique territory".</summary>
    const int MaxRolesPerSet = 6;

    public static void Run(ValidationContext ctx)
    {
        foreach (var entry in ctx.Entries)
        {
            if (!string.Equals(entry.File.Kind, "set", StringComparison.Ordinal)) continue;
            if (entry.File.IsExemplar) continue;   // a pattern, not corpus content

            var members = entry.Node["members"] as JsonArray ?? new JsonArray();
            var thresholds = entry.Node["thresholds"] as JsonArray ?? new JsonArray();

            var roles = members.OfType<JsonObject>()
                .Select(m => m["role"]?.GetValue<string>())
                .Where(r => r is not null)
                .Distinct(StringComparer.Ordinal)
                .ToList();

            if (roles.Count > MaxRolesPerSet)
                ctx.Error(entry, "SetRoleCap", "ssot-sets.md §3.4",
                    $"set claims {roles.Count} roles, over the cap of {MaxRolesPerSet}; the cap is "
                    + "what keeps at least 9 slots on a pure frame in rare or unique territory");

            var steps = thresholds.OfType<JsonObject>()
                .Select(t => t["pieces"]?.GetValue<int>())
                .Where(p => p is not null)
                .Select(p => p!.Value)
                .OrderBy(p => p)
                .ToList();

            if (steps.Count > 0 && !steps.Contains(2))
                ctx.Error(entry, "SetNoTwoPieceThreshold", "ssot-sets.md §3.4",
                    "every set has a threshold at 2, no exceptions; a set whose first bonus is at 3 "
                    + "has an invisible first step and cannot be splashed");

            if (steps.Count > 0 && steps[^1] > members.Count)
                ctx.Error(entry, "SetThresholdUnreachable", "ssot-sets.md §3.4",
                    $"top threshold is {steps[^1]} pieces but the set has {members.Count} members, "
                    + "so the last bonus can never be reached");

            // "A 6-piece set must also carry thresholds at 2 and 4, so a partial grand set is
            // playable and the last two pieces are a chase rather than a cliff."
            if (members.Count >= 6 && !steps.Contains(4))
                ctx.Error(entry, "SetGrandMissingStep", "ssot-sets.md §3.4",
                    $"a {members.Count}-piece set must carry a threshold at 4 as well as at 2, or "
                    + "the last two pieces are a cliff rather than a chase");
        }

        CheckNoUniqueMembers(ctx);
        CheckSpeciesId(ctx);
    }

    /// <summary>
    /// species-gear-chain T28 (set-species-binding b, spec-set-species-binding.md Success criterion
    /// 4/7): every non-absent `speciesId` must resolve to a real species. The corpus closure check
    /// itself — "844 of 844 creature.* themeKeys resolve" — runs at repair time (Python
    /// `species_repair.py`); this is the standing guard that keeps it true after a species rename,
    /// a registry regeneration, or a hand-authored `speciesId` slipping past review.
    ///
    /// <para>⛔ Reads <see cref="RegistrySet.CreatureSpeciesIds"/> — the SAME source the Python
    /// repair joins against (<c>gk-data/packs/fusion/data/seed/creatures/_registry/themes.v2.json</c>'s own
    /// <c>speciesId</c> column), never <c>CreatureSpeciesCatalog</c>: this tool "opens no database
    /// and issues no SQL" (its own header), and the catalog's compiled fallback
    /// (<c>CreatureSpeciesCatalog.Generated.cs</c>) is a stale, 84-species transitional fixture —
    /// checking against it would false-positive on most of the real 844. Centralized on
    /// <c>RegistrySet</c> (2026-09-20) so <see cref="Checks.ReferenceCheck"/>'s `creature.*` themeKey
    /// resolution and <see cref="Registries.NamespaceAllocation"/>'s species-set id allocation share
    /// this exact loader instead of each re-deriving it. A missing registry degrades to a warning,
    /// never a false error on every row, matching every other optional cross-reference this tool
    /// already reads (<see cref="DisplayCheck"/>'s own precedent).</para>
    /// </summary>
    static void CheckSpeciesId(ValidationContext ctx)
    {
        if (!ctx.Registries.CreatureSpeciesRegistryFound)
        {
            ctx.CorpusWarn("SetSpeciesRegistryAbsent", "spec-set-species-binding.md",
                "data/seed/creatures/_registry/themes.v2.json was not found above the working "
                + "directory, so speciesId resolution could not be checked");
            return;
        }

        foreach (var entry in ctx.Entries)
        {
            if (!string.Equals(entry.File.Kind, "set", StringComparison.Ordinal)) continue;
            if (entry.File.IsExemplar) continue;   // a pattern, not corpus content

            var speciesId = entry.AsString("speciesId");
            if (string.IsNullOrEmpty(speciesId)) continue;   // absent is legal — a build.*/theme.* set

            if (!ctx.Registries.CreatureSpeciesIds.Contains(speciesId))
                ctx.Error(entry, "SetSpeciesUnresolved", "spec-set-species-binding.md",
                    $"speciesId '{speciesId}' does not resolve in the creature theme registry — a "
                    + "non-absent speciesId must name a real species, never an invented or stale one");
        }
    }

    /// <summary>
    /// ssot-sets.md §3.8 / ssot-uniques.md §3.8 — hard no, for three stated reasons, the blunt one
    /// being that both classes cost 1.5 AE and a unique set piece is a piece paid for twice.
    /// </summary>
    static void CheckNoUniqueMembers(ValidationContext ctx)
    {
        var uniqueBaseTypes = ctx.Entries
            .Where(e => string.Equals(e.File.Kind, "unique", StringComparison.Ordinal) && !e.File.IsExemplar)
            .Select(e => e.AsString("baseType"))
            .Where(b => b is not null)
            .ToHashSet(StringComparer.Ordinal)!;

        if (uniqueBaseTypes.Count == 0) return;

        foreach (var entry in ctx.Entries)
        {
            if (!string.Equals(entry.File.Kind, "set", StringComparison.Ordinal)) continue;
            if (entry.File.IsExemplar) continue;   // a pattern, not corpus content
            var members = entry.Node["members"] as JsonArray ?? new JsonArray();

            foreach (var member in members.OfType<JsonObject>())
            {
                // A member may name a role (the exemplar's shape) or pin a specific base type.
                // Only the pinned form can collide with a unique.
                if (member["baseType"]?.GetValue<string>() is not { } pinned) continue;
                if (!uniqueBaseTypes.Contains(pinned)) continue;
                ctx.Error(entry, "UniqueSetMembership", "ssot-sets.md §3.8",
                    $"member pins base type '{pinned}', which a unique is already built on; both "
                    + "classes cost the same 1.5 AE premium, so the piece would be paid for twice");
            }
        }
    }
}
