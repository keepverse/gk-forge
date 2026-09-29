"""Tests for gk-core/scripts/guard-vocabulary-mirror.py (solid-enforcement `vocabulary-mirror`,
spec-vocabulary-mirror.md) -- V1-V4, plus the real manifest against the real tree.

The checker lives in scripts/, not inside the seedsmith package, so it is loaded by file path
(the hyphenated filename is not a valid Python module name for a normal import). Falsifiers use
in-memory C# enum text (extract_enum_members takes a plain string) and a REAL, disposable Python
module written under a temp directory added to sys.path (check_pair's own mirror resolution imports
a real module by name -- the same "prove the shipped tool, not a copy of its intent" discipline this
repo's C# guard tests already use for their own fixtures).
"""
from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
CHECKER_PATH = REPO_ROOT / "scripts" / "guard-vocabulary-mirror.py"

_spec = importlib.util.spec_from_file_location("guard_vocabulary_mirror", CHECKER_PATH)
assert _spec is not None and _spec.loader is not None
gvm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gvm)


class ExtractEnumMembersTests(unittest.TestCase):
    """In-memory C# text -- no file, no import, the narrowest possible unit."""

    def test_a_simple_enum_parses(self):
        text = "public enum Foo { A = 0, B, C }"
        self.assertEqual(gvm.extract_enum_members(text, "Foo"), ["A", "B", "C"])

    def test_comments_and_a_trailing_comma_are_ignored(self):
        text = textwrap.dedent("""
            /// <summary>doc</summary>
            public enum Foo
            {
                A = 0, // first
                /* block */ B,
                C,
            }
        """)
        self.assertEqual(gvm.extract_enum_members(text, "Foo"), ["A", "B", "C"])

    def test_a_missing_enum_raises_never_returns_empty(self):
        with self.assertRaises(gvm.VocabularyMirrorError):
            gvm.extract_enum_members("public enum Bar { X }", "Foo")

    def test_an_unparseable_member_token_raises(self):
        # A member that is not a plain identifier (e.g. leftover syntax the parser was never shown)
        # must fail loudly, never silently drop the token.
        with self.assertRaises(gvm.VocabularyMirrorError):
            gvm.extract_enum_members("public enum Foo { A, [Obsolete] B }", "Foo")


class ResolveJsonCatalogOwnerTests(unittest.TestCase):
    def test_array_field_path_resolves(self):
        doc = {"entries": [{"id": "a"}, {"id": "b"}]}
        self.assertEqual(gvm.resolve_json_catalog_owner(doc, "entries[].id"), ["a", "b"])

    def test_an_unsupported_path_shape_raises(self):
        with self.assertRaises(gvm.VocabularyMirrorError):
            gvm.resolve_json_catalog_owner({"entries": []}, "entries.id")


class ResolveLatestVersionedPathTests(unittest.TestCase):
    def test_picks_the_highest_version_regardless_of_the_manifest_text(self):
        with _TempDir() as tmp:
            (tmp / "sub").mkdir()
            (tmp / "sub" / "d.v1.json").write_text("{}", encoding="utf-8")
            (tmp / "sub" / "d.v2.json").write_text("{}", encoding="utf-8")
            (tmp / "sub" / "d.v10.json").write_text("{}", encoding="utf-8")
            # The manifest text names v1; the resolved file must be v10 (numeric-highest), never the
            # lexically-highest ("v2" would sort above "v10" as plain strings) and never v1 itself.
            resolved = gvm.resolve_latest_versioned_path(tmp, str(Path("sub") / "d.v1.json"))
            self.assertEqual(resolved.name, "d.v10.json")

    def test_a_non_versioned_hint_is_used_literally(self):
        with _TempDir() as tmp:
            (tmp / "plain.json").write_text("{}", encoding="utf-8")
            resolved = gvm.resolve_latest_versioned_path(tmp, "plain.json")
            self.assertEqual(resolved, tmp / "plain.json")


class _TempDir:
    def __enter__(self):
        import tempfile
        self._dir = tempfile.mkdtemp(prefix="fusionrpg-vocabmirror-")
        return Path(self._dir)

    def __exit__(self, *exc):
        import shutil
        shutil.rmtree(self._dir, ignore_errors=True)


def _write_mirror_module(root: Path, module_name: str, source: str) -> None:
    (root / (module_name + ".py")).write_text(source, encoding="utf-8")


def _pair(owner: dict, mirror: dict, transform: str, relation: str, excludes=None) -> dict:
    return {
        "id": "test-pair", "owner": owner, "mirror": mirror, "transform": transform,
        "relation": relation, "excludes": excludes or [],
    }


class CheckPairTests(unittest.TestCase):
    """Each test builds a real, disposable owner .cs file and mirror .py module under a temp root,
    then calls check_pair the same way the real guard does -- never a hand-rolled shortcut."""

    def setUp(self):
        import tempfile
        self.root = Path(tempfile.mkdtemp(prefix="fusionrpg-vocabmirror-"))
        self._prior_sys_path = list(sys.path)
        sys.path.insert(0, str(self.root))

    def tearDown(self):
        import shutil
        sys.path[:] = self._prior_sys_path
        for name in list(sys.modules):
            if name.startswith("_vm_fixture"):
                del sys.modules[name]
        shutil.rmtree(self.root, ignore_errors=True)

    def _write_owner_enum(self, relpath: str, csharp: str) -> dict:
        path = self.root / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(csharp, encoding="utf-8")
        return {"kind": "csharp-enum", "file": relpath, "enum": "Foo"}

    def _write_mirror(self, module_name: str, py_symbol_line: str) -> dict:
        _write_mirror_module(self.root, module_name, py_symbol_line)
        return {"module": module_name, "symbol": "VALUES"}

    def test_V1_mirror_invents_a_member(self):
        owner = self._write_owner_enum("Foo.cs", "public enum Foo { A, B }")
        mirror = self._write_mirror("_vm_fixture_v1", 'VALUES = {"a", "b", "c"}')
        findings = gvm.check_pair(self.root, _pair(owner, mirror, "lowerFirst", "equal"))
        self.assertEqual(len(findings), 1)
        self.assertIn("V1", findings[0])
        self.assertIn("'c'", findings[0])

    def test_V2_equal_with_an_absent_owner_member(self):
        # The construct incident, reproduced: the owner gains a member the mirror never learns about.
        owner = self._write_owner_enum("Foo.cs", "public enum Foo { A, B, C }")
        mirror = self._write_mirror("_vm_fixture_v2", 'VALUES = {"a", "b"}')
        findings = gvm.check_pair(self.root, _pair(owner, mirror, "lowerFirst", "equal"))
        self.assertEqual(len(findings), 1)
        self.assertIn("V2", findings[0])
        self.assertIn("'c'", findings[0])

    def test_V3_subset_with_an_unexcused_gap(self):
        owner = self._write_owner_enum("Foo.cs", "public enum Foo { A, B, C }")
        mirror = self._write_mirror("_vm_fixture_v3a", 'VALUES = {"a", "b"}')
        findings = gvm.check_pair(self.root, _pair(owner, mirror, "lowerFirst", "subset", excludes=[]))
        self.assertEqual(len(findings), 1)
        self.assertIn("V3", findings[0])

    def test_V3_subset_with_an_excused_gap_passes(self):
        owner = self._write_owner_enum("Foo.cs", "public enum Foo { A, B, C }")
        mirror = self._write_mirror("_vm_fixture_v3b", 'VALUES = {"a", "b"}')
        findings = gvm.check_pair(self.root, _pair(
            owner, mirror, "lowerFirst", "subset",
            excludes=[{"member": "c", "reason": "actions never apply this status, per vocab.py's own comment"}]))
        self.assertEqual(findings, [])

    def test_V3_an_excludes_entry_with_an_empty_reason_fails(self):
        owner = self._write_owner_enum("Foo.cs", "public enum Foo { A, B, C }")
        mirror = self._write_mirror("_vm_fixture_v3c", 'VALUES = {"a", "b"}')
        findings = gvm.check_pair(self.root, _pair(
            owner, mirror, "lowerFirst", "subset", excludes=[{"member": "c", "reason": ""}]))
        self.assertEqual(len(findings), 1)
        self.assertIn("V3", findings[0])
        self.assertIn("empty reason", findings[0])

    def test_V4_a_renamed_enum_fails(self):
        owner = self._write_owner_enum("Foo.cs", "public enum Bar { A }")  # manifest still says "Foo"
        mirror = self._write_mirror("_vm_fixture_v4a", 'VALUES = {"a"}')
        findings = gvm.check_pair(self.root, _pair(owner, mirror, "lowerFirst", "equal"))
        self.assertEqual(len(findings), 1)
        self.assertIn("V4", findings[0])

    def test_V4_an_unparseable_enum_fails_loudly_never_passes(self):
        owner = self._write_owner_enum("Foo.cs", "public enum Foo { A, [Obsolete] B }")
        mirror = self._write_mirror("_vm_fixture_v4b", 'VALUES = {"a"}')
        findings = gvm.check_pair(self.root, _pair(owner, mirror, "lowerFirst", "equal"))
        self.assertEqual(len(findings), 1)
        self.assertIn("V4", findings[0])

    def test_a_clean_pair_produces_no_findings(self):
        owner = self._write_owner_enum("Foo.cs", "public enum Foo { A, B, RolledThing }")
        mirror = self._write_mirror("_vm_fixture_clean", 'VALUES = {"a", "b", "rolledThing"}')
        findings = gvm.check_pair(self.root, _pair(owner, mirror, "lowerFirst", "equal"))
        self.assertEqual(findings, [])

    def test_json_catalog_owner_resolves_the_highest_version_on_disk(self):
        (self.root / "data" / "tuning").mkdir(parents=True)
        (self.root / "data" / "tuning" / "d.v1.json").write_text(
            json.dumps({"entries": [{"id": "a"}]}), encoding="utf-8")
        (self.root / "data" / "tuning" / "d.v2.json").write_text(
            json.dumps({"entries": [{"id": "a"}, {"id": "b"}]}), encoding="utf-8")
        owner = {"kind": "json-catalog", "file": "data/tuning/d.v1.json", "path": "entries[].id"}
        mirror = self._write_mirror("_vm_fixture_jsoncat", 'VALUES = {"a", "b"}')
        # If v1 (the manifest's own literal text) were used, "b" would be a V1 false positive.
        findings = gvm.check_pair(self.root, _pair(owner, mirror, "identity", "equal"))
        self.assertEqual(findings, [])


class RealTreeTests(unittest.TestCase):
    """The real manifest against the real repo -- proves the checker on the shipped tree, not a
    fixture. SE2.7 resolved the one known backlog finding (STATUSES 21 vs 24 -- vocab.py's own
    comment named no deliberate `nerve.*` exclusion, so the gap was drift, not a design choice; the
    mirror gained the three ids), so the real tree is now expected fully clean -- this is the guard's
    own gate-flip test, `vocabulary-mirror` moved backlog -> gating in the same commit."""

    def test_the_real_manifest_is_fully_clean(self):
        manifest = json.loads((REPO_ROOT / "scripts" / "vocabulary-mirrors.v1.json").read_text(encoding="utf-8"))
        all_findings = []
        for pair in manifest["pairs"]:
            all_findings.extend(gvm.check_pair(REPO_ROOT, pair))
        self.assertEqual(all_findings, [])


if __name__ == "__main__":
    unittest.main()
