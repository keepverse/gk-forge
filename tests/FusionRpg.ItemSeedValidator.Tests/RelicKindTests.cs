using FusionRpg.Tools.ItemSeedValidator.Registries;
using Xunit;

namespace FusionRpg.ItemSeedValidator.Tests;

/// <summary>
/// Empire-development Task 1.3a (spec-relic-item-kind.md §Design 1) — the C# mirror of the new
/// `relic` KindSpec. The Python side (`tools/seedsmith/.../items/kinds.py`, refs={}) is pinned by
/// `gk-forge/tools/seedsmith/tests/test_relic_kinds.py`; this pins the C# transcription the validator
/// actually enforces: required is the common triple plus flavorKey only — no frame, no baseType,
/// no role, no counterPressure, no powerAxis — with theme/themeKey/acquisition/fixedAtoms allowed.
/// </summary>
public class RelicKindTests
{
    [Fact]
    public void A_relic_anchor_with_no_frame_or_base_type_loads_clean()
    {
        var relic = KindCatalog.All["relic"];
        Assert.Equal(new[] { "id", "nameKey", "name", "flavorKey" }, relic.RequiredFields);
        Assert.DoesNotContain("frame", relic.RequiredFields);
        Assert.DoesNotContain("baseType", relic.RequiredFields);
        Assert.DoesNotContain("counterPressure", relic.RequiredFields);
        Assert.DoesNotContain("powerAxis", relic.RequiredFields);
        Assert.Contains("theme", relic.AllowedFields);
        Assert.Contains("themeKey", relic.AllowedFields);
        Assert.Contains("acquisition", relic.AllowedFields);
        Assert.Contains("fixedAtoms", relic.AllowedFields);
        Assert.DoesNotContain("frame", relic.AllowedFields);
        Assert.DoesNotContain("baseType", relic.AllowedFields);
    }

    [Fact]
    public void The_relic_kind_is_a_defined_shape_in_the_relics_directory()
    {
        var relic = KindCatalog.All["relic"];
        Assert.True(relic.ShapeDefined);
        Assert.Equal("relics", relic.Directory);
        Assert.Equal("relics", relic.NamespaceKey);
        Assert.Same(relic, KindCatalog.ByDirectory("relics"));
    }
}
