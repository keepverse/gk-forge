"""species-gear-chain T38 — the upgrade tree's authored `successorOf` edges.

Pure tests over the loader and the entry injection: the field is ADDITIVE (no authored edge ⇒ no key
at all, so the shipped corpus is unchanged), never model-authored, and a malformed table is a load
rejection rather than a silently ignored row.
"""
from __future__ import annotations

import json

import pytest

from seedsmith.adapters.items.basetypegen import successor_edges


def _write(tmp_path, doc) -> "object":
    path = tmp_path / "successor-edges.v1.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def test_the_shipped_table_loads_and_closes_against_the_real_corpus():
    # The shipped state is now a REAL authored table (T37, 2026-09-21). Its SIZE is a reading, not a
    # contract; what is asserted is that it loads and that every edge joins two real base types in the
    # same frame — the property the executor relies on.
    edges = successor_edges.load(successor_edges.SUCCESSOR_EDGES_REGISTRY)

    assert edges, "the authored edge table shipped empty — an armour upgrade would refuse everywhere"
    assert successor_edges.violations_in_corpus(successor_edges.SHIPPED_BASE_TYPES_DIR, edges) == []
    print(f"\nedges authored (reading, not asserted): {len(edges)}")


def test_an_authored_edge_is_read_verbatim(tmp_path):
    path = _write(tmp_path, {"edges": {"item.humanoid-footing-cloth-001": "item.humanoid-footing-leather-001"}})

    assert successor_edges.load(path) == {
        "item.humanoid-footing-cloth-001": "item.humanoid-footing-leather-001"
    }


def test_a_missing_table_is_a_rejection_not_an_empty_tree(tmp_path):
    with pytest.raises(successor_edges.SuccessorEdgeError):
        successor_edges.load(tmp_path / "absent.json")


def test_a_document_without_an_edges_object_is_rejected(tmp_path):
    with pytest.raises(successor_edges.SuccessorEdgeError):
        successor_edges.load(_write(tmp_path, {"schemaVersion": 1}))
    with pytest.raises(successor_edges.SuccessorEdgeError):
        successor_edges.load(_write(tmp_path, {"edges": []}))


def test_an_edge_pointing_at_itself_is_rejected(tmp_path):
    with pytest.raises(successor_edges.SuccessorEdgeError):
        successor_edges.load(_write(tmp_path, {"edges": {"item.a": "item.a"}}))


@pytest.mark.parametrize("bad", [None, 7, "", {}])
def test_a_non_string_or_empty_target_is_rejected(tmp_path, bad):
    with pytest.raises(successor_edges.SuccessorEdgeError):
        successor_edges.load(_write(tmp_path, {"edges": {"item.a": bad}}))


def test_apply_adds_the_edge_for_the_entry_it_names():
    entry = {"id": "item.a", "class": "cloth"}

    assert successor_edges.apply(entry, {"item.a": "item.b"})["successorOf"] == "item.b"


def test_apply_with_no_authored_edge_leaves_the_entry_byte_identical():
    # The additivity proof at its smallest: the shipped corpus has no edges, so every emitted entry
    # keeps exactly the shape it had before this mechanism existed.
    entry = {"id": "item.a", "class": "cloth"}
    before = json.dumps(entry, sort_keys=True)

    successor_edges.apply(entry, {})

    assert json.dumps(entry, sort_keys=True) == before
    assert "successorOf" not in entry


def test_an_edge_for_a_different_entry_does_not_leak_onto_this_one():
    entry = {"id": "item.a"}

    successor_edges.apply(entry, {"item.z": "item.y"})

    assert "successorOf" not in entry


# ── the corpus-wide closure check (the gate that must exist before the first edge is authored) ──────

_CORPUS = [
    {"id": "item.humanoid-footing-cloth-001", "frame": "humanoid"},
    {"id": "item.humanoid-footing-leather-001", "frame": "humanoid"},
    {"id": "item.plant-footing-leather-001", "frame": "plant"},
]


def test_no_authored_edges_is_no_violations_by_construction():
    assert successor_edges.closure_violations({}, _CORPUS) == []


def test_a_resolvable_same_frame_edge_closes():
    edges = {"item.humanoid-footing-cloth-001": "item.humanoid-footing-leather-001"}

    assert successor_edges.closure_violations(edges, _CORPUS) == []


def test_a_dangling_target_is_a_violation_naming_both_ids():
    edges = {"item.humanoid-footing-cloth-001": "item.humanoid-footing-plate-999"}

    violations = successor_edges.closure_violations(edges, _CORPUS)

    assert len(violations) == 1
    assert "item.humanoid-footing-cloth-001" in violations[0]
    assert "item.humanoid-footing-plate-999" in violations[0]


def test_an_edge_across_frames_is_a_violation():
    edges = {"item.humanoid-footing-cloth-001": "item.plant-footing-leather-001"}

    violations = successor_edges.closure_violations(edges, _CORPUS)

    assert len(violations) == 1
    assert "never changes frame" in violations[0]


def test_a_source_that_is_not_a_base_type_is_a_violation():
    violations = successor_edges.closure_violations({"item.not-a-base-type": "item.humanoid-footing-leather-001"}, _CORPUS)

    assert len(violations) == 1
    assert "not a base type in the corpus" in violations[0]


# ── the WIRING inside emit.assemble_entry (slice 2c: the passthrough proven, not assumed) ──────────

def _partition_and_answer():
    """A hand-built partition context for the REAL registries, so the emit path runs end to end
    without a model call. `assemble_entry` resolves socketMax/powerBand/enhanceTrack from the shipped
    tuning, so the vocabulary here must be the shipped one, not a fixture."""
    from seedsmith.adapters.items.basetypegen import brief as basetype_brief
    from seedsmith.adapters.items.basetypegen import tuning

    roles = tuning.load_role_registry()
    role, frame, band = "armament-primary", "humanoid", "a"
    info = roles[role]
    ctx = basetype_brief.PartitionContext(
        role=role, frame=frame, band=band,
        frame_role_name=info.frame_role_name(frame),
        class_choices=tuning.load_class_choices(role, frame),
        implicit_families=tuning.load_legal_implicit_families(role, frame),
        existing_ids=(), existing_names=(), existing_enhance_track=None,
    )
    answer = {
        "name": "Successor Edge Probe",
        "class": ctx.class_choices[0],
        "implicitFamily": ctx.implicit_families[0],
        "tags": [tuning.load_tag_vocab()[0]],
        "flavor": "probe",
    }
    return ctx, answer


def test_assemble_entry_attaches_the_authored_edge_for_the_minted_id():
    from seedsmith.adapters.items.basetypegen import emit

    ctx, answer = _partition_and_answer()
    minted = emit.entry_id(ctx.frame, ctx.frame_role_name, ctx.band, 1)
    target = "item.humanoid-armament-primary-b-001"

    entry = emit.assemble_entry(answer, ctx, seq=1, successor_edges_map={minted: target})

    assert entry["id"] == minted
    assert entry["successorOf"] == target


def test_assemble_entry_with_no_authored_edge_emits_no_key_at_all():
    from seedsmith.adapters.items.basetypegen import emit

    ctx, answer = _partition_and_answer()

    entry = emit.assemble_entry(answer, ctx, seq=1, successor_edges_map={})

    assert "successorOf" not in entry
    # The additivity claim at its smallest: the emitted key set is exactly what it was before this
    # mechanism existed, so an empty table cannot change one byte of the corpus.
    assert set(entry) == {
        "id", "nameKey", "name", "frame", "role", "class", "band", "implicit", "socketMax",
        "iconKey", "flavorKey", "flavor", "tags", "enhanceTrack",
    }


def test_assemble_entry_defaults_to_the_shipped_registry():
    from seedsmith.adapters.items.basetypegen import emit

    ctx, answer = _partition_and_answer()

    # No injection: the shipped `_registry/successor-edges.v1.json` is empty today, so the key is
    # absent — which is the proof that the default path (not just the injected one) is wired.
    entry = emit.assemble_entry(answer, ctx, seq=1)

    assert "successorOf" not in entry


# ── the corpus side of the gate: what the generator RUN validates before emitting ──────────────────

def _corpus_dir(tmp_path):
    (tmp_path / "humanoid-footing-a.json").write_text(json.dumps({"kind": "base-type", "entries": [
        {"id": "item.humanoid-footing-cloth-001", "frame": "humanoid"},
        {"id": "item.humanoid-footing-leather-001", "frame": "humanoid"},
    ]}), encoding="utf-8")
    (tmp_path / "plant-footing-b.json").write_text(json.dumps({"kind": "base-type", "entries": [
        {"id": "item.plant-footing-fibre-001", "frame": "plant"},
    ]}), encoding="utf-8")
    # A malformed file must not take the gate down: an unreadable corpus is a different failure.
    (tmp_path / "broken.json").write_text("{ not json", encoding="utf-8")
    return tmp_path


def test_the_corpus_reader_collects_id_and_frame_and_skips_a_broken_file(tmp_path):
    rows = successor_edges.base_type_rows(_corpus_dir(tmp_path))

    assert {r["id"] for r in rows} == {
        "item.humanoid-footing-cloth-001",
        "item.humanoid-footing-leather-001",
        "item.plant-footing-fibre-001",
    }
    assert all(r["frame"] in ("humanoid", "plant") for r in rows)


def test_a_clean_same_frame_edge_has_no_violations_against_the_real_corpus_shape(tmp_path):
    edges = {"item.humanoid-footing-cloth-001": "item.humanoid-footing-leather-001"}

    assert successor_edges.violations_in_corpus(_corpus_dir(tmp_path), edges) == []


def test_a_dangling_edge_is_caught_against_the_corpus(tmp_path):
    edges = {"item.humanoid-footing-cloth-001": "item.humanoid-footing-plate-999"}

    violations = successor_edges.violations_in_corpus(_corpus_dir(tmp_path), edges)

    assert len(violations) == 1
    assert "does not resolve" in violations[0]


def test_a_cross_frame_edge_is_caught_against_the_corpus(tmp_path):
    edges = {"item.humanoid-footing-cloth-001": "item.plant-footing-fibre-001"}

    violations = successor_edges.violations_in_corpus(_corpus_dir(tmp_path), edges)

    assert len(violations) == 1
    assert "never changes frame" in violations[0]


def test_the_shipped_table_validates_clean_against_the_REAL_corpus():
    # The generator's own gate, run exactly as run.py runs it: the shipped base-type tree and the
    # shipped edge table. It holds with edges authored and would hold (vacuously) with none.
    assert successor_edges.violations_in_corpus(
        successor_edges.SHIPPED_BASE_TYPES_DIR, successor_edges.load()) == []


# ── the mechanical re-stamp: the authored registry → the emitted corpus (T37, 2026-09-21) ──────────

def _tmp_corpus(tmp_path, entries):
    (tmp_path / "humanoid-footing-a.json").write_text(
        json.dumps({"kind": "base-type", "entries": entries}), encoding="utf-8")
    return tmp_path


def test_restamp_sets_the_authored_edge_and_removes_one_the_registry_dropped(tmp_path):
    corpus = _tmp_corpus(tmp_path, [
        {"id": "item.a", "frame": "humanoid"},
        {"id": "item.b", "frame": "humanoid", "successorOf": "item.a"},
        {"id": "item.c", "frame": "humanoid"},
    ])

    report = successor_edges.plan_restamp(base_types_dir=corpus, edges={"item.a": "item.b"})

    assert {(c.entry_id, c.previous, c.successor) for c in report.changed} == {
        ("item.a", None, "item.b"), ("item.b", "item.a", None)}
    assert report.unchanged == 1  # item.c: nobody authored it, and it carries no key
    assert successor_edges.apply_restamp(report, base_types_dir=corpus) == 2

    doc = json.loads((corpus / "humanoid-footing-a.json").read_text(encoding="utf-8"))
    by_id = {e["id"]: e for e in doc["entries"]}
    assert by_id["item.a"]["successorOf"] == "item.b"
    assert "successorOf" not in by_id["item.b"]
    assert "successorOf" not in by_id["item.c"]


def test_restamp_preserves_identity_and_records_one_amendment(tmp_path):
    corpus = _tmp_corpus(tmp_path, [
        {"id": "item.a", "frame": "humanoid", "name": "A", "class": "cloth", "socketMax": 3},
        {"id": "item.b", "frame": "humanoid", "name": "B", "class": "leather", "socketMax": 4},
    ])

    successor_edges.apply_restamp(
        successor_edges.plan_restamp(base_types_dir=corpus, edges={"item.a": "item.b"}),
        base_types_dir=corpus, authored_utc="1970-01-01T00:00:00Z")

    doc = json.loads((corpus / "humanoid-footing-a.json").read_text(encoding="utf-8"))
    first = doc["entries"][0]
    # Only `successorOf` moved: identity is preserved field for field.
    assert first["name"] == "A" and first["class"] == "cloth" and first["socketMax"] == 3
    amendment = doc["_meta"]["amendments"][-1]
    assert amendment["batch"] == "successor-edges"
    assert amendment["entries"] == ["item.a"]
    assert amendment["model"] == "successor-edges"


def test_restamp_is_idempotent(tmp_path):
    corpus = _tmp_corpus(tmp_path, [{"id": "item.a", "frame": "humanoid"},
                                    {"id": "item.b", "frame": "humanoid"}])
    edges = {"item.a": "item.b"}

    successor_edges.apply_restamp(successor_edges.plan_restamp(base_types_dir=corpus, edges=edges),
                                  base_types_dir=corpus)

    assert successor_edges.plan_restamp(base_types_dir=corpus, edges=edges).changed == ()


def test_restamp_dry_run_writes_nothing(tmp_path):
    corpus = _tmp_corpus(tmp_path, [{"id": "item.a", "frame": "humanoid"},
                                    {"id": "item.b", "frame": "humanoid"}])
    before = (corpus / "humanoid-footing-a.json").read_text(encoding="utf-8")

    report = successor_edges.plan_restamp(base_types_dir=corpus, edges={"item.a": "item.b"})
    assert successor_edges.apply_restamp(report, base_types_dir=corpus, dry_run=True) == 1

    assert (corpus / "humanoid-footing-a.json").read_text(encoding="utf-8") == before


def test_restamp_refuses_a_dangling_edge_before_writing_anything(tmp_path):
    corpus = _tmp_corpus(tmp_path, [{"id": "item.a", "frame": "humanoid"}])
    before = (corpus / "humanoid-footing-a.json").read_text(encoding="utf-8")

    with pytest.raises(successor_edges.SuccessorEdgeError) as ctx:
        successor_edges.plan_restamp(base_types_dir=corpus, edges={"item.a": "item.missing"})

    assert "does not resolve" in str(ctx.value)
    assert (corpus / "humanoid-footing-a.json").read_text(encoding="utf-8") == before
