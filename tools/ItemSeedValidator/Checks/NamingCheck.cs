using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using FusionRpg.Tools.ItemSeedValidator.Model;
using FusionRpg.Tools.ItemSeedValidator.Naming;

namespace FusionRpg.Tools.ItemSeedValidator.Checks;

/// <summary>
/// seed-contract.md §5 and §6 — the grammar, the collision normalizer, and the locale rules.
/// Ashen Fang / Ash Fang / Fang of Ash / Ashfang are four names and one idea; catching that is
/// this check's reason to exist, and it belongs here rather than in a reviewer's judgement.
/// </summary>
public static class NamingCheck
{
    static readonly Regex NameKeyGrammar = new(@"^[a-z0-9.-]+$", RegexOptions.Compiled);
    const string Word = @"[A-Z][a-z]+(?:-[A-Z]?[a-z]+)*";
    static readonly Regex Compound = new($"^{Word} {Word}$", RegexOptions.Compiled);
    static readonly Regex OfConstruct = new($"^{Word} of (?:the )?{Word}(?: {Word})?$", RegexOptions.Compiled);
    static readonly Regex Fusion = new($"^{Word}$", RegexOptions.Compiled);
    static readonly Regex GeneratedOnly = new($"^{Word} {Word} of (?:the )?{Word}(?: {Word})?$", RegexOptions.Compiled);

    /// <summary>Markup a presentation layer owns, never an authored string (seed-contract.md §6).</summary>
    static readonly (Regex Pattern, string What)[] Markup =
    {
        (new Regex(@"<[^>]+>", RegexOptions.Compiled), "an HTML/XML tag"),
        (new Regex(@"\[[^\]]+\]", RegexOptions.Compiled), "a bracket tag"),
        (new Regex(@"&[a-zA-Z]+;|&#\d+;", RegexOptions.Compiled), "an HTML entity"),
        (new Regex(@"\*\*|__", RegexOptions.Compiled), "markdown emphasis"),
        (new Regex("`", RegexOptions.Compiled), "a backtick"),
    };

    static readonly Regex Placeholder = new(@"\{[^}]*\}", RegexOptions.Compiled);

    /// <summary>Fields whose braces are the mechanism, not markup.</summary>
    static readonly string[] TemplateFields = { "displayTemplate", "params", "variants", "channel" };

    public static void Run(ValidationContext ctx)
    {
        var byNameKey = new Dictionary<string, SeedEntry>(StringComparer.Ordinal);
        var byNormalized = new Dictionary<string, SeedEntry>(StringComparer.Ordinal);

        foreach (var entry in ctx.Entries)
        {
            CheckNameKey(ctx, entry, byNameKey);
            CheckName(ctx, entry, byNormalized);
            CheckMarkup(ctx, entry);
        }
    }

    static void CheckNameKey(ValidationContext ctx, SeedEntry entry, Dictionary<string, SeedEntry> seen)
    {
        var key = entry.AsString("nameKey");
        if (key is null) return;

        if (!NameKeyGrammar.IsMatch(key))
        {
            ctx.Error(entry, "NameKeyGrammar", "seed-contract.md §6",
                $"nameKey '{key}' must match ^[a-z0-9.-]+$");
        }
        else
        {
            var prefix = key.Split('.')[0];
            var prefixes = ctx.Registries.NameKeyPrefixes;
            if (prefixes.Count > 0 && !prefixes.Contains(prefix, StringComparer.Ordinal))
                ctx.Error(entry, "NameKeyPrefix", "naming.v1.json namingGrammar.nameKey",
                    $"nameKey '{key}' starts with '{prefix}', which is not one of the registered "
                    + $"kind prefixes ({string.Join(", ", prefixes)})");
        }

        if (entry.File.IsExemplar) return;   // see ExemptFromGlobalUniqueness

        if (seen.TryGetValue(key, out var first))
            ctx.Error(entry, "NameKeyDuplicate", "seed-contract.md §6",
                $"nameKey '{key}' is already used by {first.Label} in {first.File.RelativePath}"
                + $"{(first.Partition == Finding.NoPartition ? "" : $" (partition {first.Partition})")}; "
                + "nameKey uniqueness is global, not per category");
        else
            seen[key] = entry;
    }

    /// <summary>
    /// ⛔ <b>An exemplar is exempt from the two GLOBAL-UNIQUENESS rules here, and from nothing else.</b>
    /// This is not a new decision — <see cref="IdentityCheck"/>'s own <c>CheckUniqueness</c> already
    /// carries it, in those words, for the id rule: <i>"An exemplar demonstrates a real partition using
    /// its real namespace — that is what makes it a usable pattern rather than an abstract one. It
    /// therefore claims ids the actual partition will legitimately author later, and the two are not in
    /// conflict: the exemplar is not corpus content and is never imported. Grammar and namespace rules
    /// still apply to it; only global uniqueness does not."</i>
    ///
    /// <para><c>nameKey</c> and normalized-name uniqueness are the same class of rule on the same
    /// entries, and this file simply never got the same guard. It was invisible until an exemplar-demoed
    /// entry was actually authored: <c>affix-family.exemplar.json</c> demonstrates
    /// <c>atom.elemental-power</c>, the g.elem-power partition then authored it for real on 2026-09-06
    /// (closing a phantom 21 shipped entries referenced), and the tool reported the exemplar and the
    /// real row as a duplicate nameKey plus a name collision — the exact conflict IdentityCheck's note
    /// says does not exist.</para>
    ///
    /// <para>Grammar, prefix, plural, markup and pool-word rules are UNCHANGED for exemplars, matching
    /// that same split — an exemplar has to validate like real content, or it is not a usable pattern.
    /// Only the two cross-entry lookups skip it, and they skip recording as well as reporting, so an
    /// exemplar can neither be blamed nor blame a real row.</para>
    /// </summary>
    const string ExemptFromGlobalUniqueness =
        "IdentityCheck.CheckUniqueness — 'the exemplar is not corpus content and is never imported'";

    static void CheckName(ValidationContext ctx, SeedEntry entry, Dictionary<string, SeedEntry> seen)
    {
        var name = entry.AsString("name");
        if (name is null) return;

        // The pool-derived naming grammar governs the names of THINGS A PLAYER PICKS UP — base
        // types, uniques, sets, charms. It does not govern kinds that name something else:
        //
        //   affix-family      a mechanic label. The shipped ones are Lifesteal, Retribution,
        //                     Volley — none assembled from a word pool, none that could be.
        //   display-template  a SENTENCE ("+{value} maximum health"), full of lowercase words the
        //                     item grammar forbids as invented connectives.
        //   gem               deliberately systematic (Ember Shard, Frost Crystal); readability
        //                     comes from sounding alike, which pools exist to prevent.
        //   curve / recipe    numeric points and cost shapes under named ids.
        //   material          ten ids already ship and are consumed by live code.
        //
        // `words.v1.json poolAccess.kindsExemptFromPools` is the registry's own statement of this,
        // so the list lives there rather than here. Collision and nameKey uniqueness still apply to
        // every kind — those are about clashes, not about grammar.
        // The exemption is per kind, and `words.v1.json` spells out what each one still owes:
        //
        //   gem               collision + nameKey + THE NAMING PATTERNS + every registry rule
        //   material          runtimeId preservation and global uniqueness
        //   display-template  nameKey uniqueness only — a template is a sentence, not a name
        //   curve             id grammar only
        //   recipe            id grammar and reference resolution
        //
        // A single early return collapsed all five into "checked for nothing", which let
        // `gem.g1-015` and `consumable.k1-007` both ship as "Mending Pulse" — the identical string,
        // reported by a reviewer quoting this registry text back. What is actually exempted is
        // POOL MEMBERSHIP, never the corpus-wide collision check.
        var kind = entry.File.Kind ?? "";
        var exemptFromPools = ctx.Registries.IsPoolExemptKind(kind);
        var namesAThing = kind is not ("display-template" or "curve" or "recipe");
        var followsPatterns = !exemptFromPools || kind == "gem";

        if (!namesAThing) return;

        if (name.Contains('\''))
            ctx.Error(entry, "PossessiveForbidden", "naming.v1.json pluralsPossessivesConnectives",
                $"name '{name}' carries an apostrophe; possessives are forbidden because "
                + "normalization strips them, which makes the variation fake");

        // The only connectives a name may contain are `of` and, right after it, `the`.
        //
        // A lowercase run inside a hyphenated compound is not a connective — `Wind-borne Inlay` is
        // <Adjective> <Base> and the pattern regex accepts it, so flagging `borne` here contradicts
        // the grammar this same method enforces two lines down. Only a free-standing word counts.
        foreach (Match m in Regex.Matches(name, @"(?<![-\w])[a-z]+(?![-\w])"))
            if (m.Value is not ("of" or "the"))
                ctx.Error(entry, "InventedConnective", "naming.v1.json pluralsPossessivesConnectives",
                    $"name '{name}' contains the lowercase word '{m.Value}'; only 'of' and a "
                    + "following 'the' are legal");

        if (!followsPatterns) { RecordCollision(ctx, entry, name, seen); return; }

        if (GeneratedOnly.IsMatch(name))
            ctx.Error(entry, "GeneratedOnlyNamePattern", "naming.v1.json generatedOnlyPattern",
                $"name '{name}' uses <Adjective> <Base> of <Concept>, which the engine assembles "
                + "for a rolled instance and no author may type");
        else if (!Compound.IsMatch(name) && !OfConstruct.IsMatch(name) && !Fusion.IsMatch(name))
            ctx.Error(entry, "NameGrammarViolation", "naming.v1.json namingGrammar.patterns",
                $"name '{name}' matches none of the three legal patterns: <Adjective> <Base>, "
                + "<Base> of [the] <Concept>, or a two-word fusion");

        var normalized = ctx.Normalizer.Normalize(name);

        if (Fusion.IsMatch(name))
        {
            var atomic = ctx.Registries.SurfaceForms.ContainsKey(name.ToLowerInvariant());
            if (normalized.FusionUndecidable)
                ctx.Warn(entry, "FusionUndecidable", "naming.v1.json namingGrammar.patterns",
                    $"name '{name}' is a single word and F1's word pool (words.v1.json) is absent, "
                    + "so it cannot be checked for the exactly-two-pool-words rule");
            // Rule 2a: a whole token that resolves is atomic, and an atomic pool word is a legal
            // one-word name. Only an unresolved single word has to decompose.
            else if (!atomic && !normalized.FusionSplit && !IsMechanicLabel(entry))
                ctx.Error(entry, "FusionNotDecomposable", "naming.v1.json namingGrammar.patterns",
                    $"name '{name}' is a fusion that does not decompose into exactly one pair of "
                    + "known pool words");
        }
        else if (ctx.Normalizer.HasWordPool)
        {
            CheckPlurals(ctx, entry, name);
        }

        RecordCollision(ctx, entry, name, seen);
    }

    /// <summary>
    /// strain-splice-host SSH5.13-P1: check ONE candidate display name with THIS check's own grammar,
    /// for a generator that must refuse a name BEFORE it writes. The regexes, the connective rule and
    /// the pool decomposition are the ones <see cref="CheckName"/> uses on corpus rows — a generator
    /// carrying its own copy of the patterns is exactly the drift this entry point exists to prevent.
    ///
    /// <para><b>What it covers, stated:</b> the three naming patterns, the engine-only pattern, the
    /// apostrophe rule, the lowercase-connective rule, and whether a single-word name decomposes into
    /// the word pool. Pool-plural spelling and markup are NOT checked here — the corpus validator still
    /// owns those, and no generator authors them.</para>
    /// </summary>
    /// <param name="isAtomicPoolWord">True when the whole name resolves as one pool word: an atomic word
    /// is a legal one-word name and is never decomposed.</param>
    /// <param name="isMechanicLabel">True for a kind whose name is a MECHANIC label rather than an
    /// assembled object name — a single-word label is legal for it.</param>
    public static IReadOnlyList<string> CandidateNameDefects(
        string name, NameNormalizer normalizer, bool isAtomicPoolWord = false, bool isMechanicLabel = false)
    {
        if (normalizer is null) throw new ArgumentNullException(nameof(normalizer));
        if (string.IsNullOrWhiteSpace(name)) return new[] { "name: empty" };

        var defects = new List<string>();

        if (name.Contains('\''))
            defects.Add("name: carries an apostrophe (a possessive is forbidden — normalization strips "
                        + "it, which makes the variation fake)");

        foreach (Match m in Regex.Matches(name, @"(?<![-\w])[a-z]+(?<![-\w])"))
            if (m.Value is not ("of" or "the"))
                defects.Add($"name: lowercase word '{m.Value}' (only 'of' and a following 'the' are legal)");

        if (GeneratedOnly.IsMatch(name))
        {
            defects.Add("name: '<Adjective> <Base> of <Concept>' is the engine's own rolled-instance "
                        + "pattern and no author may type it");
            return defects;
        }

        if (!Compound.IsMatch(name) && !OfConstruct.IsMatch(name) && !Fusion.IsMatch(name))
        {
            defects.Add("name: matches none of the three legal patterns (<Adjective> <Base>, "
                        + "<Base> of [the] <Concept>, or a two-word fusion)");
            return defects;
        }

        if (Fusion.IsMatch(name) && !isMechanicLabel)
        {
            var normalized = normalizer.Normalize(name);
            if (normalized.FusionUndecidable)
                defects.Add("name: a single word, and the word pool is not loaded, so it cannot be "
                            + "checked for the exactly-two-pool-words rule");
            else if (!isAtomicPoolWord && !normalized.FusionSplit)
                defects.Add("name: a fusion that does not decompose into exactly one pair of known pool "
                            + "words — prefer two words with a space between them");
        }

        return defects;
    }

    /// <summary>
    /// The corpus-wide collision check, split out because it applies to kinds that are exempt from
    /// the pool grammar. Every kind that names a thing a player sees goes through here.
    /// </summary>
    static void RecordCollision(
        ValidationContext ctx, SeedEntry entry, string name, Dictionary<string, SeedEntry> seen)
    {
        if (entry.File.IsExemplar) return;   // see ExemptFromGlobalUniqueness

        var normalized = ctx.Normalizer.Normalize(name);
        if (normalized.Key.Length == 0) return;
        if (seen.TryGetValue(normalized.Key, out var first))
            ctx.Error(entry, "NameCollision", "seed-contract.md §5 / naming.v1.json collisionNormalization",
                $"name '{name}' normalizes to {NameNormalizer.Describe(normalized)}, the same idea as "
                + $"'{first.AsString("name")}' ({first.Label} in {first.File.RelativePath}"
                + $"{(first.Partition == Finding.NoPartition ? "" : $", partition {first.Partition}")})");
        else
            seen[normalized.Key] = entry;
    }

    /// <summary>
    /// An affix family that already ships keeps its existing id and its existing name verbatim —
    /// naming.v1.json is explicit that those are never re-minted. Their names predate the word
    /// pools by a long way ("Lifesteal", "Retribution", "Volley"), so pool-derived grammar rules
    /// cannot apply to them: the author did not choose the name and may not change it.
    ///
    /// Detected by the id being a bare `atom.&lt;name&gt;` with no partition stem — a newly minted
    /// family carries its group's stem (`atom.hit-drain`), a shipped one does not.
    /// </summary>
    /// <summary>
    /// An affix family is a MECHANIC LABEL, not an assembled object name, and a one-word label is
    /// the shape every shipped family already has: Lifesteal, Retribution, Volley. The
    /// exactly-two-pool-words fusion rule exists to stop sixty base-type partitions sounding alike;
    /// applied to a family it demands that new mechanics look unlike every mechanic that ships.
    ///
    /// Five independent partitions produced single-word labels here — Harvest, Grit, Callusing,
    /// Stampede, Graftplate — which reads as the corpus reporting a wrong constraint rather than
    /// five agents making one mistake. So a single-word affix-family name is legal whether or not
    /// it decomposes. Multi-word family names still go through the patterns, and collision,
    /// nameKey uniqueness, possessives and connectives still apply to every kind.
    /// </summary>
    static bool IsMechanicLabel(SeedEntry entry) =>
        string.Equals(entry.File.Kind, "affix-family", StringComparison.Ordinal);

    /// <summary>Only decidable once F1's pool exists: 'Ashes' is a plural, 'Moss' is not.</summary>
    static void CheckPlurals(ValidationContext ctx, SeedEntry entry, string name)
    {
        foreach (Match m in Regex.Matches(name, @"\b[A-Z][a-z]+\b"))
        {
            var word = m.Value.ToLowerInvariant();
            if (!word.EndsWith('s') || word.Length < 3) continue;
            var singular = word[..^1];
            if (ctx.Registries.SurfaceForms.ContainsKey(word)) continue;
            if (!ctx.Registries.SurfaceForms.ContainsKey(singular)) continue;
            ctx.Error(entry, "PluralForbidden", "naming.v1.json pluralsPossessivesConnectives",
                $"name '{name}' pluralizes '{m.Value}'; an item template names one specific thing");
        }
    }

    /// <summary>
    /// Substitution braces are markup in an item name and the mechanism in a template. The named
    /// template fields carry them everywhere; `display-template` additionally carries them in
    /// `name`, because for that kind the localized string IS the template — "+{value} max health"
    /// is the whole point of the row (entry-shapes.md §10). Real markup — tags, entities, bold,
    /// backticks — stays forbidden there like anywhere else.
    /// </summary>
    static bool IsTemplateCarrier(SeedEntry entry, string key) =>
        TemplateFields.Contains(key, StringComparer.Ordinal)
        || (string.Equals(entry.File.Kind, "display-template", StringComparison.Ordinal)
            && key is "name" or "plantOverrideName");

    static void CheckMarkup(ValidationContext ctx, SeedEntry entry)
    {
        foreach (var (path, key, value) in ValidationContext.Walk(entry.Node))
        {
            if (value is not JsonValue jv || !jv.TryGetValue<string>(out var text)) continue;
            // The rule's own reason is "display formatting belongs to the presentation layer", which
            // only bites on a string that gets displayed. `notes` and `identity` are authoring
            // provenance and never reach a player, and the briefs actively ask an author to record
            // where each word came from — `nounPools['armament-primary.humanoid']` is a code
            // reference doing exactly that, not a bracket tag. Flagging it 183 times buried the
            // warnings that meant something.
            var localized = key is "name" or "flavor";
            if (!localized) continue;

            foreach (var (pattern, what) in Markup)
            {
                if (!pattern.IsMatch(text)) continue;
                var message = $"'{path}' contains {what}; display formatting belongs to the "
                              + "presentation layer";
                ctx.Error(entry, "MarkupInString", "seed-contract.md §6", message);
            }

            if (!IsTemplateCarrier(entry, key) && Placeholder.IsMatch(text))
            {
                var message = $"'{path}' contains a {{placeholder}}; only "
                              + string.Join("/", TemplateFields) + " carry substitution braces";
                ctx.Error(entry, "MarkupInString", "seed-contract.md §6", message);
            }
        }
    }
}
