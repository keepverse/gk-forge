using System.Text.Json;
using FusionRpg.Core.Effects.Atoms;
using FusionRpg.Core.PassiveTree.Binding;
using FusionRpg.Core.PassiveTree.Catalog;
using FusionRpg.Core.PassiveTree.State;
using FusionRpg.Core.Power;
using FusionRpg.Tools.TreeBinder;
using Xunit;
using FusionRpg.Core.Workspace;

namespace FusionRpg.TreeBinder.Tests;

/// <summary>MC-1 (passive-tree-repair): mechanism-class `status.apply` atoms are carried into
/// `BoundNode.StatusAtoms` verbatim — never priced, never dropped, never fabricated. The magnitude
/// resolve path filters on `stat.derived` and never sees this list; execution belongs to
/// mechanism-wiring.</summary>
public class TreeBinderStatusTests
{
    static AtomRow StatusRow(string id, string status, double durationS, string whenJson) => new()
    {
        AtomId = id, KindId = "status.apply", FamilyId = "atom.stub-apply", Tier = 1,
        Name = "Stub", WhenJson = whenJson,
        ParamsJson = $"{{\"status\":\"{status}\",\"duration\":{durationS},\"level\":1}}",
    };

    static AffixRow Affix(string affixId, string atomId) => new(affixId, null,
        new[] { new AffixRefRow(0, atomId) });

    static BindInputNode Node(string nodeId, params string[] affixIds) => new(
        nodeId, 1000, 500, 9, 2, affixIds, ExclusionForm.None, DeliberateHole: false,
        TreeBranch.Off, 1, "n0");

    static PowerTuning Tuning() => PowerTuningLoader.Parse(File.ReadAllText(
        Path.Combine(FindRepoRoot(), "data", "tuning", "power-scale.v2.json")));

    static TreeCatalogMeta Meta() => new("primary", "aptitude.Might@Commander", "broad-and-flat",
        10, 2, new[] { 4, 4, 4, 4, 4, 4, 4, 4, 4, 4 }, 1, null, null);

    [Fact]
    public void Status_apply_atom_is_carried_verbatim_not_dropped()
    {
        var atoms = new Dictionary<string, AtomRow>
        {
            ["atom.stub-apply.t1"] = StatusRow("atom.stub-apply.t1", "blight", 2.0, """{"chance":25}"""),
        };
        var affixes = new Dictionary<string, AffixRow> { ["aff.status"] = Affix("aff.status", "atom.stub-apply.t1") };

        var bound = TreeBinderRun.BindNode(Node("n0", "aff.status"), affixes, atoms, Tuning());

        Assert.Empty(bound.Atoms);
        var status = Assert.Single(bound.StatusAtoms);
        Assert.Equal("blight", status.StatusId);
        Assert.Equal(2000, status.DurationMs);
        Assert.Equal(1, status.Level);
        Assert.Equal(25, status.ChancePermille);
    }

    [Fact]
    public void Status_atom_without_chance_reads_the_downstream_default()
    {
        var atoms = new Dictionary<string, AtomRow>
        {
            ["atom.stub-apply.t1"] = StatusRow("atom.stub-apply.t1", "wither", 3.0, "{}"),
        };
        var affixes = new Dictionary<string, AffixRow> { ["aff.status"] = Affix("aff.status", "atom.stub-apply.t1") };

        var bound = TreeBinderRun.BindNode(Node("n0", "aff.status"), affixes, atoms, Tuning());

        Assert.Equal(1000, Assert.Single(bound.StatusAtoms).ChancePermille);
    }

    [Fact]
    public void Status_atom_without_a_status_refuses_by_name()
    {
        var atoms = new Dictionary<string, AtomRow>
        {
            ["atom.stub-apply.t1"] = StatusRow("atom.stub-apply.t1", "", 2.0, "{}"),
        };
        var affixes = new Dictionary<string, AffixRow> { ["aff.status"] = Affix("aff.status", "atom.stub-apply.t1") };

        var ex = Assert.Throws<BindRefusal>(() =>
            TreeBinderRun.BindNode(Node("n0", "aff.status"), affixes, atoms, Tuning()));
        Assert.Contains("names no status", ex.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Report_round_trip_carries_status_atoms_through_json_and_loader()
    {
        // Writer emits statusAtoms only when present; the catalog loader reads them back into
        // NodeRecord.StatusAtoms with structural validation. Round trip, no fixture loss.
        var bound = new BoundNode("skill.might-off-t1-n0", Array.Empty<NodeAtom>(), new[]
        {
            new NodeStatusAtom("blight", 2000, 1, 25, null, """{"chance":25}"""),
        });

        var json = ReportWriter.Serialize("might", Meta(), new[] { Node("skill.might-off-t1-n0", "aff.status") },
            BinderRunReport.From(new[] { bound }, Array.Empty<RefusedSlot>()));
        using var doc = JsonDocument.Parse(json);
        var nodeEl = Assert.Single(doc.RootElement.GetProperty("nodes").EnumerateArray());
        var statusEl = Assert.Single(nodeEl.GetProperty("statusAtoms").EnumerateArray());
        Assert.Equal("blight", statusEl.GetProperty("statusId").GetString());

        var tuning = PassiveTreeTuningLoader.Parse(File.ReadAllText(
            Path.Combine(FindRepoRoot(), "data", "tuning", "passive-tree.v1.json")));
        var (tree, report) = PassiveTreeCatalogLoader.Load(json, tuning);
        Assert.True(tree is not null, "loader refusals: " + string.Join(" | ", report.Refusals));
        var loaded = Assert.Single(tree!.Nodes);
        var carried = Assert.Single(loaded.StatusAtoms ?? Array.Empty<NodeStatusAtom>());
        Assert.Equal("blight", carried.StatusId);
        Assert.Equal(2000, carried.DurationMs);
        Assert.Equal(25, carried.ChancePermille);
        Assert.DoesNotContain(report.Refusals, r => r.Contains("status"));
    }

    static string FindRepoRoot()
    {
        return KeepverseRoots.Core();
    }
}
