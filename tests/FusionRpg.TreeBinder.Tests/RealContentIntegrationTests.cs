using System.IO;
using System.Linq;
using FusionRpg.Core.Effects.Atoms;
using FusionRpg.Core.PassiveTree.Binding;
using FusionRpg.Core.PassiveTree.Catalog;
using FusionRpg.Core.PassiveTree.State;
using FusionRpg.Core.Power;
using FusionRpg.Tools.TreeBinder;
using Xunit;
using FusionRpg.Core.Workspace;

namespace FusionRpg.TreeBinder.Tests;

/// <summary>
/// Task D2 — end-to-end wiring against the REAL committed content (`gk-core/data/tuning/power-scale.v2.json`,
/// `gk-core/data/tuning/passive-tree.v1.json`, `gk-data/packs/fusion/data/seed/passive-tree/plan/might.v1.json`), the same files
/// `gk-forge/tools/TreeBinder`'s `Program.cs` reads. `tree-language` has not shipped yet, so the real plan's
/// nodes carry no `affixIds` today -- this test pins that HONEST state (every node refused, verdict
/// `Fail`) rather than fabricating content that does not exist upstream. The moment `tree-language`
/// starts writing `affixIds` into the plan, this test's own assertions will need updating -- which is
/// the point: it will fail LOUDLY, not silently pass on stale expectations.
/// </summary>
public class RealContentIntegrationTests
{
    static string RepoRoot()
    {
        return KeepverseRoots.Core();
    }

    [Fact]
    public void Real_might_plan_reads_40_nodes_with_todays_honest_all_refused_state()
    {
        var root = RepoRoot();
        var treeTuning = PassiveTreeTuningLoader.Parse(
            File.ReadAllText(Path.Combine(root, "data", "tuning", "passive-tree.v1.json")));
        var powerTuning = PowerTuningLoader.Parse(
            File.ReadAllText(Path.Combine(root, "data", "tuning", "power-scale.v2.json")));

        var planJson = File.ReadAllText(Path.Combine(KeepverseRoots.Content(), "data", "seed", "passive-tree", "plan", "might.v1.json"));
        var nodes = PlanReader.ReadPlanNodes(planJson, treeTuning);

        // The node count (40 today) is a growing content population, never pinned (population-pin
        // SE3.4, 2026-09-20).
        Assert.NotEmpty(nodes);
        Assert.Equal(1000L, nodes[0].TreeShareMilli); // data/tuning/passive-tree.v1.json's real value
        Assert.Equal(1000L, nodes[0].TreeBudgetMilli);
        Assert.All(nodes, n => Assert.Empty(n.AffixIds)); // tree-language has not shipped yet

        var report = TreeBinderRun.BindTree(nodes,
            new Dictionary<string, AffixRow>(), new Dictionary<string, AtomRow>(), powerTuning);

        Assert.Empty(report.Bound);
        // Self-referential (population-pin SE3.4, 2026-09-20): every node is either bound or refused,
        // and Bound is empty, so this proves no node fell through uncounted, not a fact about content.
        Assert.Equal(nodes.Count, report.Refused.Count);
        Assert.Equal(RunVerdict.Fail, report.Verdict);
        Assert.All(report.Refused, r => Assert.Contains("affixIds must be 1..3, got 0", r.Reason));

        // The unspent total is the tree's own full budget column -- nothing was priced.
        var expectedTotal = nodes.Sum(n => n.BudgetShareMilli);
        Assert.Equal(expectedTotal, report.TotalUnspentBudgetShareMilli);
    }

    [Fact]
    public void ReportWriter_serializes_the_real_run_and_reparses_cleanly()
    {
        var root = RepoRoot();
        var treeTuning = PassiveTreeTuningLoader.Parse(
            File.ReadAllText(Path.Combine(root, "data", "tuning", "passive-tree.v1.json")));
        var powerTuning = PowerTuningLoader.Parse(
            File.ReadAllText(Path.Combine(root, "data", "tuning", "power-scale.v2.json")));
        var planJson = File.ReadAllText(Path.Combine(KeepverseRoots.Content(), "data", "seed", "passive-tree", "plan", "might.v1.json"));
        var nodes = PlanReader.ReadPlanNodes(planJson, treeTuning);

        var report = TreeBinderRun.BindTree(nodes,
            new Dictionary<string, AffixRow>(), new Dictionary<string, AtomRow>(), powerTuning);
        var meta = PlanReader.ReadTreeMeta(planJson);
        var json = ReportWriter.Serialize("might", meta, nodes, report);

        using var doc = System.Text.Json.JsonDocument.Parse(json); // never throws
        Assert.Equal("Fail", doc.RootElement.GetProperty("verdict").GetString());
        Assert.Equal("primary", doc.RootElement.GetProperty("category").GetString());
        Assert.Empty(doc.RootElement.GetProperty("nodes").EnumerateArray()); // every node refused, none bound
    }

    /// <summary>seedsmith-content-standard, content-completeness-passive-tree (2026-09-08) — the
    /// real seed-to-DTO chain for name/flavor, using the exact real committed
    /// `gk-data/packs/fusion/data/seed/passive-tree/nodes/ferocity.json` content (Task 14's own required real proof).
    /// Deliberately does NOT go through `TreeBinderRun.BindTree`/`AffixComposer` — that layer
    /// resolves `affixIds` into atoms and is orthogonal to name/flavor, which this test's own real
    /// investigation found cannot currently run for `ferocity` at all: `AffixComposer.ParseAtom`
    /// (`AffixComposer.cs:69`, `var channel = root.TryGetProperty("channel", ...).GetString()`) has
    /// no handling for E30's own real, documented channel-POOL reference shape
    /// (`AtomSeedFile.cs:76-78`: "an atom's `params.channel` may reference [a pool] instead of one
    /// concrete channel") — a real, pre-existing integration gap between two independently-shipped
    /// features, confirmed to predate this session (no atom/affix file appears in `git status`) and
    /// confirmed unrelated to name/flavor (the throw site never touches either field). Named here,
    /// not fixed — fixing `AffixComposer`'s channel resolution is a passive-tree/effects-atom
    /// binder concern, outside this program's scope. `ReportWriterTests.cs`'s own
    /// `The_real_ferocity_seeds_name_and_flavor_round_trip_through_PassiveTreeCatalogLoader` proves
    /// the actual chain this task owns (seed -> PlanReader -> BindInputNode -> ReportWriter ->
    /// PassiveTreeCatalogLoader -> NodeRecord) end to end against this same real file.</summary>
    [Fact]
    public void The_real_ferocity_seed_reads_via_ReadPlanNodesWithSeed_exactly_as_the_real_CLI_does()
    {
        var root = RepoRoot();
        var treeTuning = PassiveTreeTuningLoader.Parse(
            File.ReadAllText(Path.Combine(root, "data", "tuning", "passive-tree.v1.json")));

        var planJson = File.ReadAllText(Path.Combine(KeepverseRoots.Content(), "data", "seed", "passive-tree", "plan", "ferocity.v1.json"));
        var seedPath = Path.Combine(KeepverseRoots.Content(), "data", "seed", "passive-tree", "nodes", "ferocity.json");
        var seedJson = File.Exists(seedPath) ? File.ReadAllText(seedPath) : null;
        Assert.NotNull(seedJson); // this test's whole point depends on the real seed existing

        var nodes = PlanReader.ReadPlanNodesWithSeed(planJson, seedJson, treeTuning);

        var thickenedMarrow = nodes.SingleOrDefault(n => n.NodeId == "skill.ferocity-def-t1-n0");
        Assert.NotNull(thickenedMarrow);
        Assert.Equal("Thickened Marrow", thickenedMarrow!.Name);
        Assert.Equal(
            "The bone grows dense and heavy, a foundation that refuses to crack under the weight of the struggle.",
            thickenedMarrow.Flavor);

        // Every real node the seed carries content for overlays it — not just the one hand-picked
        // example above. Compares against the seed file's OWN real count rather than a hardcoded
        // number: ferocity.json is live content under active concurrent regeneration in this same
        // repo (confirmed via git status — a real, unrelated session grew it from 39 to 40 nodes
        // mid-session), so a hardcoded count here would be exactly the kind of stale corpus-count
        // assertion this program's own evidence already documents repeatedly across other files.
        using var seedDoc = System.Text.Json.JsonDocument.Parse(seedJson!);
        var realNodeCountInSeed = seedDoc.RootElement.GetProperty("nodes").EnumerateArray()
            .Count(n => n.TryGetProperty("name", out var nameEl)
                       && nameEl.ValueKind == System.Text.Json.JsonValueKind.String
                       && !string.IsNullOrEmpty(nameEl.GetString()));
        var withRealContent = nodes.Where(n => n.Name is not null).ToList();
        Assert.Equal(realNodeCountInSeed, withRealContent.Count);
        Assert.All(withRealContent, n => Assert.False(string.IsNullOrWhiteSpace(n.Flavor)));
    }
}
