"""Tests for `nodegen.migrate_retired_atk` — the fix for the 16 already-accepted passive-tree nodes
whose persisted `quotaCell.channelFamily` named the now-retired `progression.bonus.atk` channel
(solid-enforcement `retire-atk` R5, owner ruling 2026-09-18). Mirrors
`recipegen.migrate_legacy_shards`'s own test shape (detect / fix / apply-to-real-corpus / re-run).
"""
from __future__ import annotations

import json

from seedsmith.adapters.trees.nodegen import migrate_retired_atk as mod
from seedsmith.adapters.trees.nodegen import quota


def _cell(channel_family: str, **overrides):
    base = {"nodeClass": "mechanism", "trigger": "OnTimer", "element": "dark",
            "status": "rally", "channelFamily": channel_family, "exclusionForm": "none"}
    return {**base, **overrides}


def _node(node_id: str, channel_family: str, **overrides):
    node = {
        "id": node_id, "nodeKey": "n0", "branch": "defensive", "tier": 9, "nodeClass": "mechanism",
        "affixIds": ["atom.ward-brace"], "affinity": ["core"],
        "exclusion": {"form": "none", "propertyKeys": [], "printedText": ""},
        "name": "Void-Stitched Aegis", "nameKey": "tree.node.void-stitched-aegis",
        "flavor": "The darkness does not merely protect.", "rationale": "",
        "quotaCell": _cell(channel_family),
    }
    node.update(overrides)
    return node


def _doc(tree_id: str, nodes):
    return {"schemaVersion": 1, "treeId": tree_id, "nodes": nodes,
            "_provenance": {"planHash": "abc", "promptVersion": "tree-language/3", "model": "m",
                            "confidence": {}, "minorityValues": {}}}


# ---------------------------------------------------------------------------------------------
# Detect
# ---------------------------------------------------------------------------------------------


def test_detects_a_retired_cell_by_tree_node_and_index():
    doc = _doc("dark", [_node("skill.dark-def-t9-n0", "progression.bonus.atk")])
    findings = mod.find_retired_quota_cells(doc)
    assert len(findings) == 1
    f = findings[0]
    assert (f.tree_id, f.node_id, f.node_index, f.old_family, f.new_family) == (
        "dark", "skill.dark-def-t9-n0", 0, "progression.bonus.atk", "combat.power")


def test_a_clean_tree_with_only_live_channel_families_finds_nothing():
    doc = _doc("fire", [_node("skill.fire-off-t1-n0", "combat.dmg")])
    assert mod.find_retired_quota_cells(doc) == []


def test_a_legacy_node_with_no_quota_cell_at_all_is_skipped_without_error():
    doc = _doc("might", [{"id": "skill.might-off-t1-n0", "nodeKey": "n0", "branch": "offensive",
                          "tier": 1, "nodeClass": "mechanism", "affixIds": [], "affinity": [],
                          "exclusion": {"form": "none", "propertyKeys": [], "printedText": ""},
                          "name": "x", "nameKey": "tree.node.x", "flavor": "x", "rationale": ""}])
    assert mod.find_retired_quota_cells(doc) == []


# ---------------------------------------------------------------------------------------------
# Fix
# ---------------------------------------------------------------------------------------------


def test_migrate_rewrites_only_the_retired_cells_channel_family():
    doc = _doc("dark", [_node("skill.dark-def-t9-n0", "progression.bonus.atk")])
    new_doc, findings = mod.migrate_retired_quota_cells(doc)
    assert len(findings) == 1
    new_node = new_doc["nodes"][0]
    assert new_node["quotaCell"]["channelFamily"] == "combat.power"
    # every other axis, and every LLM-authored field, survives the rewrite untouched
    assert new_node["quotaCell"]["element"] == "dark"
    assert new_node["name"] == "Void-Stitched Aegis"
    assert new_node["affixIds"] == ["atom.ward-brace"]
    assert new_node["tier"] == 9


def test_migrate_is_a_no_op_on_an_already_clean_tree():
    doc = _doc("fire", [_node("skill.fire-off-t1-n0", "combat.dmg")])
    new_doc, findings = mod.migrate_retired_quota_cells(doc)
    assert findings == []
    assert new_doc == doc


def test_migrate_never_mutates_the_input_doc_in_place():
    doc = _doc("dark", [_node("skill.dark-def-t9-n0", "progression.bonus.atk")])
    before = json.loads(json.dumps(doc))
    mod.migrate_retired_quota_cells(doc)
    assert doc == before


def test_migrate_leaves_nodes_with_no_retired_cell_untouched_by_identity():
    clean_node = _node("skill.dark-off-t1-n0", "combat.dmg")
    dirty_node = _node("skill.dark-def-t9-n0", "progression.bonus.atk")
    doc = _doc("dark", [clean_node, dirty_node])
    new_doc, _ = mod.migrate_retired_quota_cells(doc)
    assert new_doc["nodes"][0] is clean_node  # untouched nodes are not even copied


def test_re_running_migrate_on_its_own_output_finds_nothing_left():
    doc = _doc("dark", [_node("skill.dark-def-t9-n0", "progression.bonus.atk")])
    once, findings1 = mod.migrate_retired_quota_cells(doc)
    assert len(findings1) == 1
    twice, findings2 = mod.migrate_retired_quota_cells(once)
    assert findings2 == []
    assert twice == once


# ---------------------------------------------------------------------------------------------
# Apply to real files (round-trip via tmp_path, never the real repo files in a test)
# ---------------------------------------------------------------------------------------------


def test_apply_to_tree_file_writes_the_fix_via_canonical_json_bytes(tmp_path):
    from seedsmith.adapters.trees.plan.emit import canonical_json_bytes

    path = tmp_path / "dark.json"
    doc = _doc("dark", [_node("skill.dark-def-t9-n0", "progression.bonus.atk")])
    path.write_bytes(canonical_json_bytes(doc))

    findings = mod.apply_to_tree_file(path)

    assert len(findings) == 1
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["nodes"][0]["quotaCell"]["channelFamily"] == "combat.power"
    # written through the same canonical serializer -- byte-identical shape to the shipped corpus
    assert path.read_bytes() == canonical_json_bytes(written)


def test_apply_to_tree_file_is_a_no_op_when_already_clean(tmp_path):
    from seedsmith.adapters.trees.plan.emit import canonical_json_bytes

    path = tmp_path / "fire.json"
    doc = _doc("fire", [_node("skill.fire-off-t1-n0", "combat.dmg")])
    original_bytes = canonical_json_bytes(doc)
    path.write_bytes(original_bytes)

    findings = mod.apply_to_tree_file(path)

    assert findings == []
    assert path.read_bytes() == original_bytes  # byte-identical -- no rewrite at all


def test_apply_to_real_corpus_walks_every_file_and_reports_only_touched_trees(tmp_path):
    from seedsmith.adapters.trees.plan.emit import canonical_json_bytes

    dirty = tmp_path / "dark.json"
    dirty.write_bytes(canonical_json_bytes(
        _doc("dark", [_node("skill.dark-def-t9-n0", "progression.bonus.atk")])))
    clean = tmp_path / "fire.json"
    clean.write_bytes(canonical_json_bytes(_doc("fire", [_node("skill.fire-off-t1-n0", "combat.dmg")])))

    results = mod.apply_to_real_corpus(tmp_path)

    assert set(results) == {"dark"}
    assert len(results["dark"]) == 1


def test_the_real_shipped_corpus_is_already_clean_of_the_retired_channel_family():
    """Regression guard, mirroring `migrate_legacy_shards`'s own real-corpus test: the real nodes
    named by spec-retire-atk.md were fixed in place by running this module's own
    `apply_to_real_corpus` against the real files (solid-enforcement `retire-atk` R5). A future
    regression (a hand-edit, or a fresh generation, reintroducing the retired channel family into a
    persisted `quotaCell`) should fail this test, not silently ship."""
    for path in sorted(mod.DEFAULT_NODES_DIR.glob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert mod.find_retired_quota_cells(doc) == [], f"{path.name} still names a retired channel family"
