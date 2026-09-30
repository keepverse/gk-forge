using System.Linq;
using FusionRpg.Core.PassiveTree.Catalog;
using FusionRpg.Core.PassiveTree.State;
using FusionRpg.Tools.TreeBinder;
using Xunit;
using FusionRpg.Core.Workspace;

namespace FusionRpg.TreeBinder.Tests;

/// <summary>Task D2 — `PlanReader` (gk-forge/tools/TreeBinder), the bridge from `tree-plan`'s committed JSON
/// shape to <see cref="BindInputNode"/>. `affixIds`/`exclusionForm`/`deliberateHole` are read if
/// present and defaulted otherwise, so this reader is forward-compatible with `tree-language`/
/// `tree-plan` the moment they start emitting those fields.</summary>
public class PlanReaderTests
{
    static PassiveTreeTuning Tuning(long treeShareMilli = 1000, long treeBudgetMilli = 1000) =>
        PassiveTreeTuningLoader.Parse($$"""
        {
          "schemaVersion": 1, "version": 1,
          "tierLadder": { "reqScalePoints": 5 },
          "budget": { "treeTotalPoints": 1000, "branchSplitMilli": 500 },
          "treeShareMilli": {{treeShareMilli}}, "treeBudgetMilli": {{treeBudgetMilli}},
          "potency": { "maxNodeShareMilli": 182, "minTerminalWidth": 1, "bandEdgesMilli": [46,91,137,182] },
          "mechanism": { "rampStartMilli": 0, "rampEndMilli": 1000 },
          "archetype": { "rewardSpreadMaxRatioMilli": 6000 },
          "exclusion": { "targetShareMilli": 20 },
          "archetypeAssignment": "ordinal-round-robin",
          "designTarget": { "thetaAllIn": 92 },
          "concentration": { "fmaxMilli": 1200, "wMilli": 500 },
          "soulTrack": { "thetaPerSoulLevelMilli": 1000 },
          "unlockCost": { "firstPoints": 5, "stepPoints": 2 },
          "respec": { "basePrice": 50, "escalationPermille": 500 },
          "gateCounters": { "masteryCurveFirstCount": 23, "masteryCurveStepCount": 23,
            "elementMasteryRatePoints": 4, "statusMasteryRatePoints": 4, "flushIntervalMs": 5000 }
        }
        """);

    [Fact]
    public void A_plain_plan_node_with_no_upstream_fields_defaults_to_empty_affixIds_and_None()
    {
        var json = """{"nodes":[{"id":"skill.might-off-t5-n0","budgetShareMilli":45}]}""";

        var nodes = PlanReader.ReadPlanNodes(json, Tuning());

        var node = Assert.Single(nodes);
        Assert.Equal("skill.might-off-t5-n0", node.NodeId);
        Assert.Equal(45L, node.BudgetShareMilli);
        Assert.Equal(1000L, node.TreeShareMilli);
        Assert.Equal(1000L, node.TreeBudgetMilli);
        Assert.Equal(PlanReader.Branches, node.Branches);
        Assert.Empty(node.AffixIds);
        Assert.Equal(ExclusionForm.None, node.ExclusionForm);
        Assert.False(node.DeliberateHole);
    }

    [Fact]
    public void AffixIds_exclusionForm_and_deliberateHole_are_read_when_present()
    {
        var json = """
        {"nodes":[{"id":"skill.might-off-t7-b3","budgetShareMilli":64,
                   "affixIds":["affix.a","affix.b"],
                   "exclusionForm":"Nullification","deliberateHole":true}]}
        """;

        var node = Assert.Single(PlanReader.ReadPlanNodes(json, Tuning()));

        Assert.Equal(new[] { "affix.a", "affix.b" }, node.AffixIds);
        Assert.Equal(ExclusionForm.Nullification, node.ExclusionForm);
        Assert.True(node.DeliberateHole);
    }

    [Fact]
    public void TreeShareMilli_and_treeBudgetMilli_come_from_the_tuning_file_not_the_plan()
    {
        var json = """{"nodes":[{"id":"skill.x-off-t1-n0","budgetShareMilli":9}]}""";

        var node = Assert.Single(PlanReader.ReadPlanNodes(json, Tuning(treeShareMilli: 700, treeBudgetMilli: 300)));

        Assert.Equal(700L, node.TreeShareMilli);
        Assert.Equal(300L, node.TreeBudgetMilli);
    }

    [Fact]
    public void A_plan_with_no_nodes_array_yields_an_empty_list()
    {
        Assert.Empty(PlanReader.ReadPlanNodes("""{"treeId":"empty"}""", Tuning()));
    }

    [Fact]
    public void Branches_is_the_structural_constant_2_D29()
    {
        Assert.Equal(2L, PlanReader.Branches);
    }
}

/// <summary>2026-09-06 real-run finding: `spec-tree-binder.md` §3.1's own IN table has always said
/// `affixIds[]` comes "from tree-language", never from the plan — but `Program.cs` only ever read
/// the plan file, so a real run against real generated content (379 nodes across 12 trees) refused
/// EVERY node. `ReadPlanNodesWithSeed` is the fix: the plan's own fields stay authoritative
/// (`budgetShareMilli`, `deliberateHole`), and `affixIds`/`exclusionForm` are overlaid from
/// `nodes/&lt;treeId&gt;.json`'s own real content, matched by node id.</summary>
public class ReadPlanNodesWithSeedTests
{
    static PassiveTreeTuning Tuning() => PassiveTreeTuningLoader.Parse("""
    {
      "schemaVersion": 1, "version": 1,
      "tierLadder": { "reqScalePoints": 5 },
      "budget": { "treeTotalPoints": 1000, "branchSplitMilli": 500 },
      "treeShareMilli": 1000, "treeBudgetMilli": 1000,
      "potency": { "maxNodeShareMilli": 182, "minTerminalWidth": 1, "bandEdgesMilli": [46,91,137,182] },
      "mechanism": { "rampStartMilli": 0, "rampEndMilli": 1000 },
      "archetype": { "rewardSpreadMaxRatioMilli": 6000 },
      "exclusion": { "targetShareMilli": 20 },
      "archetypeAssignment": "ordinal-round-robin",
      "designTarget": { "thetaAllIn": 92 },
      "concentration": { "fmaxMilli": 1200, "wMilli": 500 },
      "soulTrack": { "thetaPerSoulLevelMilli": 1000 },
      "unlockCost": { "firstPoints": 5, "stepPoints": 2 },
      "respec": { "basePrice": 50, "escalationPermille": 500 },
      "gateCounters": { "masteryCurveFirstCount": 23, "masteryCurveStepCount": 23,
        "elementMasteryRatePoints": 4, "statusMasteryRatePoints": 4, "flushIntervalMs": 5000 }
    }
    """);

    const string PlanTwoNodes = """
    {"nodes":[{"id":"skill.t-off-t1-n0","budgetShareMilli":10},
              {"id":"skill.t-off-t1-n1","budgetShareMilli":10}]}
    """;

    [Fact]
    public void A_null_seed_behaves_exactly_like_the_plan_only_reader()
    {
        // `record` equality on `IReadOnlyList<string>` is reference equality (List<T> has no value
        // equality), so two independently-built empty lists never `Equals` -- compare the fields
        // that matter instead of the whole record.
        var withSeed = PlanReader.ReadPlanNodesWithSeed(PlanTwoNodes, seedJson: null, Tuning());
        var planOnly = PlanReader.ReadPlanNodes(PlanTwoNodes, Tuning());
        Assert.Equal(planOnly.Count, withSeed.Count);
        for (var i = 0; i < planOnly.Count; i++)
        {
            Assert.Equal(planOnly[i].NodeId, withSeed[i].NodeId);
            Assert.Equal(planOnly[i].BudgetShareMilli, withSeed[i].BudgetShareMilli);
            Assert.Equal(planOnly[i].AffixIds, withSeed[i].AffixIds);
            Assert.Equal(planOnly[i].ExclusionForm, withSeed[i].ExclusionForm);
            Assert.Equal(planOnly[i].DeliberateHole, withSeed[i].DeliberateHole);
        }
    }

    [Fact]
    public void A_generated_nodes_real_affixIds_and_exclusion_form_override_the_plans_own_defaults()
    {
        var seedJson = """
        {"nodes":[{"id":"skill.t-off-t1-n0","affixIds":["atom.a","atom.b"],
                   "exclusion":{"form":"reroute","propertyKeys":["posture"]}}]}
        """;

        var nodes = PlanReader.ReadPlanNodesWithSeed(PlanTwoNodes, seedJson, Tuning());

        var generated = nodes.Single(n => n.NodeId == "skill.t-off-t1-n0");
        Assert.Equal(new[] { "atom.a", "atom.b" }, generated.AffixIds);
        Assert.Equal(ExclusionForm.Reroute, generated.ExclusionForm);
    }

    [Fact]
    public void A_node_the_seed_never_mentions_keeps_the_plan_only_empty_defaults()
    {
        // The real, common shape: a partially-generated tree. The un-generated node must still
        // refuse cleanly (empty affixIds), never silently inherit another node's content.
        var seedJson = """
        {"nodes":[{"id":"skill.t-off-t1-n0","affixIds":["atom.a"]}]}
        """;

        var nodes = PlanReader.ReadPlanNodesWithSeed(PlanTwoNodes, seedJson, Tuning());

        var ungenerated = nodes.Single(n => n.NodeId == "skill.t-off-t1-n1");
        Assert.Empty(ungenerated.AffixIds);
        Assert.Equal(ExclusionForm.None, ungenerated.ExclusionForm);
    }

    [Fact]
    public void The_plans_own_budgetShareMilli_and_deliberateHole_are_never_overridden_by_the_seed()
    {
        var plan = """
        {"nodes":[{"id":"skill.t-off-t1-n0","budgetShareMilli":77,"deliberateHole":true}]}
        """;
        var seedJson = """{"nodes":[{"id":"skill.t-off-t1-n0","affixIds":["atom.a"]}]}""";

        var node = Assert.Single(PlanReader.ReadPlanNodesWithSeed(plan, seedJson, Tuning()));

        Assert.Equal(77L, node.BudgetShareMilli);
        Assert.True(node.DeliberateHole);
        Assert.Equal(new[] { "atom.a" }, node.AffixIds);
    }

    [Fact]
    public void A_generated_nodes_real_name_and_flavor_overlay_from_the_seed()
    {
        // seedsmith-content-standard, content-completeness-passive-tree (2026-09-08): the real gap
        // this closes — name/flavor sat right next to affixIds in the same seed document and were
        // never read. Proven with the exact shape a real seed file carries.
        var seedJson = """
        {"nodes":[{"id":"skill.t-off-t1-n0","affixIds":["atom.a"],
                   "name":"Thickened Marrow",
                   "flavor":"The bone grows dense and heavy under the weight of the struggle."}]}
        """;

        var nodes = PlanReader.ReadPlanNodesWithSeed(PlanTwoNodes, seedJson, Tuning());

        var generated = nodes.Single(n => n.NodeId == "skill.t-off-t1-n0");
        Assert.Equal("Thickened Marrow", generated.Name);
        Assert.Equal("The bone grows dense and heavy under the weight of the struggle.", generated.Flavor);

        var ungenerated = nodes.Single(n => n.NodeId == "skill.t-off-t1-n1");
        Assert.Null(ungenerated.Name);
        Assert.Null(ungenerated.Flavor);
    }

    [Fact]
    public void The_real_committed_ferocity_seed_overlays_its_own_real_name_and_flavor()
    {
        // The real proof Task 14 asks for: an actual committed node from
        // gk-data/packs/fusion/data/seed/passive-tree/nodes/ferocity.json round-trips through ReadPlanNodesWithSeed with
        // its exact real content, not a hand-typed stand-in.
        var repoRoot = FindRepoRoot();
        var seedJson = File.ReadAllText(Path.Combine(KeepverseRoots.Content(), "data", "seed", "passive-tree",
            "nodes", "ferocity.json"));
        var plan = """{"nodes":[{"id":"skill.ferocity-def-t1-n0","budgetShareMilli":10}]}""";

        var node = Assert.Single(PlanReader.ReadPlanNodesWithSeed(plan, seedJson, Tuning()));

        Assert.Equal("Thickened Marrow", node.Name);
        Assert.Equal(
            "The bone grows dense and heavy, a foundation that refuses to crack under the weight of the struggle.",
            node.Flavor);
    }

    [Fact]
    public void ReadTreeIdentity_returns_null_null_for_a_tree_the_identity_stage_has_not_reached()
    {
        var (name, description) = PlanReader.ReadTreeIdentity(null);
        Assert.Null(name);
        Assert.Null(description);
    }

    [Fact]
    public void ReadTreeIdentity_reads_a_real_shaped_identity_document()
    {
        var identityJson = """
        {"treeId":"ferocity","name":"Unyielding Bastion",
         "description":"Rewards those who turn their body into a living fortress."}
        """;
        var (name, description) = PlanReader.ReadTreeIdentity(identityJson);
        Assert.Equal("Unyielding Bastion", name);
        Assert.Equal("Rewards those who turn their body into a living fortress.", description);
    }

    [Theory]
    [InlineData("ferocity", "Unyielding Bastion")]
    [InlineData("fire", "Cinderheart Bastion")]
    [InlineData("poison", "The Rotting Husk")]
    public void ReadTreeIdentity_reads_the_real_committed_identity_files_from_the_real_poc_run(
        string treeId, string expectedName)
    {
        // Task 17/18's own real proof: these 3 files are the actual, committed output of a real
        // PoC run against the live local model (spec-passive-tree-identity-content.md), not
        // hand-typed fixtures.
        var repoRoot = FindRepoRoot();
        var identityPath = Path.Combine(KeepverseRoots.Content(), "data", "seed", "passive-tree", "identity", $"{treeId}.json");
        Assert.True(File.Exists(identityPath), $"real committed identity file missing: {identityPath}");

        var (name, description) = PlanReader.ReadTreeIdentity(File.ReadAllText(identityPath));

        Assert.Equal(expectedName, name);
        Assert.False(string.IsNullOrWhiteSpace(description));
    }

    static string FindRepoRoot()
    {
        return KeepverseRoots.Core();
    }

    // ---- TreeIdFromPlanFileName (J1, 2026-09-07): the real silent-data-loss bug --------------------

    [Theory]
    [InlineData("might.v1", "might")]
    [InlineData("fire.v1", "fire")]
    [InlineData("might.v12", "might")]
    public void A_plain_tree_id_keeps_only_the_version_segment_stripped(string fileName, string expected) =>
        Assert.Equal(expected, PlanReader.TreeIdFromPlanFileName(fileName));

    [Theory]
    [InlineData("nerve.afflicted.v1", "nerve.afflicted")]
    [InlineData("nerve.shaken.v1", "nerve.shaken")]
    [InlineData("nerve.unsettled.v1", "nerve.unsettled")]
    public void A_dotted_tree_id_survives_intact_never_collapsing_to_its_first_segment(string fileName, string expected) =>
        Assert.Equal(expected, PlanReader.TreeIdFromPlanFileName(fileName));

    [Fact]
    public void The_three_real_nerve_trees_never_collide_on_the_same_id()
    {
        var ids = new[] { "nerve.afflicted.v1", "nerve.shaken.v1", "nerve.unsettled.v1" }
            .Select(PlanReader.TreeIdFromPlanFileName)
            .ToArray();

        Assert.Equal(3, ids.Distinct().Count());
    }

    [Fact]
    public void A_name_with_no_trailing_version_segment_is_returned_unchanged()
    {
        // Defensive: a malformed or hand-placed file with no "vN" suffix must never have a real
        // segment silently eaten — the old bug's failure mode (losing content with no error) is
        // exactly what this guards against for the "no version segment" edge too.
        Assert.Equal("nerve.afflicted", PlanReader.TreeIdFromPlanFileName("nerve.afflicted"));
    }
}
