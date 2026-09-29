"""NS4 — every repaired adapter entry point forwards a resolved `LlmCallerConfig`.

`spec-model-config-resolve.md` §3.2: "Every adapter function that forwards to the transport takes
`config: LlmCallerConfig | None = None` and passes it on unchanged. No adapter builds
`LlmCallerConfig(model=<literal>)`."

Each test below stubs `resolve_live_transport` (the adapter's own module attribute — the name the
adapter actually calls) with a sentinel config and asserts the sentinel reaches the model-call
seam. The model transport itself is never reached: every seam is patched. The tests prove the
resolution path, not a corpus reading.

    python -m pytest gk-forge/tools/seedsmith/tests/test_model_config_resolve_entries.py -q
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.pipeline.llm_caller import LlmCallerConfig  # noqa: E402

SENTINEL = LlmCallerConfig(endpoint="http://sentinel.invalid/v1/chat/completions",
                           model="sentinel-resolved-model", attempts=5)


class _Captured(Exception):
    """Raised by a stubbed propose seam once it has recorded the config it was handed — a
    sentinel exception is cheaper and more honest than fabricating a full Candidate."""


def _write_envelope(path: Path, scope: str, brief_id: str = "brief.x.000") -> None:
    path.write_text(json.dumps({
        "kind": "action-brief", "_meta": {"corpusHash": "envelope-hash"},
        "entries": [{"briefId": brief_id, "scope": scope}],
    }), encoding="utf-8")


class ProposedActionEntryPointsTests(unittest.TestCase):
    """The three action proposal generators: `regenerate(config=None)` resolves, then hands the
    SAME resolved config to its `propose_*` seam."""

    def _assert_forwards(self, module_name: str, scope: str, seam_name: str) -> None:
        import importlib

        mod = importlib.import_module(module_name)
        seen: dict = {}

        def fake_propose(*_args, **kwargs):
            seen.update(kwargs)
            raise _Captured()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            envelope = tmp_path / "briefs.json"
            _write_envelope(envelope, scope)
            with patch.object(mod, "resolve_live_transport", return_value=SENTINEL), \
                 patch.object(mod, seam_name, fake_propose):
                with self.assertRaises(_Captured):
                    mod.regenerate(briefs_path=envelope, dry_run=False, count=1,
                                   candidates_dir=tmp_path, write=False, config=None)

        self.assertIs(seen["config"], SENTINEL,
                      f"{module_name}.regenerate must forward the resolved config unchanged")

    def test_general_propose_forwards_the_resolved_config(self) -> None:
        self._assert_forwards("seedsmith.adapters.actions.generate_general_actions",
                              "general", "propose_general_action")

    def test_family_propose_forwards_the_resolved_config(self) -> None:
        self._assert_forwards("seedsmith.adapters.actions.generate_family_actions",
                              "family", "propose_family_action")

    def test_signature_propose_forwards_the_resolved_config(self) -> None:
        # A-S2's assembled envelope is `scope: "species"` only (its own `_signature_briefs_of`).
        self._assert_forwards("seedsmith.adapters.actions.generate_signature_actions",
                              "species", "propose_signature_action")


class ActionDescriptionsEntryPointTests(unittest.TestCase):
    def test_backfill_resolves_and_passes_the_config_to_call_model(self) -> None:
        from seedsmith.adapters.actions import generate_action_descriptions as mod

        entry = MagicMock()
        entry.id = "action.one"
        entry.data = {}
        load_result = MagicMock()
        load_result.corpus.by_kind.return_value = [entry]
        seen: dict = {}

        def fake_call_model(_system, _user, **kwargs):
            seen.update(kwargs)
            return '{"description": "a replacement description"}'

        with patch.object(mod, "resolve_live_transport", return_value=SENTINEL), \
             patch.object(mod, "plan", return_value=["action.one"]), \
             patch.object(mod, "load_committed", return_value=load_result), \
             patch.object(mod, "build_brief", return_value="a brief"), \
             patch.object(mod, "RunLedger", MagicMock()), \
             patch.object(mod, "stamp_description", MagicMock(return_value={})), \
             patch.object(mod, "group_ids_by_path", return_value={}), \
             patch.object(mod, "call_model", fake_call_model):
            summary = mod.backfill(only=("action.one",))

        self.assertIs(seen["config"], SENTINEL)
        self.assertEqual(summary["generated"], ["action.one"])


class ActionPipelineEntryPointTests(unittest.TestCase):
    def test_run_pipeline_resolves_when_config_is_omitted(self) -> None:
        from seedsmith.adapters.actions import generate_action_pipeline as mod

        with patch.object(mod, "resolve_live_transport", return_value=SENTINEL) as resolve, \
             patch.object(mod, "_foundation_inputs", side_effect=_Captured):
            with self.assertRaises(_Captured):
                mod.run_pipeline(dry_run=True)
        resolve.assert_called_once_with()

    def test_run_partition_forwards_the_same_config_object(self) -> None:
        from seedsmith.adapters.actions.generate_action_pipeline import _run_partition

        seen: list[dict] = []

        def generate(**kwargs):
            seen.append(kwargs)
            return {"selected": 1, "remaining": 0, "byOutcome": {"accepted": 1}}

        _run_partition(
            name="general", generate=generate, briefs_path=Path("briefs.json"),
            candidates_dir=Path("candidates"), round_no=1, batch_size=1, max_passes=1,
            config=SENTINEL, dry_run=False, resume=False,
        )
        self.assertIs(seen[0]["config"], SENTINEL)


class CliOnlyEntryPointsTests(unittest.TestCase):
    """`generate_commander_effects.main`, `generate_affixes.main` and `generate_families.run`
    build their config inside the CLI — the CLI is the entry point, so the test drives it with
    every input and every transport seam stubbed."""

    def test_commander_effects_main_builds_its_config_through_resolve_live_transport(self) -> None:
        from seedsmith.adapters.creatures import generate_commander_effects as mod

        captured: dict = {}

        def fake_graph(**kwargs):
            captured.update(kwargs)
            return object()

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mod, "resolve_live_transport", return_value=SENTINEL) as resolve, \
                 patch.object(mod, "load_subjects",
                              return_value=[{"speciesId": "s.one", "basis": "text", "motifs": []}]), \
                 patch.object(mod, "refuse_if_motifs_are_stale", return_value=None), \
                 patch.object(mod, "load_existing", return_value={}), \
                 patch.object(mod, "stale_ids", return_value=set()), \
                 patch.object(mod, "build_context", return_value={}), \
                 patch.object(mod, "build_brief", return_value="brief"), \
                 patch.object(mod, "new_state", return_value=object()), \
                 patch.object(mod, "OUTPUT_DIR", Path(tmp)), \
                 patch("seedsmith.workflow.graphs.commander_effect.build_commander_effect_graph",
                       fake_graph), \
                 patch("seedsmith.workflow.runner.run_many", return_value={}):
                mod.main([])

        resolve.assert_called_once_with("", "")
        config = captured["config"]
        self.assertEqual(config.model, SENTINEL.model)
        self.assertEqual(config.attempts, 2)
        self.assertEqual(config.timeout, 420)

    def test_affixes_main_builds_its_config_through_resolve_live_transport(self) -> None:
        from seedsmith.adapters.effects.affix import generate_affixes as mod

        captured: dict = {}

        def fake_draws(**kwargs):
            captured.update(kwargs)
            return {}, {}, {}

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(mod, "resolve_live_transport", return_value=SENTINEL) as resolve, \
                 patch.object(mod, "load_eligible_atoms",
                              return_value={"atom.a": True, "atom.b": True}), \
                 patch.object(mod, "load_existing", return_value={}), \
                 patch.object(mod, "next_draw_start_index", return_value=0), \
                 patch.object(mod, "run_voted_draws", fake_draws), \
                 patch.object(mod, "OUTPUT_DIR", Path(tmp)):
                mod.main([])

        resolve.assert_called_once_with("", "")
        config = captured["config"]
        self.assertEqual(config.model, SENTINEL.model)
        self.assertEqual(config.attempts, 2)

    def test_families_run_builds_its_config_through_resolve_live_transport(self) -> None:
        from seedsmith.adapters.creatures import generate_families as mod

        captured: dict = {}
        corpus = MagicMock()
        corpus.by_kind.return_value = []

        def fake_extract(_entries, **_kwargs):
            captured.update(_kwargs)
            return {}

        consolidated = MagicMock()
        consolidated.families = {}
        consolidated.assignments = {}

        with patch.object(mod, "resolve_live_transport", return_value=SENTINEL) as resolve, \
             patch.object(mod.Corpus, "load", return_value=corpus), \
             patch.object(mod, "bound_artifacts", return_value=[]), \
             patch.object(mod, "load_existing_registry", return_value=None), \
             patch.object(mod, "extract_family_candidates", fake_extract), \
             patch.object(mod, "consolidate", return_value=consolidated):
            exit_code = mod.run([])

        self.assertEqual(exit_code, 0)
        resolve.assert_called_once_with("", "")
        self.assertEqual(captured["config"].model, SENTINEL.model)


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    unittest.main()
