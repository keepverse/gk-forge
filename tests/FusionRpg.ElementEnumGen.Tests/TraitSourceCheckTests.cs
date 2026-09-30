using FusionRpg.Core.Effects.Atoms;
using FusionRpg.Tools.ElementEnumGen;
using Xunit;
using FusionRpg.TestSupport;
using FusionRpg.Core.Workspace;

namespace FusionRpg.ElementEnumGen.Tests;

/// <summary>
/// E23 (completeness-audit.md B2): does the hand-written <c>TraitAtomSource.Shipped()</c> still agree
/// with the migrated trait containers under <c>gk-data/packs/fusion/data/seed/</c>? <see cref="TraitSourceCheck"/> is the
/// checker; this is its own test plus the seam proof against the real shipped content.
/// </summary>
public class TraitSourceCheckTests
{
    static ContainerRow TraitContainer(string traitId, params string[] atomIds) => new()
    {
        ContainerId = "trait." + traitId,
        Kind = ContainerKind.Trait,
        Atoms = atomIds.Select((id, i) => new ContainerAtomRow(i, id)).ToArray(),
    };

    static AtomRow StatDerived(string atomId, string channel, int amount) => new()
    {
        AtomId = atomId,
        KindId = "stat.derived",
        FamilyId = "test.family",
        Tier = 1,
        ParamsJson = $$"""{"channel":"{{channel}}","op":"flat","amount":{{amount}}}""",
    };

    static SeedContent Content(IReadOnlyList<ContainerRow> containers, IReadOnlyList<AtomRow> atoms)
    {
        var content = new SeedContent();
        content.Containers.AddRange(containers);
        content.Atoms.AddRange(atoms);
        return content;
    }

    [Fact]
    public void The_real_shipped_migrated_trait_agrees_with_TraitAtomSource_Shipped()
    {
        // The actual critical-hunter content — same channel/amount TraitAtomSource.Shipped() carries
        // — proving the checker agrees with reality before testing that it catches disagreement.
        var content = Content(
            new[] { TraitContainer("critical-hunter", "atom.critical-hunter.t1") },
            new[] { StatDerived("atom.critical-hunter.t1", "combat.crit.rate.omni", 150) });

        var report = TraitSourceCheck.Run(content);

        Assert.True(report.IsOk, string.Join("; ", report.Mismatches));
    }

    [Fact]
    public void A_migrated_trait_with_a_different_amount_than_Shipped_is_caught()
    {
        var content = Content(
            new[] { TraitContainer("critical-hunter", "atom.critical-hunter.t1") },
            new[] { StatDerived("atom.critical-hunter.t1", "combat.crit.rate.omni", 999) });

        var report = TraitSourceCheck.Run(content);

        Assert.False(report.IsOk);
        Assert.Contains(report.Mismatches, m => m.Contains("critical-hunter", StringComparison.Ordinal));
    }

    [Fact]
    public void A_migrated_trait_Shipped_does_not_know_about_is_caught()
    {
        var content = Content(
            new[] { TraitContainer("invented-trait", "atom.invented.t1") },
            new[] { StatDerived("atom.invented.t1", "combat.crit.rate.omni", 10) });

        var report = TraitSourceCheck.Run(content);

        Assert.False(report.IsOk);
        Assert.Contains(report.Mismatches, m => m.Contains("invented-trait", StringComparison.Ordinal));
    }

    [Fact]
    public void A_trait_container_with_no_stat_derived_atom_is_caught_as_unmigrated()
    {
        var noise = new AtomRow
        {
            AtomId = "atom.noise.t1", KindId = "status.apply", FamilyId = "atom.noise", Tier = 1,
            ParamsJson = """{"status":"butter"}""",
        };
        var content = Content(new[] { TraitContainer("critical-hunter", "atom.noise.t1") }, new[] { noise });

        var report = TraitSourceCheck.Run(content);

        Assert.False(report.IsOk);
    }

    [Fact]
    public void An_item_container_is_ignored_not_mistaken_for_a_trait()
    {
        var item = new ContainerRow { ContainerId = "item.something", Kind = ContainerKind.Item, Atoms = Array.Empty<ContainerAtomRow>() };
        var content = Content(new[] { item }, Array.Empty<AtomRow>());

        var report = TraitSourceCheck.Run(content);

        Assert.True(report.IsOk);
    }

    [Fact]
    public void GenerateSource_names_the_real_channel_and_amount()
    {
        var content = Content(
            new[] { TraitContainer("critical-hunter", "atom.critical-hunter.t1") },
            new[] { StatDerived("atom.critical-hunter.t1", "combat.crit.rate.omni", 150) });

        var source = TraitSourceCheck.GenerateSource(content);

        Assert.Contains("[\"critical-hunter\"]", source, StringComparison.Ordinal);
        Assert.Contains("CombatCritRateOmni, 150", source, StringComparison.Ordinal);
    }

    // ---- the seam: the real shipped content, not a fixture -----------------------------------------

    [Fact]
    public void The_real_shipped_trait_content_agrees_with_the_real_Shipped_dictionary()
    {
        var root = RepoRoot();
        var files = new[] { "atoms", "containers" }
            .Select(d => Path.Combine(KeepverseRoots.Content(), "data", "seed", d))
            .SelectMany(d => Directory.GetFiles(d, "*.json", SearchOption.AllDirectories))
            .OrderBy(f => f, StringComparer.Ordinal)
            .Select(f => (f, File.ReadAllText(f)))
            .ToArray();

        var collected = AtomSeedFile.Collect(files);
        Assert.True(collected.IsOk, string.Join("; ", collected.Errors));

        var report = TraitSourceCheck.Run(collected.Content);

        Assert.True(report.IsOk, string.Join("; ", report.Mismatches));
    }

    static string RepoRoot() => ContentRoot.Path;
}
