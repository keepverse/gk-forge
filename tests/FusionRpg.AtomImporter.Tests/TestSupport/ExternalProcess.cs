using System.Diagnostics;
using Xunit;

namespace FusionRpg.AtomImporter.Tests;

/// <summary>
/// Correct stdout/stderr draining for a redirected child process. Copied from
/// <c>tests/FusionRpg.Core.Tests/TestSupport/ExternalProcess.cs</c> rather than referenced, since
/// test projects in this repo do not reference each other.
///
/// <para><b>The bug this exists to kill:</b> <c>Process.StandardOutput.ReadToEnd()</c> immediately
/// followed by <c>Process.StandardError.ReadToEnd()</c> is a documented deadlock hazard: if the child
/// fills the stderr pipe buffer while the parent is still blocked draining stdout to EOF, the child
/// stalls and the parent never reaches EOF either. A later <c>WaitForExit(120_000)</c> can never fire
/// because the code is blocked on the read before it — a hang with no report. `dotnet run`'s own
/// MSBuild/restore chatter fills those pipes readily. This helper drains both streams CONCURRENTLY
/// and, on timeout, kills the whole process tree and fails instead of hanging forever.</para>
/// </summary>
public static class ExternalProcess
{
    public static (int ExitCode, string Stdout, string Stderr) Run(ProcessStartInfo psi, int timeoutMs, string timeoutMessage)
    {
        psi.RedirectStandardOutput = true;
        psi.RedirectStandardError = true;
        psi.UseShellExecute = false;

        using var p = Process.Start(psi)!;
        var stdoutTask = p.StandardOutput.ReadToEndAsync();
        var stderrTask = p.StandardError.ReadToEndAsync();

        var exited = p.WaitForExit(timeoutMs);
        if (!exited)
        {
            try { p.Kill(entireProcessTree: true); } catch { /* best-effort — we are already failing */ }
            Assert.Fail(timeoutMessage);
        }

        Task.WaitAll(new Task[] { stdoutTask, stderrTask }, TimeSpan.FromSeconds(10));

        return (
            p.ExitCode,
            stdoutTask.IsCompletedSuccessfully ? stdoutTask.Result : "",
            stderrTask.IsCompletedSuccessfully ? stderrTask.Result : "");
    }
}
