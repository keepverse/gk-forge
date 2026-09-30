using FusionRpg.Core.Combat.Element;
using FusionRpg.Core.Effects.Atoms;
using FusionRpg.Tools.ElementEnumGen;
using Xunit;
// The `using FusionRpg.TestSupport;` that used to stand here is gone with the cross-repository
// Compile Include that provided it. gk-core's tests/Shared/KeepverseRoots.cs declared four
// INTERNAL root helpers in that namespace; the public FusionRpg.Core.Workspace.KeepverseRoots
// already in this assembly does the same job, and it is named explicitly at each call site so a
// reader can tell WHICH repository a path is resolved against.
using FusionRpg.Core.Workspace;

namespace FusionRpg.ElementEnumGen.Tests;

/// <summary>
/// E23 (completeness-audit.md finding B2): does the hand-written <c>ElementTypeId</c> enum still
/// agree with <c>gk-data/packs/fusion/data/seed/elements/roster.json</c>? <see cref="ElementEnumCheck"/> is the checker;
/// this is its own test plus the seam proof against the real shipped roster.
/// </summary>
public class ElementEnumCheckTests
{
    static ElementRow Row(string id, int ordinal) => new(id, id, ordinal, true);

    // The shipped order, exactly — a fixture, not a read of the real file, so this class's own
    // fabricated-mismatch tests below are not accidentally testing against production data.
    static readonly ElementRow[] Shipped =
    {
        Row("fire", 0), Row("ice", 1), Row("air", 2), Row("earth", 3), Row("light", 4), Row("dark", 5),
    };

    [Fact]
    public void The_shipped_roster_agrees_with_the_hand_written_enum()
    {
        var report = ElementEnumCheck.Run(Shipped);
        Assert.True(report.IsOk, string.Join("; ", report.Mismatches));
    }

    [Fact]
    public void A_reordered_roster_is_caught()
    {
        var reordered = new[] { Row("ice", 0), Row("fire", 1), Row("air", 2), Row("earth", 3), Row("light", 4), Row("dark", 5) };

        var report = ElementEnumCheck.Run(reordered);

        Assert.False(report.IsOk);
        Assert.Contains(report.Mismatches, m => m.Contains("ElementTypeId member 0", StringComparison.Ordinal));
    }

    [Fact]
    public void An_extra_roster_element_the_enum_does_not_have_is_caught()
    {
        var withVoid = Shipped.Append(Row("void", 6)).ToArray();

        var report = ElementEnumCheck.Run(withVoid);

        Assert.False(report.IsOk);
        Assert.Contains(report.Mismatches, m => m.Contains("6 member(s)", StringComparison.Ordinal) || m.Contains("7", StringComparison.Ordinal));
    }

    [Fact]
    public void A_missing_roster_element_the_enum_still_has_is_caught()
    {
        var missingDark = Shipped.Take(5).ToArray();

        var report = ElementEnumCheck.Run(missingDark);

        Assert.False(report.IsOk);
    }

    [Fact]
    public void An_id_that_does_not_pascal_case_match_the_enum_member_is_caught()
    {
        // TryParse would happily accept an id that does not match the enum's spelling — this proves
        // the mismatch is caught at the enum-member-name level, not only at the count level.
        var relabelled = new[] { Row("blaze", 0), Row("ice", 1), Row("air", 2), Row("earth", 3), Row("light", 4), Row("dark", 5) };

        var report = ElementEnumCheck.Run(relabelled);

        Assert.False(report.IsOk);
        Assert.Contains(report.Mismatches, m => m.Contains("Blaze", StringComparison.Ordinal));
    }

    [Fact]
    public void GenerateSource_reproduces_the_shipped_definitions_content()
    {
        var source = ElementEnumCheck.GenerateSource(Shipped);

        Assert.Contains("ElementTypeId.Fire,", source, StringComparison.Ordinal);
        Assert.Contains("case \"dark\": id = ElementTypeId.Dark; return true;", source, StringComparison.Ordinal);
        Assert.Contains("ElementTypeId.Light => \"light\",", source, StringComparison.Ordinal);
        // Order is the roster's, not alphabetical — proven by fire (position 0) preceding dark
        // (position 5) in the emitted enum block specifically, not merely appearing somewhere.
        var enumBlockStart = source.IndexOf("public enum ElementTypeId", StringComparison.Ordinal);
        var enumBlockEnd = source.IndexOf('}', enumBlockStart);
        var enumBlock = source[enumBlockStart..enumBlockEnd];
        Assert.True(enumBlock.IndexOf("Fire", StringComparison.Ordinal) < enumBlock.IndexOf("Dark", StringComparison.Ordinal));
    }

    // ---- the seam: the real shipped roster, not a fixture -----------------------------------------

    [Fact]
    public void The_real_shipped_roster_file_agrees_with_the_real_enum()
    {
        var rosterFile = Path.Combine(KeepverseRoots.Content(), "data", "seed", "elements", "roster.json");
        var collected = AtomSeedFile.Collect(new[] { (rosterFile, File.ReadAllText(rosterFile)) });
        Assert.True(collected.IsOk, string.Join("; ", collected.Errors));

        var report = ElementEnumCheck.Run(collected.Content.Elements);

        Assert.True(report.IsOk, string.Join("; ", report.Mismatches));
    }

}
