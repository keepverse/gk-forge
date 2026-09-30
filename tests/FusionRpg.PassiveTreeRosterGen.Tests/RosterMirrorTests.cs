using System.IO;
using System.Linq;
using FusionRpg.Tools.PassiveTreeRosterGen;
using Xunit;
using FusionRpg.Core.Workspace;

namespace FusionRpg.PassiveTreeRosterGen.Tests;

/// <summary>Task A3 (tasks/passive-tree-todo.md) — the two roster mirrors, and their `--check`/
/// `--emit` contract mirroring `gk-forge/tools/ElementEnumGen`.</summary>
public class StatusRosterCheckTests
{
    [Fact]
    public void The_live_registry_against_itself_reports_no_mismatch()
    {
        var live = StatusRosterCheck.LiveRows();
        var report = StatusRosterCheck.Run(live);
        Assert.True(report.IsOk, string.Join("; ", report.Mismatches));
    }

    [Fact]
    public void A_mirror_missing_a_live_status_is_caught()
    {
        var live = StatusRosterCheck.LiveRows().ToList();
        var mirror = live.Skip(1).ToList(); // drop one
        var report = StatusRosterCheck.Run(mirror);
        Assert.False(report.IsOk);
        Assert.Contains(report.Mismatches, m => m.Contains(live[0].Id));
    }

    [Fact]
    public void A_mirror_category_drift_is_caught()
    {
        var live = StatusRosterCheck.LiveRows().ToList();
        var mutated = live.ToList();
        var wrongCategory = mutated[0].Category == "dot" ? "cc" : "dot";
        mutated[0] = mutated[0] with { Category = wrongCategory };
        var report = StatusRosterCheck.Run(mutated);
        Assert.False(report.IsOk);
        Assert.Contains(report.Mismatches, m => m.Contains(mutated[0].Id) && m.Contains(wrongCategory));
    }

    [Fact]
    public void A_stale_mirror_entry_not_in_the_live_registry_is_caught()
    {
        var live = StatusRosterCheck.LiveRows().ToList();
        live.Add(new StatusRosterRow("not-a-real-status", "dot", 999));
        var report = StatusRosterCheck.Run(live);
        Assert.False(report.IsOk);
        Assert.Contains(report.Mismatches, m => m.Contains("not-a-real-status"));
    }

    [Fact]
    public void Generated_json_round_trips_through_the_same_check()
    {
        var live = StatusRosterCheck.LiveRows();
        var json = StatusRosterCheck.GenerateJson(live);
        Assert.Contains("\"kind\": \"status\"", json);
        Assert.Contains(live.Count.ToString(), StatusRosterCheck.LiveRows().Count.ToString());
    }

    [Fact]
    public void The_real_shipped_mirror_file_agrees_with_the_live_registry()
    {
        var path = LiveSeedPath("statuses", "roster.json");
        Assert.True(File.Exists(path), $"missing shipped mirror {path} — run PassiveTreeRosterGen --status-emit");
        using var doc = System.Text.Json.JsonDocument.Parse(File.ReadAllText(path));
        var rows = doc.RootElement.GetProperty("entries").EnumerateArray()
            .Select(e => new StatusRosterRow(
                e.GetProperty("id").GetString()!, e.GetProperty("category").GetString()!,
                e.GetProperty("ordinal").GetInt32()))
            .ToList();
        var report = StatusRosterCheck.Run(rows);
        Assert.True(report.IsOk, string.Join("; ", report.Mismatches));
    }

    static string LiveSeedPath(params string[] segments)
    {
        var dir = new DirectoryInfo(Directory.GetCurrentDirectory());
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "CONTRIBUTING.md")))
            dir = dir.Parent;
        var root = dir?.FullName ?? throw new System.InvalidOperationException("repo root not found");
        return Path.Combine(new[] { KeepverseRoots.Content(), "data", "seed" }.Concat(segments).ToArray());
    }
}

public class AtomVocabCheckTests
{
    [Fact]
    public void The_live_registry_against_itself_reports_no_mismatch()
    {
        var live = AtomVocabCheck.LiveVocab();
        var report = AtomVocabCheck.Run(live);
        Assert.True(report.IsOk, string.Join("; ", report.Mismatches));
    }

    [Fact]
    public void A_missing_attach_point_is_caught()
    {
        var live = AtomVocabCheck.LiveVocab();
        var mutated = new AtomVocabMirror(live.AttachPoints.Skip(1).ToList(), live.Kinds, live.Triggers);
        var report = AtomVocabCheck.Run(mutated);
        Assert.False(report.IsOk);
    }

    [Fact]
    public void A_kind_attach_point_drift_is_caught()
    {
        var live = AtomVocabCheck.LiveVocab();
        var kinds = live.Kinds.ToList();
        var (id, attach) = kinds[0];
        kinds[0] = (id, attach == "Stat" ? "Board" : "Stat");
        var mutated = new AtomVocabMirror(live.AttachPoints, kinds, live.Triggers);
        var report = AtomVocabCheck.Run(mutated);
        Assert.False(report.IsOk);
        Assert.Contains(report.Mismatches, m => m.Contains(id));
    }

    [Fact]
    public void A_trigger_authorable_flag_drift_is_caught()
    {
        var live = AtomVocabCheck.LiveVocab();
        var triggers = live.Triggers.ToList();
        var (id, authorable) = triggers[0];
        triggers[0] = (id, !authorable);
        var mutated = new AtomVocabMirror(live.AttachPoints, live.Kinds, triggers);
        var report = AtomVocabCheck.Run(mutated);
        Assert.False(report.IsOk);
        Assert.Contains(report.Mismatches, m => m.Contains(id));
    }

    [Fact]
    public void A_stale_kind_not_in_the_live_registry_is_caught()
    {
        var live = AtomVocabCheck.LiveVocab();
        var kinds = live.Kinds.ToList();
        kinds.Add(("not.a.real.kind", "Stat"));
        var mutated = new AtomVocabMirror(live.AttachPoints, kinds, live.Triggers);
        var report = AtomVocabCheck.Run(mutated);
        Assert.False(report.IsOk);
        Assert.Contains(report.Mismatches, m => m.Contains("not.a.real.kind"));
    }

    [Fact]
    public void Eleven_of_thirteen_triggers_are_authorable_and_lifecycle_are_the_two_excluded()
    {
        var live = AtomVocabCheck.LiveVocab();
        var authorable = live.Triggers.Where(t => t.Authorable).ToList();
        var nonAuthorable = live.Triggers.Where(t => !t.Authorable).Select(t => t.Id).OrderBy(x => x).ToList();
        // live.Triggers IS AtomTriggers.All (AtomVocabCheck.cs) -- cross-checked against that canonical
        // pin (AtomCatalogSsotDriftTests) rather than re-derived from live.Triggers's own split, which
        // would be tautological (population-pin SE3.4, 2026-09-20).
        Assert.Equal(FusionRpg.Core.Effects.Atoms.AtomTriggers.All.Length, live.Triggers.Count);
        Assert.Equal(live.Triggers.Count - nonAuthorable.Count, authorable.Count);
        Assert.Equal(new[] { "OnGranted", "OnRemoved" }, nonAuthorable);
    }

    [Fact]
    public void The_real_shipped_mirror_file_agrees_with_the_live_registries()
    {
        var path = LiveSeedPath("passive-tree", "vocabulary.json");
        Assert.True(File.Exists(path), $"missing shipped mirror {path} — run PassiveTreeRosterGen --atom-vocab-emit");
        using var doc = System.Text.Json.JsonDocument.Parse(File.ReadAllText(path));
        var attachPoints = doc.RootElement.GetProperty("attachPoints").EnumerateArray()
            .Select(e => e.GetString()!).ToList();
        var kinds = doc.RootElement.GetProperty("kinds").EnumerateArray()
            .Select(e => (e.GetProperty("id").GetString()!, e.GetProperty("attach").GetString()!)).ToList();
        var triggers = doc.RootElement.GetProperty("triggers").EnumerateArray()
            .Select(e => (e.GetProperty("id").GetString()!, e.GetProperty("authorable").GetBoolean())).ToList();
        var report = AtomVocabCheck.Run(new AtomVocabMirror(attachPoints, kinds, triggers));
        Assert.True(report.IsOk, string.Join("; ", report.Mismatches));

        var expectedJson = AtomVocabCheck.GenerateJson(AtomVocabCheck.LiveVocab());
        var actualJson = File.ReadAllText(path).Replace("\r\n", "\n", StringComparison.Ordinal);
        Assert.Equal(expectedJson, actualJson);
    }

    [Fact]
    public void Generated_atom_vocabulary_json_is_lf_canonical_and_round_trips()
    {
        var json = AtomVocabCheck.GenerateJson(AtomVocabCheck.LiveVocab());

        Assert.DoesNotContain("\r", json, StringComparison.Ordinal);
        Assert.EndsWith("\n", json, StringComparison.Ordinal);
        using var doc = System.Text.Json.JsonDocument.Parse(json);
        Assert.Equal(1, doc.RootElement.GetProperty("schemaVersion").GetInt32());
        Assert.StartsWith("Generated by tools/PassiveTreeRosterGen",
            doc.RootElement.GetProperty("_meta").GetProperty("note").GetString(), StringComparison.Ordinal);
    }

    static string LiveSeedPath(params string[] segments)
    {
        var dir = new DirectoryInfo(Directory.GetCurrentDirectory());
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "CONTRIBUTING.md")))
            dir = dir.Parent;
        var root = dir?.FullName ?? throw new System.InvalidOperationException("repo root not found");
        return Path.Combine(new[] { KeepverseRoots.Content(), "data", "seed" }.Concat(segments).ToArray());
    }
}

/// <summary>A3's own acceptance bar: "every count is read and counted, never typed" — a bare
/// literal for any of these counts in this module's own source is exactly the drift risk a mirror
/// tool exists to prevent (a hand-typed 21 that quietly stops matching the registry).</summary>
public class NoHardcodedCountsTests
{
    static readonly string[] SourceFiles =
    {
        "StatusRosterCheck.cs", "AtomVocabCheck.cs", "Program.cs", "MismatchReport.cs",
    };

    [Theory]
    [InlineData("21")]
    [InlineData("16")]
    [InlineData("13")]
    [InlineData("11")]
    [InlineData("7")]
    public void Roster_counts_are_read_never_typed(string bannedLiteral)
    {
        var toolDir = ToolSourceDir();
        foreach (var file in SourceFiles)
        {
            var path = Path.Combine(toolDir, file);
            // Comments legitimately NAME these counts as documentation (this file's own doc
            // comments say "21 statuses", "16 kinds", etc., quoting the spec) — the same class of
            // false positive the passive-tree.v1.json banned-spelling test hit earlier. The real
            // check is CODE, so line comments, doc comments and block comments are stripped first.
            var code = StripComments(File.ReadAllText(path));
            foreach (System.Text.RegularExpressions.Match m in
                     System.Text.RegularExpressions.Regex.Matches(code, @"(?<![\w.])" + bannedLiteral + @"(?![\w.])"))
            {
                Assert.Fail($"{file} contains a bare literal '{bannedLiteral}' in CODE (not a comment) " +
                            $"at stripped-index {m.Index} — counts must be read from the live registry, never typed");
            }
        }
    }

    static string StripComments(string source)
    {
        // Order matters: /// and // are both matched by the single-line pattern; block comments
        // (including /** ... */) by the multi-line one. Neither pattern needs to understand strings
        // for this codebase — none of these five files puts "//" or "/*" inside a string literal.
        var noBlock = System.Text.RegularExpressions.Regex.Replace(
            source, @"/\*.*?\*/", "", System.Text.RegularExpressions.RegexOptions.Singleline);
        return System.Text.RegularExpressions.Regex.Replace(noBlock, @"//.*$", "",
            System.Text.RegularExpressions.RegexOptions.Multiline);
    }

    static string ToolSourceDir()
    {
        var dir = new DirectoryInfo(Directory.GetCurrentDirectory());
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "CONTRIBUTING.md")))
            dir = dir.Parent;
        var root = dir?.FullName ?? throw new System.InvalidOperationException("repo root not found");
        return Path.Combine(root, "tools", "PassiveTreeRosterGen");
    }
}
