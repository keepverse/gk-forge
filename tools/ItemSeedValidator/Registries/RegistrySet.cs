using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace FusionRpg.Tools.ItemSeedValidator.Registries;

/// <summary>
/// The six wave-0 registries, loaded from disk. Nothing in this class hardcodes a registry's
/// contents — every vocabulary below is read out of the files, so a registry v2 changes the
/// validator's behaviour without changing its code.
/// </summary>
public sealed class RegistrySet
{
    public required string RegistryDir { get; init; }

    public JsonObject Core { get; private init; } = new();
    public JsonObject Bands { get; private init; } = new();
    public JsonObject Tags { get; private init; } = new();
    public JsonObject Themes { get; private init; } = new();
    public JsonObject Classes { get; private init; } = new();
    public JsonObject Naming { get; private init; } = new();

    /// <summary>
    /// The `build.*` themeKey population (item module 13, set-charm-gen): 12 aptitudes x 3
    /// archetypes, derived from gk-data/packs/fusion/data/seed/aptitudes/roster.json rather than authored. Optional
    /// on purpose — every check that reads it degrades to the legacy population when it is
    /// absent, so an older tree still validates.
    /// </summary>
    public JsonObject? BuildThemes { get; private init; }

    /// <summary>F1's reserved word pools. Not authored yet; absent is legal and reported.</summary>
    public JsonObject? Words { get; private init; }

    /// <summary>Optional ledger of ids retired by earlier runs (see seed-contract.md §7.2).</summary>
    public JsonObject? RetiredIds { get; private init; }

    /// <summary>
    /// D3's role-override table (item module 8, `affix-legality`): a role-wide tier cap or family
    /// removal. Optional on the same "absence degrades, never blocks" rule every other registry
    /// here follows — a scoped validation run over a handful of hand-built entries has no reason to
    /// carry this file, and `RoleFamilyCheck` reports rather than errors when it is absent.
    /// </summary>
    public JsonObject? FamilyOverrides { get; private init; }

    /// <summary>D3's relocation table (item module 8): a family dropped from `ward-array`/
    /// `head-guard`/`sense` re-legalised on a surviving hybrid-core host, at a reduced tier. Same
    /// optionality rule as <see cref="FamilyOverrides"/>.</summary>
    public JsonObject? RoleRelocation { get; private init; }

    // --- core.v1.json -------------------------------------------------------------------
    public IReadOnlyList<string> RoleIds { get; private set; } = Array.Empty<string>();
    public IReadOnlyList<string> WaveOneRoleIds { get; private set; } = Array.Empty<string>();
    public IReadOnlyDictionary<string, (string Humanoid, string Plant)> RoleDisplayNames { get; private set; }
        = new Dictionary<string, (string, string)>();
    public IReadOnlyList<string> FrameIds { get; private set; } = Array.Empty<string>();
    public IReadOnlyList<string> RarityIds { get; private set; } = Array.Empty<string>();
    public IReadOnlyList<string> CategoryIds { get; private set; } = Array.Empty<string>();

    /// <summary>
    /// The five power-vector categories. Distinct from `tags.v1.json`'s three-value
    /// `combat-posture` axis, which overlaps it on the word "utility" and is a different thing —
    /// a confusion that has cost this build several rejected files.
    /// </summary>
    public IReadOnlyList<string> PowerCategoryIds { get; private set; } = Array.Empty<string>();

    // --- bands.v1.json ------------------------------------------------------------------
    /// <summary>band-field name (powerBand / costBand / dropBand / variance) to its closed enum.</summary>
    public IReadOnlyDictionary<string, IReadOnlyList<string>> BandEnums { get; private set; }
        = new Dictionary<string, IReadOnlyList<string>>();

    /// <summary>powerBand value to tier ordinal, for the tier-gap lint.</summary>
    public IReadOnlyDictionary<string, int> PowerBandTiers { get; private set; } = new Dictionary<string, int>();

    // --- tags.v1.json -------------------------------------------------------------------
    public IReadOnlyDictionary<string, string> TagAxis { get; private set; } = new Dictionary<string, string>();
    public IReadOnlyDictionary<string, TagAxisInfo> Axes { get; private set; } = new Dictionary<string, TagAxisInfo>();

    // --- themes.v1.json -----------------------------------------------------------------
    /// <summary>
    /// The legal <c>themeKey</c> bodies — the union of the legacy <c>theme.*</c> population
    /// (themes.v1.json, frozen) and the <c>build.*</c> population build-themes.v1.json adds
    /// (item module 13, set-charm-gen). A <c>set</c> REQUIRES a themeKey and the 36 build set
    /// families belong to no species, so without the second population a build set is
    /// unauthorable. The two cannot collide: one is prefixed <c>theme.</c>, the other
    /// <c>build.</c>, and <see cref="Checks.ReferenceCheck"/> strips whichever it sees.
    /// </summary>
    public IReadOnlyList<string> ThemeIds { get; private set; } = Array.Empty<string>();

    /// <summary>Element vocabulary. No registry owns it outright — see README, "element".</summary>
    public IReadOnlyList<string> ElementIds { get; private set; } = Array.Empty<string>();

    // --- classes.v1.json ----------------------------------------------------------------
    public IReadOnlyList<string> ClassIds { get; private set; } = Array.Empty<string>();

    /// <summary>
    /// Kinds whose <c>name</c> is not a drawn item name, per
    /// <c>words.v1.json poolAccess.kindsExemptFromPools</c>. The pool-derived naming grammar does
    /// not apply to them — a display template is a sentence, a gem is deliberately systematic, a
    /// recipe names a verb. Collision and nameKey uniqueness still do.
    /// </summary>
    public bool IsPoolExemptKind(string? kind)
    {
        if (kind is null) return false;
        var access = Words?["poolAccess"] as JsonObject;
        if (access?["kindsExemptFromPools"] is not JsonObject block) return false;
        if (block["exempt"] is not JsonArray list) return false;
        return list.OfType<JsonObject>()
            .Any(o => o["kind"] is JsonValue v
                      && v.TryGetValue<string>(out var k)
                      && string.Equals(k, kind, StringComparison.Ordinal));
    }

    /// <summary>
    /// Which class ladders a role may draw from, per <c>words.v1.json poolAccess.roleToLadders</c>.
    /// Empty when the registry says nothing about the role, in which case the caller must not judge.
    /// </summary>
    public IReadOnlyList<string> LaddersForRole(string roleId)
    {
        var access = Words?["poolAccess"] as JsonObject;
        if (access?["roleToLadders"] is not JsonObject map) return Array.Empty<string>();
        if (map[roleId] is not JsonArray arr) return Array.Empty<string>();
        return arr.OfType<JsonValue>()
            .Select(v => v.TryGetValue<string>(out var s) ? s : null)
            .OfType<string>()
            .ToList();
    }

    /// <summary>class id to (ladder, frame, rung), for the empty-rung lint.</summary>
    public IReadOnlyDictionary<string, (string Ladder, string Frame, int Rung)> ClassRungs { get; private set; }
        = new Dictionary<string, (string, string, int)>();

    /// <summary>Affix families already shipped by the atom layer, named by the registries.</summary>
    public IReadOnlySet<string> ShippedFamilies { get; private set; } = new HashSet<string>();

    // --- naming.v1.json -----------------------------------------------------------------
    public IReadOnlyList<string> NameKeyPrefixes { get; private set; } = Array.Empty<string>();
    public IReadOnlyList<string> Connectives { get; private set; } = Array.Empty<string>();
    public string ConnectiveSource { get; private set; } = "";
    public int SequenceMin { get; private set; } = 1;
    public int SequenceMax { get; private set; } = 899;

    /// <summary>surface form (lowercased) to canonical word-pool id. Empty when F1 has not run.</summary>
    public IReadOnlyDictionary<string, string> SurfaceForms { get; private set; } = new Dictionary<string, string>();

    /// <summary>Every canonical pool id, for fusion decomposition.</summary>
    public IReadOnlySet<string> CanonicalWords { get; private set; } = new HashSet<string>();

    public IReadOnlySet<string> Retired { get; private set; } = new HashSet<string>();

    /// <summary>
    /// Every `speciesId` the creature theme registry carries (`gk-data/packs/fusion/data/seed/creatures/_registry/
    /// themes.v2.json`), read independently of <see cref="RegistryDir"/> by walking up from the
    /// process's own working directory — the discovery `SetRuleCheck`'s species-binding guard
    /// established first (species-gear-chain T28), centralized here so every check (namespace
    /// allocation included) shares one loader instead of re-deriving it. A tiny in-memory
    /// <see cref="FromNodes"/> fixture in a unit test still resolves against the REAL shipped roster
    /// this way, rather than needing its own 904-row copy. Deliberately reads the creature corpus's
    /// own registry, never <c>CreatureSpeciesCatalog</c>'s stale compiled fallback — this tool "opens
    /// no database and issues no SQL" (its own file header). Empty when the registry cannot be found;
    /// check <see cref="CreatureSpeciesRegistryFound"/> before treating emptiness as "no species
    /// exist" rather than "not reachable from here".
    /// </summary>
    public IReadOnlySet<string> CreatureSpeciesIds { get; private set; } = new HashSet<string>();

    /// <summary>False when `themes.v2.json` was not found above the working directory (or failed to
    /// parse) — callers must degrade (skip / warn once), never report a false error on every row that
    /// merely couldn't be checked.</summary>
    public bool CreatureSpeciesRegistryFound { get; private set; }

    /// <summary>
    /// Every affix-family id already claimed as a KEY in `gk-data/packs/fusion/data/seed/actions/pairings.json`
    /// (`EnablerPayoffPairings`, a different corpus this tool otherwise never reads) — read
    /// independently of <see cref="RegistryDir"/> by walking up from the working directory, the
    /// same cross-corpus pattern <see cref="CreatureSpeciesIds"/> already established.
    ///
    /// item-seed-regen coordinator item 3 (2026-09-20): `atom.chill-punisher`/`atom.rot-punisher`
    /// are genuinely NEW families (not part of the pre-existing ~70 <c>IsShippedFamilyId</c>
    /// protects in `IdentityCheck.cs`), so they read as `IdOutsideNamespace` under the ordinary
    /// `atom.{stem}-{word}` mint rule. But a real, tested C# consumer
    /// (`EnablerPayoffPairings.IsPayoff`, `gk-core/src/FusionRpg.Core/Actions/Seeding/`) already matches
    /// them by this EXACT literal id string as a dictionary key — renaming either id here would
    /// silently break that lookup with no compile error on either side, exactly the failure mode
    /// <c>IsShippedFamilyId</c>'s own docstring already protects against for the original 70. Read
    /// live from the table's own keys, never hardcoded to these two ids, so a third payoff family
    /// registered the same way needs no code change here.
    /// </summary>
    public IReadOnlySet<string> EnablerPayoffPairingFamilyIds { get; private set; } = new HashSet<string>();

    /// <summary>False when `gk-data/packs/fusion/data/seed/actions/pairings.json` was not found above the working
    /// directory (or failed to parse) — degrades the same way <see cref="CreatureSpeciesRegistryFound"/>
    /// does.</summary>
    public bool EnablerPayoffPairingsRegistryFound { get; private set; }

    /// <summary>logical registry name to its registryVersion, for the _meta cross-check.</summary>
    public IReadOnlyDictionary<string, int> Versions { get; private set; } = new Dictionary<string, int>();

    /// <summary>
    /// The oldest registry version whose content is still valid. A bump that only adds leaves this
    /// alone; a bump that changes or removes meaning raises it, and every file authored below it
    /// must re-run. Declared per registry as <c>minCompatibleVersion</c>.
    /// </summary>
    public IReadOnlyDictionary<string, int> MinCompatible { get; private set; } = new Dictionary<string, int>();

    /// <summary>Registries still carrying frozen:false at the freeze gate.</summary>
    public IReadOnlyList<string> Unfrozen { get; private set; } = Array.Empty<string>();

    public sealed record TagAxisInfo(string Id, bool Exclusive, IReadOnlyList<string> AppliesTo);

    public static RegistrySet Load(string registryDir)
    {
        JsonObject Read(string name)
        {
            var path = Path.Combine(registryDir, name);
            if (!File.Exists(path)) throw new FileNotFoundException($"registry not found: {path}");
            return JsonNode.Parse(File.ReadAllText(path)) as JsonObject
                   ?? throw new InvalidDataException($"registry is not a JSON object: {path}");
        }

        JsonObject? ReadOptional(string name)
        {
            var path = Path.Combine(registryDir, name);
            return File.Exists(path) ? JsonNode.Parse(File.ReadAllText(path)) as JsonObject : null;
        }

        var set = new RegistrySet
        {
            RegistryDir = registryDir,
            Core = Read("core.v1.json"),
            Bands = Read("bands.v1.json"),
            Tags = Read("tags.v1.json"),
            Themes = Read("themes.v1.json"),
            // item-ideal.md, base-types (module 6, D35): v2 re-derives the 32-family global
            // exclusion list against AtomKindRegistry.cs, lifting 15 stale D6-quarantine entries.
            // v1 and v2 stay on disk (frozen, never edited); v3 is additive on top of v2 — it adds
            // `legalFamiliesByFrame` per role (D11 clause 1, 2026-09-12) and leaves the role-wide
            // `legalFamilies` as the union, so nothing legal under v2 becomes illegal here.
            Classes = Read("classes.v3.json"),
            Naming = Read("naming.v1.json"),
            BuildThemes = ReadOptional("build-themes.v1.json"),
            Words = ReadOptional("words.v1.json"),
            RetiredIds = ReadOptional("retired-ids.json"),
            FamilyOverrides = ReadOptional("family-overrides.v1.json"),
            RoleRelocation = ReadOptional("role-relocation.v1.json"),
        };
        set.Index();
        return set;
    }

    /// <summary>Test seam: build a set straight from in-memory registry nodes.</summary>
    public static RegistrySet FromNodes(
        JsonObject core, JsonObject bands, JsonObject tags, JsonObject themes,
        JsonObject classes, JsonObject naming, JsonObject? words = null, JsonObject? retired = null,
        JsonObject? buildThemes = null, JsonObject? familyOverrides = null, JsonObject? roleRelocation = null)
    {
        var set = new RegistrySet
        {
            RegistryDir = "(in-memory)",
            Core = core, Bands = bands, Tags = tags, Themes = themes,
            Classes = classes, Naming = naming, Words = words, RetiredIds = retired,
            BuildThemes = buildThemes, FamilyOverrides = familyOverrides, RoleRelocation = roleRelocation,
        };
        set.Index();
        return set;
    }

    internal static IReadOnlyList<string> Strings(JsonNode? node) =>
        node is JsonArray arr
            ? arr.OfType<JsonValue>()
                .Select(v => v.TryGetValue<string>(out var s) ? s : null)
                .Where(s => !string.IsNullOrEmpty(s)).Select(s => s!).ToList()
            : Array.Empty<string>();

    void Index()
    {
        IndexCore();
        IndexBands();
        IndexTags();
        IndexThemes();
        IndexClasses();
        IndexNaming();
        IndexWords();
        IndexRetired();
        IndexCreatureThemes();
        IndexEnablerPayoffPairings();

        var versions = new Dictionary<string, int>(StringComparer.Ordinal);
        var minCompatible = new Dictionary<string, int>(StringComparer.Ordinal);
        var unfrozen = new List<string>();
        void Version(string logical, JsonObject reg, string file)
        {
            versions[logical] = reg["registryVersion"]?.GetValue<int>() ?? 0;
            minCompatible[logical] = reg["minCompatibleVersion"]?.GetValue<int>() ?? versions[logical];
            if (reg["frozen"] is JsonValue f && f.TryGetValue<bool>(out var frozen) && !frozen
                && !unfrozen.Contains(file)) unfrozen.Add(file);
        }
        Version("core", Core, "core.v1.json");
        // core owns three vocabularies the contract's _meta example names separately.
        Version("roles", Core, "core.v1.json");
        Version("rarity", Core, "core.v1.json");
        Version("categories", Core, "core.v1.json");
        Version("bands", Bands, "bands.v1.json");
        Version("tags", Tags, "tags.v1.json");
        Version("themes", Themes, "themes.v1.json");
        Version("classes", Classes, "classes.v2.json");
        Version("naming", Naming, "naming.v1.json");
        // words.v1.json is optional to load but nameable in _meta: an author who drew from the
        // pools has every reason to record which version they drew from.
        if (Words is not null) Version("words", Words, "words.v1.json");
        Versions = versions;
        MinCompatible = minCompatible;
        Unfrozen = unfrozen;
    }

    void IndexCore()
    {
        var roles = Core["roles"] as JsonObject;
        var list = roles?["list"] as JsonArray ?? new JsonArray();
        var display = new Dictionary<string, (string, string)>(StringComparer.Ordinal);
        var ids = new List<string>();
        var waveOne = new List<string>();
        foreach (var row in list.OfType<JsonObject>())
        {
            var id = row["roleId"]?.GetValue<string>();
            if (id is null) continue;
            ids.Add(id);
            waveOne.Add(id);
            display[id] = (row["humanoidName"]?.GetValue<string>() ?? id,
                           row["plantName"]?.GetValue<string>() ?? id);
        }
        foreach (var row in (roles?["commanderOnly"] as JsonArray ?? new JsonArray()).OfType<JsonObject>())
        {
            var id = row["roleId"]?.GetValue<string>();
            if (id is null) continue;
            ids.Add(id);
            display[id] = (row["humanoidName"]?.GetValue<string>() ?? id,
                           row["plantName"]?.GetValue<string>() ?? id);
        }
        RoleIds = ids;
        WaveOneRoleIds = waveOne;
        RoleDisplayNames = display;
        FrameIds = (roles?["frames"] as JsonArray ?? new JsonArray())
            .OfType<JsonObject>().Select(f => f["id"]?.GetValue<string>()).OfType<string>().ToList();
        RarityIds = ((Core["rarity"] as JsonObject)?["ladder"] as JsonArray ?? new JsonArray())
            .OfType<JsonObject>().Select(r => r["id"]?.GetValue<string>()).OfType<string>().ToList();
        CategoryIds = ((Core["categories"] as JsonObject)?["list"] as JsonArray ?? new JsonArray())
            .OfType<JsonObject>().Select(r => r["id"]?.GetValue<string>()).OfType<string>().ToList();
        PowerCategoryIds = ((Core["powerCategories"] as JsonObject)?["list"] as JsonArray ?? new JsonArray())
            .OfType<JsonObject>().Select(r => r["id"]?.GetValue<string>()).OfType<string>().ToList();
    }

    void IndexBands()
    {
        var enums = new Dictionary<string, IReadOnlyList<string>>(StringComparer.Ordinal);
        foreach (var field in new[] { "powerBand", "costBand", "dropBand", "variance" })
            if (Bands[field] is JsonObject band)
                enums[field] = Strings(band["enum"]);
        BandEnums = enums;

        var tiers = new Dictionary<string, int>(StringComparer.Ordinal);
        if ((Bands["powerBand"] as JsonObject)?["tierMap"] is JsonObject map)
            foreach (var kv in map)
                if (kv.Value is JsonValue v && v.TryGetValue<int>(out var tier)) tiers[kv.Key] = tier;
        PowerBandTiers = tiers;
    }

    void IndexTags()
    {
        var axes = new Dictionary<string, TagAxisInfo>(StringComparer.Ordinal);
        foreach (var axis in (Tags["axes"] as JsonArray ?? new JsonArray()).OfType<JsonObject>())
        {
            var id = axis["id"]?.GetValue<string>();
            if (id is null) continue;
            axes[id] = new TagAxisInfo(id, axis["exclusive"]?.GetValue<bool>() ?? false, Strings(axis["appliesTo"]));
        }
        Axes = axes;

        var tagAxis = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var tag in (Tags["tags"] as JsonArray ?? new JsonArray()).OfType<JsonObject>())
        {
            var id = tag["id"]?.GetValue<string>();
            if (id is null) continue;
            tagAxis[id] = tag["axis"]?.GetValue<string>() ?? "";
        }
        TagAxis = tagAxis;
    }

    void IndexThemes()
    {
        var themes = (Themes["themes"] as JsonArray ?? new JsonArray()).OfType<JsonObject>().ToList();
        // The union of the two themeKey populations. build-themes.v1.json's own `id` is already
        // the bare body (`might-offense`); its `themeKey` carries the `build.` prefix, which
        // ReferenceCheck strips before it looks here — the same shape the legacy `theme.` prefix
        // has always had. Absent file = legacy population only, which is what every tree before
        // item module 13 has.
        var buildThemes = (BuildThemes?["themes"] as JsonArray ?? new JsonArray())
            .OfType<JsonObject>()
            .Select(t => t["id"]?.GetValue<string>())
            .OfType<string>();
        ThemeIds = themes.Select(t => t["id"]?.GetValue<string>()).OfType<string>()
            .Concat(buildThemes)
            .Distinct(StringComparer.Ordinal)
            .ToList();

        // No wave-0 registry declares the element list on its own. themes.v1.json is the only one
        // that names elements at all, and definitions.md §1 fixes the shape at "6 elements + omni",
        // so the union of every theme's affinity plus omni is the vocabulary. An explicit
        // `elements` key in any registry wins over this derivation the moment one lands.
        var explicitList = Strings(Themes["elements"]).Concat(Strings(Core["elements"])).ToList();
        var elements = explicitList.Count > 0
            ? explicitList
            : themes.SelectMany(t => Strings(t["elementAffinity"])).Concat(new[] { "omni" }).ToList();
        ElementIds = elements.Distinct(StringComparer.Ordinal).OrderBy(e => e, StringComparer.Ordinal).ToList();
    }

    void IndexClasses()
    {
        var rungs = new Dictionary<string, (string, string, int)>(StringComparer.Ordinal);
        foreach (var ladder in Classes["classLadders"] as JsonObject ?? new JsonObject())
        {
            if (ladder.Value is not JsonObject ladderNode) continue;
            foreach (var frame in ladderNode)
            {
                if (frame.Value is not JsonArray rows) continue;
                foreach (var row in rows.OfType<JsonObject>())
                {
                    var id = row["id"]?.GetValue<string>();
                    if (id is null) continue;
                    rungs[id] = (ladder.Key, frame.Key, row["rung"]?.GetValue<int>() ?? 0);
                }
            }
        }
        ClassRungs = rungs;
        ClassIds = rungs.Keys.OrderBy(k => k, StringComparer.Ordinal).ToList();

        // Families the registries already name as shipped: a seed file may legally reference one
        // even though no seed file authors it.
        var families = new HashSet<string>(StringComparer.Ordinal);
        foreach (var row in ((Classes["excludedFamilies"] as JsonObject)?["global"] as JsonArray ?? new JsonArray())
                     .OfType<JsonObject>())
            if (row["family"]?.GetValue<string>() is { } f) families.Add(f);
        foreach (var slate in Classes["implicitSlates"] as JsonObject ?? new JsonObject())
        {
            if (slate.Value is not JsonObject node) continue;
            foreach (var f in Strings(node["legalFamilies"])) families.Add(f);
            foreach (var row in (node["excludedForRole"] as JsonArray ?? new JsonArray()).OfType<JsonObject>())
                if (row["family"]?.GetValue<string>() is { } f) families.Add(f);
        }
        // naming.v1.json's affix groups name every shipped family by its display shorthand.
        var groups = ((Naming["idNamespaces"] as JsonObject)?["affixFamilies"] as JsonObject)?["groups"] as JsonArray;
        foreach (var group in (groups ?? new JsonArray()).OfType<JsonObject>())
            foreach (var existing in Strings(group["existingFamilies"]))
                if (Regex.IsMatch(existing, "^[a-z0-9_]+$"))
                    families.Add("atom." + existing.Replace('_', '-'));
        ShippedFamilies = families;
    }

    void IndexNaming()
    {
        var grammar = Naming["namingGrammar"] as JsonObject;
        NameKeyPrefixes = Strings((grammar?["nameKey"] as JsonObject)?["kindPrefixes"]);

        var policy = Naming["idPolicy"] as JsonObject;
        var range = (policy?["sequenceRange"] as JsonObject)?["wave1Batch"]?.GetValue<string>();
        var m = range is null ? Match.Empty : Regex.Match(range, @"^(\d+)\s*-\s*(\d+)$");
        if (m.Success) { SequenceMin = int.Parse(m.Groups[1].Value); SequenceMax = int.Parse(m.Groups[2].Value); }

        var norm = grammar?["collisionNormalization"] as JsonObject;

        // Preferred: words.v1.json lists the four as a structured array it reserves out of pools.
        var reserved = Strings((Words?["reservedOutOfPools"] as JsonObject)?["connectives"]);
        if (reserved.Count > 0)
        {
            Connectives = reserved;
            ConnectiveSource = "words.v1.json reservedOutOfPools.connectives";
            return;
        }

        // Next: a structured key on the naming registry, if F8 ever adds one.
        var structured = Strings(norm?["connectives"]);
        if (structured.Count > 0)
        {
            Connectives = structured;
            ConnectiveSource = "naming.v1.json collisionNormalization.connectives";
            return;
        }

        // Otherwise read them out of algorithm step 4, where they are written as backticked
        // literals. The registry declares that list closed at exactly four entries forever
        // (namingGrammar.pluralsPossessivesConnectives.invatedConnectives), so parsing it is safe.
        var step4 = Strings(norm?["algorithm"]).FirstOrDefault(s => s.StartsWith("4.", StringComparison.Ordinal));
        if (step4 is not null)
        {
            var words = Regex.Matches(step4, "`([a-z]+)`").Select(x => x.Groups[1].Value).Distinct().ToList();
            if (words.Count > 0)
            {
                Connectives = words;
                ConnectiveSource = "naming.v1.json collisionNormalization.algorithm step 4";
                return;
            }
        }

        Connectives = new[] { "of", "the", "a", "and" };
        ConnectiveSource = "built-in fallback (seed-contract.md §5 step 3) — registry parse failed";
    }

    void IndexWords()
    {
        if (Words is null) return;
        var surfaces = new Dictionary<string, string>(StringComparer.Ordinal);
        var canonical = new HashSet<string>(StringComparer.Ordinal);

        // The shape naming.v1.json asks F1 for, as F1 shipped it:
        //   pools.<group>.<poolName> = [ { canonicalId, surfaceForms: { noun?: [..], ... } } ]
        // A flat top-level `words` array is also accepted so a smaller fixture can be hand-built.
        void Ingest(JsonArray rows)
        {
            foreach (var word in rows.OfType<JsonObject>())
            {
                var id = word["canonicalId"]?.GetValue<string>() ?? word["id"]?.GetValue<string>();
                if (id is null) continue;
                canonical.Add(id);
                surfaces[id.ToLowerInvariant()] = id;
                if (word["surfaceForms"] is not JsonObject forms) continue;
                foreach (var slot in forms)
                {
                    if (slot.Value is JsonValue single && single.TryGetValue<string>(out var one))
                        surfaces[one.ToLowerInvariant()] = id;
                    foreach (var form in Strings(slot.Value))
                        surfaces[form.ToLowerInvariant()] = id;
                }
            }
        }

        if (Words["words"] as JsonArray is { } flat) Ingest(flat);

        foreach (var group in Words["pools"] as JsonObject ?? new JsonObject())
        {
            if (group.Value is not JsonObject pools) continue;
            foreach (var pool in pools)
            {
                if (pool.Key.StartsWith('_')) continue;
                if (pool.Value is JsonArray rows) Ingest(rows);
            }
        }
        SurfaceForms = surfaces;
        CanonicalWords = canonical;
    }

    void IndexRetired()
    {
        if (RetiredIds is null) return;
        var set = new HashSet<string>(StringComparer.Ordinal);
        foreach (var s in Strings(RetiredIds["retired"])) set.Add(s);
        foreach (var row in (RetiredIds["retired"] as JsonArray ?? new JsonArray()).OfType<JsonObject>())
            if (row["id"]?.GetValue<string>() is { } id) set.Add(id);
        Retired = set;
    }

    void IndexCreatureThemes()
    {
        var path = FindUpwards(Path.Combine("data", "seed", "creatures", "_registry", "themes.v2.json"));
        if (path is null) return;

        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            if (!doc.RootElement.TryGetProperty("themes", out var themes) ||
                themes.ValueKind != JsonValueKind.Object)
                return;

            var ids = new HashSet<string>(StringComparer.Ordinal);
            foreach (var theme in themes.EnumerateObject())
                if (theme.Value.TryGetProperty("speciesId", out var idEl) &&
                    idEl.ValueKind == JsonValueKind.String && idEl.GetString() is { Length: > 0 } id)
                    ids.Add(id);
            CreatureSpeciesIds = ids;
            CreatureSpeciesRegistryFound = true;
        }
        catch (Exception ex) when (ex is IOException or JsonException)
        {
            // Not found / unreadable degrades to "not found" — callers warn once, never report a
            // false error on every row (the convention every other optional cross-reference here
            // follows: Words, BuildThemes, FamilyOverrides, RoleRelocation, RetiredIds).
        }
    }

    void IndexEnablerPayoffPairings()
    {
        var path = FindUpwards(Path.Combine("data", "seed", "actions", "pairings.json"));
        if (path is null) return;

        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(path));
            if (doc.RootElement.ValueKind != JsonValueKind.Object) return;

            var ids = new HashSet<string>(StringComparer.Ordinal);
            foreach (var prop in doc.RootElement.EnumerateObject()) ids.Add(prop.Name);
            EnablerPayoffPairingFamilyIds = ids;
            EnablerPayoffPairingsRegistryFound = true;
        }
        catch (Exception ex) when (ex is IOException or JsonException)
        {
            // Not found / unreadable degrades to "not found" — same convention as every other
            // optional cross-reference here (Words, BuildThemes, FamilyOverrides, RoleRelocation,
            // RetiredIds, CreatureSpeciesIds).
        }
    }

    /// <summary>
    /// Walks up from the process's own working directory looking for a file outside this registry
    /// set's own <see cref="RegistryDir"/> — a cross-corpus reference (the creature theme registry
    /// lives under <c>gk-data/packs/fusion/data/seed/creatures/</c>, not <c>gk-data/packs/fusion/data/seed/items/</c>), so it cannot be resolved
    /// relative to the wave-0 registry directory the way every other file in this class is.
    /// </summary>
    static string? FindUpwards(string relativeFile)
    {
        var probe = new DirectoryInfo(Directory.GetCurrentDirectory());
        while (probe is not null)
        {
            var candidate = Path.Combine(probe.FullName, relativeFile);
            if (File.Exists(candidate)) return candidate;
            probe = probe.Parent;
        }
        return null;
    }
}
