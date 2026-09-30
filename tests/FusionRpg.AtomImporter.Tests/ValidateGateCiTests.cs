using System.Diagnostics;
using Xunit;
using FusionRpg.Core.Workspace;

namespace FusionRpg.AtomImporter.Tests;

/// <summary>
/// E47 (spec-validate-gate-ci.md §5): the CI step itself, exercised as a real cold `dotnet run` —
/// every test here is a separate process, the same discipline <see cref="RealColdProcessTests"/>
/// established, because the in-process test host already has every tuning hub configured and could
/// never catch a wiring gap the standalone binary hits on its own. This file proves the gate the
/// module is named for actually gates: a planted structural defect fails the build, a planted lint
/// only reports, and the `--db` flag is load-bearing rather than decoration.
/// </summary>
public class ValidateGateCiTests
{
    /// <summary>Test 1 — the CI step, run against the real shipped corpus, exits 0 today.</summary>
    [Fact]
    public void The_real_seed_tree_validates_clean_and_names_what_it_evaluated()
    {
        var repoRoot = FindRepoRoot();
        var dbDir = FreshTempDir("real");
        try
        {
            var (exitCode, stdout, _) = Run(repoRoot, dbDir, seedRoot: null);

            Assert.Equal(0, exitCode);
            // Test 5: the output names what it evaluated, so an empty pass cannot look green.
            Assert.Matches(@"lint: \d+ evaluated", stdout);
            Assert.Matches(@"power drift: \d+ evaluated", stdout);
            Assert.Matches(@"\d+ file\(s\): \d+ atom\(s\)", stdout);
        }
        finally { TryDelete(dbDir); }
    }

    /// <summary>Test 2 — a planted unknown-kind atom fails the build. It fails inside
    /// <c>store.ImportContent</c>'s catalog refusal (upstream of <c>if (validate)</c>), not inside
    /// <c>AtomSeedFile.Collect</c> — confirmed by running it, not assumed from the spec's line numbers —
    /// but the load-bearing fact §3.2 depends on is the same either way: a structural defect never
    /// reaches the lint/drift gate, because the import itself has already refused it.</summary>
    [Fact]
    public void A_planted_unknown_kind_atom_fails_the_import_before_the_gate_runs()
    {
        var repoRoot = FindRepoRoot();
        var seedRoot = FreshTempDir("bad-kind");
        var dbDir = FreshTempDir("bad-kind-db");
        try
        {
            File.WriteAllText(Path.Combine(seedRoot, "bad.json"), """
                {
                  "schemaVersion": 1,
                  "kind": "atom",
                  "entries": [
                    {
                      "family": "atom.e47-bad-kind",
                      "tier": 1,
                      "kind": "bogus.nonsense.kind",
                      "name": "Planted bad kind",
                      "icdKey": "fx.e47_bad_kind",
                      "params": {},
                      "when": { "trigger": "OnDamageDealt" }
                    }
                  ]
                }
                """);

            var (exitCode, stdout, stderr) = Run(repoRoot, dbDir, seedRoot);

            Assert.Equal(1, exitCode);
            Assert.Contains("nothing was written", stdout + stderr, StringComparison.Ordinal);
            Assert.Contains("bogus.nonsense.kind", stdout + stderr, StringComparison.Ordinal);
        }
        finally { TryDelete(seedRoot); TryDelete(dbDir); }
    }

    /// <summary>Test 3 — a planted orphan atom (a real registered kind, no container referencing it)
    /// reports the lint and still exits 0 — proving §3.2's policy is real: lints are `Blocking: false`
    /// by construction, not just described that way.</summary>
    [Fact]
    public void A_planted_orphan_atom_reports_and_does_not_fail()
    {
        var repoRoot = FindRepoRoot();
        var seedRoot = FreshTempDir("orphan");
        var dbDir = FreshTempDir("orphan-db");
        try
        {
            File.WriteAllText(Path.Combine(seedRoot, "orphan.json"), """
                {
                  "schemaVersion": 1,
                  "kind": "atom",
                  "entries": [
                    {
                      "family": "atom.e47-orphan",
                      "tier": 1,
                      "kind": "stat.modify",
                      "name": "Planted orphan",
                      "icdKey": "fx.e47_orphan",
                      "params": { "channel": "atk", "op": "flat", "amount": 5 },
                      "when": { "trigger": "OnDamageDealt" }
                    }
                  ]
                }
                """);

            var (exitCode, stdout, _) = Run(repoRoot, dbDir, seedRoot);

            Assert.Equal(0, exitCode);
            Assert.Contains("orphan", stdout, StringComparison.Ordinal);
            Assert.Contains("atom.e47-orphan", stdout, StringComparison.Ordinal);
        }
        finally { TryDelete(seedRoot); TryDelete(dbDir); }
    }

    /// <summary>Test 3b — the flag is load-bearing, not decoration: with no <c>--db</c>, no
    /// <c>FUSIONRPG_DATA</c>, and a working directory with no <c>dist/FusionRpg.Server/data</c> above it
    /// (a fresh CI checkout's exact shape), the tool exits 2 before reading a single seed file.</summary>
    [Fact]
    public void Omitting_db_with_no_dist_and_no_env_var_exits_2_before_reading_any_seed_file()
    {
        var repoRoot = FindRepoRoot();
        var seedRoot = FreshTempDir("no-db-seed");
        var cwd = FreshTempDir("no-db-cwd");
        try
        {
            File.WriteAllText(Path.Combine(seedRoot, "orphan.json"), """
                {
                  "schemaVersion": 1,
                  "kind": "atom",
                  "entries": [
                    {
                      "family": "atom.e47-nodb",
                      "tier": 1,
                      "kind": "stat.modify",
                      "name": "Planted no-db",
                      "icdKey": "fx.e47_nodb",
                      "params": { "channel": "atk", "op": "flat", "amount": 5 },
                      "when": { "trigger": "OnDamageDealt" }
                    }
                  ]
                }
                """);

            var psi = ToolStartInfo(cwd, $"\"{seedRoot}\" --check --validate");
            psi.EnvironmentVariables.Remove("FUSIONRPG_DATA");
            var (exitCode, stdout, stderr) = ExternalProcess.Run(psi, 120_000, "AtomImporter did not exit within 120s");

            Assert.Equal(2, exitCode);
            Assert.Contains("no database directory", stdout + stderr, StringComparison.Ordinal);
        }
        finally { TryDelete(seedRoot); TryDelete(cwd); }
    }

    static (int ExitCode, string Stdout, string Stderr) Run(string repoRoot, string dbDir, string? seedRoot)
    {
        var positional = seedRoot is null ? "" : $"\"{seedRoot}\" ";
        var psi = ToolStartInfo(repoRoot, $"{positional}--check --validate --db \"{dbDir}\"");
        return ExternalProcess.Run(psi, 120_000, "AtomImporter did not exit within 120s");
    }

    /// <summary>
    /// The referenced tool's own apphost, launched WITHOUT an implicit build.
    ///
    /// <para>Both call sites in this file used <c>dotnet run --project ... -c Release</c>, which
    /// rebuilds AtomImporter in a child process while the parent <c>dotnet test</c> still holds the
    /// same assemblies — the CS2012 locked-file race that is red inside a full-suite run and green
    /// alone. <c>RealColdProcessTests</c>, this file's own sibling, was fixed for exactly that on
    /// 2026-09-12; these two sites were missed. Found 2026-09-17 while fixing the identical race in
    /// <c>FusionRpg.SquadHarness.Tests</c>, where it HAD fired and looked like a determinism break.</para>
    ///
    /// <para>The <c>-c Release</c> the old form passed was part of the problem, not a setting worth
    /// keeping: it demanded a Release build the parent test run may never have produced.</para>
    /// </summary>
    static ProcessStartInfo ToolStartInfo(string workingDirectory, string arguments)
    {
        var dir = AppContext.BaseDirectory;
        var apphost = Path.Combine(dir, OperatingSystem.IsWindows() ? "AtomImporter.exe" : "AtomImporter");
        var dll = Path.Combine(dir, "AtomImporter.dll");

        Assert.True(File.Exists(apphost) || File.Exists(dll),
            $"AtomImporter was not built beside the test dll ({dir}); the test project's ProjectReference should have produced it");

        return File.Exists(apphost)
            ? new ProcessStartInfo
            {
                FileName = apphost,
                Arguments = arguments,
                WorkingDirectory = workingDirectory,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            }
            : new ProcessStartInfo
            {
                FileName = "dotnet",
                Arguments = $"\"{dll}\" {arguments}",
                WorkingDirectory = workingDirectory,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
                CreateNoWindow = true
            };
    }

    static string FreshTempDir(string label)
    {
        var dir = Path.Combine(Path.GetTempPath(), $"fusionrpg-e47-{label}-{Guid.NewGuid():N}");
        Directory.CreateDirectory(dir);
        return dir;
    }

    static void TryDelete(string dir)
    {
        try { Directory.Delete(dir, recursive: true); } catch { /* temp dir */ }
    }

    static string FindRepoRoot()
    {
        return KeepverseRoots.Core();
    }
}
