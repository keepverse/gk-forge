using FusionRpg.Core.Effects.Atoms.Power;

namespace FusionRpg.Tools.AtomImporter;

/// <summary>
/// The decision half of <c>--validate</c> (E24, completeness-audit.md B4): given the three
/// <see cref="ContentReport"/>s, what to print and whether to fail — extracted out of
/// <c>Program.cs</c>'s top-level statements so it has a test, the same reason <c>SeedScanner</c> does.
/// </summary>
public sealed record ValidationOutcome(bool Ok, IReadOnlyList<string> Lines);

public static class ValidationGate
{
    public static ValidationOutcome Decide(ContentReport lint, ContentReport drift)
    {
        var lines = new List<string>
        {
            lint.Render("lint"),
            drift.Render("power drift"),
            "budget: skipped — no ceiling data source exists yet (rarity table has no budget column)",
        };

        var ok = lint.Ok && drift.Ok;
        if (!ok)
            lines.Add("--validate found a blocking finding; see FAIL lines above");

        return new ValidationOutcome(ok, lines);
    }
}
