using System.Text.Json.Nodes;
using FusionRpg.Tools.ItemSeedValidator.Model;
using FusionRpg.Tools.ItemSeedValidator.Registries;

namespace FusionRpg.Tools.ItemSeedValidator.Checks;

/// <summary>
/// D11 clause 1 at seed time (spec-base-types.md, item module 6): every role's humanoid and plant
/// `implicit.family` sets must be disjoint. Retired entries (`enabled: false`, the `standard` role's
/// legacy rows — D14, out of scope) are excluded: dead content cannot violate a live-content rule.
/// </summary>
public static class FrameDirectionCheck
{
    public static void Run(ValidationContext ctx)
    {
        // classes.v3.json (2026-09-12) adds a per-frame slate alongside the role-wide union. The
        // authority for an entry is ITS FRAME's set, so read that first and fall back to the union
        // for a v2-shaped fixture.
        var legalByRole = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
        var legalByRoleFrame = new Dictionary<(string Role, string Frame), HashSet<string>>();
        if (ctx.Registries.Classes["implicitSlates"] is JsonObject slates)
            foreach (var slate in slates)
                if (slate.Value is JsonObject node)
                {
                    legalByRole[slate.Key] =
                        RegistrySet.Strings(node["legalFamilies"]).ToHashSet(StringComparer.Ordinal);
                    if (node["legalFamiliesByFrame"] is JsonObject byFrame)
                        foreach (var frameEntry in byFrame)
                            if (frameEntry.Value is JsonArray arr)
                                legalByRoleFrame[(slate.Key, frameEntry.Key)] =
                                    RegistrySet.Strings(arr).ToHashSet(StringComparer.Ordinal);
                }

        var byRoleFrame = new Dictionary<(string Role, string Frame), List<SeedEntry>>();
        foreach (var entry in ctx.Entries)
        {
            if (entry.File.Kind != "base-type") continue;
            if (entry.File.IsExemplar) continue; // a pattern, not corpus content
            if (entry.Node["enabled"] is JsonValue en && en.TryGetValue<bool>(out var enabled) && !enabled) continue;

            var role = entry.AsString("role");
            var frame = entry.AsString("frame");
            if (role is null || frame is null) continue;

            var family = FamilyOf(entry);
            // The entry's own FRAME slate is the contract when the registry carries one; the
            // role-wide union is the fallback so an older fixture still validates.
            var hasFrameSlate = legalByRoleFrame.TryGetValue((role, frame), out var frameLegal);
            var legal = hasFrameSlate ? frameLegal! : legalByRole.GetValueOrDefault(role);
            if (family is not null && legal is not null && !legal.Contains(family))
                ctx.Error(entry, "ImplicitFamilyNotLegalForRole",
                    hasFrameSlate ? "classes.v3.json legalFamiliesByFrame" : "classes.v2.json implicitSlates",
                    $"'{entry.Label}': implicit family '{family}' is not in role '{role}' frame "
                    + $"'{frame}''s legal slate");

            var key = (role, frame);
            if (!byRoleFrame.TryGetValue(key, out var list)) byRoleFrame[key] = list = new List<SeedEntry>();
            list.Add(entry);
        }

        foreach (var role in byRoleFrame.Keys.Select(k => k.Role).Distinct(StringComparer.Ordinal).OrderBy(r => r, StringComparer.Ordinal))
        {
            var humanoid = byRoleFrame.GetValueOrDefault((role, "humanoid"), new List<SeedEntry>());
            var plant = byRoleFrame.GetValueOrDefault((role, "plant"), new List<SeedEntry>());
            if (humanoid.Count == 0 || plant.Count == 0) continue;

            var hFamilies = humanoid.Select(FamilyOf).Where(f => f is not null).ToHashSet(StringComparer.Ordinal)!;
            var pFamilies = plant.Select(FamilyOf).Where(f => f is not null).ToHashSet(StringComparer.Ordinal)!;

            var overlap = hFamilies.Intersect(pFamilies, StringComparer.Ordinal).ToList();
            if (overlap.Count > 0)
                ctx.CorpusError("FrameImplicitNotDisjoint", "spec-base-types.md D11 clause 1",
                    $"role '{role}': humanoid and plant implicit families are not disjoint — shared: {string.Join(", ", overlap)}");
        }

        EmitFlavourDriftWarnings(ctx);
    }

    /// <summary>
    /// D11's prose half (`spec-base-types.md` "Ask first"): an entry keeps its name and flavor while
    /// its `implicit.family` changes, so prose written for one family can end up over another. A
    /// re-slate therefore leaves drift behind, and the spec names this module's job as a WARNING
    /// only — *"the authoring fleet ... this module emits an `ImplicitFlavourDrift` warning per
    /// entry; it does not call a model"*. So re-flavouring is NOT done here; the warning makes the
    /// debt visible to the fleet that owns it.
    ///
    /// <para><b>How drift is detected without a model.</b> Each family's own display name
    /// (`affix-families` entries) is its vocabulary. A row is flagged when its `flavor` mentions a
    /// word from a DIFFERENT family's vocabulary and none from its own — prose that names the thing
    /// the entry no longer is. That is a conservative signal: it misses silent prose, and it
    /// deliberately does not flag a row whose prose is family-neutral.</para>
    /// </summary>
    static void EmitFlavourDriftWarnings(ValidationContext ctx)
    {
        var vocabulary = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
        foreach (var entry in ctx.Entries)
        {
            if (entry.File.Kind != "affix-family") continue;
            var familyId = entry.AsString("id");
            var display = entry.AsString("name");
            if (familyId is null || display is null) continue;
            vocabulary[familyId] = Words(display);
        }
        if (vocabulary.Count == 0) return;

        // A word shared by many families is not evidence of anything; require a distinctive word.
        var wordFamilyCount = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var words in vocabulary.Values)
            foreach (var w in words)
                wordFamilyCount[w] = wordFamilyCount.GetValueOrDefault(w) + 1;

        foreach (var entry in ctx.Entries)
        {
            if (entry.File.Kind != "base-type") continue;
            if (entry.File.IsExemplar) continue;
            if (entry.Node["enabled"] is JsonValue en && en.TryGetValue<bool>(out var enabled) && !enabled) continue;

            var family = FamilyOf(entry);
            var flavor = entry.AsString("flavor");
            if (family is null || string.IsNullOrWhiteSpace(flavor)) continue;
            if (!vocabulary.TryGetValue(family, out var own)) continue;

            var words = Words(flavor);
            if (words.Overlaps(own)) continue; // prose already names its own family — fine

            var foreign = words.Where(w => wordFamilyCount.GetValueOrDefault(w) == 1
                                           && vocabulary.Any(kv => kv.Key != family && kv.Value.Contains(w)))
                .OrderBy(w => w, StringComparer.Ordinal).ToList();
            if (foreign.Count > 0)
                ctx.Warn(entry, "ImplicitFlavourDrift", "spec-base-types.md D11 (flavour half)",
                    $"'{entry.Label}': flavor names '{foreign[0]}', from another family, while the "
                    + $"entry's implicit is '{family}' — owed a re-flavour by the authoring fleet");
        }
    }

    static HashSet<string> Words(string text) =>
        new(System.Text.RegularExpressions.Regex.Matches(text.ToLowerInvariant(), "[a-z]{4,}")
            .Select(m => m.Value), StringComparer.Ordinal);

    static string? FamilyOf(SeedEntry e) =>
        e.Node["implicit"] is JsonObject implicitObj && implicitObj["family"] is JsonValue f && f.TryGetValue<string>(out var s)
            ? s : null;
}
