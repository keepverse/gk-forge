"""Task 2 (seedsmith-content-standard) — the shared staleness-key function, proven against a REAL
passive-tree fixture, not synthetic data (plan's own Checkpoint 0 requirement).

`gk-data/packs/fusion/data/seed/passive-tree/nodes/ferocity.json` is real, committed content whose own recorded
`_provenance.promptVersion` is `"tree-language/1"` while the current code's
`nodegen.brief.PROMPT_VERSION` is `"tree-language/2"` — a genuinely already-stale real record,
found by this test rather than manufactured for it. It doubles as the worked example
spec-content-completeness-core.md §10 requires.
"""
from __future__ import annotations

import json
from pathlib import Path

from seedsmith.adapters.trees.nodegen.brief import PROMPT_VERSION
from seedsmith.pipeline.staleness import brief_hash, is_stale, staleness_key

REPO_ROOT = Path(__file__).resolve().parents[4]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from seedsmith.workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

FEROCITY_SEED = _owned("data/seed/passive-tree/nodes/ferocity.json")


def _real_ferocity_doc() -> dict:
    assert FEROCITY_SEED.exists(), f"real fixture missing: {FEROCITY_SEED}"
    return json.loads(FEROCITY_SEED.read_text(encoding="utf-8"))


def test_brief_hash_is_stable_and_content_sensitive_on_real_node_text():
    doc = _real_ferocity_doc()
    node = doc["nodes"][0]
    real_text = f"{node['name']} — {node['flavor']}"

    h1 = brief_hash(real_text)
    h2 = brief_hash(real_text)
    assert h1 == h2

    other_node = doc["nodes"][1]
    other_text = f"{other_node['name']} — {other_node['flavor']}"
    assert brief_hash(other_text) != h1


def test_staleness_key_changes_when_the_real_prompt_version_changes():
    doc = _real_ferocity_doc()
    node = doc["nodes"][0]
    text = f"{node['name']} — {node['flavor']}"
    bh = brief_hash(text)

    key_v1 = staleness_key(brief_hash=bh, prompt_version="tree-language/1",
                           schema_version="1", model_id="google/gemma-4-26b-a4b-qat")
    key_v2 = staleness_key(brief_hash=bh, prompt_version=PROMPT_VERSION,
                           schema_version="1", model_id="google/gemma-4-26b-a4b-qat")

    assert PROMPT_VERSION != "tree-language/1", (
        "this test's whole point is a real version bump — if PROMPT_VERSION ever reverts to "
        "tree-language/1, this assertion (not a false pass) is what should catch it"
    )
    assert key_v1 != key_v2


def test_staleness_key_is_stable_given_identical_inputs():
    key_a = staleness_key(brief_hash="x", prompt_version="p1", schema_version="s1", model_id="m1")
    key_b = staleness_key(brief_hash="x", prompt_version="p1", schema_version="s1", model_id="m1")
    assert key_a == key_b


def test_staleness_key_does_not_collide_across_a_field_boundary():
    # "ab" + "c" must not hash the same as "a" + "bc" once separated — proves the separator matters.
    key_1 = staleness_key(brief_hash="ab", prompt_version="c", schema_version="s", model_id="m")
    key_2 = staleness_key(brief_hash="a", prompt_version="bc", schema_version="s", model_id="m")
    assert key_1 != key_2


def test_the_real_committed_ferocity_seed_is_stale_against_the_current_prompt_version():
    """The real, already-found stale record: ferocity.json cannot prove it was generated under the
    current `PROMPT_VERSION`, so `Content/FieldStale` (Task 3) must report it.

    ⛔ CORRECTED 2026-09-11: the doc-level stamp is no longer a single literal. `emit.build_seed_document`
    now derives it from the records: a tree that mixed vintages (here `''` from pre-provenance
    re-roll survivors and `tree-language/3` from fresh nodes) stamps `"mixed"` and carries the
    per-node split in `promptVersionByNode`. Pinning `"tree-language/1"` was stale the moment that
    landed. The invariant that actually matters — and that this test exists for — is that the
    committed record is NOT current, proven against whatever stamp the document carries."""
    doc = _real_ferocity_doc()
    prov = doc["_provenance"]
    recorded_prompt_version = prov["promptVersion"]

    # Not current: either an explicit older vintage, or `mixed` whose per-node split contains at
    # least one value that is not the current vintage.
    if recorded_prompt_version == "mixed":
        per_node = prov.get("promptVersionByNode", {})
        assert any(v != PROMPT_VERSION for v in per_node.values()), (
            "a `mixed` stamp must carry at least one non-current per-node vintage"
        )
    else:
        assert recorded_prompt_version != PROMPT_VERSION

    recorded = {"stalenessKey": staleness_key(
        brief_hash="irrelevant-for-this-check", prompt_version=recorded_prompt_version,
        schema_version="1", model_id=prov["model"])}
    current_key = staleness_key(
        brief_hash="irrelevant-for-this-check", prompt_version=PROMPT_VERSION,
        schema_version="1", model_id=prov["model"])

    assert is_stale(recorded, current_key) is True


def test_is_stale_reports_stale_for_a_record_with_no_recorded_key_at_all():
    assert is_stale(None, "any-key") is True


def test_is_stale_reports_current_for_a_matching_key():
    key = staleness_key(brief_hash="a", prompt_version="b", schema_version="c", model_id="d")
    assert is_stale({"stalenessKey": key}, key) is False
