using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using FusionRpg.Tools.ItemSeedValidator.Model;

namespace FusionRpg.Tools.ItemSeedValidator.Checks;

/// <summary>
/// seed-contract.md §7.1 — a reference resolves at validation or the file rejects. Forward and
/// cyclic references are errors, and a stage-1a file referencing another stage-1a file is an
/// error too: that restriction is what makes "independent" true rather than aspirational.
/// Unknown registry values are errors, never warnings (§2.1: naming a value is not owning it).
/// </summary>
public static class ReferenceCheck
{
    /// <summary>Keys whose value names something in a registry, and which registry.</summary>
    static readonly (string Key, string Registry)[] RegistryRefs =
    {
        ("role", "roles"), ("frame", "frames"), ("class", "classes"),
        ("rarity", "rarity"), ("theme", "themes"), ("themeKey", "themes"),
        ("element", "elements"), ("category", "categories"),
    };

    /// <summary>The two legacy/build themeKey prefixes, stripped before resolving against ThemeIds.
    /// `creature.` is the third population and resolves separately — see
    /// <see cref="CheckCreatureThemeReference"/>.</summary>
    static readonly string[] ThemePrefixes = { "theme.", "build." };

    const string CreaturePrefix = "creature.";

    static string StripThemePrefix(string value)
    {
        foreach (var prefix in ThemePrefixes)
            if (value.StartsWith(prefix, StringComparison.Ordinal)) return value[prefix.Length..];
        return value;
    }

    /// <summary>Keys that hold a nameKey or an icon key, never an id reference.</summary>
    static bool IsKeyField(string key) => key is "id" || key.EndsWith("Key", StringComparison.Ordinal);

    public static void Run(ValidationContext ctx)
    {
        var namespaceRoots = ctx.Allocation.All
            .Select(a => a.Prefix.Split('.')[0])
            .Distinct(StringComparer.Ordinal)
            .ToHashSet(StringComparer.Ordinal);
        // Underscores are accepted here ON PURPOSE, even though no legal id contains one. The regex
        // decides whether a string is even *considered* a reference, so a stricter pattern does not
        // reject a misspelled id — it makes it invisible. Ten references to `atom.keen_edge` and
        // friends sat in the corpus producing no error and no warning, because they failed this
        // gate and `ResolveReference` was never called on them.
        //
        // They came from `naming.v1.json`, which lists the shipped families in snake_case while
        // every authored id is kebab-case. The affix-family authors converted; the gem and
        // socket-word authors, only *referencing* the families, copied the registry verbatim.
        // Letting the underscore form through means it resolves against nothing and reports
        // ReferenceUnresolved, which is the whole point.
        var idLike = new Regex(@"^(" + string.Join('|', namespaceRoots.Select(Regex.Escape))
                                     + @")\.[a-z0-9]+([-_][a-z0-9]+)*$", RegexOptions.Compiled);

        var edges = new List<(SeedEntry From, string To)>();
        var mintedFamilies = new Dictionary<string, SeedEntry>(StringComparer.Ordinal);
        ctx.MintedRuntime = MintedRuntimeIds(ctx);

        foreach (var entry in ctx.Entries)
        {
            CheckTags(ctx, entry);
            CheckRoles(ctx, entry);
            CheckClassBelongsToRoleLadder(ctx, entry);
            CheckMintedRuntimeFamily(ctx, entry, mintedFamilies);

            foreach (var (path, key, value) in ValidationContext.Walk(entry.Node))
            {
                if (value is not JsonValue jv || !jv.TryGetValue<string>(out var text)) continue;

                CheckRegistryValue(ctx, entry, path, key, text);

                if (IsKeyField(key)) continue;
                if (IsMintedRuntimeId(entry, key)) continue;
                if (!idLike.IsMatch(text)) continue;
                edges.Add((entry, text));
                // species-gear-chain T37/T38: `successorOf` is the upgrade tree's authored edge between
                // two base types, and a base type's successor is BY DESIGN a peer in the same authoring
                // stage (1b) — the field is authored as a reviewed table
                // (`gk-data/packs/fusion/data/seed/items/_registry/successor-edges.v1.json`) after the corpus exists, and its
                // resolution + same-frame closure is enforced by the generator's own gate
                // (`basetypegen/successor_edges.py::violations_in_corpus`, run before any emit). The
                // reference is still resolved here, so a typo is `ReferenceUnresolved` as usual; only
                // the stage rule is relaxed, and only for this field.
                ResolveReference(ctx, entry, path, text, allowSameStage: key == "successorOf");
            }
        }

        DetectCycles(ctx, edges);
    }

    /// <summary>
    /// A base type's class must belong to its ROLE's ladder. `words.v1.json` `poolAccess.roleToLadders`
    /// is the mapping — retinue and the three jewel roles take the jewel ladder, armament takes weapon
    /// (and off-hand also takes offhand), everything else takes armour.
    ///
    /// Added after a brief wrongly told four retinue partitions to use the armour ladder. Three of them
    /// complied and produced content that validated cleanly, because a class id is legal on its own and
    /// nothing checked it against the role. Only the fourth read the registry and refused. A silent
    /// wrong answer that three agents agree on is exactly what a validator is for.
    /// </summary>
    static void CheckClassBelongsToRoleLadder(ValidationContext ctx, SeedEntry entry)
    {
        if (!string.Equals(entry.File.Kind, "base-type", StringComparison.Ordinal)) return;
        if (entry.AsString("class") is not { } classId) return;
        if (entry.AsString("role") is not { } roleId) return;
        if (!ctx.Registries.ClassRungs.TryGetValue(classId, out var rung)) return;

        var ladders = ctx.Registries.LaddersForRole(roleId);
        if (ladders.Count == 0) return;
        if (ladders.Contains(rung.Ladder, StringComparer.Ordinal)) return;

        ctx.Error(entry, "ClassNotInRoleLadder", "words.v1.json poolAccess.roleToLadders",
            $"class '{classId}' is on the '{rung.Ladder}' ladder, but role '{roleId}' draws from "
            + $"{string.Join(" / ", ladders)}");
    }

    static void CheckRegistryValue(ValidationContext ctx, SeedEntry entry, string path, string key, string value)
    {
        foreach (var (refKey, registry) in RegistryRefs)
        {
            if (!string.Equals(key, refKey, StringComparison.Ordinal)) continue;

            // themeKey is written as the theme's nameKey (theme.rot-bloom); accept both spellings.
            // Three populations share the field and cannot collide because each has its own
            // prefix: `theme.` (legacy, frozen), `build.` (item module 13's 36 aptitude x
            // archetype build sets) and `creature.` (published by the creatures feature, one per
            // shipped species). The first two resolve against ThemeIds once their prefix is
            // stripped; `creature.` resolves against RegistrySet.CreatureSpeciesIds instead — a
            // species id and a legacy/build theme id are different vocabularies that only happen to
            // share this field, so they cannot share ThemeIds either (fixed 2026-09-20; previously a
            // named, open gap — "creature. does not resolve here at all yet" — that produced 844
            // RegistryValueUnknown errors, one per species-population set entry).
            if (registry == "themes" && value.StartsWith(CreaturePrefix, StringComparison.Ordinal))
            {
                CheckCreatureThemeReference(ctx, entry, path, value);
                continue;
            }

            var candidate = registry == "themes"
                ? StripThemePrefix(value)
                : value;

            var (members, label) = registry switch
            {
                "roles" => (ctx.Registries.RoleIds, "core.v1.json roles.list"),
                "frames" => (ctx.Registries.FrameIds, "core.v1.json roles.frames"),
                "classes" => (ctx.Registries.ClassIds, "classes.v1.json classLadders"),
                "rarity" => (ctx.Registries.RarityIds, "core.v1.json rarity.ladder"),
                "themes" => (ctx.Registries.ThemeIds, "themes.v1.json"),
                "elements" => (ctx.Registries.ElementIds, "themes.v1.json elementAffinity + omni"),
                "categories" => (ctx.Registries.CategoryIds, "core.v1.json categories.list"),
                _ => (Array.Empty<string>(), registry),
            };
            if (members.Count == 0) continue;
            if (members.Contains(candidate, StringComparer.Ordinal)) continue;
            // A brace token is a template placeholder, not a value. seed-contract.md §6 names
            // params/variants/channel/displayTemplate as the fields that legitimately carry
            // substitution braces, and a generated family writes params.element = "{variant}"
            // precisely so one authored family expands into one row per element. Checking that
            // against the element roster rejects the correct thing.
            if (candidate.StartsWith('{') && candidate.EndsWith('}')) continue;
            // On a recipe, `frame` is the scope the recipe applies to, not the body an item hangs
            // on, and entry-shapes.md §4 gives it three values: humanoid | plant | any. `any` is
            // how a recipe says "either frame" — eighteen of the thirty shipped recipes are
            // frame-agnostic and there is nothing else for them to write. core.v1.json's frame
            // roster is the body list and correctly has no `any` in it.
            if (registry == "frames" && candidate == "any"
                && string.Equals(entry.File.Kind, "recipe", StringComparison.Ordinal)) continue;

            ctx.Error(entry, "RegistryValueUnknown", "seed-contract.md §2.1 (VALIDATED)",
                $"'{path}' is '{value}', which {label} does not contain "
                + $"({string.Join(", ", members)})");
        }
    }

    /// <summary>
    /// The `creature.&lt;speciesId&gt;` population resolves against the creature theme registry's own
    /// `speciesId` column (<see cref="Registries.RegistrySet.CreatureSpeciesIds"/>) — the same source
    /// <see cref="SetRuleCheck"/>'s `speciesId` closure guard and
    /// <see cref="Registries.NamespaceAllocation"/>'s species-set id allocation both read, so all
    /// three species-population checks share one loader and one definition of "a real species".
    /// Degrades (reports nothing) when the registry is unreachable, the same convention every other
    /// optional cross-reference in this tool follows — a missing sibling registry is never a false
    /// error on every row that merely could not be checked.
    /// </summary>
    static void CheckCreatureThemeReference(ValidationContext ctx, SeedEntry entry, string path, string value)
    {
        if (!ctx.Registries.CreatureSpeciesRegistryFound) return;
        var speciesId = value[CreaturePrefix.Length..];
        if (ctx.Registries.CreatureSpeciesIds.Contains(speciesId)) return;
        ctx.Error(entry, "RegistryValueUnknown",
            "seed-contract.md §2.1 (VALIDATED) / creatures/_registry/themes.v2.json",
            $"'{path}' is '{value}', which the shipped creature species roster does not contain "
            + $"(species '{speciesId}')");
    }

    static void CheckTags(ValidationContext ctx, SeedEntry entry)
    {
        if (entry.Node["tags"] is not JsonArray tags) return;
        var kind = entry.File.Kind ?? "";
        var byAxis = new Dictionary<string, List<string>>(StringComparer.Ordinal);

        foreach (var node in tags)
        {
            if (node is not JsonValue jv || !jv.TryGetValue<string>(out var tag))
            {
                ctx.Error(entry, "TagNotString", "tags.v1.json", "tags must be strings");
                continue;
            }
            if (!ctx.Registries.TagAxis.TryGetValue(tag, out var axisId))
            {
                ctx.Error(entry, "TagUnknown", "seed-contract.md §2.1 / tags.v1.json",
                    $"tag '{tag}' is not in the closed tag vocabulary; free-text tags rot into "
                    + "heavy/weighty/bulky");
                continue;
            }
            if (!byAxis.TryGetValue(axisId, out var list)) byAxis[axisId] = list = new List<string>();
            list.Add(tag);

            if (ctx.Registries.Axes.TryGetValue(axisId, out var axis)
                && axis.AppliesTo.Count > 0
                && kind.Length > 0
                && !axis.AppliesTo.Contains(kind, StringComparer.Ordinal))
                // tags.v1.json's own `appliesToNote` says this field is "authoring guidance, not
                // an enforced constraint" — the registry is the SSOT for its own vocabulary, so
                // enforcing it as an error contradicts the file being enforced. It stays reported,
                // because an off-axis tag is usually still a mistake worth a human glance.
                ctx.Warn(entry, "TagAxisNotApplicable", "tags.v1.json axes.appliesTo",
                    $"tag '{tag}' is on axis '{axisId}', which applies to "
                    + $"{string.Join("/", axis.AppliesTo)}, not to kind '{kind}'");
        }

        foreach (var (axisId, list) in byAxis)
        {
            if (list.Count < 2) continue;
            if (!ctx.Registries.Axes.TryGetValue(axisId, out var axis) || !axis.Exclusive) continue;
            ctx.Error(entry, "TagAxisExclusive", "tags.v1.json axes.exclusive",
                $"axis '{axisId}' is exclusive but carries {list.Count} tags: {string.Join(", ", list)}");
        }
    }

    /// <summary>
    /// `roles` (seed-contract.md's current name — it renamed the field from `roleGroups` because
    /// the value is a list of role ids, not a group vocabulary) is the input the role x family
    /// legality matrix derives from. Scoped to `affix-family`: `charm`'s own `roleGroups` field
    /// (entry-shapes.md §7) names pool-group family ids, a different vocabulary entirely, and
    /// must not be run through a role-id check just because it shares a key name.
    ///
    /// The old name still validates rather than hard-rejecting, because a lane document an author
    /// might still be reading uses it — a rejection there would blame the author for a contract
    /// rename, so it warns instead.
    /// </summary>
    static void CheckRoles(ValidationContext ctx, SeedEntry entry)
    {
        if (entry.File.Kind != "affix-family") return;

        var legacy = entry.Node["roleGroups"] as JsonArray;
        var roles = entry.Node["roles"] as JsonArray;

        if (legacy is null && roles is null)
            ctx.Error(entry, "RequiredFieldMissing", "seed-contract.md §9/§10",
                "kind 'affix-family' requires 'roles'");

        if (legacy is not null)
        {
            ctx.Warn(entry, "RoleGroupsRenamed", "seed-contract.md §10",
                "'roleGroups' was renamed to 'roles' by the contract; the value still validates "
                + "but should be migrated to 'roles'");
            CheckRoleList(ctx, entry, legacy, "roleGroups");
        }

        if (roles is not null)
            CheckRoleList(ctx, entry, roles, "roles");
    }

    static void CheckRoleList(ValidationContext ctx, SeedEntry entry, JsonArray list, string fieldName)
    {
        foreach (var node in list)
        {
            if (node is not JsonValue jv || !jv.TryGetValue<string>(out var group))
            {
                ctx.Error(entry, "RoleGroupNotString", "seed-contract.md §2.1", $"{fieldName} must be strings");
                continue;
            }
            if (ctx.Registries.RoleIds.Contains(group, StringComparer.Ordinal)) continue;
            ctx.Warn(entry, "RoleGroupUnknown", "seed-contract.md §2.1 (gap)",
                $"{fieldName} value '{group}' is not a role id and no wave-0 registry owns the "
                + "role-group vocabulary; legality cannot be derived from it");
        }
    }

    /// <summary>
    /// Five kinds carry a runtime-facing id alongside their allocated tracking id, and that runtime
    /// id is MINTED by the entry, not borrowed from another one (entry-shapes.md §0, "tracking id
    /// vs. runtime id"). Resolving it as a reference inverts the rule: a milestone's
    /// `atom.enhance-vigor` is required NOT to match an existing family, so demanding that it
    /// resolve fails every correctly-authored row.
    /// </summary>
    static bool IsMintedRuntimeId(SeedEntry entry, string key) =>
        key is "runtimeFamily" or "runtimeId" or "containerId";

    static readonly Regex EnhanceStem = new(@"^atom\.enhance-[a-z0-9-]+$", RegexOptions.Compiled);

    /// <summary>
    /// The rules entry-shapes.md §6 actually states for a milestone's minted family: it sits in the
    /// reserved `atom.enhance-` stem, it does not collide with an affix family, and no two
    /// milestones share one.
    /// </summary>
    static void CheckMintedRuntimeFamily(
        ValidationContext ctx, SeedEntry entry, Dictionary<string, SeedEntry> seen)
    {
        if (!string.Equals(entry.File.Kind, "enhancement-milestone", StringComparison.Ordinal)) return;
        if (entry.AsString("runtimeFamily") is not { } family) return;

        if (!EnhanceStem.IsMatch(family))
        {
            ctx.Error(entry, "RuntimeFamilyStem", "entry-shapes.md §6 / ssot-enhancement.md §5.5",
                $"runtimeFamily '{family}' is outside the reserved 'atom.enhance-' stem; the stem is "
                + "what keeps a milestone from colliding with a rolled affix on (family_id, variant)");
            return;
        }

        if (ctx.ById.ContainsKey(family) || ctx.Registries.ShippedFamilies.Contains(family))
            ctx.Error(entry, "RuntimeFamilyCollision", "entry-shapes.md §6",
                $"runtimeFamily '{family}' collides with an affix family that already exists; the "
                + "reserved stem exists precisely so this cannot happen");

        if (seen.TryGetValue(family, out var first))
            ctx.Error(entry, "RuntimeFamilyDuplicate", "entry-shapes.md §6",
                $"runtimeFamily '{family}' is already minted by {first.Label}");
        else
            seen[family] = entry;
    }

    /// <summary>
    /// Runtime ids minted by an entry rather than allocated as one. A milestone mints
    /// `atom.enhance-vigor`; a base type's `enhanceTrack` then points at it, and a socket word's
    /// `runtimeId` is the same species. These are real targets in the runtime namespace and simply
    /// are not entry ids, so `ById` will never hold them.
    /// </summary>
    static HashSet<string> MintedRuntimeIds(ValidationContext ctx) =>
        ctx.Entries
            .SelectMany(e => new[] { e.AsString("runtimeFamily"), e.AsString("runtimeId"),
                                     e.AsString("containerId") })
            .OfType<string>()
            .ToHashSet(StringComparer.Ordinal);

    static void ResolveReference(ValidationContext ctx, SeedEntry entry, string path, string target,
                                bool allowSameStage = false)
    {
        if (ctx.Registries.ShippedFamilies.Contains(target)) return;
        if (ctx.MintedRuntime.Contains(target)) return;

        if (!ctx.ById.TryGetValue(target, out var referenced))
        {
            ctx.Error(entry, "ReferenceUnresolved", "seed-contract.md §7.1",
                $"'{path}' references '{target}', which no seed file authors and no registry ships");
            return;
        }

        if (ReferenceEquals(referenced, entry))
        {
            ctx.Error(entry, "CyclicReference", "seed-contract.md §7.1",
                $"'{path}' references the entry itself");
            return;
        }

        if (entry.Stage.Length == 0 || referenced.Stage.Length == 0) return;

        // 1a defines, 1b references. A reference is legal only to a strictly earlier stage —
        // anything else is forward (its target is not frozen yet) or same-stage cross-partition.
        // `allowSameStage` is the upgrade tree's ONE documented exception (see the call site): the
        // successor edge is a peer edge by owner ruling (spec-item-upgrade-tree.md, 2026-09-21), and
        // its resolution + same-frame closure has its own gate in the generator.
        if (string.CompareOrdinal(referenced.Stage, entry.Stage) < 0) return;
        if (allowSameStage && string.Equals(referenced.Stage, entry.Stage, StringComparison.Ordinal)) return;

        var code = string.Equals(referenced.Stage, entry.Stage, StringComparison.Ordinal)
            ? "SameStageReference"
            : "ForwardReference";
        ctx.Error(entry, code, "seed-contract.md §7.1 / authoring-fleet-plan.md §3",
            $"'{path}' references '{target}' (stage {referenced.Stage}, partition "
            + $"{referenced.Partition}) from stage {entry.Stage}; a reference must resolve against "
            + "frozen content, never against a peer mid-write");
    }

    static void DetectCycles(ValidationContext ctx, List<(SeedEntry From, string To)> edges)
    {
        var graph = new Dictionary<string, List<string>>(StringComparer.Ordinal);
        foreach (var (from, to) in edges)
        {
            if (from.Id is not { } id) continue;
            if (!ctx.ById.ContainsKey(to)) continue;
            if (!graph.TryGetValue(id, out var list)) graph[id] = list = new List<string>();
            list.Add(to);
        }

        var state = new Dictionary<string, int>(StringComparer.Ordinal); // 0 unseen, 1 on stack, 2 done
        var stack = new List<string>();

        void Visit(string node)
        {
            state[node] = 1;
            stack.Add(node);
            if (graph.TryGetValue(node, out var next))
            {
                foreach (var child in next)
                {
                    if (!state.TryGetValue(child, out var s) || s == 0) { Visit(child); continue; }
                    if (s != 1) continue;
                    var at = stack.IndexOf(child);
                    var cycle = string.Join(" -> ", stack.Skip(at).Append(child));
                    if (ctx.ById.TryGetValue(node, out var entry))
                        ctx.Error(entry, "CyclicReference", "seed-contract.md §7.1",
                            $"reference cycle: {cycle}");
                }
            }
            stack.RemoveAt(stack.Count - 1);
            state[node] = 2;
        }

        foreach (var node in graph.Keys.Order(StringComparer.Ordinal))
            if (!state.TryGetValue(node, out var s) || s == 0)
                Visit(node);
    }
}
