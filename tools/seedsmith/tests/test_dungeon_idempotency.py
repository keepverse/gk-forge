"""Tests for seedsmith.adapters.dungeon.{emit,provenance} (D1.11, spec-dungeon-seed-contract.md
§6) and the offline guarantee (decision 6: "in game runtime don't use LLM — this seed generator is
only contained in seedsmith").

    python -m pytest gk-forge/tools/seedsmith/tests/test_dungeon_idempotency.py -v
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.dungeon.emit import (  # noqa: E402
    build_provenance, render_entry, render_index, write_corpus, write_entry,
)
from seedsmith.adapters.dungeon.provenance import DungeonProvenance, stale_ids, staleness_key  # noqa: E402
from seedsmith.pipeline.staleness import staleness_key as core_staleness_key  # noqa: E402

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

DUNGEON_ADAPTER_DIR = _owned("tools/seedsmith/seedsmith/adapters/dungeon")


class CanonicalSerialisationTests(unittest.TestCase):
    def test_render_entry_is_sorted_keys_two_space_indent(self) -> None:
        entry = {"b": 1, "a": "x", "_provenance": {"planHash": "abc"}}
        rendered = render_entry(entry).decode("utf-8")
        self.assertTrue(rendered.startswith("{\n  \"_provenance\""))  # sorted: "_provenance" < "a" < "b"
        self.assertTrue(rendered.endswith("}\n"))

    def test_render_entry_unescapes_cjk_and_keeps_explicit_nulls(self) -> None:
        entry = {"flavor": "灰烬回廊", "chainRef": None}
        rendered = render_entry(entry).decode("utf-8")
        self.assertIn("灰烬回廊", rendered)
        self.assertNotIn("\\u", rendered)
        self.assertIn("null", rendered)

    def test_render_index_maps_id_to_filename_sorted(self) -> None:
        rendered = render_index(["room.b-001", "room.a-001"]).decode("utf-8")
        self.assertLess(rendered.index('"room.a-001"'), rendered.index('"room.b-001"'))


class RerunIsByteIdenticalTests(unittest.TestCase):
    def test_two_runs_over_unchanged_input_produce_identical_bytes(self) -> None:
        entries = {
            "room.cache-ice-001": {"roomId": "room.cache-ice-001", "kind": "cache", "climate": "ice"},
            "room.fight-fire-001": {"roomId": "room.fight-fire-001", "kind": "fight", "climate": "fire"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "rooms"
            first_run = write_corpus(directory, entries)
            first_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in first_run}

            second_run = write_corpus(directory, entries)
            second_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in second_run}

            self.assertEqual(first_hashes, second_hashes)
            self.assertEqual(set(first_hashes), {"room.cache-ice-001.json", "room.fight-fire-001.json", "_index.json"})


class StalenessTests(unittest.TestCase):
    def test_an_entry_with_no_provenance_is_stale(self) -> None:
        entries = [{"roomId": "room.a-001"}]
        current = DungeonProvenance(plan_hash="p1", brief_hash="b1").to_dict()
        self.assertEqual(stale_ids(entries, id_field="roomId", current=current), ["room.a-001"])

    def test_an_entry_matching_the_current_staleness_key_is_not_stale(self) -> None:
        prov = DungeonProvenance(
            plan_hash="p1", brief_hash="b1", prompt_versions={"room-identity": 1},
            registry_versions={"room-kinds": 1}, motif_subset_hash="m1",
        ).to_dict()
        entries = [{"roomId": "room.a-001", "_provenance": prov}]
        self.assertEqual(stale_ids(entries, id_field="roomId", current=prov), [])

    def test_adding_a_plan_cell_stales_nothing_when_brief_hash_is_unchanged(self) -> None:
        # §6's own point: planHash is recorded but never part of the staleness key -- a plan that
        # adds a cell (new planHash) must not stale an untouched entry whose brief did not change.
        prov = DungeonProvenance(plan_hash="p1", brief_hash="b1", motif_subset_hash="m1").to_dict()
        entries = [{"roomId": "room.a-001", "_provenance": prov}]
        current_after_plan_v2 = DungeonProvenance(plan_hash="p2", brief_hash="b1", motif_subset_hash="m1").to_dict()
        self.assertEqual(stale_ids(entries, id_field="roomId", current=current_after_plan_v2), [])

    def test_a_changed_brief_hash_stales_the_entry(self) -> None:
        prov = DungeonProvenance(plan_hash="p1", brief_hash="b1").to_dict()
        entries = [{"roomId": "room.a-001", "_provenance": prov}]
        current = DungeonProvenance(plan_hash="p1", brief_hash="b2").to_dict()
        self.assertEqual(stale_ids(entries, id_field="roomId", current=current), ["room.a-001"])

    def test_staleness_key_excludes_planHash(self) -> None:
        prov_a = DungeonProvenance(plan_hash="p1", brief_hash="b1").to_dict()
        prov_b = DungeonProvenance(plan_hash="p999", brief_hash="b1").to_dict()
        self.assertEqual(staleness_key(prov_a), staleness_key(prov_b))


class ProvenanceStampingTests(unittest.TestCase):
    """`seedsmith-content-standard` Task 12: `write_entry`/`write_corpus` previously had no way to
    attach `_provenance` at all — the real, precise reason no committed dungeon content ever
    carried the field despite `DungeonProvenance`/`stale_ids` existing as real code. Proves the fix
    is additive (no-provenance calls unaffected, matching `RerunIsByteIdenticalTests` above
    unchanged) and that `build_provenance` reuses `content-completeness-core`'s own shared
    `pipeline.staleness.staleness_key`, not a re-derived dungeon-local one."""

    def test_write_entry_with_no_provenance_is_unaffected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "events"
            path = write_entry(directory, "event.a-001", {"eventId": "event.a-001"})
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertNotIn("_provenance", data)

    def test_write_entry_with_provenance_stamps_it_onto_the_written_file(self) -> None:
        prov = build_provenance(brief_hash="b1", prompt_version="event/1",
                                schema_version="dungeon-event.v1", model_id="m1")
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "events"
            path = write_entry(directory, "event.a-001", {"eventId": "event.a-001"}, provenance=prov)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["_provenance"]["briefHash"], "b1")
            self.assertEqual(data["_provenance"]["promptVersion"], "event/1")
            self.assertIn("stalenessKey", data["_provenance"])

    def test_build_provenance_reuses_the_shared_core_staleness_key(self) -> None:
        prov = build_provenance(brief_hash="b1", prompt_version="event/1",
                                schema_version="dungeon-event.v1", model_id="m1")
        expected = core_staleness_key(brief_hash="b1", prompt_version="event/1",
                                      schema_version="dungeon-event.v1", model_id="m1")
        self.assertEqual(prov["stalenessKey"], expected)

    def test_a_changed_prompt_version_changes_the_staleness_key(self) -> None:
        prov_v1 = build_provenance(brief_hash="b1", prompt_version="event/1",
                                   schema_version="s1", model_id="m1")
        prov_v2 = build_provenance(brief_hash="b1", prompt_version="event/2",
                                   schema_version="s1", model_id="m1")
        self.assertNotEqual(prov_v1["stalenessKey"], prov_v2["stalenessKey"])

    def test_write_corpus_stamps_only_the_ids_given_a_provenance(self) -> None:
        prov = build_provenance(brief_hash="b1", prompt_version="event/1",
                                schema_version="s1", model_id="m1")
        entries = {
            "event.a-001": {"eventId": "event.a-001"},
            "event.b-001": {"eventId": "event.b-001"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp) / "events"
            write_corpus(directory, entries, provenance_by_id={"event.a-001": prov})
            a = json.loads((directory / "event.a-001.json").read_text(encoding="utf-8"))
            b = json.loads((directory / "event.b-001.json").read_text(encoding="utf-8"))
            self.assertIn("_provenance", a)
            self.assertNotIn("_provenance", b)


class OfflineGuaranteeTests(unittest.TestCase):
    """decision 6: 'in game runtime don't use LLM — this seed generator is only contained in
    seedsmith.' Nothing built so far in adapters/dungeon/ calls a model at all (pipelines.py,
    the one module that would, is not built — see planner.py's own stated-gap docstring), so this
    proves the guarantee structurally: no module here imports a transport/model-calling symbol."""

    def test_no_dungeon_adapter_module_imports_a_transport(self) -> None:
        offenders = []
        for path in DUNGEON_ADAPTER_DIR.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and "transport" in node.module.lower():
                    offenders.append(f"{path.name}: {node.module}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "transport" in alias.name.lower():
                            offenders.append(f"{path.name}: {alias.name}")
        self.assertEqual(offenders, [], f"a dungeon adapter module imports a transport: {offenders}")

    def test_importing_every_dungeon_adapter_module_makes_no_network_call(self) -> None:
        # A weaker but real guarantee available today: importing every module that exists cannot
        # itself reach the network, because none of them defines a call at import time (no
        # module-level HTTP client construction, no eager model warm-up). Import-time side effects
        # are exactly what a hidden model call would look like if one were smuggled in.
        import importlib

        for path in sorted(DUNGEON_ADAPTER_DIR.glob("*.py")):
            if path.name == "__init__.py":
                continue
            module_name = f"seedsmith.adapters.dungeon.{path.stem}"
            importlib.import_module(module_name)  # raises if import itself fails/blocks


if __name__ == "__main__":
    unittest.main()


class EventCommitterIdempotencyTests(unittest.TestCase):
    """NS12 — two commits of the same draws are byte-identical, file for file."""

    def _entries(self):
        from seedsmith.adapters.dungeon.commit import commit_event_draws
        from seedsmith.adapters.dungeon.pipelines import EventDrawResult
        from seedsmith.pipeline.llm_caller import LlmCallerConfig

        entry = {
            "eventId": "event.curio-creature.wallnut-001", "kind": "curio",
            "theme": "creature.wallnut", "name": "Ash Confluence",
            "flavor": "A cold draught crosses the chamber.", "reason": "because",
            "climateAffinity": "fire", "repeatScope": "per-delve", "eligibility": None,
            "outcomes": [{"ordinal": "good", "consequence": "none", "dropBand": "staple", "effects": []}],
            "supplyOverride": "none", "chainRef": "none",
        }
        return commit_event_draws, EventDrawResult, LlmCallerConfig, entry

    def test_commit_is_byte_identical_on_rerun(self) -> None:
        commit_event_draws, EventDrawResult, LlmCallerConfig, entry = self._entries()
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            results = [EventDrawResult("curio-creature.wallnut", 0, entry, brief_hash="c" * 64)]
            commit_event_draws(results, Path(first), config=LlmCallerConfig(model="m"))
            commit_event_draws(results, Path(second), config=LlmCallerConfig(model="m"))

            first_files = sorted(p.name for p in Path(first).iterdir())
            second_files = sorted(p.name for p in Path(second).iterdir())
            self.assertEqual(first_files, second_files)
            self.assertIn("_index.json", first_files)
            first_hash = hashlib.sha256(
                b"".join((Path(first) / n).read_bytes() for n in first_files)).hexdigest()
            second_hash = hashlib.sha256(
                b"".join((Path(second) / n).read_bytes() for n in second_files)).hexdigest()
            self.assertEqual(first_hash, second_hash)
