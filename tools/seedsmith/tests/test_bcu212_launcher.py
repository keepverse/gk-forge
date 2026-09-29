"""Process-lifecycle regression for the BCU2.12 detached launcher.

A fake ``python`` command proves the launcher fails closed before the unbounded phase and cannot leave
an older report/results file looking current. No model endpoint or generated corpus is touched.
"""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[3] / ".claude" / "cmdc-agents" / "scripts" /
          "bcu212-full-run.ps1")


@unittest.skipUnless(os.name == "nt", "the deterministic command shim is a Windows batch fixture")
class Bcu212LauncherLifecycleTests(unittest.TestCase):
    def _run_with_roster(self, output: "str | None", exit_code: int):
        """Run the launcher with a fake command whose first call is the roster probe."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_text:
            tmp = Path(tmp_text)
            bin_dir = tmp / "bin"
            worktree = tmp / "worktree"
            bin_dir.mkdir()
            worktree.mkdir()
            state = tmp / "python-calls.txt"
            python_cmd = bin_dir / "python.cmd"
            python_cmd.write_text(
                "@echo off\r\n"
                "setlocal\r\n"
                ">>\"%BCU_FAKE_STATE%\" echo %*\r\n"
                "if \"%~1\"==\"-c\" (\r\n"
                "  if \"%BCU_FAKE_HAS_OUTPUT%\"==\"1\" echo %BCU_FAKE_ROSTER_OUTPUT%\r\n"
                "  exit /b %BCU_FAKE_ROSTER_EXIT%\r\n"
                ")\r\n"
                "exit /b 0\r\n",
                encoding="utf-8",
            )

            old_results = worktree / "tools" / "seedsmith" / "_j9_batch_run_results.json"
            old_report = worktree / "tasks" / "reports" / "BCU2.12-full-run.json"
            old_results.parent.mkdir(parents=True)
            old_report.parent.mkdir(parents=True)
            old_results.write_text('[{"speciesId":"stale"}]', encoding="utf-8")
            old_report.write_text('{"head":"stale"}', encoding="utf-8")

            env = os.environ.copy()
            env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
            env["BCU_FAKE_STATE"] = str(state)
            env["BCU_FAKE_HAS_OUTPUT"] = "0" if output is None else "1"
            env["BCU_FAKE_ROSTER_OUTPUT"] = "" if output is None else output
            env["BCU_FAKE_ROSTER_EXIT"] = str(exit_code)
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
                 "-Worktree", str(worktree), "-Smoke", "2", "-Python", str(python_cmd)],
                cwd=worktree, env=env, capture_output=True, text=True, timeout=30)
            calls = state.read_text(encoding="utf-8").splitlines() if state.exists() else []
            return result, calls, not old_results.exists(), not old_report.exists()

    def test_nonzero_roster_command_stops_before_smoke(self) -> None:
        result, calls, old_results_removed, old_report_removed = self._run_with_roster("904", 9)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual(1, len(calls), result.stdout)
        self.assertIn("ROSTER_FAILURE=roster_count_command_nonzero exit=9", result.stdout)
        self.assertNotIn("=== smoke", result.stdout)
        self.assertTrue(old_results_removed)
        self.assertTrue(old_report_removed)

    def test_empty_roster_output_stops_before_smoke(self) -> None:
        result, calls, old_results_removed, old_report_removed = self._run_with_roster(None, 0)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual(1, len(calls), result.stdout)
        self.assertIn("ROSTER_FAILURE=roster_count_empty", result.stdout)
        self.assertNotIn("=== smoke", result.stdout)
        self.assertTrue(old_results_removed)
        self.assertTrue(old_report_removed)

    def test_non_integer_roster_output_stops_before_smoke(self) -> None:
        result, calls, old_results_removed, old_report_removed = self._run_with_roster("not-a-count", 0)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual(1, len(calls), result.stdout)
        self.assertIn("ROSTER_FAILURE=roster_count_not_integer", result.stdout)
        self.assertNotIn("=== smoke", result.stdout)
        self.assertTrue(old_results_removed)
        self.assertTrue(old_report_removed)

    def test_zero_roster_count_stops_before_smoke(self) -> None:
        result, calls, old_results_removed, old_report_removed = self._run_with_roster("0", 0)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual(1, len(calls), result.stdout)
        self.assertIn("ROSTER_FAILURE=roster_count_non_positive", result.stdout)
        self.assertNotIn("=== smoke", result.stdout)
        self.assertTrue(old_results_removed)
        self.assertTrue(old_report_removed)

    def test_negative_roster_count_stops_before_smoke(self) -> None:
        result, calls, old_results_removed, old_report_removed = self._run_with_roster("-1", 0)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertEqual(1, len(calls), result.stdout)
        self.assertIn("ROSTER_FAILURE=roster_count_non_positive", result.stdout)
        self.assertNotIn("=== smoke", result.stdout)
        self.assertTrue(old_results_removed)
        self.assertTrue(old_report_removed)

    def test_valid_roster_uses_the_selected_python_for_every_launcher_phase(self) -> None:
        result, calls, old_results_removed, old_report_removed = self._run_with_roster("904", 0)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("roster_species=904", result.stdout)
        self.assertIn("smoke_exit=0", result.stdout)
        self.assertIn("full_exit=0", result.stdout)
        self.assertIn("resume_exit=0", result.stdout)
        self.assertIn("check_exit=0", result.stdout)
        self.assertIn("report_exit=0", result.stdout)
        self.assertIn("=== VERDICT JOB END ===", result.stdout)
        self.assertTrue(any("bcu212-report.py" in line and "--python" in line
                            for line in calls), calls)
        self.assertTrue(any("bcu212-report.py" in line and "python.cmd" in line
                            for line in calls), calls)
        self.assertEqual(3, sum("_j9_batch_run.py" in line for line in calls), calls)
        self.assertTrue(old_results_removed)
        self.assertTrue(old_report_removed)

    def test_failed_smoke_stops_before_full_run_and_invalidates_old_results(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_text:
            tmp = Path(tmp_text)
            bin_dir = tmp / "bin"
            worktree = tmp / "worktree"
            bin_dir.mkdir()
            worktree.mkdir()
            state = tmp / "python-calls.txt"
            python_cmd = bin_dir / "python.cmd"
            python_cmd.write_text(
                "@echo off\r\n"
                "setlocal EnableDelayedExpansion\r\n"
                "set /a N=0\r\n"
                "if exist \"%BCU_FAKE_STATE%\" for /f \"usebackq tokens=1\" %%i in "
                "(\"%BCU_FAKE_STATE%\") do set /a N=%%i\r\n"
                "set /a N+=1\r\n"
                ">>\"%BCU_FAKE_STATE%\" echo !N!\r\n"
                "if !N! equ 1 echo 2\r\n"
                "if !N! equ 2 exit /b %BCU_FAKE_SMOKE_EXIT%\r\n"
                "if !N! equ 3 exit /b %BCU_FAKE_FULL_EXIT%\r\n"
                "if !N! equ 4 exit /b %BCU_FAKE_RESUME_EXIT%\r\n"
                "if !N! equ 5 exit /b %BCU_FAKE_CHECK_EXIT%\r\n"
                "if !N! equ 6 exit /b %BCU_FAKE_REPORT_EXIT%\r\n"
                "exit /b 0\r\n",
                encoding="utf-8",
            )

            old_results = worktree / "tools" / "seedsmith" / "_j9_batch_run_results.json"
            old_report = worktree / "tasks" / "reports" / "BCU2.12-full-run.json"
            old_results.parent.mkdir(parents=True)
            old_report.parent.mkdir(parents=True)
            old_results.write_text('[{"speciesId":"stale"}]', encoding="utf-8")
            old_report.write_text('{"head":"stale"}', encoding="utf-8")

            env = os.environ.copy()
            env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
            env["BCU_FAKE_STATE"] = str(state)
            env["BCU_FAKE_SMOKE_EXIT"] = "7"
            env["BCU_FAKE_FULL_EXIT"] = "0"
            env["BCU_FAKE_RESUME_EXIT"] = "0"
            env["BCU_FAKE_CHECK_EXIT"] = "0"
            env["BCU_FAKE_REPORT_EXIT"] = "0"
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
                 "-Worktree", str(worktree), "-Smoke", "2", "-Python", str(python_cmd)],
                cwd=worktree, env=env, capture_output=True, text=True, timeout=30)

            self.assertEqual(7, result.returncode, result.stdout + result.stderr)
            calls = [int(line) for line in state.read_text(encoding="utf-8").splitlines() if line]
            self.assertEqual(2, len(calls), "roster count + smoke only; full/resume/report never start")
            self.assertFalse(old_results.exists(), "stale batch results must not survive a new attempt")
            self.assertFalse(old_report.exists(), "stale final report must not survive a new attempt")
            self.assertIn("smoke_exit=7", result.stdout)

    def test_failed_full_run_skips_resume_and_finishes_nonzero(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_text:
            tmp = Path(tmp_text)
            bin_dir = tmp / "bin"
            worktree = tmp / "worktree"
            bin_dir.mkdir()
            worktree.mkdir()
            state = tmp / "python-calls.txt"
            python_cmd = bin_dir / "python.cmd"
            python_cmd.write_text(
                "@echo off\r\n"
                "setlocal EnableDelayedExpansion\r\n"
                "set /a N=0\r\n"
                "if exist \"%BCU_FAKE_STATE%\" for /f \"usebackq tokens=1\" %%i in "
                "(\"%BCU_FAKE_STATE%\") do set /a N=%%i\r\n"
                "set /a N+=1\r\n"
                ">>\"%BCU_FAKE_STATE%\" echo !N!\r\n"
                "if !N! equ 1 echo 904\r\n"
                "if !N! equ 2 exit /b 0\r\n"
                "if !N! equ 3 exit /b 9\r\n"
                "if !N! equ 4 exit /b 0\r\n"
                "if !N! equ 5 exit /b 0\r\n"
                "exit /b 0\r\n",
                encoding="utf-8",
            )
            old_results = worktree / "tools" / "seedsmith" / "_j9_batch_run_results.json"
            old_report = worktree / "tasks" / "reports" / "BCU2.12-full-run.json"
            old_results.parent.mkdir(parents=True)
            old_report.parent.mkdir(parents=True)
            old_results.write_text('[{"speciesId":"stale"}]', encoding="utf-8")
            old_report.write_text('{"head":"stale"}', encoding="utf-8")

            env = os.environ.copy()
            env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
            env["BCU_FAKE_STATE"] = str(state)
            result = subprocess.run(
                ["pwsh", "-NoProfile", "-NonInteractive", "-File", str(SCRIPT),
                 "-Worktree", str(worktree), "-Smoke", "2", "-Python", str(python_cmd)],
                cwd=worktree, env=env, capture_output=True, text=True, timeout=30)

            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            calls = [int(line) for line in state.read_text(encoding="utf-8").splitlines() if line]
            self.assertEqual(5, len(calls), "roster + smoke + failed full + check + report; no resume")
            self.assertIn("full_exit=9", result.stdout)
            self.assertIn("resume_exit=skipped_after_failed_full_run", result.stdout)
            self.assertIn("VERDICT JOB FAILED", result.stdout)
            self.assertFalse(old_results.exists())
            self.assertFalse(old_report.exists())
