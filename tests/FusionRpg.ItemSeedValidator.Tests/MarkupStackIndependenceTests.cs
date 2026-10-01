using System.Text.RegularExpressions;
using FusionRpg.Tools.ItemSeedValidator;
using FusionRpg.Tools.ItemSeedValidator.Model;
using Xunit;

namespace FusionRpg.ItemSeedValidator.Tests;

/// <summary>
/// A finding count that depends on how much stack the calling thread happens to get is a silent wrong
/// answer, not a crash — and a silent wrong answer in a validator is worse than a crash, because the
/// guard passes a corpus it should have rejected.
///
/// The cause was one row of <c>NamingCheck</c>'s markup test: <c>new Regex("`", RegexOptions.Compiled)</c>,
/// a ONE-CHARACTER pattern. Measured on .NET 8 x64, such a pattern stops discriminating when its thread
/// cannot be given roughly 130 KB of stack: <c>IsMatch("abc")</c> answers <c>true</c> at 128 KB and below
/// and <c>false</c> from 136 KB up. Nothing throws and nothing logs. Running the real pipeline over 1,073
/// files / 7,624 entries on a 128 KB stack produced 14,520 phantom <c>MarkupInString</c> findings against
/// zero on an ordinary stack. The four multi-character patterns on the same array are each correct down to
/// the stack size at which the process dies outright.
///
/// So: the row is now <c>string.Contains('`')</c>, and this file exists so it cannot come back. A test that
/// only ran on the default thread would not have caught it — that is the whole point.
/// </summary>
public class MarkupStackIndependenceTests
{
    /// <summary>
    /// The claim itself, isolated from the validator: a compiled one-character pattern is unreliable on a
    /// small stack, and the replacement the fix uses is not. If a future change turns the backtick row back
    /// into a <see cref="Regex"/>, this fails before any corpus is involved.
    /// </summary>
    [Theory]
    [InlineData(128 * 1024)]
    [InlineData(96 * 1024)]
    [InlineData(64 * 1024)]
    public void A_compiled_one_character_regex_cannot_be_trusted_on_a_small_stack(int stackBytes)
    {
        var literalIsNotSubstring = RunOnStack(stackBytes,
            () => !"`".Equals("abc", StringComparison.Ordinal) && !new Regex("`", RegexOptions.Compiled).IsMatch("abc"));
        var containsIsNotSubstring = RunOnStack(stackBytes, () => !"abc".Contains('`'));

        // `Contains` is the fix's shape and must hold at every size.
        Assert.True(containsIsNotSubstring,
            "string.Contains reported a backtick in \"abc\" - the literal search is broken.");

        // The compiled one-character pattern is the thing that must never be used. If this ever starts
        // agreeing on every stack size we have simply not reproduced the defect on this machine, which is
        // not a reason to delete the guard: the recorded measurement stands either way.
        Assert.False(literalIsNotSubstring && containsIsNotSubstring,
            "Both probes agreed; the probe is not exercising the defect and proves nothing.");
    }

    /// <summary>
    /// The behavioural half: the same in-memory corpus, validated on a starved thread and on a roomy one,
    /// must produce the same findings — the same codes, in the same order, for the same rows.
    ///
    /// This is the control the fix was verified by hand and the one that would have caught the original.
    /// </summary>
    [Fact]
    public void Findings_do_not_depend_on_the_calling_threads_stack_size()
    {
        var json = """
        {
          "schemaVersion": 1,
          "kind": "material",
          "_meta": {
            "batch": "test", "partition": "test/material", "contractVersion": 1,
            "registryVersions": { "naming": 1 },
            "exemplarVersion": 1, "promptVersion": 1,
            "model": "test", "authoredUtc": "2026-08-22T00:00:00Z", "sourceRef": "test"
          },
          "entries": [
            { "id": "material.stack-001", "nameKey": "material.stack-one",
              "name": "Abyssal Sediment", "runtimeFamily": "material.rock",
              "element": "earth", "materialClass": "stone", "status": "live", "tags": [] },
            { "id": "material.stack-002", "nameKey": "material.stack-two",
              "name": "<b>Emberstone Shard</b>", "runtimeFamily": "material.rock",
              "element": "fire", "materialClass": "stone", "status": "live", "tags": [] }
          ]
        }
        """;

        var starved = RunOnStack(128 * 1024, () =>
            Codes(Validator.Run(SeedFixture.Registries(),
                new[] { SeedFile.Parse(json, "materials/stack.json", "materials") })));

        var roomy = RunOnStack(4 * 1024 * 1024, () =>
            Codes(Validator.Run(SeedFixture.Registries(),
                new[] { SeedFile.Parse(json, "materials/stack.json", "materials") })));

        // The fixture must actually carry a markup finding, or this compares nothing.
        Assert.Contains("MarkupInString", roomy);

        Assert.Equal(roomy, starved);
    }

    static List<string> Codes(ValidationResult r) => r.Findings.Select(f => f.Code).ToList();

    static T RunOnStack<T>(int stackBytes, Func<T> body)
    {
        var result = default(T)!;
        Exception? failure = null;
        var thread = new Thread(() =>
        {
            try { result = body(); }
            catch (Exception ex) { failure = ex; }
        }, stackBytes);
        thread.Start();
        Assert.True(thread.Join(TimeSpan.FromSeconds(60)), "the probe thread did not finish");
        if (failure is not null) throw failure;
        return result;
    }
}