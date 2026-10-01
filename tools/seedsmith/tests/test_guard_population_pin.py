"""Tests for gk-core/scripts/guard-population-pin.py (solid-enforcement `population-pin`,
spec-population-pin.md) -- P1-P3, against a disposable fixture tree (never the real 178-site
backlog, which is SE3.2-SE3.5's own dispositioned work).

The checker lives in scripts/, not the seedsmith package, so it is loaded by file path, the same
pattern test_guard_vocabulary_mirror.py already uses.
"""
from __future__ import annotations

import importlib.util
import shutil
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

CHECKER_PATH = _owned("scripts/guard-population-pin.py")

_spec = importlib.util.spec_from_file_location("guard_population_pin", CHECKER_PATH)
assert _spec is not None and _spec.loader is not None
gpp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gpp)


class PopulationPinFixture:
    """A disposable `tests/` tree plus a real `src/` symbol and a real `gk-core/data/tuning/` file, so P3's
    own owner/immutable-path resolution has something genuine to find."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="fusionrpg-populationpin-"))
        (self.root / "tests").mkdir()
        src_dir = self.root / "src"
        src_dir.mkdir()
        (src_dir / "RealOwner.cs").write_text("public enum RealOwner { A, B, C }\n", encoding="utf-8")
        tuning_dir = self.root / "data" / "tuning"
        tuning_dir.mkdir(parents=True)
        (tuning_dir / "widget.v1.json").write_text("{}", encoding="utf-8")

    def write_test(self, relpath: str, content: str) -> Path:
        path = self.root / "tests" / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def scan(self):
        return gpp.scan(repo_root=self.root, scan_roots=("tests",))

    def close(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


class GuardPopulationPinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = PopulationPinFixture()

    def tearDown(self) -> None:
        self.fx.close()

    def test_P1_an_unmarked_large_pin_in_a_content_reading_test_fails(self) -> None:
        self.fx.write_test("Foo.cs", """
using Xunit;
public class Foo {
    void T() {
        var repoRoot = FindRepoRoot();
        var species = Load(repoRoot + "/data/seed/creatures");
        Assert.Equal(904, species.Count);
    }
}
""")
        findings = self.fx.scan()
        self.assertEqual(len(findings["P1"]), 1)
        self.assertIn("904", findings["P1"][0][2])

    def test_P1_the_same_line_in_a_pure_fixture_test_passes(self) -> None:
        # No content-reading signal anywhere in the file -- out of scope entirely.
        self.fx.write_test("Bar.cs", """
using Xunit;
public class Bar {
    void T() {
        var species = new List<int>();
        Assert.Equal(904, species.Count);
    }
}
""")
        findings = self.fx.scan()
        self.assertEqual(findings["P1"], [])

    def test_P1_a_literal_below_minLiteral_never_fires(self) -> None:
        self.fx.write_test("Small.cs", """
using Xunit;
public class Small {
    void T() {
        var repoRoot = FindRepoRoot();
        Assert.Equal(6, resources.Count);
    }
}
""")
        findings = self.fx.scan()
        self.assertEqual(findings["P1"], [])

    def test_P1_a_marked_pin_passes(self) -> None:
        self.fx.write_test("Marked.cs", """
using Xunit;
public class Marked {
    void T() {
        var repoRoot = FindRepoRoot();
        // pin: closed-vocabulary RealOwner -- a new member is a reviewed change
        Assert.Equal(268, RealOwner.AllRegistered.Count);
    }
}
""")
        findings = self.fx.scan()
        self.assertEqual(findings["P1"], [])
        self.assertEqual(findings["P3"], [])

    def test_P1_python_len_and_count_shapes_both_argument_orders(self) -> None:
        # The example counts are interpolated, not typed as literals in THIS file's own source
        # (population-pin SE3.5, 2026-09-20): a bare `904`/`775` here would make the real repo-wide
        # scan flag its own falsifier as an unmarked site -- exactly the false positive `pin:` markers
        # cannot fix without breaking what this test proves (that UNMARKED code IS caught).
        species_count, catalog_count = 904, 775
        self.fx.write_test("test_py_shapes.py", f'''
import unittest

class T(unittest.TestCase):
    def test_a(self):
        repo_root = find_repo_root()
        self.assertEqual(len(species), {species_count})

    def test_b(self):
        repo_root = find_repo_root()
        self.assertEqual({species_count}, len(species))

    def test_c(self):
        repo_root = find_repo_root()
        self.assertEqual(catalog.count, {catalog_count})
''')
        findings = self.fx.scan()
        self.assertEqual(len(findings["P1"]), 3)

    def test_P2_a_second_site_pinning_the_same_owner_fails(self) -> None:
        self.fx.write_test("First.cs", """
using Xunit;
public class First {
    void T() {
        var repoRoot = FindRepoRoot();
        // pin: closed-vocabulary RealOwner
        Assert.Equal(268, RealOwner.AllRegistered.Count);
    }
}
""")
        self.fx.write_test("Second.cs", """
using Xunit;
public class Second {
    void T() {
        var repoRoot = FindRepoRoot();
        // pin: closed-vocabulary RealOwner
        Assert.Equal(268, RealOwner.AllRegistered.Count);
    }
}
""")
        findings = self.fx.scan()
        self.assertEqual(len(findings["P2"]), 1)
        self.assertIn("RealOwner", findings["P2"][0][2])

    def test_P3_a_closed_vocabulary_marker_naming_a_nonexistent_owner_fails(self) -> None:
        self.fx.write_test("Bogus.cs", """
using Xunit;
public class Bogus {
    void T() {
        var repoRoot = FindRepoRoot();
        // pin: closed-vocabulary TotallyInventedOwnerXyz
        Assert.Equal(42, TotallyInventedOwnerXyz.All.Count);
    }
}
""")
        findings = self.fx.scan()
        self.assertEqual(len(findings["P3"]), 1)
        self.assertIn("TotallyInventedOwnerXyz", findings["P3"][0][2])

    def test_P3_an_immutable_marker_with_no_version_fails(self) -> None:
        self.fx.write_test("NoVersion.cs", """
using Xunit;
public class NoVersion {
    void T() {
        var repoRoot = FindRepoRoot();
        // pin: immutable data/tuning/widget.json
        Assert.Equal(42, widget.Edges.Count);
    }
}
""")
        findings = self.fx.scan()
        self.assertEqual(len(findings["P3"]), 1)

    def test_P3_an_immutable_marker_naming_a_file_that_does_not_exist_fails(self) -> None:
        self.fx.write_test("Missing.cs", """
using Xunit;
public class Missing {
    void T() {
        var repoRoot = FindRepoRoot();
        // pin: immutable data/tuning/nosuchdomain.v1.json
        Assert.Equal(42, doc.Edges.Count);
    }
}
""")
        findings = self.fx.scan()
        self.assertEqual(len(findings["P3"]), 1)

    def test_P3_a_real_immutable_marker_passes(self) -> None:
        self.fx.write_test("RealImmutable.cs", """
using Xunit;
public class RealImmutable {
    void T() {
        var repoRoot = FindRepoRoot();
        // pin: immutable data/tuning/widget.v1.json
        Assert.Equal(42, doc.Edges.Count);
    }
}
""")
        findings = self.fx.scan()
        self.assertEqual(findings["P3"], [])


class RealTreeTests(unittest.TestCase):
    """The real guard against the real repo -- proves it runs cleanly (never crashes) and, now that
    SE3.2-SE3.5 have dispositioned every P1-P3 finding, that the backlog is closed for good. The
    zero here is a GATING invariant this test protects (SE3.6 registers the guard as `gating`), not
    a population reading -- a future unmarked/mismarked site is a real regression, not content
    growth, so asserting 0 is the correct contract, never the mistake this module forbids."""

    def test_the_real_scan_runs_clean_and_the_backlog_stays_closed(self) -> None:
        findings = gpp.scan()
        total = sum(len(v) for v in findings.values())
        self.assertEqual(total, 0, "population-pin backlog regressed -- SE3.2-SE3.5 closed it to zero")

    def test_P1_backlog_stays_empty(self) -> None:
        # SE3.2-SE3.5 dispositioned every real site (marker at the owner, equality with the owner, or
        # a contract rewrite). A future P1 finding means new unmarked/mismarked code landed, not that
        # the sweep is still running -- so this asserts the closed state, not a population reading.
        findings = gpp.scan()
        self.assertEqual(len(findings["P1"]), 0, "a new unmarked site landed -- disposition it, never re-widen this test")


if __name__ == "__main__":
    unittest.main()
