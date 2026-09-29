using System.Text.Json.Nodes;
using FusionRpg.Tools.ItemSeedValidator.Model;

namespace FusionRpg.Tools.ItemSeedValidator.Checks;

/// <summary>
/// `nameWords` shape, re-keyed 2026-09-04 (item-ideal.md, `affix-legality` module 8): every row is
/// `{band|variant, word, wordPlant?}`, never a bare string. A band-keyed family's bands must form a
/// contiguous run starting at A (most families are A/B/C; a handful use fewer or more letters — see
/// `RoleFamilyTable.cs`'s doc comment) — a naming lookup that misses a band inside that run throws at
/// the worst possible time, a real drop.
/// </summary>
public static class NameWordCheck
{
    public static void Run(ValidationContext ctx)
    {
        foreach (var entry in ctx.Entries)
        {
            if (entry.File.Kind != "affix-family") continue;
            if (entry.File.IsExemplar) continue; // a pattern, not corpus content
            if (entry.Node["nameWords"] is not JsonObject nameWords) continue;

            foreach (var slot in new[] { "prefix", "suffix" })
            {
                if (nameWords[slot] is not JsonArray rows) continue;
                CheckSlot(ctx, entry, slot, rows);
            }
        }
    }

    static void CheckSlot(ValidationContext ctx, SeedEntry entry, string slot, JsonArray rows)
    {
        var bandsSeen = new List<string>();
        var variantsSeen = new List<string>();

        foreach (var rowNode in rows)
        {
            if (rowNode is not JsonObject row)
            {
                ctx.Error(entry, "NameWordNotRekeyed", "seed-contract.md (affix family)",
                    $"'{entry.Label}'.nameWords.{slot}: row is a bare string -- the flat shape was retired, every row is now an object");
                continue;
            }

            var hasBand = row["band"] is JsonValue b && b.TryGetValue<string>(out _);
            var hasVariant = row["variant"] is JsonValue v && v.TryGetValue<string>(out _);
            if (hasBand == hasVariant)
            {
                ctx.Error(entry, "NameWordKeyAmbiguous", "seed-contract.md (affix family)",
                    $"'{entry.Label}'.nameWords.{slot}: row must carry exactly one of 'band' or 'variant'");
                continue;
            }

            if (row["word"] is not JsonValue w || !w.TryGetValue<string>(out var word) || string.IsNullOrEmpty(word))
                ctx.Error(entry, "NameWordMissing", "seed-contract.md (affix family)",
                    $"'{entry.Label}'.nameWords.{slot}: row is missing 'word'");

            if (hasBand) bandsSeen.Add(row["band"]!.GetValue<string>());
            if (hasVariant) variantsSeen.Add(row["variant"]!.GetValue<string>());
        }

        if (bandsSeen.Count > 0)
        {
            var dup = bandsSeen.GroupBy(b => b).Where(g => g.Count() > 1).Select(g => g.Key).ToList();
            if (dup.Count > 0)
                ctx.Error(entry, "NameWordBandDuplicated", "seed-contract.md (affix family)",
                    $"'{entry.Label}'.nameWords.{slot}: band(s) {string.Join(", ", dup)} appear more than once");

            // The bands present must be a contiguous run starting at 'A' -- families use different
            // letter counts (one word: just A; four words: A-D; most: A-C), never a gap in the middle.
            var expected = Enumerable.Range(0, bandsSeen.Count).Select(i => ((char)('A' + i)).ToString()).ToHashSet(StringComparer.Ordinal);
            var missing = expected.Except(bandsSeen, StringComparer.Ordinal).ToList();
            if (missing.Count > 0)
                ctx.Error(entry, "NameWordBandNotContiguous", "seed-contract.md (affix family)",
                    $"'{entry.Label}'.nameWords.{slot}: bands [{string.Join(",", bandsSeen)}] are not a contiguous run starting at A");
        }

        if (variantsSeen.Count > 0)
        {
            var dup = variantsSeen.GroupBy(v => v).Where(g => g.Count() > 1).Select(g => g.Key).ToList();
            if (dup.Count > 0)
                ctx.Error(entry, "NameWordVariantDuplicated", "seed-contract.md (affix family)",
                    $"'{entry.Label}'.nameWords.{slot}: variant(s) {string.Join(", ", dup)} appear more than once");
        }
    }
}
