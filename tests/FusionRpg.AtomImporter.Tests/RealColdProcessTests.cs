using System.Diagnostics;
using Xunit;

namespace FusionRpg.AtomImporter.Tests;

/// <summary>A real, cold run of the tool as a genuinely separate process — every other test
/// in this project runs in-process inside the test host, which already has every tuning hub
/// configured globally (`ContractTuningTestBootstrap`'s `[ModuleInitializer]`), so none of them could
/// ever catch a missing `Configure(...)` call the standalone binary itself needs. Found for real
/// 2026-08-30 running an actual deploy: `RpgStore`'s static ctor (T2's `ComposeKindRegistry`) needs
/// `DerivedStatPolicy.Tuning`, and this tool never configured it — the in-process test suite was
/// 21/21 green the whole time this was broken.</summary>
///
/// <para><b>Why the apphost and not `dotnet run` (2026-09-12):</b> `dotnet run` performs an implicit
/// MSBuild build, which races every concurrent `dotnet build`/`dotnet test` touching the same
/// `FusionRpg.Core.dll`/`FusionRpg.Data.dll` outputs — a transient MSB3026/MSB3027 file lock, not a
/// defect in this tool or this test. The old code papered over that with a 3-attempt retry (375s
/// worst case) and still left the test depending on a build it never arranged. This project already
/// has a `ProjectReference` to AtomImporter, so the test host's own build produces the tool's apphost
/// beside the test dll; the test now launches that directly. It is still a separate process with its
/// own statics and composition root — the cold-process property this test exists for is unchanged —
/// but there is no build, no lock race, and so no retry is needed.</para>
public class RealColdProcessTests
{
    [Fact]
    public void A_real_cold_run_against_a_fresh_db_does_not_crash_on_RpgStore_s_static_ctor()
    {
        var repoRoot = FindRepoRoot();
        var dbDir = Path.Combine(Path.GetTempPath(), "fusionrpg-atomimporter-cold-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dbDir);
        try
        {
            var (exitCode, stdout, stderr) = RunCold(repoRoot, dbDir);

            Assert.True(exitCode == 0,
                $"expected exit 0, got {exitCode}\nstdout:\n{stdout}\nstderr:\n{stderr}");
            Assert.DoesNotContain("type initializer", stderr, StringComparison.OrdinalIgnoreCase);

            // The unconfigured-hub signature, named rather than left as a bare non-zero exit. This
            // test was RED for exactly this before 2026-09-26: the importer never configured
            // LeadNamesHub, so a cold import against an empty data dir reached RpgStore's reader and
            // rolled the whole import back — which is the state every first-time live-probe slot is
            // in. A warm dir re-imports clean, so nothing else in this project could see it.
            Assert.DoesNotContain("has not run", stderr, StringComparison.OrdinalIgnoreCase);
            Assert.DoesNotContain("LeadNamesHub", stderr, StringComparison.OrdinalIgnoreCase);
        }
        finally
        {
            try { Directory.Delete(dbDir, recursive: true); } catch { /* temp dir */ }
        }
    }

    /// <summary>
    /// Launches the tool apphost the test host's own build produced (see the class doc), so a
    /// transient MSBuild file-lock race is structurally impossible and no retry is needed. The working
    /// directory must be the repo root: AtomImporter's own <c>FindUp("data", "seed")</c> walks up from
    /// it, so the test exercises that real default rather than passing a seed path explicitly.
    /// </summary>
    static (int ExitCode, string Stdout, string Stderr) RunCold(string repoRoot, string dbDir)
    {
        var psi = ToolStartInfo(repoRoot, arguments: $"--db \"{dbDir}\"");

        // 60s is far above the real runtime (~0.5s) and exists only to fail with a name instead of
        // hanging. The old 120s cap was sized for the implicit build this path no longer performs.
        return ExternalProcess.Run(psi, 60_000, "AtomImporter did not exit within 60s");
    }

    /// <summary>
    /// The tool the test project references, resolved from the test's own output directory. Prefer the
    /// apphost — a true standalone executable, exactly what a deploy runs — and fall back to
    /// <c>dotnet &lt;dll&gt;</c> on hosts that do not emit one. Neither path builds.
    /// </summary>
    static ProcessStartInfo ToolStartInfo(string repoRoot, string arguments)
    {
        var dir = AppContext.BaseDirectory;
        var apphost = Path.Combine(dir, OperatingSystem.IsWindows() ? "AtomImporter.exe" : "AtomImporter");
        var dll = Path.Combine(dir, "AtomImporter.dll");

        Assert.True(File.Exists(apphost) || File.Exists(dll),
            $"AtomImporter was not built beside the test dll ({dir}); the test project's ProjectReference should have produced it");

        return File.Exists(apphost)
            ? new ProcessStartInfo { FileName = apphost, Arguments = arguments, WorkingDirectory = repoRoot, CreateNoWindow = true }
            : new ProcessStartInfo { FileName = "dotnet", Arguments = $"\"{dll}\" {arguments}", WorkingDirectory = repoRoot, CreateNoWindow = true };
    }

    static string FindRepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null)
        {
            if (Directory.Exists(Path.Combine(dir.FullName, "tools", "AtomImporter"))) return dir.FullName;
            dir = dir.Parent;
        }
        throw new DirectoryNotFoundException("could not locate repo root above " + AppContext.BaseDirectory);
    }
}
