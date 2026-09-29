using System.Text.Json;
using FusionRpg.Core.PassiveTree.Binding;
using FusionRpg.Core.PassiveTree.Catalog;
using FusionRpg.Core.PassiveTree.State;

namespace FusionRpg.Tools.TreeBinder;

/// <summary>
/// Reads one `tree-plan` output file (`gk-data/packs/fusion/data/seed/passive-tree/plan/&lt;treeId&gt;.v1.json`, B1) into
/// this module's own <see cref="BindInputNode"/> shape. `deliberateHole` is `tree-plan`'s own field
/// (read here if present, defaulted otherwise — see <see cref="BindInputNode.DeliberateHole"/>'s own
/// doc comment). `budgetShareMilli` is read as given (R4) — never recomputed from a tier weight.
///
/// <b>`affixIds`/`exclusionForm` are `tree-language`'s fields, never `tree-plan`'s</b> — found real
/// 2026-09-06, the day this program's generation pipeline (H9) first produced real content for more
/// than one tree: `spec-tree-binder.md` §3.1's own IN table has ALWAYS said `affixIds[]` arrives
/// "from tree-language", and `spec-tree-language.md` §6.4's own diagram has ALWAYS shown
/// `plan/&lt;treeId&gt;.json` and `nodes/&lt;treeId&gt;.json` as two separate files, the second being
/// tree-language's own committed output — but this reader's ORIGINAL one-argument overload (kept
/// below, unchanged, for the plan-only fixtures `PlanReaderTests.cs` already covers) only ever read
/// the plan file, so a real run against real generated content refused every node
/// ("`affixIds` must be 1..3, got 0") even after 379 real nodes existed with real chosen affixes —
/// confirmed by actually running `gk-forge/tools/TreeBinder` against the real committed corpus, not assumed.
/// `ReadPlanNodesWithSeed` is the fix: it reads the plan exactly as before, then overlays each
/// matching node's real `affixIds`/`exclusion.form` from `nodes/&lt;treeId&gt;.json` where that node
/// has been generated. A node the language stage has not yet accepted keeps the plan-only defaults
/// (empty `affixIds`, `ExclusionForm.None`) and is correctly refused with its unspent budget reported
/// — the same partial-corpus behavior §7.2 already designs for, now reachable by a REAL cause
/// (not-yet-generated) instead of only a hypothetical one.
/// </summary>
public static class PlanReader
{
    // branches = 2 is D29's structural fact (10 tiers x 2 branches), never a tunable --
    // spec-tree-binder.md §3.3's own worked example fixes it the same way.
    public const long Branches = 2;

    /// <summary>
    /// J1 (2026-09-07): a real, silent-data-loss bug found the first time `gk-forge/tools/TreeBinder` ran
    /// against a dotted tree id (`nerve.afflicted.v1.json`, `nerve.shaken.v1.json`,
    /// `nerve.unsettled.v1.json` -- 5 of the 24 real status ids legitimately contain a dot). The
    /// original call site did `Path.GetFileNameWithoutExtension(planFile).Split('.')[0]`, which takes
    /// only the FIRST dot-segment -- all three collapsed onto the SAME "nerve" dictionary key in
    /// `Program.cs`'s own `allNodesByTree`, last-write-wins, silently dropping two of three real trees
    /// from every binder run with no error of any kind. Confirmed by actually running the real binder
    /// against the real 42-tree corpus: 40 `tree-binder:` report lines instead of 42.
    ///
    /// <para>Every real plan filename is `&lt;treeId&gt;.v&lt;N&gt;.json` (the caller's own glob,
    /// `*.v*.json`, already assumes this) -- so the fix strips only the trailing `.v&lt;digits&gt;`
    /// VERSION segment, never simply the first dot, letting a tree id that itself contains a dot
    /// survive intact.</para>
    /// </summary>
    /// <param name="fileNameWithoutJsonExtension">A plan file's name with `.json` already stripped
    /// (e.g. <c>Path.GetFileNameWithoutExtension</c>'s own output) -- e.g. `"might.v1"` or
    /// `"nerve.afflicted.v1"`.</param>
    public static string TreeIdFromPlanFileName(string fileNameWithoutJsonExtension)
    {
        var segments = fileNameWithoutJsonExtension.Split('.');
        var last = segments[^1];
        var isVersionSegment = last.Length > 1 && last[0] == 'v' && last[1..].All(char.IsDigit);
        return isVersionSegment ? string.Join('.', segments[..^1]) : fileNameWithoutJsonExtension;
    }

    public static List<BindInputNode> ReadPlanNodes(string planJson, PassiveTreeTuning treeTuning)
    {
        using var doc = JsonDocument.Parse(planJson);
        var nodesEl = doc.RootElement.TryGetProperty("nodes", out var n) ? n : default;
        var result = new List<BindInputNode>();
        if (nodesEl.ValueKind != JsonValueKind.Array) return result;

        foreach (var nodeEl in nodesEl.EnumerateArray())
        {
            var nodeId = nodeEl.GetProperty("id").GetString()!;
            var budgetShareMilli = nodeEl.GetProperty("budgetShareMilli").GetInt64();

            var affixIds = nodeEl.TryGetProperty("affixIds", out var aiEl) && aiEl.ValueKind == JsonValueKind.Array
                ? aiEl.EnumerateArray().Select(e => e.GetString()!).ToList()
                : new List<string>();

            var exclusionFormStr = nodeEl.TryGetProperty("exclusionForm", out var efEl) ? efEl.GetString() : "None";
            Enum.TryParse<ExclusionForm>(exclusionFormStr, ignoreCase: true, out var exclusionForm);

            var deliberateHole = nodeEl.TryGetProperty("deliberateHole", out var dhEl) && dhEl.ValueKind == JsonValueKind.True;

            // 2026-09-07: the plan's own identity fields `tree-catalog`'s `NodeRecord` needs but this
            // module never used to carry through -- see `BindInputNode`'s own doc comment for the
            // full finding. `branch` here is the plan's own full word ("offensive"/"defensive"),
            // translated to the catalog's `TreeBranch` enum member (`Off`/`Def`) at the one point a
            // translation is needed, never carried as a raw string.
            var branchWord = nodeEl.TryGetProperty("branch", out var brEl) ? brEl.GetString() : null;
            var branch = string.Equals(branchWord, "defensive", StringComparison.OrdinalIgnoreCase)
                ? TreeBranch.Def : TreeBranch.Off;
            var tier = nodeEl.TryGetProperty("tier", out var tEl) ? tEl.GetInt32() : 0;
            var nodeKey = nodeEl.TryGetProperty("nodeKey", out var nkEl) ? nkEl.GetString() ?? "" : "";
            var nodeClassWord = nodeEl.TryGetProperty("nodeClass", out var ncEl) ? ncEl.GetString() : null;
            var nodeClass = string.Equals(nodeClassWord, "mechanism", StringComparison.OrdinalIgnoreCase)
                ? NodeClass.Mechanism : NodeClass.Magnitude;

            result.Add(new BindInputNode(nodeId, treeTuning.TreeShareMilli, treeTuning.TreeBudgetMilli,
                budgetShareMilli, Branches, affixIds, exclusionForm, deliberateHole,
                branch, tier, nodeKey, nodeClass));
        }
        return result;
    }

    /// <summary>The `tree-catalog` `TreeRecord` fields (spec-tree-catalog.md §2.1), read from the
    /// SAME plan document `ReadPlanNodes` already parses — a second read, not a second file, since
    /// `Program.cs` already has the raw plan JSON in hand at the one call site that needs both.
    /// `nodesPerTier` is derived from the CHOSEN archetype's own `widths[]` (`archetypes[]`, keyed by
    /// the plan's own singular `archetype` id) doubled for both branches (D10/D29: branches is
    /// always 2) — a structural, always-known fact about the tree's SHAPE, independent of how much
    /// of its content has been generated yet, never counted off the (possibly partial) `nodes[]`
    /// array itself.</summary>
    public static TreeCatalogMeta ReadTreeMeta(string planJson)
    {
        using var doc = JsonDocument.Parse(planJson);
        var root = doc.RootElement;

        var category = root.TryGetProperty("category", out var catEl) ? catEl.GetString() ?? "" : "";
        var gateQuantity = root.TryGetProperty("gateQuantity", out var gqEl) ? gqEl.GetString() ?? "" : "";
        var shapeArchetype = root.TryGetProperty("archetype", out var arEl) ? arEl.GetString() ?? "" : "";
        var catalogVersion = root.TryGetProperty("version", out var vEl) ? vEl.GetInt32() : 0;

        var widths = Array.Empty<int>();
        if (root.TryGetProperty("archetypes", out var archsEl) && archsEl.ValueKind == JsonValueKind.Array)
        {
            foreach (var archEl in archsEl.EnumerateArray())
            {
                if (archEl.TryGetProperty("id", out var idEl) &&
                    string.Equals(idEl.GetString(), shapeArchetype, StringComparison.Ordinal) &&
                    archEl.TryGetProperty("widths", out var wEl) && wEl.ValueKind == JsonValueKind.Array)
                {
                    widths = wEl.EnumerateArray().Select(e => e.GetInt32()).ToArray();
                    break;
                }
            }
        }
        var nodesPerTier = widths.Select(w => w * (int)Branches).ToArray();

        return new TreeCatalogMeta(category, gateQuantity, shapeArchetype, widths.Length,
            (int)Branches, nodesPerTier, catalogVersion);
    }

    /// <summary>seedsmith-content-standard, passive-tree-identity-content (2026-09-08): reads the
    /// tree's own real generated display name/description from its committed identity file
    /// (`gk-data/packs/fusion/data/seed/passive-tree/identity/&lt;treeId&gt;.json`) — a SEPARATE per-tree file, matching
    /// this program's own existing `plan/&lt;treeId&gt;.v1.json`/`nodes/&lt;treeId&gt;.json`
    /// convention, since identity content is a genuinely different generation stage from either.
    /// `identityJson` is `null` for a tree the identity stage has not reached yet — returns
    /// `(null, null)`, never a refusal and never a fabricated placeholder.</summary>
    public static (string? Name, string? Description) ReadTreeIdentity(string? identityJson)
    {
        if (string.IsNullOrEmpty(identityJson)) return (null, null);
        using var doc = JsonDocument.Parse(identityJson);
        var root = doc.RootElement;
        var name = root.TryGetProperty("name", out var nameEl) && nameEl.ValueKind == JsonValueKind.String
            ? nameEl.GetString() : null;
        var description = root.TryGetProperty("description", out var descEl) && descEl.ValueKind == JsonValueKind.String
            ? descEl.GetString() : null;
        return (name, description);
    }

    /// <summary>The real production path (`Program.cs`'s own CLI run): the plan read exactly as
    /// `ReadPlanNodes` already does, with each node's `affixIds`/`exclusionForm` overridden from
    /// `seedJson` (`nodes/&lt;treeId&gt;.json`'s own content) wherever that node id has been
    /// generated. `seedJson` is `null` for a tree tree-language has not touched at all yet (the
    /// whole tree correctly refuses, exactly as `ReadPlanNodes` alone already did).</summary>
    public static List<BindInputNode> ReadPlanNodesWithSeed(string planJson, string? seedJson,
                                                            PassiveTreeTuning treeTuning)
    {
        var nodes = ReadPlanNodes(planJson, treeTuning);
        if (string.IsNullOrEmpty(seedJson)) return nodes;

        var overrides = ReadSeedOverrides(seedJson);
        return nodes.ConvertAll(node => overrides.TryGetValue(node.NodeId, out var seed)
            ? node with
            {
                AffixIds = seed.AffixIds, ExclusionForm = seed.ExclusionForm,
                ExcludeProps = seed.ExcludeProps, Name = seed.Name, Flavor = seed.Flavor,
            }
            : node);
    }

    static Dictionary<string, (IReadOnlyList<string> AffixIds, ExclusionForm ExclusionForm,
        IReadOnlyList<string> ExcludeProps, string? Name, string? Flavor)> ReadSeedOverrides(string seedJson)
    {
        using var doc = JsonDocument.Parse(seedJson);
        var nodesEl = doc.RootElement.TryGetProperty("nodes", out var n) ? n : default;
        var result = new Dictionary<string,
            (IReadOnlyList<string>, ExclusionForm, IReadOnlyList<string>, string?, string?)>(StringComparer.Ordinal);
        if (nodesEl.ValueKind != JsonValueKind.Array) return result;

        foreach (var nodeEl in nodesEl.EnumerateArray())
        {
            var nodeId = nodeEl.GetProperty("id").GetString()!;
            var affixIds = nodeEl.TryGetProperty("affixIds", out var aiEl) && aiEl.ValueKind == JsonValueKind.Array
                ? aiEl.EnumerateArray().Select(e => e.GetString()!).ToList()
                : new List<string>();

            var exclusionEl = nodeEl.TryGetProperty("exclusion", out var exEl) ? exEl : default;
            var exclusionFormStr = exclusionEl.ValueKind == JsonValueKind.Object &&
                                   exclusionEl.TryGetProperty("form", out var formEl)
                ? formEl.GetString() : "None";
            Enum.TryParse<ExclusionForm>(exclusionFormStr, ignoreCase: true, out var exclusionForm);

            // tree-language's own field name is `propertyKeys` (§6.3); `tree-catalog`'s `NodeRecord`
            // calls the same content `excludeProps` (§2.2) — a rename this reader bridges, same as
            // `exclusion.form` -> `ExclusionForm` above, never a second vocabulary.
            var excludeProps = exclusionEl.ValueKind == JsonValueKind.Object &&
                               exclusionEl.TryGetProperty("propertyKeys", out var pkEl) &&
                               pkEl.ValueKind == JsonValueKind.Array
                ? pkEl.EnumerateArray().Select(e => e.GetString()!).ToList()
                : new List<string>();

            // seedsmith-content-standard, content-completeness-passive-tree (2026-09-08): the real
            // player-facing content tree-language already writes per node (real example: every one
            // of ferocity.json's 39 nodes) — read here for the first time; previously dropped even
            // though this same parsed document already carried it, right next to affixIds above.
            var name = nodeEl.TryGetProperty("name", out var nameEl) && nameEl.ValueKind == JsonValueKind.String
                ? nameEl.GetString() : null;
            var flavor = nodeEl.TryGetProperty("flavor", out var flavorEl) && flavorEl.ValueKind == JsonValueKind.String
                ? flavorEl.GetString() : null;

            result[nodeId] = (affixIds, exclusionForm, excludeProps, name, flavor);
        }
        return result;
    }
}

/// <summary>The `tree-catalog` `TreeRecord` fields this module's own plan read already has in hand
/// (spec-tree-catalog.md §2.1) — everything a `TreeRecord` needs except `treeId` (the caller's own
/// loop variable) and `enabled` (always `true` for a tree this run is actively binding; a retired
/// tree is a `tree-state` concern, never something `tree-binder` decides).</summary>
public sealed record TreeCatalogMeta(
    string Category,
    string GateQuantity,
    string ShapeArchetype,
    int Tiers,
    int Branches,
    IReadOnlyList<int> NodesPerTier,
    int CatalogVersion,
    // seedsmith-content-standard, passive-tree-identity-content (2026-09-08): the tree's own real
    // generated display name/description, read separately via ReadTreeIdentity and merged in by
    // Program.cs — additive, nullable, never required.
    string? Name = null,
    string? Description = null);
