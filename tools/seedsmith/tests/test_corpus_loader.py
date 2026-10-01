"""Tests for the corpus-loader load algorithm (spec-corpus-loader.md §3/§5, module A-C1):
`seedsmith.adapters.actions.load.load_committed`.

    python -m pytest gk-forge/tools/seedsmith/tests/test_corpus_loader.py -v

Synthetic fixtures for the tree shape (manifest, envelopes, prefixes), same discipline as
`test_corpus.py` — a throwaway temp directory per test, never the live corpus for the SHAPE of the
tree. The three closed vocabularies this module reads fresh from data rather than transcribing
(`atomFamilies`, `pairedPayoffFamily`, family-scoped `scopeKey` — `vocab.py`'s `load_family_ids` /
`load_pairing_keys` / `load_family_map_keys`) are hard-wired to the REAL repo paths, so entries in
these fixtures use real, live ids for the "valid" cases (`atom.searing-strike` / `atom.volley` from
`gk-data/packs/fusion/data/seed/items/affix-families/g-on-hit.json` — the same two ids the spec's own envelope example
uses; `atom.chill-punisher` / `atom.rot-punisher` from the live `pairings.json`; `cherry` from the
live `family-map.json`) and the spec's own planted-violation examples for the "invalid" cases
(`"economy"`, `"marigold"`, `"rot"`).
"""
from __future__ import annotations

import hashlib
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.actions.load import load_committed  # noqa: E402
from seedsmith.corpus import CorpusLoadError  # noqa: E402

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

LIVE_ACTIONS_ROOT = _owned("data/seed/actions")

# Real, live ids — see module docstring for why these specific ones.
REAL_FAMILY_A = "atom.searing-strike"
REAL_FAMILY_B = "atom.volley"
REAL_PAYOFF_FAMILY = "atom.rot-punisher"
REAL_ENABLED_FAMILY = "atom.chill-punisher"
REAL_FAMILY_MAP_KEY = "cherry"

FULL_DISPOSITION_MANIFEST = {
    "schemaVersion": 1,
    "kind": "action-config",
    "entries": [
        {"id": "pairings.json", "type": "config-file", "reason": "root parser, cannot wrap"},
        {"id": "name-templates.json", "type": "config-file", "reason": "root parser, cannot wrap"},
        {"id": "_rounds/", "type": "prefix", "disposition": "exclude", "reason": "shares action.* grammar"},
        {"id": "_generated/", "type": "prefix", "disposition": "load", "reason": "pool./lean./weights."},
        {"id": "_briefs/", "type": "prefix", "disposition": "load", "reason": "brief."},
        {"id": "_reports/", "type": "prefix", "disposition": "load", "reason": "cell./target."},
    ],
}


def _write(root: Path, rel_path: str, doc: dict) -> None:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _write_manifest(root: Path, manifest: dict = FULL_DISPOSITION_MANIFEST) -> None:
    _write(root, "_manifest.json", manifest)


def _valid_action_seed(entry_id: str, **overrides) -> dict:
    row = {
        "id": entry_id,
        "scope": "general",
        "category": "attack",
        "rungBand": [1, 10],
        "targetMode": "single",
        "relation": "enemy",
        "atomFamilies": [REAL_FAMILY_A, REAL_FAMILY_B],
        "pairingRole": "none",
    }
    row.update(overrides)
    return row


def _corpus_hash(corpus) -> str:
    canon = sorted((e.id, e.kind, json.dumps(e.data, sort_keys=True)) for e in corpus.entries.values())
    return hashlib.sha256(json.dumps(canon, sort_keys=True).encode("utf-8")).hexdigest()


class DeterminismTests(unittest.TestCase):
    """Testing table row 1 + acceptance #7."""

    def test_two_loads_over_an_unchanged_tree_are_byte_identical_by_hash(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        _write(root, "widgets.json", {
            "schemaVersion": 1, "kind": "action-seed", "_meta": {"partition": "general"},
            "entries": [_valid_action_seed("action.general.0001"),
                       _valid_action_seed("action.general.0002")],
        })

        first = load_committed(root)
        second = load_committed(root)

        self.assertEqual(_corpus_hash(first.corpus), _corpus_hash(second.corpus))
        self.assertEqual([e.id for e in first.corpus.entries.values()],
                         [e.id for e in second.corpus.entries.values()])
        self.assertEqual(len(first.findings), 0)


class RoundTripTests(unittest.TestCase):
    """Checkpoint 1 + acceptance #1."""

    def test_a_written_action_seed_file_loads_back_with_the_same_entry(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        row = _valid_action_seed(
            "action.species.cherrybomb.001", scope="species", scopeKey="cherrybomb",
            name="Searing Volley", tags=["offensive"], kindHint="skill",
            pairingRole="enabler", pairedPayoffFamily=REAL_PAYOFF_FAMILY,
        )
        _write(root, "species/cherrybomb.json", {
            "schemaVersion": 1, "kind": "action-seed",
            "_meta": {"partition": "species/cherrybomb", "generator": "action-corpus/dedup-select", "round": 1},
            "entries": [row],
        })

        result = load_committed(root)

        self.assertEqual([e.kind for e in result.corpus.by_kind("action-seed")], ["action-seed"])
        loaded = result.corpus.by_id("action.species.cherrybomb.001")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.data, row)
        self.assertEqual(loaded.partition, "species/cherrybomb")
        self.assertEqual([f for f in result.findings if f.entry_id == loaded.id], [])


class LostEnvelopeTests(unittest.TestCase):
    """Testing table row 3."""

    def test_entries_with_no_kind_and_not_declared_is_an_undeclared_finding(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        _write(root, "species/broken.json", {"entries": [_valid_action_seed("action.species.foo.001")]})

        result = load_committed(root)

        self.assertEqual(len(result.corpus.entries), 0)  # never silently loaded either
        undeclared = [f for f in result.findings if f.code == "undeclared"]
        self.assertEqual(len(undeclared), 1)
        self.assertIn("species/broken.json", undeclared[0].path)


class DuplicateIdTests(unittest.TestCase):
    """Testing table row 4 + acceptance #4."""

    def test_two_entries_sharing_an_id_in_different_files_raise_naming_both(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        _write(root, "a.json", {"schemaVersion": 1, "kind": "action-seed", "entries": [
            _valid_action_seed("action.general.0001")]})
        _write(root, "b.json", {"schemaVersion": 1, "kind": "action-seed", "entries": [
            _valid_action_seed("action.general.0001")]})

        with self.assertRaises(CorpusLoadError) as ctx:
            load_committed(root)
        message = str(ctx.exception)
        self.assertIn("action.general.0001", message)
        self.assertTrue("a.json" in message or "b.json" in message)


class UnknownEnumTests(unittest.TestCase):
    """Testing table row 5."""

    def test_unknown_category_is_refused_naming_field_and_value(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        _write(root, "a.json", {"schemaVersion": 1, "kind": "action-seed", "entries": [
            _valid_action_seed("action.general.0001", category="economy")]})

        result = load_committed(root)

        refused = [f for f in result.findings if f.code == "unknown-enum"]
        self.assertEqual(len(refused), 1)
        self.assertIn("category", refused[0].message)
        self.assertIn("economy", refused[0].message)


class WrongCasingTests(unittest.TestCase):
    """Testing table row 6 — the exact shape the spec's own pre-F10 example carried."""

    def test_pascal_case_target_mode_area_shape_relation_are_all_refused(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        _write(root, "a.json", {"schemaVersion": 1, "kind": "action-seed", "entries": [
            _valid_action_seed("action.general.0001", targetMode="Area", areaShape="Row",
                              relation="Enemy")]})

        result = load_committed(root)

        refused_fields = {f.message.split("field ")[1].split(" ")[0] for f in result.findings
                          if f.code == "unknown-enum"}
        self.assertEqual(refused_fields, {"'targetMode'", "'areaShape'", "'relation'"})


class UnknownFamilyTests(unittest.TestCase):
    """Testing table row 7 + acceptance #6e — the eleventh vocabulary."""

    def test_family_scoped_entry_with_unknown_scope_key_is_refused(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        _write(root, "family/marigold.json", {"schemaVersion": 1, "kind": "action-seed", "entries": [
            _valid_action_seed("action.family.marigold.001", scope="family", scopeKey="marigold")]})

        result = load_committed(root)

        refused = [f for f in result.findings if f.code == "unknown-family-scope-key"]
        self.assertEqual(len(refused), 1)
        self.assertIn("scopeKey", refused[0].message)
        self.assertIn("marigold", refused[0].message)

    def test_family_scoped_entry_with_a_real_family_key_is_not_refused(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        _write(root, "family/cherry.json", {"schemaVersion": 1, "kind": "action-seed", "entries": [
            _valid_action_seed("action.family.cherry.001", scope="family",
                              scopeKey=REAL_FAMILY_MAP_KEY)]})

        result = load_committed(root)

        self.assertEqual([f for f in result.findings if f.code == "unknown-family-scope-key"], [])

    def test_unknown_atom_family_is_refused(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        _write(root, "a.json", {"schemaVersion": 1, "kind": "action-seed", "entries": [
            _valid_action_seed("action.general.0001", atomFamilies=["atom.does-not-exist"])]})

        result = load_committed(root)

        refused = [f for f in result.findings if f.code == "unknown-family"]
        self.assertEqual(len(refused), 1)
        self.assertIn("atom.does-not-exist", refused[0].message)


class StatusInPairingFieldTests(unittest.TestCase):
    """Testing table row 9."""

    def test_a_bare_status_id_in_paired_payoff_family_is_refused(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        _write(root, "a.json", {"schemaVersion": 1, "kind": "action-seed", "entries": [
            _valid_action_seed("action.general.0001", pairingRole="enabler", pairedPayoffFamily="rot")]})

        result = load_committed(root)

        refused = [f for f in result.findings if f.code == "unknown-pairing-family"]
        self.assertEqual(len(refused), 1)
        self.assertIn("pairedPayoffFamily", refused[0].message)
        self.assertIn("'rot'", refused[0].message)

    def test_a_real_pairings_json_key_is_not_refused(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        _write(root, "a.json", {"schemaVersion": 1, "kind": "action-seed", "entries": [
            _valid_action_seed("action.general.0001", pairingRole="enabler",
                              pairedPayoffFamily=REAL_PAYOFF_FAMILY)]})

        result = load_committed(root)

        self.assertEqual([f for f in result.findings if f.code == "unknown-pairing-family"], [])


class PrefixDispositionTests(unittest.TestCase):
    """Testing table row 8 + acceptance #6d."""

    def test_a_fifth_undeclared_prefix_is_a_finding(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        _write(root, "_extra/x.json", {"schemaVersion": 1, "kind": "action-brief", "entries": [
            {"id": "brief.general.001"}]})

        result = load_committed(root)

        undeclared = [f for f in result.findings if f.code == "undeclared-prefix"]
        self.assertEqual(len(undeclared), 1)
        self.assertEqual(undeclared[0].path, "_extra/")

    def test_all_four_dispositions_declared_produces_no_prefix_finding(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        for prefix in ("_generated", "_briefs", "_reports"):
            (root / prefix).mkdir(parents=True, exist_ok=True)
        (root / "_rounds" / "round-1").mkdir(parents=True, exist_ok=True)

        result = load_committed(root)

        self.assertEqual([f for f in result.findings if f.code == "undeclared-prefix"], [])

    def test_a_briefs_entry_and_a_committed_action_seed_load_into_one_graph_with_the_edge_recorded(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        _write(root, "species/foo.json", {"schemaVersion": 1, "kind": "action-seed", "entries": [
            _valid_action_seed("action.species.foo.001", scope="species", scopeKey="foo")]})
        _write(root, "_briefs/foo.json", {"schemaVersion": 1, "kind": "action-brief", "entries": [
            {"id": "brief.species.foo.001",
             "avoidNeighbours": {"actionId": "action.species.foo.001"}},
        ]})

        result = load_committed(root)

        self.assertIsNotNone(result.corpus.by_id("brief.species.foo.001"))
        self.assertIsNotNone(result.corpus.by_id("action.species.foo.001"))
        pairs = {(e.from_id, e.to_id) for e in result.edges}
        self.assertIn(("brief.species.foo.001", "action.species.foo.001"), pairs)


class RoundIsolationTests(unittest.TestCase):
    """Testing table row 10 (F14) + acceptance #6c."""

    def test_a_round_survivor_and_its_promoted_twin_do_not_both_load(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        twin_id = "action.species.foo.001"
        _write(root, "_rounds/round-1/survivors.json", {
            "schemaVersion": 1, "kind": "action-seed", "entries": [_valid_action_seed(twin_id)]})
        _write(root, "species/foo.json", {
            "schemaVersion": 1, "kind": "action-seed", "entries": [_valid_action_seed(twin_id)]})

        result = load_committed(root)  # must not raise CorpusLoadError

        self.assertEqual(len(result.corpus.by_kind("action-seed")), 1)
        self.assertEqual(result.corpus.by_id(twin_id).path, "species/foo.json")


class PerKindIdPatternEdgeTests(unittest.TestCase):
    """Testing table row 11 + acceptance #6b."""

    def test_an_innate_pick_reference_is_recorded_as_an_edge(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        _write(root, "species/foo.json", {"schemaVersion": 1, "kind": "action-seed", "entries": [
            _valid_action_seed("action.species.foo.001", scope="species", scopeKey="foo")]})
        _write(root, "innate.json", {"schemaVersion": 1, "kind": "action-innate", "entries": [
            {"id": "innate.foo", "innateActionId": "action.species.foo.001"}]})

        result = load_committed(root)

        pairs = {(e.from_id, e.to_id) for e in result.edges}
        self.assertIn(("innate.foo", "action.species.foo.001"), pairs)

    def test_a_weights_rows_scope_key_reference_is_recorded_as_an_edge(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        _write(root, "_generated/lean.json", {"schemaVersion": 1, "kind": "action-role-lean",
                                              "entries": [{"id": "lean.foo"}]})
        _write(root, "_generated/weights.json", {"schemaVersion": 1, "kind": "action-type-weights",
                                                 "entries": [{"id": "weights.species.foo",
                                                             "scopeKey": "lean.foo"}]})

        result = load_committed(root)

        pairs = {(e.from_id, e.to_id) for e in result.edges}
        self.assertIn(("weights.species.foo", "lean.foo"), pairs)


class ConfigFilesSurviveTests(unittest.TestCase):
    """Acceptance #2 (Python half — the C# half is `dotnet test ... --filter ActionSeeding`,
    run separately, see the build report)."""

    @unittest.skipUnless(LIVE_ACTIONS_ROOT.is_dir(), "live data/seed/actions not present in this checkout")
    def test_loading_the_live_corpus_does_not_change_the_two_config_files(self) -> None:
        pairings_path = LIVE_ACTIONS_ROOT / "pairings.json"
        templates_path = LIVE_ACTIONS_ROOT / "name-templates.json"
        before = (pairings_path.read_bytes(), templates_path.read_bytes())

        load_committed(LIVE_ACTIONS_ROOT)

        after = (pairings_path.read_bytes(), templates_path.read_bytes())
        self.assertEqual(before, after)

    @unittest.skipUnless(LIVE_ACTIONS_ROOT.is_dir(), "live data/seed/actions not present in this checkout")
    def test_loading_the_live_corpus_raises_no_findings_today(self) -> None:
        # Today `gk-data/packs/fusion/data/seed/actions/` holds only the two config files and A-S0's family-map.json,
        # all three declared in `_manifest.json` -- no action-seed content exists yet (A-S6 hasn't
        # run), so a clean load should report zero entries and zero findings.
        result = load_committed(LIVE_ACTIONS_ROOT)
        self.assertEqual(result.findings, [])


class OfflineGuaranteeTests(unittest.TestCase):
    """Testing table row 13. This module makes no model call at all (spec §4's second bullet), so
    there is no transport to stub-and-raise the way `test_classify_pipelines.py:36` does for a
    pipeline that DOES call one — the equivalent proof here is structural (no LLM-transport import
    anywhere under this package) plus a dynamic proof that `load_committed` opens no non-loopback
    socket, same technique `test_offline_guarantee.py` uses for the whole suite."""

    def test_no_source_file_under_the_actions_adapter_references_the_llm_transport(self) -> None:
        """Scoped to THIS module's own files, not every top-level file under `adapters/actions/`
        (2026-09-04, `validate-heal`/A-S4): the class docstring above always said "this module makes
        no model call", but the original glob (`*.py` over the whole `adapters/actions/` directory)
        was written back when A-C1 was the only thing living there, so it silently asserted a much
        broader claim than it stated — that NO module in this whole adapter family would ever call a
        model. That stopped being true the moment A-S4 (`validate-heal`) was built: it is the
        action-corpus program's own designated "mixed model calls" module (a bounded self-heal is a
        genuinely new generation, spec-validate-heal.md's own opening line), and its entrypoint
        `generate_validate_heal.py` legitimately imports `pipeline.llm_caller`. A-S4 owns its own
        offline guarantee instead (`test_validate_heal.py`: every gate/vote/round test runs against a
        stubbed transport that raises, per binding constraint 8 — only its own heal-path tests call a
        transport at all, and that one is a loopback `MockModelServer`, never a real endpoint)."""
        package_dir = _owned("tools/seedsmith/seedsmith/adapters/actions")
        forbidden = ("llm_caller", "langchain", "langgraph", "requests", "urllib.request", "httpx")
        corpus_loader_files = {"kinds.py", "vocab.py", "load.py", "__init__.py"}
        for path in sorted(package_dir.glob("*.py")):
            if path.name not in corpus_loader_files:
                continue
            text = path.read_text(encoding="utf-8")
            for token in forbidden:
                self.assertNotIn(token, text, f"{path.name} references {token!r}")

    def test_load_committed_opens_no_non_loopback_socket(self) -> None:
        root = Path(tempfile.mkdtemp())
        _write_manifest(root)
        _write(root, "a.json", {"schemaVersion": 1, "kind": "action-seed",
                                "entries": [_valid_action_seed("action.general.0001")]})

        real_connect = socket.socket.connect
        attempts: list = []

        def guarded(self, address):
            host = address[0] if isinstance(address, tuple) else str(address)
            if isinstance(host, str) and not (
                host.startswith("127.") or host in ("localhost", "::1", "0.0.0.0")
            ):
                attempts.append(address)
                raise AssertionError(f"non-loopback connection attempted: {address}")
            return real_connect(self, address)

        socket.socket.connect = guarded
        try:
            load_committed(root)
        finally:
            socket.socket.connect = real_connect
        self.assertEqual(attempts, [])


if __name__ == "__main__":
    unittest.main()
