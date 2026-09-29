using System.Text.RegularExpressions;
using FusionRpg.Tools.ItemSeedValidator.Model;
using FusionRpg.Tools.ItemSeedValidator.Registries;

namespace FusionRpg.Tools.ItemSeedValidator.Checks;

/// <summary>
/// seed-contract.md §4 — the namespace is allocated, the sequence is the agent's. Global
/// uniqueness is the safety net; the prefix allocation is the mechanism. This check also assigns
/// each entry its partition, which is how every later finding gets grouped for a fix pass.
/// </summary>
public static class IdentityCheck
{
    /// <summary>definitions.md §1: a container_id body carries no dot. Two lanes learned this the hard way.</summary>
    public static readonly Regex ContainerIdGrammar =
        new(@"^(item|trait|skill|species-passive|patron|world-buff)\.[a-z0-9-]+$", RegexOptions.Compiled);

    static readonly Regex ContainerIdPrefix =
        new(@"^(item|trait|skill|species-passive|patron|world-buff)\.", RegexOptions.Compiled);

    /// <summary>General authored-id shape: lowercase kebab segments separated by dots.</summary>
    public static readonly Regex IdGrammar =
        new(@"^[a-z][a-z0-9]*(\.[a-z0-9]+(-[a-z0-9]+)*)+$", RegexOptions.Compiled);

    static readonly Regex ThreeDigit = new(@"^\d{3}$", RegexOptions.Compiled);
    static readonly Regex AffixWord = new(@"^[a-z0-9]+(-[a-z0-9]+)*$", RegexOptions.Compiled);
    static readonly Regex AffixFallback = new(@"^x\d{3}$", RegexOptions.Compiled);

    public static void Run(ValidationContext ctx)
    {
        foreach (var entry in ctx.Entries)
        {
            var id = entry.AsString("id");
            if (id is null)
            {
                if (entry.Node["id"] is not null)
                    ctx.Error(entry, "IdNotString", "seed-contract.md §4", "id is not a string");
                continue;
            }

            CheckGrammar(ctx, entry, id);
            CheckNamespace(ctx, entry, id);
            CheckUniqueness(ctx, entry, id);
            CheckRetired(ctx, entry, id);
        }

        CheckPartitionCohesion(ctx);
    }

    static void CheckGrammar(ValidationContext ctx, SeedEntry entry, string id)
    {
        if (!IdGrammar.IsMatch(id))
        {
            ctx.Error(entry, "IdGrammar", "seed-contract.md §4",
                $"id '{id}' is not lowercase-kebab segments separated by dots");
            return;
        }

        // The no-dot-in-body rule applies to every id that is, or feeds, a container_id.
        if (!ContainerIdPrefix.IsMatch(id)) return;
        var body = id[(id.IndexOf('.') + 1)..];
        if (body.Contains('.'))
            ctx.Error(entry, "ContainerIdDotInBody", "seed-contract.md §4 / definitions.md §1",
                $"id '{id}' is a container_id and its body '{body}' contains a dot; separate "
                + "segments with hyphens, never dots");
        else if (!ContainerIdGrammar.IsMatch(id))
            ctx.Error(entry, "ContainerIdGrammar", "definitions.md §1",
                $"id '{id}' does not match the container_id grammar {ContainerIdGrammar}");
    }

    /// <summary>
    /// An affix family that already ships keeps its existing `atom.&lt;name&gt;` id verbatim —
    /// naming.v1.json says so explicitly, and re-minting one would orphan every reference the
    /// engine already holds. Those ids predate the partition namespaces and sit outside all of
    /// them by design, so the namespace rule cannot apply to them.
    ///
    /// A newly minted family carries its group's stem and a hyphen (`atom.sust-callus`); a shipped
    /// one is a single bare word (`atom.regeneration`).
    /// </summary>
    static bool IsShippedFamilyId(SeedEntry entry, string id) =>
        string.Equals(entry.File.Kind, "affix-family", StringComparison.Ordinal)
        && id.StartsWith("atom.", StringComparison.Ordinal)
        && !id.AsSpan("atom.".Length).Contains('-');

    /// <summary>
    /// A NEW (not pre-existing) family whose id is nonetheless already claimed as a KEY in
    /// `gk-data/packs/fusion/data/seed/actions/pairings.json` — `atom.chill-punisher`/`atom.rot-punisher` are the found
    /// case (item-seed-regen coordinator item 3, 2026-09-20): genuinely minted in 2026-09-06, so
    /// <see cref="IsShippedFamilyId"/>'s "predates the partition namespaces" reasoning does not
    /// apply to them, and their body is hyphenated so its no-hyphen check would reject them anyway.
    /// But `EnablerPayoffPairings.IsPayoff` (a real, tested C# consumer) already matches them by
    /// this exact literal string, so renaming to fit `atom.{stem}-{word}` would silently orphan that
    /// lookup — the SAME failure <see cref="IsShippedFamilyId"/> exists to prevent, just from a
    /// different (cross-corpus) source of "already load-bearing". See
    /// <see cref="RegistrySet.EnablerPayoffPairingFamilyIds"/> for why this is read live rather
    /// than a two-id special case.
    /// </summary>
    static bool IsCrossReferencedPayoffFamily(ValidationContext ctx, SeedEntry entry, string id) =>
        string.Equals(entry.File.Kind, "affix-family", StringComparison.Ordinal)
        && ctx.Registries.EnablerPayoffPairingFamilyIds.Contains(id);

    static void CheckNamespace(ValidationContext ctx, SeedEntry entry, string id)
    {
        if (IsShippedFamilyId(entry, id)) return;
        if (IsCrossReferencedPayoffFamily(ctx, entry, id)) return;

        var match = ctx.Allocation.Match(id);
        if (match is null)
        {
            ctx.Error(entry, "IdOutsideNamespace", "seed-contract.md §4 / naming.v1.json idNamespaces",
                $"id '{id}' begins with no prefix allocated to any wave-1 partition; an agent owns "
                + "only the sequence inside its own prefix");
            return;
        }

        entry.Partition = match.PartitionId;
        entry.Stage = match.Stage;
        entry.Allocation = match;

        if (entry.File.Kind is { } kind && !string.Equals(kind, match.Kind, StringComparison.Ordinal))
            ctx.Error(entry, "IdKindMismatch", "naming.v1.json idNamespaces",
                $"id '{id}' belongs to the '{match.Kind}' namespace but the file declares kind '{kind}'");

        var tail = match.Shape == SequenceShape.Fixed ? "" : id[match.Prefix.Length..];
        var reg = ctx.Registries;

        switch (match.Shape)
        {
            case SequenceShape.Fixed:
                break;

            case SequenceShape.Derived:
                // No grammar left to check: the tail is whatever the deterministic generator (a grid
                // cell, not an author) produced. The prefix match above is the whole review.
                break;

            case SequenceShape.ThreeDigit:
                if (!ThreeDigit.IsMatch(tail))
                {
                    ctx.Error(entry, "SequenceGrammar", "naming.v1.json idPolicy",
                        $"id '{id}' must end in a zero-padded 3-digit sequence after '{match.Prefix}', not '{tail}'");
                    break;
                }
                var seq = int.Parse(tail);
                if (seq < reg.SequenceMin)
                    ctx.Error(entry, "SequenceOutOfRange", "naming.v1.json idPolicy",
                        $"sequence {tail} is below the wave-1 range {reg.SequenceMin:000}-{reg.SequenceMax:000}");
                else if (seq > reg.SequenceMax)
                    ctx.Error(entry, "SequenceReserved", "naming.v1.json idPolicy",
                        $"sequence {tail} is inside {reg.SequenceMax + 1:000}-999, reserved in every "
                        + "partition for later hand-authored corrections");
                break;

            case SequenceShape.AffixWord:
                if (AffixFallback.IsMatch(tail))
                    ctx.Warn(entry, "AffixFallbackId", "naming.v1.json idNamespaces.affixFamilies",
                        $"id '{id}' uses the anonymous 'x{tail[1..]}' checkpoint form; it must be "
                        + "replaced with a real word before this partition is final");
                else if (!AffixWord.IsMatch(tail))
                    ctx.Error(entry, "AffixWordGrammar", "naming.v1.json idNamespaces.affixFamilies",
                        $"id '{id}' must be atom.{{stem}}-{{word}} with a lowercase-kebab word, not '{tail}'");
                break;
        }
    }

    static void CheckUniqueness(ValidationContext ctx, SeedEntry entry, string id)
    {
        // An exemplar demonstrates a real partition using its real namespace — that is what makes
        // it a usable pattern rather than an abstract one. It therefore claims ids the actual
        // partition will legitimately author later, and the two are not in conflict: the exemplar
        // is not corpus content and is never imported. Grammar and namespace rules still apply to
        // it; only global uniqueness does not.
        if (entry.File.IsExemplar) return;

        if (ctx.ById.TryGetValue(id, out var first))
        {
            ctx.Error(entry, "IdDuplicate", "seed-contract.md §4",
                $"id '{id}' is already claimed by {first.File.RelativePath}"
                + (first.Partition == Finding.NoPartition ? "" : $" (partition {first.Partition})"));
            return;
        }
        ctx.ById[id] = entry;
    }

    static void CheckRetired(ValidationContext ctx, SeedEntry entry, string id)
    {
        var disabled = entry.Node["enabled"] is { } e
                       && e.GetValueKind() == System.Text.Json.JsonValueKind.False;
        if (disabled)
        {
            // Content is disabled, never deleted, and the id is retired forever.
            ctx.RetiredHere.Add(id);
            return;
        }

        if (ctx.Registries.Retired.Contains(id))
            ctx.Error(entry, "RetiredIdReused", "seed-contract.md §4/§7.2",
                $"id '{id}' is in the retired ledger; a reused id silently repoints every "
                + "reference that already resolved to it");
    }

    /// <summary>
    /// One file, one partition. An agent writes only under its own prefix, so a file whose entries
    /// span two allocations means someone reached outside their namespace.
    /// </summary>
    static void CheckPartitionCohesion(ValidationContext ctx)
    {
        foreach (var file in ctx.Files)
        {
            var partitions = file.Entries
                .Where(e => e.Partition != Finding.NoPartition)
                .Select(e => e.Partition)
                .Distinct(StringComparer.Ordinal)
                .Order(StringComparer.Ordinal)
                .ToList();

            if (partitions.Count > 1)
                ctx.FileError(file, "PartitionMixed", "authoring-fleet-plan.md §1",
                    "entries span more than one allocated partition ("
                    + string.Join(", ", partitions)
                    + "); one authored unit per file, one file per agent");

            if (partitions.Count != 1) continue;

            // _meta.partition is a free-form label, so treat a disagreement as a lint, not a stop.
            var declared = file.Meta?["partition"]?.GetValueKind() == System.Text.Json.JsonValueKind.String
                ? file.Meta!["partition"]!.GetValue<string>()
                : null;
            if (declared is null) continue;

            // The contract's own example writes the partition with the frame DISPLAY word
            // ("plant/crown/a") while the allocation is keyed on the role id, so compare against
            // the allocation's token set rather than its label.
            var known = file.Entries.FirstOrDefault(e => e.Allocation is not null)?.Allocation?.Tokens;
            var tokens = declared.Split(new[] { '/', '\\', '-', '.' }, StringSplitOptions.RemoveEmptyEntries);
            if (tokens.Length == 0) continue;
            if (known is not null && tokens.All(known.Contains)) continue;
            if (known is null && tokens.All(t => partitions[0].Contains(t, StringComparison.OrdinalIgnoreCase)))
                continue;
            ctx.FileWarn(file, "PartitionMetaMismatch", "seed-contract.md §9",
                $"_meta.partition is '{declared}' but the ids allocate to '{partitions[0]}'");
        }
    }
}
