"""A guard for the class `a41d5d152` fixed: every seedsmith subprocess launch goes through `run_tool`.

That commit made a missing `dotnet` a NAMED refusal instead of a bare `FileNotFoundError`, and it was
applied to eight call sites in six modules — derived from a grep whose output was truncated with
`head -20`, so it MISSED `adapters/items/unique_frame_repair.py`. That ninth site kept the exact defect
the commit exists to remove, and nothing said so.

This test is the thing that would have caught it, and it is a source scan rather than a behaviour test
because the failure mode is a call shape, not a value: any module that calls `subprocess.run` directly
with a bare executable name reintroduces an opaque failure the moment the tool is absent.

    python -m pytest gk-forge/tools/seedsmith/tests/test_tool_invocation_guard.py -q
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402

PACKAGE = Path(__file__).resolve().parents[1] / "seedsmith"

#: The one module allowed to call `subprocess` — everything else goes through `run_tool`, which names a
#: missing executable and preserves the caller's own refusal type.
SANCTIONED = {"tooling.py"}

#: A direct process launch. `subprocess.CompletedProcess`/`DEVNULL` are not launches, so the pattern
#: requires a call. The `os.*`/`pty.*` shapes are included because they are the same defect in a different
#: spelling — a launch whose missing executable is an opaque `OSError` rather than a named refusal — and a
#: guard for the CLASS has to cover the spellings nobody uses yet. `shutil.which` is deliberately NOT
#: here: it is a RESOLVER, which is the shape this guard exists to push call sites toward.
LAUNCH = re.compile(
    r"subprocess\.(run|Popen|check_output|check_call|call)\s*\("
    r"|os\.(system|popen|spawn[a-z]*|exec[a-z]*)\s*\("
    r"|pty\.spawn\s*\("
)


def _code_lines(path: Path) -> "list[tuple[int, str]]":
    """(lineno, line) for every line that is not a comment.

    A source scan that matches prose is a false positive, and this file's own sibling
    (`refresh_allocated_partitions.py`) documents the very shape this guard bans in a `#` comment. Only
    whole-line comments are skipped, which is what a docstring-style explanation of a launch looks like;
    a trailing `# ...` after real code is rare enough that leaving it in is the conservative choice.
    """
    out = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        out.append((lineno, line))
    return out


def test_every_seedsmith_process_launch_goes_through_run_tool() -> None:
    offenders = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.name in SANCTIONED:
            continue
        for lineno, line in _code_lines(path):
            if LAUNCH.search(line):
                offenders.append(f"{path.relative_to(PACKAGE.parent.parent).as_posix()}:{lineno}")
    assert offenders == [], (
        "these modules launch a process directly instead of through `seedsmith.tooling.run_tool`, so a "
        "missing executable there surfaces as an opaque OSError rather than the module's own refusal: "
        + ", ".join(offenders)
    )


def test_the_scan_would_actually_catch_one(tmp_path: Path) -> None:
    """A source scan that cannot fail is not a guard: plant the shape in a temporary module and assert
    the same pattern matches it — in both spellings, so the `os.*` half is proven too."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "import os\n"
        "import subprocess\n"
        "def go():\n"
        "    return subprocess.run(['dotnet', 'run'], capture_output=True, text=True)\n"
        "def go2():\n"
        "    return os.system('dotnet run')\n",
        encoding="utf-8",
    )
    hits = [n for n, line in enumerate(planted.read_text(encoding="utf-8").splitlines(), 1)
            if LAUNCH.search(line)]
    assert hits == [4, 6]


# ---------------------------------------------------------------------------------------------
# The same class in TEST code, with the rule that fits it: a test must launch the interpreter it is
# running under, never a bare `python` from PATH.
#
# `a41d5d152` fixed the package half of this class and `SGC5-F5` files the C# half. Test code is a third
# scope with a DIFFERENT rule: a test that shells out to `python` may (a) run a different interpreter than
# the one executing it, and (b) fail opaquely where `python` is not on PATH — while `sys.executable` is
# by construction present and is the same interpreter. Two sites here used the bare name
# (`test_distribution_planner.py`, `test_innate_picker.py`); both now use `sys.executable`, and this case
# keeps the third one from being written.
# ---------------------------------------------------------------------------------------------

TESTS = Path(__file__).resolve().parent

BARE_PYTHON = re.compile(r"subprocess\.\w+\(\s*\[?\s*[\"']python3?[\"']")


def test_test_code_launches_the_interpreter_it_is_running_under() -> None:
    offenders = []
    for path in sorted(TESTS.rglob("test_*.py")):
        text = path.read_text(encoding="utf-8")
        for match in BARE_PYTHON.finditer(text):
            offenders.append(f"{path.name}:{text[:match.start()].count(chr(10)) + 1}")
    assert offenders == [], (
        "these tests launch a bare `python` from PATH instead of `sys.executable`, so they may run a "
        "different interpreter than the one executing them and fail opaquely where `python` is absent: "
        + ", ".join(offenders)
    )


def test_the_test_code_scan_would_actually_catch_one(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text(
        "import subprocess\n"
        "subprocess.run(\n"
        "    ['python', '-m', 'seedsmith', 'check'],\n"
        "    capture_output=True)\n",
        encoding="utf-8",
    )
    assert BARE_PYTHON.search(planted.read_text(encoding="utf-8")) is not None


# ---------------------------------------------------------------------------------------------
# The tool ROOT — the loose scripts beside the package (`refresh_allocated_partitions.py` and the
# one-off run scripts). Same rule as the package: a launch goes through `run_tool`, never directly.
# ---------------------------------------------------------------------------------------------

TOOL_ROOT = Path(__file__).resolve().parents[1]


def test_tool_root_scripts_launch_through_run_tool_too() -> None:
    offenders = []
    for path in sorted(TOOL_ROOT.glob("*.py")):
        for lineno, line in _code_lines(path):
            if LAUNCH.search(line):
                offenders.append(f"{path.name}:{lineno}")
    assert offenders == [], (
        "these tool-root scripts launch a process directly instead of through "
        "`seedsmith.tooling.run_tool`, so a missing executable surfaces as an opaque OSError rather "
        "than a named refusal: " + ", ".join(offenders)
    )


# ---------------------------------------------------------------------------------------------
# The scope inventory itself — the failure this guard has ALREADY had three times.
#
# Each version of this guard scanned the scope it was written for: the package (a41d5d152's sweep), then
# `tests/`, then the tool root. Each time a site was hiding in the scope nobody had looked at, and each
# time the reason was the same — "I swept" meant "I swept the place I was thinking about". So the last
# case asserts the INVENTORY: every `.py` under `gk-forge/tools/seedsmith/**` is inside one of the three scanned
# scopes. A new directory (a `scripts/`, a `tools/`) fails this case on the day it is created, rather
# than silently sitting outside every scan.
# ---------------------------------------------------------------------------------------------

SCANNED_SCOPES = ("seedsmith", "tests")

#: A virtual environment under the tool root is not SOURCE, and this inventory is about source.
#:
#: ⛔ Measured 2026-09-28: this case reported 1,975 unscanned files, every one of them under
#: `.venv-verify/Lib/site-packages/...` - an environment the suite itself creates, transiently, under
#: `gk-forge/tools/seedsmith/`. Whether it fails therefore depends on whether a venv happens to exist at that
#: instant, which is the worst property a scope guard can have: it is green in CI and red on a
#: developer machine, or the reverse, for reasons that have nothing to do with the tree's source.
#: `__pycache__` was already excluded for the same class of reason (a build artefact, not a file
#: anyone can launch by hand), so this extends that rule to the other build artefact that appears here.
UNSCANNED_ARTEFACT_DIRS = ("__pycache__", "site-packages", ".venv", "venv", ".tox", ".nox")


def _is_build_artefact(parts: "tuple[str, ...]") -> bool:
    return any(p in UNSCANNED_ARTEFACT_DIRS for p in parts)


def test_every_python_file_under_the_tool_is_inside_a_scanned_scope() -> None:
    unscanned = []
    for path in sorted(TOOL_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = path.relative_to(TOOL_ROOT)
        if _is_build_artefact(relative.parts):
            continue
        if len(relative.parts) == 1:
            continue  # the tool root's own loose scripts — the third scan
        if relative.parts[0] in SCANNED_SCOPES:
            continue
        unscanned.append(relative.as_posix())
    assert unscanned == [], (
        "these Python files are under `tools/seedsmith/` but outside every scope this guard scans "
        f"({', '.join(SCANNED_SCOPES)} plus the tool root), so a direct launch in them would be "
        f"invisible: {', '.join(unscanned[:20])}"
        + (f" (+{len(unscanned) - 20} more)" if len(unscanned) > 20 else "")
    )


def test_the_artefact_exclusion_cannot_hide_a_real_source_file() -> None:
    """The exclusion is the one thing that could hide a real file, so it is pinned: `site-packages` as a
    DIRECTORY component is excluded, while a source file that merely CONTAINS the word - a module named
    `site_packages.py`, or a `seedsmith/venv_rules.py` - is still inventoried.

    Without this, "skip anything matching the name" is how a genuine unscanned module disappears behind a
    convenient substring.
    """
    assert _is_build_artefact(("site-packages", "requests", "__init__.py"))
    assert _is_build_artefact((".venv-verify", "Lib", "site-packages", "x.py"))
    assert _is_build_artefact(("__pycache__", "x.py"))
    for parts in (("seedsmith", "site_packages.py"),
                  ("seedsmith", "venv_rules.py"),
                  ("seedsmith", "pipeline", "site-packages.py"),
                  ("scripts", "reemit-colliding-item-names.py")):
        assert not _is_build_artefact(parts), f"FAIL-BEFORE: {parts[0]!r} is source and must be inventoried"
