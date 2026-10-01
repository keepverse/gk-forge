"""Tests for `gk-forge/tools/seedsmith/action_run_preflight.py` (T4.5's model-free preflight).

The preflight itself runs the real planner/pipeline in memory and takes ~6 s, so the load-bearing
checks are exercised by running the script; these tests pin the pure pieces — the endpoint URL
derivation, the unreachable-endpoint behaviour, the plan-hash read, and the tag vocabulary — so a
regression in them is caught without a live model.
"""
from __future__ import annotations

import importlib.util
import json
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

SCRIPT_PATH = _owned("tools/seedsmith/action_run_preflight.py")

_spec = importlib.util.spec_from_file_location("action_run_preflight", SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
preflight = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(preflight)


class ModelsUrlTests(unittest.TestCase):
    def test_chat_completions_endpoint_derives_its_models_url(self) -> None:
        self.assertEqual(preflight.models_url("http://localhost:1234/v1/chat/completions"),
                         "http://localhost:1234/v1/models")

    def test_legacy_completions_endpoint_derives_its_models_url(self) -> None:
        self.assertEqual(preflight.models_url("http://localhost:1234/v1/completions"),
                         "http://localhost:1234/v1/models")

    def test_an_unrecognised_endpoint_gets_models_appended(self) -> None:
        self.assertEqual(preflight.models_url("http://localhost:1234/v1"), "http://localhost:1234/v1/models")

    def test_a_trailing_slash_does_not_double_up(self) -> None:
        self.assertEqual(preflight.models_url("http://localhost:1234/v1/chat/completions/"),
                         "http://localhost:1234/v1/models")


class UnreachableEndpointTests(unittest.TestCase):
    def test_an_unreachable_endpoint_reports_no_model_instead_of_raising(self) -> None:
        # Port 1 is reserved and never listened on; the probe must return False, never raise -- a
        # preflight that crashes on an absent LM Studio is worse than one that reports it.
        self.assertFalse(preflight.endpoint_has_model(
            "http://127.0.0.1:1/v1/chat/completions", "google/gemma-4-26b-a4b-qat", timeout=1.0))


class PlanHashTests(unittest.TestCase):
    def test_committed_plan_hash_reads_the_meta_corpus_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "round-1.json"
            path.write_text(json.dumps({"_meta": {"corpusHash": "abc123"}, "entries": []}),
                            encoding="utf-8")
            self.assertEqual(preflight.committed_plan_hash(path), "abc123")


class VocabularyTests(unittest.TestCase):
    def test_expected_tags_are_the_closed_nine_member_vocabulary(self) -> None:
        # The preflight's own literal must stay the closed set the wire actually carries
        # (ActionTag, `vocab.TAGS`) -- a widened vocabulary is a reviewed change, not drift.
        self.assertEqual(preflight.EXPECTED_TAGS, frozenset(preflight.vocab.TAGS))
        self.assertIn("construct", preflight.EXPECTED_TAGS)


if __name__ == "__main__":
    unittest.main()
