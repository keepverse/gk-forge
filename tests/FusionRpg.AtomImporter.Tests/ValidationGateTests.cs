using FusionRpg.Core.Effects.Atoms.Power;
using FusionRpg.Tools.AtomImporter;
using Xunit;

namespace FusionRpg.AtomImporter.Tests;

/// <summary>
/// E24 (completeness-audit.md B4): <c>ContentValidation</c> ran only inside its own tests — no
/// <c>--validate</c> flag existed to fail a real import on a real finding.
/// <see cref="ValidationGate.Decide"/> is the decision logic extracted so it has a test independent
/// of stdin/stdout/exit codes, mirroring why <c>SeedScanner</c> is its own class.
/// </summary>
public class ValidationGateTests
{
    static ContentReport Clean(int evaluated = 5) => new(evaluated, Array.Empty<ContentFinding>());

    static ContentReport WithFailure() => new(3, new[]
    {
        new ContentFinding("atom.test.t1", "drift", "off by more than tolerance", Blocking: true),
    });

    static ContentReport WithWarningOnly() => new(3, new[]
    {
        new ContentFinding("atom.test.t1", "orphan", "no container references it", Blocking: false),
    });

    [Fact]
    public void Two_clean_reports_pass()
    {
        var outcome = ValidationGate.Decide(Clean(), Clean());
        Assert.True(outcome.Ok);
    }

    [Fact]
    public void A_lint_warning_alone_does_not_fail()
    {
        // Lint never blocks by construction (ContentFinding.Blocking is always false for a lint
        // finding) — this is the "warnings do not fail the process" half of the contract, proven
        // against a real ContentReport shape rather than assumed from ContentValidation.Lint's
        // implementation.
        var outcome = ValidationGate.Decide(WithWarningOnly(), Clean());
        Assert.True(outcome.Ok);
    }

    [Fact]
    public void A_drift_failure_fails_the_gate()
    {
        var outcome = ValidationGate.Decide(Clean(), WithFailure());
        Assert.False(outcome.Ok);
    }

    [Fact]
    public void A_lint_failure_fails_the_gate_too()
    {
        // Lint findings are never Blocking in practice, but the gate itself must not hardcode that
        // assumption — it reads ContentReport.Ok, which is true regardless of which report failed.
        var outcome = ValidationGate.Decide(WithFailure(), Clean());
        Assert.False(outcome.Ok);
    }

    [Fact]
    public void Every_pass_prints_its_evaluated_count_so_an_empty_pass_cannot_look_thorough()
    {
        var outcome = ValidationGate.Decide(Clean(evaluated: 0), Clean(evaluated: 0));

        Assert.Contains(outcome.Lines, l => l.Contains("0 evaluated", StringComparison.Ordinal) && l.StartsWith("lint", StringComparison.Ordinal));
        Assert.Contains(outcome.Lines, l => l.Contains("0 evaluated", StringComparison.Ordinal) && l.StartsWith("power drift", StringComparison.Ordinal));
        Assert.Contains(outcome.Lines, l => l.Contains("budget: skipped", StringComparison.Ordinal));
    }

    [Fact]
    public void A_failing_gate_names_the_offender_in_its_output()
    {
        var outcome = ValidationGate.Decide(Clean(), WithFailure());

        Assert.Contains(outcome.Lines, l => l.Contains("atom.test.t1", StringComparison.Ordinal));
        Assert.Contains(outcome.Lines, l => l.Contains("blocking finding", StringComparison.Ordinal));
    }
}
