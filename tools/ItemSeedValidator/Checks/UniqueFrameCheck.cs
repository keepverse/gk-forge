using System.Text.Json.Nodes;
using FusionRpg.Tools.ItemSeedValidator.Model;

namespace FusionRpg.Tools.ItemSeedValidator.Checks;

/// <summary>
/// ssot-uniques.md §3.5's <b>physics</b> carve-out on the shipped unique corpus (module 17).
///
/// <para>The lane draws a line inside the frame filter that no registry encoded, so nothing mechanical
/// enforced it: <i>"a unique may bypass it where the reason is flavour; it may not bypass it where the
/// reason is that the Unity field does not exist. `plating` and `carapace` write `arm1`/`arm2`, which
/// are zombie-only fields — a plant unique carrying either is not daring, it is dead."</i></para>
///
/// <para>The rule is checked against the <b>affix family's own <c>frames</c> list</b>, not against a
/// hardcoded pair of family ids: the two families the lane names are examples of the class, and the
/// corpus turned out to carry two different members of it. A family with no <c>frames</c> list, or one
/// this run cannot resolve, is skipped — <c>ReferenceUnresolved</c> owns that.</para>
///
/// <para>An ERROR, not a warning: the atom loads, the container validates, the item drops, and the
/// executor silently drops the line for that side. The player's reward is a stat that does nothing,
/// which is SC7's "a lie in a table" wearing an item's clothes.</para>
/// </summary>
public static class UniqueFrameCheck
{
    public static void Run(ValidationContext ctx)
    {
        // familyId -> the frames that family may sit on, from the affix-family corpus itself.
        var frames = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
        foreach (var entry in ctx.Entries)
        {
            if (!string.Equals(entry.File.Kind, "affix-family", StringComparison.Ordinal)) continue;
            if (entry.Id is not { } famId) continue;
            if (entry.Node["frames"] is not JsonArray arr || arr.Count == 0) continue;

            var set = new HashSet<string>(StringComparer.Ordinal);
            foreach (var f in arr)
                if (f is JsonValue v && v.TryGetValue<string>(out var s)) set.Add(s);
            if (set.Count > 0) frames[famId] = set;
        }

        if (frames.Count == 0) return;   // no family corpus loaded — nothing to check against

        foreach (var entry in ctx.Entries)
        {
            if (!string.Equals(entry.File.Kind, "unique", StringComparison.Ordinal)) continue;
            if (entry.File.IsExemplar) continue;   // a pattern, not corpus content
            if (entry.AsString("frame") is not { } frame) continue;

            foreach (var famId in FamiliesOf(entry))
            {
                if (!frames.TryGetValue(famId, out var allowed)) continue;
                if (allowed.Contains(frame)) continue;

                ctx.Error(entry, "UniqueFrameImpossible", "ssot-uniques.md §3.5",
                    $"'{entry.Label}' is a {frame} unique carrying family '{famId}', which the family " +
                    $"corpus restricts to {string.Join("/", allowed.OrderBy(x => x, StringComparer.Ordinal))}. " +
                    "A unique may bypass the frame filter where the filter is TASTE; where it is physics — " +
                    "a channel that only exists on the other side — the executor drops the line and the " +
                    "item is dead rather than daring");
            }
        }
    }

    static IEnumerable<string> FamiliesOf(SeedEntry entry)
    {
        if (entry.Node["fixedAtoms"] is JsonArray fixedAtoms)
            foreach (var a in fixedAtoms)
                if (a?["family"] is JsonValue v && v.TryGetValue<string>(out var s))
                    yield return s;

        if (entry.Node["varianceSlot"]?["family"] is JsonValue vv && vv.TryGetValue<string>(out var variance))
            yield return variance;
    }
}
