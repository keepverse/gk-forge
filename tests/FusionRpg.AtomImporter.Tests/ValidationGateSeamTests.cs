using FusionRpg.Core.Effects.Atoms;
using FusionRpg.Core.Effects.Atoms.Power;
using FusionRpg.Tools.AtomImporter;
using Xunit;

namespace FusionRpg.AtomImporter.Tests;

/// <summary>
/// E24's seam: the real <see cref="ContentValidation.Lint"/>/<see cref="ContentValidation.Drift"/> —
/// the exact calls <c>Program.cs</c> makes under <c>--validate</c> — wired through the real
/// <see cref="ValidationGate"/>, proving the flag actually rejects bad content rather than always
/// reporting clean. Constructs <see cref="AtomRow"/>s directly rather than a seed file: <c>power_json</c>
/// is a backfilled column, not an authored one, so reaching a real drift through the file format would
/// need a full import-then-backfill round trip for no more coverage than this gives directly.
/// </summary>
public class ValidationGateSeamTests
{
    static AtomRow StatModify(string id, string powerJson, string? note = null) => new()
    {
        AtomId = id,
        KindId = "stat.modify",
        FamilyId = "test.family",
        Tier = 1,
        ParamsJson = """{"channel":"atk","op":"flat","amount":10}""",
        PowerJson = powerJson,
        PowerNote = note,
    };

    [Fact]
    public void Real_atoms_with_wildly_wrong_stored_power_fail_the_real_gate()
    {
        // Ten million offense points is not what a +10 flat atk atom prices to under any coefficient
        // set — a genuine, large drift, not a rounding edge case.
        var wrong = StatModify("atom.e24.drift.t1", """{"offense":10000000,"survivability":0,"control":0,"utility":0,"economy":0}""");

        var lint = ContentValidation.Lint(new[] { wrong }, Array.Empty<ContainerRow>());
        var drift = ContentValidation.Drift(new[] { wrong }, PowerTables.Authored());
        var decision = ValidationGate.Decide(lint, drift);

        Assert.False(decision.Ok);
        Assert.Contains(decision.Lines, l => l.Contains("atom.e24.drift.t1", StringComparison.Ordinal));
        Assert.Contains(decision.Lines, l => l.Contains("blocking finding", StringComparison.Ordinal));
    }

    [Fact]
    public void The_same_drift_with_a_note_passes_because_a_note_is_permission_not_a_fix()
    {
        var noted = StatModify("atom.e24.noted.t1",
            """{"offense":10000000,"survivability":0,"control":0,"utility":0,"economy":0}""",
            note: "deliberately overpriced for the E24 seam test");

        var lint = ContentValidation.Lint(new[] { noted }, Array.Empty<ContainerRow>());
        var drift = ContentValidation.Drift(new[] { noted }, PowerTables.Authored());
        var decision = ValidationGate.Decide(lint, drift);

        Assert.True(decision.Ok);
    }

    [Fact]
    public void Real_clean_atoms_pass_the_real_gate()
    {
        // The real shipped corpus is asserted clean elsewhere (Core.Tests' ContentValidationTests
        // over the real files); this proves the specific wiring --validate uses, end to end, once
        // more with content that should not fail.
        var priced = StatModify("atom.e24.clean.t1", CostFunction.Price(
            StatModify("atom.e24.clean.t1", ""), PowerTables.Authored()).Power.ToJson());

        var lint = ContentValidation.Lint(new[] { priced }, Array.Empty<ContainerRow>());
        var drift = ContentValidation.Drift(new[] { priced }, PowerTables.Authored());
        var decision = ValidationGate.Decide(lint, drift);

        Assert.True(decision.Ok, string.Join("\n", decision.Lines));
    }
}
