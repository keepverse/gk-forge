"""Tests for `enhancement-milestones-gen` (item-seedgen module 11,
`docs/architecture/item-seedgen/spec-enhancement-milestones-gen.md`).

Three groups:
1. Vocabulary/schema/emit unit tests — the closed op/channel vocabularies, id/slug minting.
2. Real-corpus regression tests — assertions made directly against the shipped
   `gk-data/packs/fusion/data/seed/items/enhancement-milestones/milestones.json`, not a fixture, so a drift in the real
   data is caught here.
3. Harness integration tests — `RunLedger` resume/reconcile/overwrite wired through this module's
   own `run.py`, all against a `tmp_path` ledger/corpus, never the real repo files.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from seedsmith.adapters.items.milestonegen import brief as brief_mod
from seedsmith.adapters.items.milestonegen import emit as emit_mod
from seedsmith.adapters.items.milestonegen import run as run_mod
from seedsmith.adapters.items.milestonegen import schema as schema_mod
from seedsmith.pipeline.run_ledger import RunLedger

REAL_CORPUS_PATH = (
    Path(__file__).resolve().parents[3]
    / "data" / "seed" / "items" / "enhancement-milestones" / "milestones.json"
)


def _load_real_corpus() -> dict:
    return json.loads(REAL_CORPUS_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------
# 1. Vocabulary / schema / emit
# ---------------------------------------------------------------------------------------------


def test_stat_modify_ops_matches_the_real_AtomKindRegistry_vocabulary():
    # AtomKindRegistry.cs:349-357 / 517: "Ops are Flat|Increased|More — effects cannot emit
    # Override". PascalCase, three entries, Override deliberately absent.
    assert schema_mod.STAT_MODIFY_OPS == ("Flat", "Increased", "More")
    assert schema_mod.ILLEGAL_STAT_MODIFY_OP == "Override"
    assert schema_mod.ILLEGAL_STAT_MODIFY_OP not in schema_mod.STAT_MODIFY_OPS


def test_primary_channels_matches_StatChannels_All_transcription():
    # ModifierOp.cs:69-75 — literal transcription, 23 entries, declaration order preserved.
    assert len(schema_mod.PRIMARY_CHANNELS) == 23
    assert schema_mod.PRIMARY_CHANNELS[:3] == ("hp", "maxHp", "atk")
    assert "armorFlat" in schema_mod.PRIMARY_CHANNELS
    # The real bare "armor" string is NOT a primary channel — armorFlat is. This generator must
    # never offer the non-existent "armor" spelling.
    assert "armor" not in schema_mod.PRIMARY_CHANNELS
    assert "crit-rate" not in schema_mod.PRIMARY_CHANNELS
    assert "dodge" not in schema_mod.PRIMARY_CHANNELS


def test_channel_tuning_is_a_strict_subset_of_primary_channels_with_legal_op_and_band():
    primary = set(schema_mod.PRIMARY_CHANNELS)
    for channel, (op, band) in schema_mod.CHANNEL_TUNING.items():
        assert channel in primary, f"{channel!r} is not a real PrimaryChannels member"
        assert op in schema_mod.STAT_MODIFY_OPS, f"{channel!r} maps to illegal op {op!r}"
        assert op != schema_mod.ILLEGAL_STAT_MODIFY_OP
        assert band in schema_mod.POWER_BANDS, f"{channel!r} maps to unrecognized band {band!r}"


def test_channel_vocab_is_sorted_and_deterministic():
    assert schema_mod.channel_vocab() == tuple(sorted(schema_mod.CHANNEL_TUNING))
    assert schema_mod.channel_vocab() == schema_mod.channel_vocab()


def test_answer_schema_never_offers_the_fields_code_must_resolve():
    schema = schema_mod.answer_schema()
    fields = schema_mod.schema_field_names(schema)
    # P1: the model picks identity (name/flavor/channel/tags), never op/powerBand/id/nameKey/
    # runtimeFamily — those are always code-derived.
    for forbidden in ("op", "powerBand", "id", "nameKey", "runtimeFamily", "kindId"):
        assert forbidden not in fields, f"{forbidden!r} must never be an authorable field"
    assert set(fields) == {"name", "flavor", "channel", "tags", "blocked"}


def test_answer_schema_channel_enum_matches_the_offered_vocabulary():
    schema = schema_mod.answer_schema(channels=("maxHp", "atk"), tags=("offensive",))
    assert schema["properties"]["channel"]["enum"] == ["maxHp", "atk"]
    assert schema["properties"]["tags"]["items"]["enum"] == ["offensive"]


def test_answer_schema_refuses_an_empty_vocabulary():
    with pytest.raises(ValueError):
        schema_mod.answer_schema(channels=())
    with pytest.raises(ValueError):
        schema_mod.answer_schema(tags=())


def test_answer_schema_name_pattern_matches_every_real_entrys_name():
    import re
    pattern = re.compile(schema_mod.answer_schema()["properties"]["name"]["pattern"])
    doc = _load_real_corpus()
    for entry in doc["entries"]:
        assert pattern.match(entry["name"]), (
            f"{entry['name']!r} does not match the schema's own naming convention"
        )


def test_build_brief_lists_channels_and_tags_and_the_naming_convention():
    text = brief_mod.build_brief(("maxHp", "atk"), ("offensive", "defensive"), ("Enhancement Vigor",))
    assert "maxHp" in text
    assert "atk" in text
    assert "offensive" in text
    assert "Enhancement Vigor" in text
    assert "Enhancement <Word>" in text
    assert "never chosen by you" not in text  # sanity: no stray placeholder text


def test_build_brief_refuses_empty_vocabularies():
    with pytest.raises(ValueError):
        brief_mod.build_brief((), ("offensive",))
    with pytest.raises(ValueError):
        brief_mod.build_brief(("maxHp",), ())


def test_slug_from_name_matches_the_real_atom_enhance_convention():
    assert emit_mod.slug_from_name("Enhancement Vigor") == "vigor"
    assert emit_mod.slug_from_name("Enhancement Edge") == "edge"


def test_slug_from_name_kebabs_a_multi_word_tail():
    assert emit_mod.slug_from_name("Enhancement Storm Ward") == "storm-ward"


def test_slug_from_name_refuses_a_name_missing_the_prefix():
    with pytest.raises(emit_mod.MintRefused):
        emit_mod.slug_from_name("Vigor Enhancement")


def test_runtime_family_and_name_key_follow_the_real_atom_dot_name_convention():
    slug = emit_mod.slug_from_name("Enhancement Ferocity")
    family = emit_mod.runtime_family_for(slug)
    key = emit_mod.name_key_for(slug)
    assert family == "atom.enhance-ferocity"
    assert key == "enh.enhance-ferocity"
    assert emit_mod.RUNTIME_FAMILY_RE.match(family)
    assert emit_mod.ENHANCE_FAMILY_RE.match(family)


def test_next_entry_id_continues_past_the_highest_existing_and_starts_at_001_when_empty():
    assert emit_mod.next_entry_id(set()) == "enh.001"
    assert emit_mod.next_entry_id({f"enh.{n:03d}" for n in range(1, 11)}) == "enh.011"
    # Non-standard ids are ignored, never crash the parse.
    assert emit_mod.next_entry_id({"enh.001", "not-an-id", "enh.003"}) == "enh.004"


def test_resolve_op_and_band_never_returns_override_and_only_real_bands():
    for channel in schema_mod.CHANNEL_TUNING:
        op, band = emit_mod.resolve_op_and_band(channel)
        assert op in schema_mod.STAT_MODIFY_OPS
        assert op != "Override"
        assert band in schema_mod.POWER_BANDS


def test_resolve_op_and_band_refuses_a_channel_outside_the_offered_tuning():
    with pytest.raises(emit_mod.MintRefused):
        emit_mod.resolve_op_and_band("armor")  # the real gap this module deliberately never offers
    with pytest.raises(emit_mod.MintRefused):
        emit_mod.resolve_op_and_band("not-a-channel")


def test_entry_for_produces_the_real_corpus_shape():
    entry = emit_mod.entry_for(
        entry_id="enh.011", name="Enhancement Ferocity", channel="maxHp",
        flavor="A steady boost to maximum health.", tags=["defensive"],
    )
    d = entry.to_dict()
    real_entry = _load_real_corpus()["entries"][0]
    assert set(d.keys()) == set(real_entry.keys())
    assert d["id"] == "enh.011"
    assert d["nameKey"] == "enh.enhance-ferocity"
    assert d["runtimeFamily"] == "atom.enhance-ferocity"
    assert d["kindId"] == "stat.modify"
    assert d["params"] == {"channel": "maxHp", "op": "Flat"}
    assert d["powerBand"] == "medium"
    assert d["tags"] == ["defensive"]


def test_entry_for_refuses_empty_tags():
    with pytest.raises(emit_mod.MintRefused):
        emit_mod.entry_for(entry_id="enh.011", name="Enhancement Ferocity", channel="maxHp",
                            flavor="x", tags=[])


def test_entry_for_dedupes_repeated_tags_preserving_order():
    entry = emit_mod.entry_for(entry_id="enh.011", name="Enhancement Ferocity", channel="maxHp",
                                flavor="x", tags=["defensive", "offensive", "defensive"])
    assert entry.to_dict()["tags"] == ["defensive", "offensive"]


# ---------------------------------------------------------------------------------------------
# 2. Real-corpus regression
# ---------------------------------------------------------------------------------------------


def test_real_corpus_stat_modify_ops_are_all_in_the_real_closed_vocabulary():
    doc = _load_real_corpus()
    stat_modify = [e for e in doc["entries"] if e["kindId"] == "stat.modify"]
    assert stat_modify, "expected at least one stat.modify entry in the real corpus"
    for entry in stat_modify:
        op = entry["params"]["op"]
        assert op in schema_mod.STAT_MODIFY_OPS, (
            f"{entry['id']} uses op {op!r}, outside the real AtomKindRegistry vocabulary"
        )
        assert op != "Override"


def test_real_corpus_channel_gap_is_exactly_the_four_known_entries():
    """Documents a real finding rather than silently tolerating it: four of the ten hand-authored
    entries use a channel string outside `stat.modify`'s own real `PrimaryChannels` vocabulary —
    `actionSpeed` (not a primary channel; `attackSpeedAdder`/`attackInterval` are), `crit-rate` and
    `dodge` (neither a primary channel at all), and `armor` (`armorFlat` is the real one). This
    generator's own `CHANNEL_TUNING` cannot reproduce the gap (proven above), but the gap is real,
    pre-existing, hand-authored content this module does not touch — pinned here so a future fix
    updates this test deliberately instead of the gap silently disappearing or growing."""
    doc = _load_real_corpus()
    stat_modify = [e for e in doc["entries"] if e["kindId"] == "stat.modify"]
    primary = set(schema_mod.PRIMARY_CHANNELS)
    out_of_vocab = {
        e["id"]: e["params"]["channel"]
        for e in stat_modify if e["params"]["channel"] not in primary
    }
    assert out_of_vocab == {
        "enh.004": "actionSpeed", "enh.005": "crit-rate", "enh.008": "armor", "enh.010": "dodge",
    }


def test_real_corpus_runtime_families_all_follow_the_atom_enhance_convention():
    doc = _load_real_corpus()
    for entry in doc["entries"]:
        family = entry["runtimeFamily"]
        assert emit_mod.RUNTIME_FAMILY_RE.match(family), f"{family!r} fails atom.<name> grammar"
        assert emit_mod.ENHANCE_FAMILY_RE.match(family), (
            f"{family!r} fails this module's own atom.enhance-<name> convention"
        )


def test_real_corpus_ids_and_families_are_unique():
    doc = _load_real_corpus()
    ids = [e["id"] for e in doc["entries"]]
    families = [e["runtimeFamily"] for e in doc["entries"]]
    assert len(ids) == len(set(ids))
    assert len(families) == len(set(families))


def test_a_freshly_generated_entrys_runtime_family_is_a_real_well_formed_id_a_future_consumer_could_reference():
    """Stands in for `base-types-gen`'s own `enhanceTrack[].family` reference resolution — that
    module does not exist yet (parallel work), so this only proves OUR side of the contract: a
    generated `runtimeFamily` is real, well-formed, and does not collide with the existing corpus,
    which is everything a future hard-reference resolver would need to see."""
    existing = {e["id"]: e for e in _load_real_corpus()["entries"]}
    entry = emit_mod.entry_for(
        entry_id=emit_mod.next_entry_id(set(existing)),
        name="Enhancement Ferocity", channel="atk", flavor="A sharper offensive edge.",
        tags=["offensive"],
    )
    d = entry.to_dict()
    assert emit_mod.RUNTIME_FAMILY_RE.match(d["runtimeFamily"])
    existing_families = {e["runtimeFamily"] for e in existing.values()}
    assert d["runtimeFamily"] not in existing_families
    assert d["id"] not in existing


# ---------------------------------------------------------------------------------------------
# 3. Harness integration — RunLedger resume / reconcile / overwrite, via run.py
# ---------------------------------------------------------------------------------------------


def _fake_call_for(channel: str = "maxHp", word: str = "Ferocity", *, block: bool = False):
    def call(brief: str, schema: dict) -> dict:
        if block:
            return {"blocked": "no legal channel fits"}
        return {
            "name": f"Enhancement {word}",
            "flavor": "A generated milestone family for testing.",
            "channel": channel,
            "tags": ["offensive"],
        }
    return call


def test_plan_run_mints_sequential_draw_slots_starting_from_zero():
    ledger = RunLedger(Path("unused-does-not-need-to-exist.json"))

    class _EmptyLedger:
        def read_done(self):
            return {}

    plan = run_mod.plan_run(count=3, ledger=_EmptyLedger(), existing={})
    assert [s.subject_id for s in plan.subjects] == [
        "milestone-draw-000", "milestone-draw-001", "milestone-draw-002",
    ]


def test_run_draws_marks_the_ledger_done_and_partitions_fresh_vs_blocked(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.json")
    plan = run_mod.plan_run(count=2, ledger=ledger, existing={})

    calls = iter([_fake_call_for(word="Ferocity"), _fake_call_for(block=True)])
    fresh, blocked = run_mod.run_draws(plan, ledger=ledger, call=lambda b, s: next(calls)(b, s))

    assert len(fresh) == 1
    (entry,) = fresh.values()
    assert entry["runtimeFamily"] == "atom.enhance-ferocity"
    assert len(blocked) == 1
    assert "milestone-draw-001" in blocked

    done = ledger.read_done()
    assert set(done) == {"milestone-draw-000"}
    assert done["milestone-draw-000"]["runtimeFamily"] == "atom.enhance-ferocity"


def test_run_draws_does_not_checkpoint_before_persist_callback(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.json")
    plan = run_mod.plan_run(count=1, ledger=ledger, existing={})

    def persist(_entry):
        raise RuntimeError("simulated corpus write failure")

    with pytest.raises(RuntimeError, match="corpus write failure"):
        run_mod.run_draws(plan, ledger=ledger, call=_fake_call_for(word="Retry Me"), persist=persist)
    assert ledger.read_done() == {}


def test_resume_never_repeats_a_committed_draw_across_two_plan_run_calls(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.json")
    plan1 = run_mod.plan_run(count=2, ledger=ledger, existing={})
    fresh1, _ = run_mod.run_draws(
        plan1, ledger=ledger,
        call=lambda b, s: _fake_call_for(word="One")(b, s)
        if "milestone-draw-000" not in ledger.read_done()
        else _fake_call_for(word="Two")(b, s),
    )
    run_mod.write_corpus(fresh1, existing={}, path=tmp_path / "milestones.json")
    # Second invocation of the whole pipeline (simulating a fresh process) must continue from
    # draw index 2, never re-issuing milestone-draw-000/001.
    plan2 = run_mod.plan_run(
        count=2, ledger=ledger,
        existing=run_mod.load_existing(tmp_path / "milestones.json"),
    )
    assert [s.subject_id for s in plan2.subjects] == ["milestone-draw-002", "milestone-draw-003"]
    assert len(fresh1) == 2


def test_reconcile_resurfaces_a_draw_whose_recorded_entry_was_deleted_from_the_corpus(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.json")
    ledger.mark_done("milestone-draw-000", {
        "entryId": "enh.011", "runtimeFamily": "atom.enhance-ferocity",
    })
    # The corpus on disk no longer has enh.011 (a hand edit removed it, or it never landed).
    current_corpus: "dict[str, dict]" = {}

    needing_work = ledger.plan(
        ["milestone-draw-000"],
        lambda sid, entry: run_mod.is_valid(sid, entry, existing=current_corpus),
    )
    assert needing_work == ["milestone-draw-000"]


def test_plan_run_reuses_an_invalid_ledger_slot_before_allocating_new_draws(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.json")
    ledger.mark_done("milestone-draw-000", {
        "entryId": "enh.999", "runtimeFamily": "atom.enhance-ghost",
    })
    plan = run_mod.plan_run(count=1, ledger=ledger, existing={})
    assert plan.subjects[0].subject_id == "milestone-draw-000"


def test_reconcile_leaves_a_draw_alone_when_its_entry_still_matches(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.json")
    ledger.mark_done("milestone-draw-000", {
        "entryId": "enh.011", "runtimeFamily": "atom.enhance-ferocity",
    })
    current_corpus = {"enh.011": {"runtimeFamily": "atom.enhance-ferocity"}}

    needing_work = ledger.plan(
        ["milestone-draw-000"],
        lambda sid, entry: run_mod.is_valid(sid, entry, existing=current_corpus),
    )
    assert needing_work == []


def test_reconcile_resurfaces_a_draw_whose_runtime_family_was_renamed_out_from_under_it(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.json")
    ledger.mark_done("milestone-draw-000", {
        "entryId": "enh.011", "runtimeFamily": "atom.enhance-ferocity",
    })
    # enh.011 still exists, but a hand edit renamed its runtimeFamily out from under the ledger.
    current_corpus = {"enh.011": {"runtimeFamily": "atom.enhance-something-else"}}

    needing_work = ledger.plan(
        ["milestone-draw-000"],
        lambda sid, entry: run_mod.is_valid(sid, entry, existing=current_corpus),
    )
    assert needing_work == ["milestone-draw-000"]


def test_overwrite_by_id_bypasses_validity_for_named_ids_only(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.json")
    ledger.mark_done("milestone-draw-000", {"entryId": "enh.011", "runtimeFamily": "atom.enhance-a"})
    ledger.mark_done("milestone-draw-001", {"entryId": "enh.012", "runtimeFamily": "atom.enhance-b"})

    forced = ledger.force(["milestone-draw-000"], "ids")
    assert forced == ["milestone-draw-000"]


def test_overwrite_all_requires_the_literal_all_string(tmp_path):
    ledger = RunLedger(tmp_path / "ledger.json")
    ledger.mark_done("milestone-draw-000", {"entryId": "enh.011", "runtimeFamily": "atom.enhance-a"})

    assert ledger.force(["milestone-draw-000"], "all") == ["milestone-draw-000"]
    with pytest.raises(ValueError):
        ledger.force(["milestone-draw-000"], "everything")  # anything but 'ids'/'all' is refused


def test_write_corpus_is_additive_and_never_drops_an_existing_entry(tmp_path):
    out_path = tmp_path / "milestones.json"
    existing = {e["id"]: e for e in _load_real_corpus()["entries"]}
    fresh = {"enh.011": emit_mod.entry_for(
        entry_id="enh.011", name="Enhancement Ferocity", channel="maxHp",
        flavor="x", tags=["offensive"],
    ).to_dict()}

    run_mod.write_corpus(fresh, existing=existing, path=out_path)
    written = json.loads(out_path.read_text(encoding="utf-8"))
    written_ids = {e["id"] for e in written["entries"]}
    assert written_ids == set(existing) | {"enh.011"}


def test_cli_dry_run_prints_a_sample_brief_and_makes_no_model_calls(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run_mod, "OUTPUT_PATH", tmp_path / "milestones.json")
    monkeypatch.setattr(run_mod, "DEFAULT_LEDGER_PATH", tmp_path / "ledger.json")
    exit_code = run_mod.main(["--dry-run", "--count", "2"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "no model calls made" in out
    assert "Enhancement <Word>" in out


def test_cli_refuses_a_real_run_with_no_model_call_wired(tmp_path, monkeypatch):
    """⛔ Renamed in spirit 2026-09-08, unchanged in assertion — see basetypegen's identical test
    for the full account: this now refuses for lack of `--write`, not lack of wiring."""
    monkeypatch.setattr(run_mod, "OUTPUT_PATH", tmp_path / "milestones.json")
    monkeypatch.setattr(run_mod, "DEFAULT_LEDGER_PATH", tmp_path / "ledger.json")
    with pytest.raises(SystemExit):
        run_mod.main([])


def test_cli_write_without_endpoint_refuses(tmp_path, monkeypatch):
    """Refuse only when the *resolved* transport has no endpoint (CLI empty + config empty)."""
    from seedsmith.pipeline.llm_caller import LlmCallerConfig
    monkeypatch.setattr(run_mod, "OUTPUT_PATH", tmp_path / "milestones.json")
    monkeypatch.setattr(run_mod, "DEFAULT_LEDGER_PATH", tmp_path / "ledger.json")
    monkeypatch.setattr(
        "seedsmith.pipeline.llm_caller.resolve_live_transport",
        lambda *a, **k: LlmCallerConfig(endpoint="", model="x"))
    with pytest.raises(SystemExit):
        run_mod.main(["--write"])



def test_cli_a_real_live_run_writes_a_real_corpus_file(tmp_path, monkeypatch, capsys):
    """⛔ Real gap, closed 2026-09-08 — see basetypegen's identical test for the full account:
    `--write --endpoint <url>` was unreachable before this."""
    monkeypatch.setattr(run_mod, "OUTPUT_PATH", tmp_path / "milestones.json")
    monkeypatch.setattr(run_mod, "DEFAULT_LEDGER_PATH", tmp_path / "ledger.json")

    called_with = {}

    def _fake_live_answer_caller(config):
        called_with["config"] = config
        return _fake_call_for(word="Live-Wired")

    monkeypatch.setattr("seedsmith.pipeline.llm_caller.live_answer_caller",
                        _fake_live_answer_caller)

    exit_code = run_mod.main(["--count", "1", "--write", "--endpoint", "http://unit-test-endpoint",
                             "--model", "unit-test-model"])

    assert exit_code == 0
    assert called_with["config"].endpoint == "http://unit-test-endpoint"
    assert called_with["config"].model == "unit-test-model"
    written = json.loads((tmp_path / "milestones.json").read_text(encoding="utf-8"))
    names = {e["name"] for e in written["entries"]}
    assert "Enhancement Live-Wired" in names
    summary = json.loads(capsys.readouterr().out)
    assert summary == {"planned": 1, "fresh": 1, "blocked": 0, "blockedReasons": {}}


def test_cli_overwrite_all_and_by_id_both_route_through_the_real_ledger(tmp_path, monkeypatch, capsys):
    ledger_path = tmp_path / "ledger.json"
    monkeypatch.setattr(run_mod, "OUTPUT_PATH", tmp_path / "milestones.json")
    monkeypatch.setattr(run_mod, "DEFAULT_LEDGER_PATH", ledger_path)

    ledger = RunLedger(ledger_path)
    ledger.mark_done("milestone-draw-000", {"entryId": "enh.011", "runtimeFamily": "atom.enhance-a"})

    exit_code = run_mod.main(["--overwrite", "milestone-draw-000"])
    assert exit_code == 0
    assert "milestone-draw-000" in capsys.readouterr().out

    exit_code = run_mod.main(["--overwrite", "all"])
    assert exit_code == 0
    assert "milestone-draw-000" in capsys.readouterr().out


def test_cli_force_is_an_accepted_alias_for_overwrite(tmp_path, monkeypatch, capsys):
    """seedsmith-content-standard Task 6: `--force` is `content-completeness-core`'s own naming
    convention (`RunLedger.force()`, `generate_commander_effects.py --force`); this CLI's real,
    already-shipped flag is `--overwrite` (spec-enhancement-milestones-gen.md). Added as a second
    flag string on the same argument rather than a rename, so nothing already typing `--overwrite`
    breaks."""
    ledger_path = tmp_path / "ledger.json"
    monkeypatch.setattr(run_mod, "OUTPUT_PATH", tmp_path / "milestones.json")
    monkeypatch.setattr(run_mod, "DEFAULT_LEDGER_PATH", ledger_path)

    ledger = RunLedger(ledger_path)
    ledger.mark_done("milestone-draw-000", {"entryId": "enh.011", "runtimeFamily": "atom.enhance-a"})

    exit_code = run_mod.main(["--force", "milestone-draw-000"])
    assert exit_code == 0
    assert "milestone-draw-000" in capsys.readouterr().out
