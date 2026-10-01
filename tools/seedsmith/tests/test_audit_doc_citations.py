"""Tests for scripts/audit-doc-citations.py (solid-enforcement `doc-citation-gate`,
spec-doc-citation-gate.md) -- D1-D4 and the seven exemptions, against a disposable fixture git
repository (never the real ~1600-document tree, whose backlog is SE3.8-SE3.12's own dispositioned
work).

The checker lives in scripts/, not the seedsmith package, so it is loaded by file path, the same
pattern test_guard_population_pin.py already uses. It also shells out to `git ls-files`/`git log`
against the process's current working directory, so each fixture is a REAL, disposable git
repository (git init + commit), and every scan chdir's into it and back.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from seedsmith.workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

CHECKER_PATH = _owned("scripts/audit-doc-citations.py")

_spec = importlib.util.spec_from_file_location("audit_doc_citations", CHECKER_PATH)
assert _spec is not None and _spec.loader is not None
adc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(adc)


class DocCitationFixture:
    """A disposable git repository under `docs/` and `src/`, so D1's "does this file exist" and
    D3's "how many files share this basename" have something real to check against, and D4's
    ideal/map pair has real files at the paths the check expects."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="fusionrpg-doccitations-"))
        self._git("init", "-q")
        self._git("config", "user.email", "fixture@example.invalid")
        self._git("config", "user.name", "fixture")
        (self.root / "src").mkdir()
        (self.root / "docs" / "architecture").mkdir(parents=True)

    def _git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True,
                               check=True).stdout

    def write(self, relpath: str, content: str) -> Path:
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def commit(self, message: str = "fixture commit") -> None:
        self._git("add", "-A")
        self._git("commit", "-q", "-m", message)

    def scan(self, scope: str = "docs/"):
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            findings, checked, doc_count = adc.audit(scope)
        finally:
            os.chdir(cwd)
        return findings, checked, doc_count

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def _by_code(findings, code):
    return [f for f in findings if f["code"] == code]


class D1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = DocCitationFixture()

    def tearDown(self) -> None:
        self.fx.close()

    def test_a_dead_file_fails_d1(self) -> None:
        self.fx.write("docs/architecture/spec-x.md",
                       "See `src/NeverExisted.cs:10` for the real logic.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        hits = _by_code(findings, "D1")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["sev"], "HIGH")

    def test_the_same_line_under_a_citations_historical_marker_passes(self) -> None:
        self.fx.write("docs/architecture/spec-x.md",
                       "<!-- citations-historical: NeverExisted.cs was fused into Real.cs -->\n"
                       "See `src/NeverExisted.cs:10` for the real logic.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        self.assertEqual(_by_code(findings, "D1"), [])

    def test_the_same_line_whose_text_says_deleted_passes(self) -> None:
        self.fx.write("docs/architecture/spec-x.md",
                       "`src/NeverExisted.cs:10` was deleted; the logic moved to Real.cs.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        self.assertEqual(_by_code(findings, "D1"), [])

    def test_a_real_file_resolves_clean(self) -> None:
        self.fx.write("src/Real.cs", "public class Real {}\n")
        self.fx.write("docs/architecture/spec-x.md", "See `src/Real.cs:1`.\n")
        self.fx.commit()
        findings, checked, _ = self.fx.scan()
        self.assertEqual(_by_code(findings, "D1"), [])
        self.assertEqual(checked, 1)


class D2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = DocCitationFixture()

    def tearDown(self) -> None:
        self.fx.close()

    def test_a_line_past_eof_fails_d2(self) -> None:
        self.fx.write("src/Real.cs", "line one\nline two\n")
        self.fx.write("docs/architecture/spec-x.md", "See `src/Real.cs:50`.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        hits = _by_code(findings, "D2")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["sev"], "HIGH")

    def test_a_line_inside_the_file_passes(self) -> None:
        self.fx.write("src/Real.cs", "line one\nline two\nline three\n")
        self.fx.write("docs/architecture/spec-x.md", "See `src/Real.cs:2`.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        self.assertEqual(_by_code(findings, "D2"), [])

    def test_a_line_past_eof_marked_deleted_passes(self) -> None:
        self.fx.write("src/Real.cs", "line one\n")
        self.fx.write("docs/architecture/spec-x.md",
                       "`src/Real.cs:50` no longer exists at that line; the method was removed.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        self.assertEqual(_by_code(findings, "D2"), [])


class D3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = DocCitationFixture()

    def tearDown(self) -> None:
        self.fx.close()

    def test_a_bare_ambiguous_basename_fails_d3_outside_research(self) -> None:
        self.fx.write("src/one/Program.cs", "line one\nline two\n")
        self.fx.write("src/two/Program.cs", "line one\nline two\n")
        self.fx.write("docs/architecture/spec-x.md", "See `Program.cs:10`.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        hits = _by_code(findings, "D3")
        self.assertEqual(len(hits), 1)
        # Promoted (spec-doc-citation-gate.md): HIGH outside docs/research/ and prior art.
        self.assertEqual(hits[0]["sev"], "HIGH")

    def test_the_same_ambiguous_basename_stays_low_under_docs_research(self) -> None:
        self.fx.write("src/one/Program.cs", "line one\nline two\n")
        self.fx.write("src/two/Program.cs", "line one\nline two\n")
        self.fx.write("docs/research/prior-art.md", "See `Program.cs:10`.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan(scope="docs/")
        hits = _by_code(findings, "D3")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["sev"], "LOW")

    def test_an_unambiguous_path_qualified_citation_passes(self) -> None:
        self.fx.write("src/one/Program.cs", "line one\nline two\n")
        self.fx.write("src/two/Program.cs", "line one\nline two\n")
        self.fx.write("docs/architecture/spec-x.md", "See `src/one/Program.cs:1`.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        self.assertEqual(_by_code(findings, "D3"), [])


class D4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = DocCitationFixture()

    def tearDown(self) -> None:
        self.fx.close()

    MAP_APPROVED = "# Capability map: widget\n\n**Status: approved 2026-09-20.**\n"
    IDEAL_UNBUILT = ("# Widget -- the ideal\n\n"
                      "**Status:** idea phase. Not a spec. No build authorized.\n")
    IDEAL_UNBUILT_WITH_BANNER = (
        "# Widget -- the ideal\n\n"
        "> ### Status line vs. what shipped (checked 2026-09-20)\n"
        ">\n"
        "> This document's status line is stale; the map says approved.\n\n"
        "**Status:** idea phase. Not a spec. No build authorized.\n")

    def test_ideal_plus_approved_map_without_the_banner_fails_d4(self) -> None:
        self.fx.write("docs/architecture/widget-map.md", self.MAP_APPROVED)
        self.fx.write("docs/architecture/widget-ideal.md", self.IDEAL_UNBUILT)
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        hits = _by_code(findings, "D4")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["sev"], "HIGH")
        self.assertEqual(hits[0]["doc"], "docs/architecture/widget-ideal.md")

    def test_ideal_plus_approved_map_with_the_banner_passes(self) -> None:
        self.fx.write("docs/architecture/widget-map.md", self.MAP_APPROVED)
        self.fx.write("docs/architecture/widget-ideal.md", self.IDEAL_UNBUILT_WITH_BANNER)
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        self.assertEqual(_by_code(findings, "D4"), [])

    def test_a_map_that_is_not_yet_approved_never_fires_d4(self) -> None:
        self.fx.write("docs/architecture/widget-map.md",
                       "# Capability map: widget\n\n**Status: proposed 2026-09-20, pending owner approval.**\n")
        self.fx.write("docs/architecture/widget-ideal.md", self.IDEAL_UNBUILT)
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        self.assertEqual(_by_code(findings, "D4"), [])

    def test_an_ideal_with_no_corresponding_map_never_fires_d4(self) -> None:
        self.fx.write("docs/architecture/widget-ideal.md", self.IDEAL_UNBUILT)
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        self.assertEqual(_by_code(findings, "D4"), [])


class ExemptionTests(unittest.TestCase):
    """The remaining exemptions the citation loop itself carries (basenames, prior-art scope,
    forward-looking proposals, the (new) marker, and an unpublished next tuning version)."""

    def setUp(self) -> None:
        self.fx = DocCitationFixture()

    def tearDown(self) -> None:
        self.fx.close()

    def test_an_exempt_basename_never_fires_d1(self) -> None:
        self.fx.write("docs/architecture/spec-x.md", "See `AGENTS.md:1`.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        self.assertEqual(_by_code(findings, "D1"), [])

    def test_a_missing_file_under_docs_research_is_low(self) -> None:
        self.fx.write("docs/research/prior-art.md", "See `mob_db.yml:1` from another project.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        hits = _by_code(findings, "D1")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["sev"], "LOW")

    def test_a_forward_looking_doc_naming_a_new_file_with_no_line_is_low(self) -> None:
        self.fx.write("docs/architecture/widget-plan.md",
                       "Will add `src/NotYetWritten.cs` for the new feature.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        hits = _by_code(findings, "D1")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["sev"], "LOW")

    def test_a_forward_looking_doc_naming_a_file_git_history_shows_deleted_is_high(self) -> None:
        self.fx.write("src/OnceReal.cs", "x\n")
        self.fx.commit("add OnceReal.cs")
        (self.fx.root / "src" / "OnceReal.cs").unlink()
        self.fx.write("docs/architecture/widget-plan.md",
                       "Will add `src/OnceReal.cs` for the new feature.\n")
        self.fx.commit("delete OnceReal.cs, add the plan")
        findings, _, _ = self.fx.scan()
        hits = _by_code(findings, "D1")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["sev"], "HIGH")

    def test_an_ideal_doc_needs_the_new_marker_not_just_forward_looking_status(self) -> None:
        self.fx.write("docs/architecture/widget-ideal.md",
                       "Will use `src/NotYetWritten.cs` for the new feature.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        hits = _by_code(findings, "D1")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["sev"], "HIGH")

    def test_an_ideal_doc_with_the_new_marker_is_low(self) -> None:
        self.fx.write("docs/architecture/widget-ideal.md",
                       "Will use `src/NotYetWritten.cs` (new) for the new feature.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        hits = _by_code(findings, "D1")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["sev"], "LOW")

    def test_an_unpublished_next_tuning_version_is_exempt(self) -> None:
        self.fx.write("data/tuning/widget.v1.json", "{}")
        self.fx.write("docs/architecture/spec-x.md", "Publish `data/tuning/widget.v2.json` next.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        self.assertEqual(_by_code(findings, "D1"), [])

    def test_a_prior_art_heading_exempts_the_section_below_it(self) -> None:
        self.fx.write("docs/architecture/widget-ideal.md",
                       "# Widget ideal\n\n## Prior art\n\nSee `mob_db.yml:1`.\n")
        self.fx.commit()
        findings, _, _ = self.fx.scan()
        hits = _by_code(findings, "D1")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["sev"], "LOW")


class RealTreeTests(unittest.TestCase):
    """The real audit against the real repo -- proves it runs cleanly (never crashes). The backlog
    size is SE3.8-SE3.12's own dispositioned work, so it is measured, never asserted here.

    The checker shells out to `git ls-files`/`git log` against the PROCESS's cwd, and the
    verification boundary runs this suite from `gk-forge/tools/seedsmith` (a repo subdirectory with no `docs/`
    of its own), so the scan chdir's to the repo root the way `DocCitationFixture.scan` already does.
    Without it the SAME file passes from the repo root and reports `doc_count == 0` from the
    boundary's cwd -- an outcome that describes the caller, not the tree (species-gear-chain T55
    item 4, re-measured 2026-09-22: 0 not greater than 0 from `gk-forge/tools/seedsmith`, 1 passed from the
    repo root).
    """

    def test_the_real_scan_runs_and_produces_a_report(self) -> None:
        # NOT REPO_ROOT. This file lives in gk-forge because that is where the seedsmith suite lives, so
        # REPO_ROOT is gk-forge -- and gk-forge has NO docs/ directory. The documents are gk-workflow's.
        # Measured: gk-forge/docs does not exist, workspace/docs has 24 entries, and this assertion was
        # failing on its own precondition because the scan enumerated zero documents.
        #
        # The anchor is the repository carrying the AUDIT, derived from CHECKER_PATH -- already resolved
        # through `owning_base` for a FILE. Deliberately not `owning_base("docs")`: `docs` is a directory
        # present in more than one repository (gk-core has one entry, gk-workflow 24), so nearest-match-wins
        # returns gk-core and the scan would still find almost nothing. Resolve per FILE, never per
        # directory.
        docs_root = CHECKER_PATH.parent.parent
        self.assertTrue((docs_root / "docs").is_dir(),
                        f"the repository carrying the audit ({docs_root}) has no docs/ directory, so this "
                        f"test has no tree to scan and its assertions would prove nothing")
        cwd = os.getcwd()
        os.chdir(docs_root)
        try:
            findings, checked, doc_count = adc.audit("docs/")
        finally:
            os.chdir(cwd)
        self.assertGreater(doc_count, 0)
        self.assertGreater(checked, 0)
        self.assertIsInstance(findings, list)


if __name__ == "__main__":
    unittest.main()
