using FusionRpg.Tools.ElementEnumGen;
using Xunit;
using FusionRpg.TestSupport;
using FusionRpg.Core.Workspace;

namespace FusionRpg.ElementEnumGen.Tests;

/// <summary>
/// lawn-combat-wire L-N24: the checked-in <c>EffectAtomCatalog.Generated.cs</c> must equal what
/// <c>data/seed/atoms/fx-*.json</c> generates. Id-level tests (<c>EffectAtomCatalogGeneratedTests</c>)
/// never caught a params-only drift such as an atom's amount changing.
/// </summary>
public class EffectCatalogCheckTests
{
    static readonly string[] ShippedFxFiles = { "fx-board.json", "fx-core.json", "fx-status.json" };

    [Fact]
    public void The_checked_in_effect_catalog_matches_the_seed()
    {
        var root = RepoRoot();
        var gen = EffectCatalogGen.GenerateFromSeed(Path.Combine(KeepverseRoots.Content(), "data", "seed"), ShippedFxFiles);
        Assert.True(gen.Code == 0, gen.Message);

        var checkedIn = File.ReadAllText(Path.Combine(root, "src", "FusionRpg.Core", "Effects", "EffectAtomCatalog.Generated.cs"));
        Assert.True(EffectCatalogGen.Matches(gen.Source!, checkedIn),
            "EffectAtomCatalog.Generated.cs is stale — run: dotnet run --project tools/ElementEnumGen -- --effect-emit src/FusionRpg.Core/Effects/EffectAtomCatalog.Generated.cs");
    }

    [Fact]
    public void A_single_changed_value_is_a_mismatch()
    {
        const string generated = "[\"multiplierMilli\"] = -1000,\n";
        Assert.False(EffectCatalogGen.Matches(generated, "[\"multiplierMilli\"] = 1000,\n"));
    }

    [Fact]
    public void Line_endings_alone_are_not_a_mismatch()
    {
        Assert.True(EffectCatalogGen.Matches("a\nb\n", "a\r\nb\r\n"));
    }

    static string RepoRoot() => ContentRoot.Path;
}
