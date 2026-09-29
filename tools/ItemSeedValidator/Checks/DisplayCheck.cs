using System.Text.Json.Nodes;
using FusionRpg.Core.Items.Display;
using FusionRpg.Tools.ItemSeedValidator.Model;

namespace FusionRpg.Tools.ItemSeedValidator.Checks;

/// <summary>
/// spec-item-card.md's four display reason codes, enforced against the real corpus (item module 10).
///
/// <para>⛔ <b>It owns no rule of its own.</b> The four rules live in Core
/// (<see cref="DisplayContentRules"/>), because a rule implemented inside a build tool cannot be
/// called by the importer later — and definitions §10's two-phase rule ("import is all-or-nothing,
/// load is per-row") means these have to be reachable from both. This file only reads the corpus and
/// maps each finding onto a <see cref="Finding"/>.</para>
///
/// <para><c>gk-content/content/display/en.json</c> lives outside the seed root, so it is located by walking up
/// from it. <b>Absence degrades, it never blocks</b> — the same precedent every optional registry here
/// follows (WordPoolAbsent, SocketCeilingTableAbsent): a scoped run that never had the file is not
/// evidence that 98 string keys are missing.</para>
/// </summary>
public static class DisplayCheck
{
    /// <summary>The finding code each rule id reports under. Kept as an explicit map rather than
    /// derived from the string so a rule id rename cannot silently rename a report column.</summary>
    static string CodeOf(string ruleId) => ruleId switch
    {
        DisplayRules.MissingUnitClass => "MissingUnitClass",
        DisplayRules.MissingDisplayTemplate => "MissingDisplayTemplate",
        DisplayRules.MissingDisplayKey => "MissingDisplayKey",
        DisplayRules.UnrenderedMagnitude => "UnrenderedMagnitude",
        _ => "DisplayRuleViolated",
    };

    public static void Run(ValidationContext ctx)
    {
        var families = new List<(SeedEntry Entry, DisplayFamilyFact Fact)>();
        var templates = new List<DisplayTemplateRow>();
        var templateEntries = new Dictionary<string, SeedEntry>(StringComparer.Ordinal);

        foreach (var entry in ctx.Entries)
        {
            if (entry.File.IsExemplar) continue;   // a pattern, not corpus content
            if (entry.Id is not { } id) continue;

            switch (entry.File.Kind)
            {
                case "affix-family":
                {
                    var pars = entry.Node["params"] as JsonObject;
                    families.Add((entry, new DisplayFamilyFact(
                        id,
                        Str(entry.Node, "kindId"),
                        pars is null ? "" : Str(pars, "channel"),
                        DeclaresMagnitude: pars?["amount"] is not null)));
                    break;
                }

                case "display-template":
                {
                    var runtimeFamily = Str(entry.Node, "runtimeFamily");
                    if (runtimeFamily.Length == 0) break;   // StructuralCheck already refuses this
                    templates.Add(new DisplayTemplateRow(
                        runtimeFamily,
                        Str(entry.Node, "nameKey"),
                        Str(entry.Node, "name"),
                        NullIfEmpty(Str(entry.Node, "plantOverrideKey")),
                        NullIfEmpty(Str(entry.Node, "plantOverrideName")),
                        Str(entry.Node, "groupId"),
                        Str(entry.Node, "status")));
                    templateEntries[runtimeFamily] = entry;
                    break;
                }
            }
        }

        // A scoped run that loaded neither corpus has nothing to say -- and saying it anyway would
        // report every template as orphaned, which is the RoleFamilyCheck lesson applied here.
        if (families.Count == 0 && templates.Count == 0) return;

        // MissingUnitClass reads the derived-stat registry, whose caps come from tuning and have no
        // built-in default on purpose (tunables-ssot.md T5). This tool never configured it -- nothing
        // in it touched the registry before -- so it configures it here, from the same file the Server
        // loads, and skips the one rule that needs it if the file is not reachable rather than
        // crashing a content sweep on a tuning path.
        var registry = TryBuildRegistry(ctx);
        if (registry is null) return;

        var findings = DisplayContentRules.Check(
            families.Select(f => f.Fact).ToList(), templates, LoadStringKeys(ctx), registry);

        // ⛔ "No template rows loaded" means the display corpus was not part of THIS run -- it does not
        // mean 98 families lost their templates. A scoped run (a single-fixture unit test, most
        // obviously) supplies one affix-family entry and nothing else, and reporting every one of them
        // as untemplated would fail that test for a reason with nothing to do with what it is testing.
        // Exactly the lesson RoleFamilyCheck's own `if (familyRoles.Count == 0) return;` records, and
        // it cost two of this tool's own tests before it was applied here. MissingUnitClass survives:
        // it reads only the entry in front of it, so it is right in a scoped run too.
        if (templates.Count == 0)
            findings = findings.Where(f => f.RuleId == DisplayRules.MissingUnitClass).ToList();

        var familyEntries = families.ToDictionary(f => f.Fact.FamilyId, f => f.Entry, StringComparer.Ordinal);

        foreach (var finding in findings)
        {
            var code = CodeOf(finding.RuleId);
            var entry = familyEntries.TryGetValue(finding.Subject, out var fe) ? fe
                : templateEntries.TryGetValue(finding.Subject, out var te) ? te
                : null;

            if (entry is null)
                ctx.CorpusError(code, finding.RuleId, $"{finding.Subject}: {finding.Detail}");
            else
                ctx.Error(entry, code, finding.RuleId, finding.Detail);
        }
    }

    /// <summary>
    /// The derived-stat registry, with its tuning configured from the same file the Server loads.
    /// <c>null</c> when the tuning is not reachable — the whole check is then skipped with a warning
    /// rather than crashing a content sweep on a tuning path, and rather than reporting every
    /// channel-bearing family as unitless, which would be a false accusation on ~60 good rows.
    /// </summary>
    static FusionRpg.Core.Stats.Derived.DerivedStatRegistry? TryBuildRegistry(ValidationContext ctx)
    {
        try
        {
            if (FindUpwards(Path.Combine("data", "tuning")) is not { } tuningDir)
            {
                ctx.CorpusWarn("DisplayTuningAbsent", "tunables-ssot.md T5",
                    "data/tuning/ was not found above the working directory, so the four display rules "
                    + "could not run -- MissingUnitClass reads the derived-stat registry, whose caps have "
                    + "no built-in default by design");
                return null;
            }

            var file = Directory.GetFiles(tuningDir, "derived-stats.v*.json")
                .OrderByDescending(f => f, StringComparer.Ordinal)
                .FirstOrDefault();
            if (file is null)
            {
                ctx.CorpusWarn("DisplayTuningAbsent", "tunables-ssot.md T5",
                    $"no derived-stats.v*.json under {tuningDir}; the four display rules did not run");
                return null;
            }

            FusionRpg.Core.Stats.Derived.DerivedStatPolicy.Configure(
                FusionRpg.Core.Stats.Derived.DerivedStatTuningLoader.Parse(File.ReadAllText(file)));
            return FusionRpg.Core.Stats.Derived.DerivedStatRegistry.CreateDefault();
        }
        catch (Exception ex) when (ex is IOException or System.Text.Json.JsonException
                                       or FusionRpg.Core.Stats.Derived.DerivedStatTuningRejection)
        {
            ctx.CorpusWarn("DisplayTuningAbsent", "tunables-ssot.md T5",
                $"derived-stat tuning could not be loaded ({ex.Message}); the four display rules did not run");
            return null;
        }
    }

    /// <summary>Every key <c>gk-content/content/display/en.json</c> defines, or <c>null</c> when it is not
    /// reachable — absence degrades to "skip the key rule", the same precedent every optional registry
    /// here follows, never to a false positive on all 98 rows.</summary>
    static IReadOnlySet<string>? LoadStringKeys(ValidationContext ctx)
    {
        var path = FindUpwards(Path.Combine("content", "display", "en.json"), file: true);
        if (path is not null && JsonNode.Parse(File.ReadAllText(path)) is JsonObject node)
            return node.Select(p => p.Key).ToHashSet(StringComparer.Ordinal);

        ctx.CorpusWarn("DisplayStringCatalogAbsent", DisplayRules.MissingDisplayKey,
            "content/display/en.json was not found above the working directory, so template string "
            + "keys could not be checked -- the other three display rules still ran");
        return null;
    }

    /// <summary>Walks up from the working directory. The tool is always run from inside the repo, and
    /// its own seed root is <c>&lt;repo&gt;/data/seed/items</c>.</summary>
    static string? FindUpwards(string relative, bool file = false)
    {
        var probe = new DirectoryInfo(Directory.GetCurrentDirectory());
        while (probe is not null)
        {
            var candidate = Path.Combine(probe.FullName, relative);
            if (file ? File.Exists(candidate) : Directory.Exists(candidate)) return candidate;
            probe = probe.Parent;
        }
        return null;
    }

    static string Str(JsonNode? node, string name) =>
        node?[name] is JsonValue v && v.TryGetValue<string>(out var s) ? s : "";

    static string? NullIfEmpty(string s) => s.Length == 0 ? null : s;
}
