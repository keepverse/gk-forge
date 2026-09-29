using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace FusionRpg.Tools.ItemSeedValidator.Registries;

/// <summary>What the agent owns after its allocated prefix.</summary>
public enum SequenceShape
{
    /// <summary>A zero-padded 3-digit sequence the agent owns (naming.v1.json idPolicy).</summary>
    ThreeDigit,

    /// <summary>An affix family's mechanical word, or the `x000` checkpoint form.</summary>
    AffixWord,

    /// <summary>The whole id is fixed by the registry; the agent owns nothing.</summary>
    Fixed,

    /// <summary>
    /// The tail after the prefix is fully determined by deterministic upstream logic (a grid cell,
    /// not an author's own sequence) — item-seedgen `combination-write-unblock` (2026-09-07),
    /// `combogen`'s own tokens after `combo.strain-`/`combo.splice-`. Unlike <see cref="Fixed"/> the
    /// id still varies per subject, so it needs prefix matching, not exact; unlike
    /// <see cref="ThreeDigit"/>/<see cref="AffixWord"/> the tail has no grammar of its own left to
    /// check here — the deterministic generator that produced it is the review, not a human sequence
    /// an agent could get wrong.
    /// </summary>
    Derived,
}

/// <param name="PartitionId">Stable label used to group findings for a fix pass.</param>
/// <param name="Prefix">Everything before the agent's own sequence, including the trailing dash.</param>
/// <param name="Tokens">Words that legitimately name this partition — role id, frame, band and
/// the frame's display word — so a free-form _meta.partition label can be checked against it.</param>
public sealed record AllocatedNamespace(
    string NamespaceKey,
    string Kind,
    string Stage,
    string PartitionId,
    string Prefix,
    SequenceShape Shape,
    IReadOnlySet<string> Tokens);

/// <summary>
/// Expands naming.v1.json's idTemplates into the finite list of prefixes actually allocated to
/// wave-1 partitions. This is the mechanism seed-contract.md §4 relies on: an id that does not
/// begin with exactly one allocated prefix was written outside its agent's namespace.
/// </summary>
public sealed class NamespaceAllocation
{
    readonly List<AllocatedNamespace> _all = new();

    public IReadOnlyList<AllocatedNamespace> All => _all;

    /// <summary>Namespaces the expander could not build, with why. Reported, never silent.</summary>
    public List<string> Problems { get; } = new();

    public static NamespaceAllocation Build(RegistrySet registries)
    {
        var alloc = new NamespaceAllocation();
        var namespaces = registries.Naming["idNamespaces"] as JsonObject ?? new JsonObject();

        foreach (var (key, node) in namespaces)
        {
            if (key.StartsWith('_') || key == "partitionCountCheck") continue;
            if (node is not JsonObject ns) continue;

            var kind = KindCatalog.ByNamespace(key);
            if (kind is null)
            {
                alloc.Problems.Add($"idNamespaces.{key} has no kind in KindCatalog — ids under it cannot be validated");
                continue;
            }

            switch (key)
            {
                case "baseTypes": alloc.ExpandBaseTypes(registries, ns, kind); break;
                case "affixFamilies": alloc.ExpandAffixFamilies(registries, ns, kind); break;
                case "uniques": alloc.ExpandUniques(ns, kind); break;
                case "sets":
                    alloc.ExpandByList(ns, kind, "themeIds", "set.");
                    // Additive 2026-09-07 (registryVersion 5->6): `setgen`'s own build-population
                    // grid (aptitude x archetype) gets the SAME id shape as the 5 legacy themeIds,
                    // via a deliberately separate list key — merging it into `themeIds` itself would
                    // have broken `legacy_partition_ids()`'s own meaning on the Python side (that
                    // function reads `themeIds` specifically as "the 5 hand-authored partitions",
                    // caught by a real test regression and reverted to this shape).
                    alloc.ExpandByList(ns, kind, "buildThemeIds", "set.");
                    // Additive 2026-09-20 (registryVersion 7->8): the SAME "no allocation existed"
                    // defect the build population hit on 2026-09-07 recurred for the THIRD `set.`
                    // population — `creature.<speciesId>`, setgen's species stage, one set per shipped
                    // species — found via ItemSeedValidator returning 848 IdOutsideNamespace errors,
                    // one per species-keyed `set.<speciesId>-NNN` id. Unlike the first two, this one
                    // is read LIVE from RegistrySet.CreatureSpeciesIds rather than a list embedded
                    // here: the species roster is a population that grows every time content ships
                    // (the closed-vocabulary-vs-derived-population distinction validation-ssot.md
                    // draws for a test assertion applies just as much to an allocation source —
                    // hardcoding it in naming.v1.json would itself go stale the next time a species
                    // shipped).
                    alloc.ExpandSpeciesThemes(registries, kind);
                    break;
                case "charms": alloc.ExpandCharms(ns, kind); break;
                case "combinations": alloc.ExpandCombinations(ns, kind); break;
                case "rareNameWords": alloc.ExpandRareNameWords(ns, kind); break;
                default: alloc.ExpandSlotOrFlat(ns, kind); break;
            }
        }

        return alloc;
    }

    void Add(SeedKind kind, string partitionId, string prefix, SequenceShape shape,
        params string[] extraTokens)
    {
        var tokens = partitionId.Split(new[] { '/', '-', '.' }, StringSplitOptions.RemoveEmptyEntries)
            .Concat(extraTokens)
            .ToHashSet(StringComparer.OrdinalIgnoreCase);
        _all.Add(new AllocatedNamespace(
            kind.NamespaceKey, kind.Kind, kind.Stage, partitionId, prefix, shape, tokens));
    }

    /// <summary>item.{frame}-{frameRoleName}-{band}-{seq:03}, 15 roles x 2 frames x 2 bands.</summary>
    void ExpandBaseTypes(RegistrySet reg, JsonObject ns, SeedKind kind)
    {
        var frames = RegistrySet.Strings(ns["frames"]);
        var bands = RegistrySet.Strings(ns["bands"]);
        if (frames.Count == 0 || bands.Count == 0)
        {
            Problems.Add("idNamespaces.baseTypes is missing frames or bands");
            return;
        }

        foreach (var roleId in reg.WaveOneRoleIds)
        {
            if (!reg.RoleDisplayNames.TryGetValue(roleId, out var names)) continue;
            foreach (var frame in frames)
            {
                // frameRoleNameRule: humanoidName on humanoid, plantName on plant, verbatim.
                var display = frame switch
                {
                    "humanoid" => names.Humanoid,
                    "plant" => names.Plant,
                    _ => null,
                };
                if (display is null) continue;
                foreach (var band in bands)
                    Add(kind, $"{kind.Directory}/{roleId}/{frame}/{band}",
                        $"item.{frame}-{display}-{band}-", SequenceShape.ThreeDigit,
                        display, names.Humanoid, names.Plant);
            }
        }

        ExpandCommanderBaseTypes(reg, frames, kind);
    }

    /// <summary>
    /// The commander-only roles carry base types too, but they sit in core.v1.json's
    /// <c>roles.commanderOnly</c> rather than <c>roles.list</c> — deliberately, because they are
    /// outside the fifteen-role 1000‰ budget. WaveOneRoleIds therefore excludes them, so the loop
    /// above never reaches them and every commander id was rejected as outside any allocated
    /// namespace. Found by the pilot.
    ///
    /// They are single-band by design (commander gear is not item-level tiered in v1), so the
    /// prefix carries no band segment at all.
    /// </summary>
    void ExpandCommanderBaseTypes(RegistrySet reg, IReadOnlyList<string> frames, SeedKind kind)
    {
        foreach (var roleId in reg.RoleIds.Except(reg.WaveOneRoleIds, StringComparer.Ordinal))
        {
            if (!reg.RoleDisplayNames.TryGetValue(roleId, out var names)) continue;
            foreach (var frame in frames)
            {
                var display = frame switch
                {
                    "humanoid" => names.Humanoid,
                    "plant" => names.Plant,
                    _ => null,
                };
                if (display is null) continue;
                Add(kind, $"{kind.Directory}/{frame}-{roleId}",
                    $"item.{frame}-{display}-", SequenceShape.ThreeDigit,
                    display, roleId, names.Humanoid, names.Plant);
            }
        }
    }

    /// <summary>
    /// atom.{stem}-{word} for a newly invented family, plus every shipped family's existing id
    /// kept verbatim (the registry is explicit that those are never re-minted).
    /// </summary>
    void ExpandAffixFamilies(RegistrySet reg, JsonObject ns, SeedKind kind)
    {
        var groups = (ns["groups"] as JsonArray ?? new JsonArray()).OfType<JsonObject>().ToList();
        if (groups.Count == 0) { Problems.Add("idNamespaces.affixFamilies declares no groups"); return; }

        foreach (var group in groups)
        {
            var groupId = group["groupId"]?.GetValue<string>();
            var stem = group["stem"]?.GetValue<string>();
            if (groupId is null || stem is null) continue;
            var partition = $"{kind.Directory}/{groupId}";
            Add(kind, partition, $"atom.{stem}-", SequenceShape.AffixWord);

            foreach (var existing in RegistrySet.Strings(group["existingFamilies"]))
            {
                // The g.affliction row names its families in prose rather than as ids.
                if (!Regex.IsMatch(existing, "^[a-z0-9_]+$")) continue;
                Add(kind, partition, "atom." + existing.Replace('_', '-'), SequenceShape.Fixed);
            }
        }
    }

    /// <summary>unique.{themeId}-{rungBandLowOrdinal}-{seq:03}, from the band assignment table.</summary>
    void ExpandUniques(JsonObject ns, SeedKind kind)
    {
        var rows = (ns["bandAssignment"] as JsonArray ?? new JsonArray()).OfType<JsonObject>().ToList();
        if (rows.Count == 0) { Problems.Add("idNamespaces.uniques declares no bandAssignment"); return; }

        foreach (var row in rows)
        {
            var ordinal = row["rungBandLowOrdinal"]?.GetValue<int>();
            if (ordinal is null) continue;
            foreach (var themeId in RegistrySet.Strings(row["themeIds"]))
                Add(kind, $"{kind.Directory}/{themeId}/{ordinal}",
                    $"unique.{themeId}-{ordinal}-", SequenceShape.ThreeDigit);
        }
    }

    void ExpandByList(JsonObject ns, SeedKind kind, string listKey, string idPrefix)
    {
        var values = RegistrySet.Strings(ns[listKey]);
        if (values.Count == 0) { Problems.Add($"idNamespaces.{kind.NamespaceKey} declares no {listKey}"); return; }
        foreach (var value in values)
            Add(kind, $"{kind.Directory}/{value}", $"{idPrefix}{value}-", SequenceShape.ThreeDigit);
    }

    /// <summary>
    /// `set.{speciesId}-{seq:03}` — one allocation per shipped species (`setgen`'s species stage,
    /// species-gear-chain), read LIVE from <see cref="RegistrySet.CreatureSpeciesIds"/> rather than a
    /// list embedded in naming.v1.json. The species roster is a population that grows every time
    /// content ships, so embedding it here would itself go stale the next time a species shipped —
    /// the distinction validation-ssot.md draws between a closed vocabulary (pin it) and a derived
    /// population (never pin it), applied to an allocation source rather than a test assertion.
    /// Absence of the registry (a scoped run outside the full repo tree) allocates nothing here
    /// rather than failing — consistent with every other optional cross-reference this tool makes.
    ///
    /// A handful of species carry a variant suffix in their own `speciesId` written with an
    /// UNDERSCORE (`driver_a`, `elephantzombie_a`, `caltropkelp_land`) because the id grammar the
    /// authored `id` field must satisfy is kebab-case only (`IdGrammar`) — the minted id hyphenates it
    /// (`set.driver-a-001`). The prefix here must hyphenate the same way or it silently never matches
    /// (found live: without this, `elephantzombie_a`/`_b`/`_c` fell through to the BARE
    /// `elephantzombie` species' own allocation, which matched enough of the prefix to report
    /// `SequenceGrammar` on the variant tail instead of resolving cleanly, and species with no bare
    /// form at all — `driver_a`, `caltropkelp_land`/`_water`, `eternalzombie_a` — got no allocation
    /// whatsoever and stayed `IdOutsideNamespace`).
    ///
    /// ⭐ **The partition id is the id TEMPLATE's slot value, not the species id (2026-09-26,
    /// partition-key audit).** This used to read `{kind.Directory}/species/{speciesId}`, and the
    /// `species/` scope segment had no support anywhere: `naming.v1.json`'s `idNamespaces.sets`
    /// declares ONE partition key — `"partitionKey": "themeId"`, a single component, against a
    /// single `"idTemplate": "set.{themeId}-{seq:03}"` — and one `"partitionCount": 41`. Every other
    /// kind in that registry allocates exactly as many path segments as its declared key has
    /// components (`baseTypes` `(roleId, frame, band)` → 3 segments; `uniques`
    /// `(themeId, rungBandLowOrdinal)` → 2; `charms`/`consumables`/`gems`/`dropTables`/
    /// `displayTemplates`/`relics` → 1). `sets` was the only kind emitting two depths for one
    /// key, and the registry's own `speciesThemesNote` — which claims this population uses the
    /// "Same `idTemplate`/`SequenceShape.ThreeDigit` mechanism as the other two populations" — never
    /// mentions a second partition shape. So the segment was this method's own invention, and it
    /// cost 844 partitions: `setgen` derives its partition from the template's slot
    /// (`authored.py::_partition_of`, "the id's own body minus the sequence, which is what
    /// `naming.v1.json`'s `idTemplate` already says it is"), so every species set filed itself as
    /// `sets/&lt;idSlug&gt;` and the exact-string occupancy set-difference in
    /// `Coverage/EmptyPartition` read all 904 species slots as empty. Measured on that head: 911
    /// gaps, of which 904 were `sets/species/*` and 844 already held a same-species set; 65
    /// `PartitionMetaMismatch` warnings, one per underscored variant.
    ///
    /// The underscored `speciesId` is NOT discarded — it is the identity, and it stays where the
    /// design puts it: as the second token below (so `CheckPartitionCohesion` keeps tolerating a
    /// label written either way), and as the `speciesId`/`themeKey` a set entry actually carries
    /// (`setgen/emit.py::container_species_id` calls the underscore form "the authoritative
    /// `speciesId` in the theme registry" and hyphenates only "at the item boundary"). A partition
    /// is derived from an id, so it names the id's token; the canonical species identity is a field
    /// on the entry, not a path segment.
    /// </summary>
    void ExpandSpeciesThemes(RegistrySet reg, SeedKind kind)
    {
        foreach (var speciesId in reg.CreatureSpeciesIds.OrderBy(s => s, StringComparer.Ordinal))
        {
            var idSlug = speciesId.Replace('_', '-');
            Add(kind, $"{kind.Directory}/{idSlug}", $"set.{idSlug}-",
                SequenceShape.ThreeDigit, speciesId, idSlug);
        }
    }

    /// <summary>charm.{axisGroupId}-{seq:03} plus the fixed charm.res-{axis}-{countReq} list.</summary>
    void ExpandCharms(JsonObject ns, SeedKind kind)
    {
        var groups = (ns["axisGroups"] as JsonArray ?? new JsonArray()).OfType<JsonObject>().ToList();
        if (groups.Count == 0) { Problems.Add("idNamespaces.charms declares no axisGroups"); return; }

        var axes = new List<string>();
        foreach (var group in groups)
        {
            var groupId = group["axisGroupId"]?.GetValue<string>();
            if (groupId is null) continue;
            Add(kind, $"{kind.Directory}/{groupId}", $"charm.{groupId}-", SequenceShape.ThreeDigit);
            axes.AddRange(RegistrySet.Strings(group["axes"]));
        }

        // Resonance tiers are a fixed, fully enumerable list keyed on the single-word axis. The
        // breakpoints are given only inside resonanceNote's worked ids, so read them from there.
        var note = ns["resonanceNote"]?.GetValue<string>() ?? "";
        var breakpoints = Regex.Matches(note, @"charm\.res-[a-z]+-(\d+)")
            .Select(m => m.Groups[1].Value).Distinct().ToList();
        if (breakpoints.Count == 0)
        {
            Problems.Add("idNamespaces.charms.resonanceNote names no charm.res-* breakpoints — "
                         + "resonance ids cannot be allocated");
            return;
        }
        foreach (var axis in axes.Distinct())
            foreach (var breakpoint in breakpoints)
                Add(kind, $"{kind.Directory}/resonance",
                    $"charm.res-{axis}-{breakpoint}", SequenceShape.Fixed);
    }

    /// <summary>
    /// combo.strain-{gridCellTokens} / combo.splice-{gridCellTokens} — two fixed prefixes, one per
    /// `combogen` shape, each covering every id that shape can ever produce (item-seedgen
    /// `combination-write-unblock`, 2026-09-07, registryVersion 4→5). No `{seq:03}` exists to expand,
    /// so this does not go through `ExpandSlotOrFlat` — the same reason `SequenceShape.Derived` exists
    /// instead of forcing a 3-digit tail that was never going to be there.
    /// </summary>
    void ExpandCombinations(JsonObject ns, SeedKind kind)
    {
        foreach (var shape in new[] { "strain", "splice" })
            Add(kind, $"{kind.Directory}/{shape}", $"combo.{shape}-", SequenceShape.Derived);
    }

    /// <summary>
    /// rarename.head / rarename.tail -- exactly two fixed slots, never a sequence (item-seed-regen
    /// coordinator item 3, 2026-09-20: `rare-name-words` shipped in 2026-09-06 but naming.v1.json
    /// never allocated it a namespace). Each slot's whole id is fixed, the same shape
    /// `ExpandCombinations`/the charm resonance list above use for a fully-enumerable small set.
    ///
    /// Both slots share ONE partition id (<see cref="SeedKind.Directory"/> alone, not
    /// `{Directory}/{slot}`): unlike a wave-1 kind, this is one small hand-authored table, one file,
    /// one authored unit -- head and tail are two rows of the SAME table, not two agents' separate
    /// partitions. A per-slot partition id here would trip `IdentityCheck.CheckPartitionCohesion`'s
    /// `PartitionMixed` the moment the single shipped file (which legitimately carries both slots)
    /// was checked -- found live the first time this ran.
    /// </summary>
    void ExpandRareNameWords(JsonObject ns, SeedKind kind)
    {
        var slots = RegistrySet.Strings(ns["slots"]);
        if (slots.Count == 0) { Problems.Add("idNamespaces.rareNameWords declares no slots"); return; }
        foreach (var slot in slots)
            Add(kind, kind.Directory, $"rarename.{slot}", SequenceShape.Fixed);
    }

    /// <summary>
    /// Everything whose template is either a bare prefix plus {seq:03} or one slot token plus
    /// {seq:03} — gems, consumables, drop tables, display templates, materials, curves and friends.
    /// </summary>
    void ExpandSlotOrFlat(JsonObject ns, SeedKind kind)
    {
        var template = ns["idTemplate"]?.GetValue<string>();
        if (template is null) { Problems.Add($"idNamespaces.{kind.NamespaceKey} has no idTemplate"); return; }

        var seqAt = template.IndexOf("{seq:03}", StringComparison.Ordinal);
        if (seqAt < 0) { Problems.Add($"idNamespaces.{kind.NamespaceKey} template has no {{seq:03}}: {template}"); return; }
        var head = template[..seqAt];

        var slots = RegistrySet.Strings(ns["slots"]).ToList();
        if (slots.Count == 0 && ns["slots"] is JsonArray rawSlots)
            slots = rawSlots.OfType<JsonValue>()
                .Select(v => v.TryGetValue<int>(out var i) ? i.ToString() : null)
                .OfType<string>().ToList();
        if (slots.Count == 0)
            slots = (ns["slotAssignment"] as JsonArray ?? new JsonArray()).OfType<JsonObject>()
                .Select(r => r["slot"]?.GetValue<int>().ToString()).OfType<string>().ToList();

        if (!head.Contains('{'))
        {
            Add(kind, kind.Directory, head, SequenceShape.ThreeDigit);
            return;
        }

        if (slots.Count == 0)
        {
            Problems.Add($"idNamespaces.{kind.NamespaceKey} template {template} has an unexpanded token "
                         + "and no slot list");
            return;
        }

        foreach (var slot in slots)
        {
            var prefix = Regex.Replace(head, @"\{[a-zA-Z]+\}", slot);
            Add(kind, $"{kind.Directory}/{slot}", prefix, SequenceShape.ThreeDigit);
        }
    }

    /// <summary>Longest allocated prefix that this id starts with, or null.</summary>
    public AllocatedNamespace? Match(string id)
    {
        AllocatedNamespace? best = null;
        foreach (var candidate in _all)
        {
            if (candidate.Shape == SequenceShape.Fixed)
            {
                if (string.Equals(candidate.Prefix, id, StringComparison.Ordinal)) return candidate;
                continue;
            }
            if (!id.StartsWith(candidate.Prefix, StringComparison.Ordinal)) continue;
            if (best is null || candidate.Prefix.Length > best.Prefix.Length) best = candidate;
        }
        return best;
    }
}
