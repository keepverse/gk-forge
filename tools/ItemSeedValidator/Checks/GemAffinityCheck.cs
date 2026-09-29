using System.Text.Json.Nodes;
using FusionRpg.Tools.ItemSeedValidator.Model;

namespace FusionRpg.Tools.ItemSeedValidator.Checks;

/// <summary>
/// The socket layer's own vocabulary on the shipped gem corpus (spec-sockets.md §6, module 16).
///
/// <para>Two rules, both from <c>element-hub-ssot.md</c> §4 by way of the socket lane:</para>
/// <list type="number">
/// <item><c>affinityElement</c> names a <b>concrete</b> element. <c>omni</c> is <b>not an affinity</b>
/// — it is the additive baseline, not an actor type slot — so a gem declaring an omni affinity names a
/// socket that can never exist, and its "attuned" bonus can never fire.</item>
/// <item><c>element</c> names a concrete element, <c>omni</c>, or is absent. An unknown element would
/// contribute to no resonance shape while looking like it should.</item>
/// </list>
///
/// <para>Both are ERRORS rather than warnings: an insert whose affinity can never match is a row that
/// promises a bonus the evaluator will never grant, which is SC7's "a lie in a table" exactly.</para>
/// </summary>
public static class GemAffinityCheck
{
    static readonly HashSet<string> Concrete =
        new(new[] { "fire", "ice", "air", "earth", "light", "dark" }, StringComparer.Ordinal);

    const string Omni = "omni";

    public static void Run(ValidationContext ctx)
    {
        foreach (var entry in ctx.Entries)
        {
            if (entry.File.Kind != "gem") continue;
            if (entry.File.IsExemplar) continue; // a pattern, not corpus content
            if (entry.Node["enabled"] is JsonValue en && en.TryGetValue<bool>(out var enabled) && !enabled) continue;

            var affinity = entry.AsString("affinityElement");
            if (affinity is not null && !Concrete.Contains(affinity))
                ctx.Error(entry, "GemAffinityNotConcrete", "spec-sockets.md §6 / element-hub-ssot.md §4",
                    $"'{entry.Label}': affinityElement '{affinity}' is not a concrete element" +
                    (affinity == Omni
                        ? " — `omni` is the additive baseline, never a socket affinity, so this gem's attuned bonus can never fire"
                        : ""));

            var element = entry.AsString("element");
            if (element is not null && element.Length > 0 && !Concrete.Contains(element) && element != Omni)
                ctx.Error(entry, "GemElementUnknown", "spec-sockets.md §8 / element-hub-ssot.md §4",
                    $"'{entry.Label}': element '{element}' is neither a concrete element nor 'omni', so it " +
                    "contributes to no resonance shape at all");
        }
    }
}
