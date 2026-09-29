namespace FusionRpg.Tools.ItemSeedValidator.Registries;

/// <summary>
/// The bridge between three things the wave-0 artifacts name differently: the seed file's
/// <c>kind</c> (seed-contract.md §9), the directory it lives in, and naming.v1.json's
/// <c>idNamespaces</c> key. Nothing in the registries states this mapping, so it lives here —
/// and <see cref="MissingNamespaces"/> fails loudly if the registry grows a namespace this
/// catalog does not know, rather than letting it validate against nothing.
/// </summary>
public sealed record SeedKind(
    string Kind,
    string Directory,
    string NamespaceKey,
    string Stage,
    bool ShapeDefined,
    IReadOnlyList<string> RequiredFields,
    IReadOnlyList<string> AllowedFields);

public static class KindCatalog
{
    /// <summary>Envelope fields every entry may carry, whatever its kind (seed-contract.md §9).</summary>
    public static readonly string[] CommonFields =
    {
        "id", "nameKey", "name", "tags", "notes", "enabled", "overrides",
        "flavor", "flavorKey", "iconKey", "unlockGate",
        // seed-contract.md §7.2 "retire, don't delete" is both halves: an entry may retire
        // (enabled: false, already above) only alongside a stated reason -- unguarded until
        // SlotRolesTests.cs's 2026-09-06 assert (`a retired entry must say why`) made the second
        // half real. `IdentityCheck.CheckRetired` treats retirement as a common-envelope concept
        // for every kind, so the field belongs here rather than duplicated per kind (item-seed-regen
        // cause 6, 2026-09-20: found as 20 of 55 UnknownKey errors -- retiredReason on base-type;
        // the other 35 are a separate cause, non-content files (_runs/_tuning) reaching this check
        // at all).
        "retiredReason",
    };

    /// <summary>Fields every entry must carry.</summary>
    public static readonly string[] CommonRequired = { "id", "nameKey", "name" };

    /// <summary>_meta provenance the contract requires (§9). sourceRef is warned, not required.</summary>
    public static readonly string[] RequiredMeta =
    {
        "batch", "partition", "contractVersion", "registryVersions",
        "exemplarVersion", "promptVersion", "model", "authoredUtc",
    };

    static SeedKind Defined(string kind, string dir, string ns, string stage,
        string[] required, string[] extra) =>
        new(kind, dir, ns, stage, ShapeDefined: true,
            CommonRequired.Concat(required).ToArray(),
            CommonFields.Concat(extra).ToArray());

    static SeedKind Undefined(string kind, string dir, string ns, string stage) =>
        new(kind, dir, ns, stage, ShapeDefined: false, CommonRequired, CommonFields);

    /// <summary>
    /// A closed, hand-authored lookup TABLE, not id/nameKey/name content -- unlike every other
    /// entry in this catalog, <paramref name="required"/> is taken verbatim rather than having
    /// <see cref="CommonRequired"/> prepended, because a table row's identity field is whatever the
    /// table's own shape says (`categoryId`, or `id` alone with no `nameKey`/`name`), never the
    /// common content triad. <see cref="CommonFields"/> is still folded into the ALLOWED set (a
    /// stray `notes`/`enabled` on a table row is harmless), just never required.
    /// </summary>
    static SeedKind DefinedTable(string kind, string dir, string ns, string stage,
        string[] required, string[] extra) =>
        new(kind, dir, ns, stage, ShapeDefined: true,
            RequiredFields: required,
            AllowedFields: CommonFields.Concat(extra).ToArray());

    /// <summary>Every kind, keyed by its <c>kind</c> value.</summary>
    public static readonly IReadOnlyDictionary<string, SeedKind> All = new[]
    {
        // Shapes seed-contract.md §10 actually specifies.
        Defined("base-type", "base-types", "baseTypes", "1b",
            required: new[] { "frame", "role", "class", "band", "iconKey", "tags" },
            // `enhanceTrack` is entry-shapes.md §6's `item_enhance_track`, scoped onto this kind
            // rather than onto the milestone: the family says what the +X grants, the base type
            // says who grants it and at which rung.
            extra: new[] { "frame", "role", "class", "band", "implicit", "socketMax", "enhanceTrack", "successorOf" }),
        // "roles" is not in this required list even though it is effectively mandatory: the
        // requirement is "roles" OR the pre-rename "roleGroups", and the generic single-key
        // RequiredFields check has no OR — ReferenceCheck.CheckRoles enforces the real rule
        // (missing both is RequiredFieldMissing; roleGroups alone warns RoleGroupsRenamed instead
        // of rejecting) so an author who has not yet migrated off the old name is not blamed for
        // a contract rename.
        Defined("affix-family", "affix-families", "affixFamilies", "1a",
            required: new[] { "kindId", "powerBand", "tags" },
            extra: new[]
            {
                "kindId", "params", "variants", "frames", "side", "roles", "roleGroups",
                "powerBand", "nameWords", "displayTemplate", "channel",
            }),
        Defined("unique", "uniques", "uniques", "1c",
            required: new[]
            {
                "frame", "baseType", "rarity", "fixedAtoms", "counterPressure", "tags",
                // ssot-uniques.md §3.7 keys its anti-convergence rule on (role, rung band, power
                // axis) and the shape carried no axis, so the rule was unverifiable and eighteen
                // partitions were trusted rather than checked. Required, not optional: an optional
                // field that half the corpus omits cannot gate anything.
                "powerAxis",
            },
            extra: new[]
            {
                "frame", "baseType", "rarity", "fixedAtoms", "varianceSlot",
                "counterPressure", "theme", "themeKey", "acquisition", "powerAxis",
            }),
        // species-gear-chain T27 (set-species-binding a): speciesId is optional, never required —
        // a build.*/theme.* themed set carries none, the correct explicit-absent state.
        Defined("set", "sets", "sets", "1c",
            required: new[] { "themeKey", "members", "thresholds" },
            extra: new[] { "themeKey", "theme", "members", "thresholds", "speciesId", "setClass" }),

        // Shapes docs/architecture/item/entry-shapes.md gives, closing the gap the ten
        // UnknownKeyShapeUndefined warnings used to report. Field lists are transcribed from that
        // document's per-kind tables; DERIVED/GENERATED fields (tiers, resonances, weight, grade
        // on a consumable, souls_cost, qty_curve_id, affixClass, min_count/max_count, …) are
        // deliberately absent so they stay rejectable as UnknownKey.
        Defined("gem", "gems", "gems", "1b",
            required: new[] { "family", "powerBand" },
            extra: new[] { "family", "element", "powerBand", "affinityElement" }),
        Defined("material", "materials", "materials", "1a",
            required: new[] { "runtimeId", "materialClass" },
            extra: new[] { "runtimeId", "materialClass", "element", "frame", "grade",
                "scope", "scopeKey", "slot" }),
        Defined("curve", "curves", "curves", "1a",
            required: new[] { "input", "points" },
            extra: new[] { "input", "points" }),
        Undefined("attribute", "attributes", "attributes", "1a"),
        Defined("charm", "charms", "charms", "1c",
            required: new[] { "charmClass", "apCost", "axis", "frameHint", "fixedAtoms" },
            extra: new[]
            {
                "charmClass", "apCost", "axis", "frameHint", "uniqueCarry", "fixedAtoms",
                // prefixRolls/suffixRolls (effect-pipeline T3.2) replace the single poolRolls, same
                // split as the real container schema's prefix_rolls/suffix_rolls columns.
                "roleGroups", "prefixRolls", "suffixRolls",
            }),
        // strain-splice-host SSH2.6 (rename bundle #3, spec-combination-regen.md): the legacy
        // `socket-word` row is REMOVED for real. SSH2.4 found (real `dotnet run`) that removing it
        // earlier, while `data/seed/items/socket-words/sockwords.json` still existed and still
        // declared `"kind": "socket-word"`, produced a real `KindUnknown` + 25 `IdOutsideNamespace`
        // findings -- so the row stayed until this task's own `combogen-migrate --write` actually
        // deleted that file (95 real `combination` entries now replace the 25 legacy ones, SSH2.5).
        // `combination` (below) already existed as its own separate row since
        // `combination-write-unblock` (2026-09-07), so removing this one leaves exactly one row for
        // the kind, matching the Python port's own in-place rename (`kinds.py`'s `KINDS`, SSH2.4).
        // item-seedgen `combination-write-unblock` (2026-09-07): the retirement target for
        // `socket-word` (already RULED, `seedsmith-map.md` §5: "regenerate, do not retain"), and the
        // real gap this catalog carried until now — `combogen`'s own generation graph, schema and
        // ledger were all built and proven this same day, but nothing here could validate a real
        // `combination` entry once written, since no SeedKind existed to recognize the directory
        // `combogen/authored.py`'s own `COMBINATIONS_DIR` already names
        // (`gk-data/packs/fusion/data/seed/items/combinations/`). Field shape transcribed directly from `combogen/
        // emit.py`'s `assemble_entry` — the one place a real entry is assembled — not guessed:
        // `shape` ("strain" or "splice", `grid.py`'s own `combination_kind`) and `aptitudes` are
        // unconditional; `archetype` (splices carry none), `hostRole` and `hostFrame` are optional,
        // set only when the model pinned one. `minSockets`/`ingredients`/`grants` always present.
        // No `naming.v1.json` namespace exists for this kind and none is needed — `combogen` mints
        // its own ids directly from the deterministic grid cell (one pipeline, zero parallel
        // partitions), so the collision problem `idNamespaces` solves for wave-1 fan-out never
        // arises here; `MissingNamespaces` below is a registry-to-catalog check, not the reverse, so
        // this entry having no counterpart in `naming.v1.json` trips nothing.
        // strain-splice-host SSH7.5 (spec-tier-ladder §3): `grantedTier` is no longer REQUIRED — the
        // tier a shape grants is the tuning's, filled by `CombinationCorpus` at import. It stays in
        // `extra` until SSH7.6 re-emits the corpus without it, so today's rows still validate.
        // SSH7.6: the re-emitted corpus carries no tier number, so `grantedTier` leaves `extra` too —
        // a row that reintroduces one is now refused rather than tolerated.
        Defined("combination", "combinations", "combinations", "1c",
            required: new[] { "shape", "aptitudes", "minSockets", "ingredients", "grants" },
            extra: new[]
            {
                "shape", "aptitudes", "archetype", "hostRole", "hostFrame",
                "minSockets", "ingredients", "grants",
            }),
        Defined("recipe", "recipes", "recipes", "1c",
            required: new[] { "operation", "outputKind", "frame", "costLines" },
            extra: new[]
            {
                "operation", "outputKind", "outputRef", "outputQty", "frame", "costLines", "soulsCostBand",
            }),
        Defined("enhancement-milestone", "enhancement-milestones", "enhancementMilestones", "1c",
            required: new[] { "runtimeFamily", "kindId", "params", "powerBand" },
            extra: new[] { "runtimeFamily", "kindId", "params", "powerBand" }),
        Defined("consumable", "consumables", "consumables", "1c",
            required: new[] { "classId", "useContext", "family", "powerBand" },
            extra: new[]
            {
                "classId", "useContext", "family", "element", "powerBand", "manifestCost",
                "grantsActionId", "cooldownKey",
            }),
        // Stage 1d, alone. A drop table is the only kind that references *every* other kind —
        // base types, uniques, sets, gems, charms, consumables — so it cannot share a stage with
        // its own targets: `SameStageReference` exists precisely because same-stage partitions are
        // authored in parallel and cannot see each other. Drop tables were always dispatched last
        // for this reason; the stage label simply had not caught up, and ssot-uniques.md §4.5
        // requires "a drop-table entry naming a unique's container", which is a 1c target.
        Defined("drop-table", "drop-tables", "dropTables", "1d",
            required: new[] { "sourceAllow", "groups" },
            extra: new[] { "sourceAllow", "groups" }),
        Defined("display-template", "display-templates", "displayTemplates", "1c",
            required: new[] { "runtimeFamily", "groupId", "status" },
            extra: new[] { "runtimeFamily", "plantOverrideKey", "plantOverrideName", "groupId", "status" }),
        // relic-item-kind (empire-development Task 1.3a, spec-relic-item-kind.md §Design 1) — a
        // rolled, never-equipped item with no equip role and no base type. Required is the common
        // triple plus flavorKey only: no frame, no baseType, no role, no counterPressure, no
        // powerAxis. fixedAtoms is optional (many relics are pure Wonder-build cost tokens), and
        // there is no reference field — a relic never points at a base type or role.
        Defined("relic", "relics", "relics", "1c",
            required: new[] { "flavorKey" },
            extra: new[] { "flavorKey", "theme", "themeKey", "acquisition", "fixedAtoms" }),

        // item-seed-regen coordinator item 3 (2026-09-20): two kinds that already shipped content
        // (ssot-item-categories.md §5.1, ssot-affixes.md §4.12) but were never onboarded here, so
        // every file under them read as KindUnknown. Stage "0": neither is a wave-1 partition (no
        // agent authors new rows here; both are closed, hand-authored tables), so the 1a-1d stage
        // ladder does not apply -- "0" sorts before every real stage and nothing references either
        // kind's rows, so ReferenceCheck's same-stage rule never engages it.
        DefinedTable("item-category", "_seed", "itemCategories", "0",
            required: new[]
            {
                "categoryId", "rollsValues", "stackIntent", "ownerScope", "store", "consumer",
                "declareOnly",
            },
            extra: new[]
            {
                "categoryId", "rollsValues", "stackIntent", "ownerScope", "store", "consumer",
                "declareOnly",
            }),
        // rare-name-words carries `id` (unlike item-category) but no `nameKey`/`name` -- the two
        // rows are a fixed head/tail word LIST, not a display-named entry. Ids renamed
        // rare-name.head/tail -> rarename.head/tail in the same change (IdGrammar's first segment
        // is `[a-z][a-z0-9]*`, no hyphen; nothing outside this one file reads the `id` field, only
        // `slot` -- confirmed against RareNameCorpus.Load, gk-core/src/FusionRpg.Server/ItemCardEndpoints.cs
        // -- so renaming carries no cross-reference risk), and registered in naming.v1.json
        // (idNamespaces.rareNameWords, registryVersion 8->9, additive).
        DefinedTable("rare-name-words", "rare-names", "rareNameWords", "0",
            required: new[] { "id", "slot", "words" },
            extra: new[] { "slot", "words" }),
    }.ToDictionary(k => k.Kind, StringComparer.Ordinal);

    public static SeedKind? ByDirectory(string directory) =>
        All.Values.FirstOrDefault(k => string.Equals(k.Directory, directory, StringComparison.Ordinal));

    public static SeedKind? ByNamespace(string namespaceKey) =>
        All.Values.FirstOrDefault(k => string.Equals(k.NamespaceKey, namespaceKey, StringComparison.Ordinal));

    /// <summary>
    /// idNamespaces keys this catalog does not cover. A non-empty result means naming.v1.json
    /// allocated a namespace nothing here validates — a stop-the-fleet gap, not a warning.
    /// </summary>
    public static IReadOnlyList<string> MissingNamespaces(RegistrySet registries)
    {
        var declared = (registries.Naming["idNamespaces"] as System.Text.Json.Nodes.JsonObject)
            ?.Select(kv => kv.Key)
            .Where(k => !k.StartsWith('_') && k != "partitionCountCheck")
            .ToList() ?? new List<string>();
        return declared.Where(k => ByNamespace(k) is null).ToList();
    }
}
