namespace FusionRpg.Tools.PassiveTreeRosterGen;

/// <summary>Same shape as `ElementEnumGen`'s own `MismatchReport` — every disagreement found,
/// empty when the mirror and the live registry agree.</summary>
public sealed record MismatchReport(IReadOnlyList<string> Mismatches)
{
    public bool IsOk => Mismatches.Count == 0;
}
