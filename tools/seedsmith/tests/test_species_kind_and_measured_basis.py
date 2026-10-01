"""creature-seed R-CS1..R-CS4 (owner rulings, 2026-09-17): the measured-stat basis upgrade and the
`SPECIES_KIND` mark.

Every assertion here is a CONTRACT or a closed vocabulary. Nothing pins a population size — not the
species count, not how many rows are `excluded`, not how many upgrade to `observed`. Those are
readings that move whenever content ships or the game updates, and a test that pinned one would fail
on the normal case and train the next reader to bump the number.
"""
from __future__ import annotations

import json
from pathlib import Path

from seedsmith.adapters.creatures.anchor.derive import derive_species_kind
from seedsmith.adapters.creatures.anchor.schema import (
    BASIS,
    DERIVED_FIELDS,
    OWNERSHIP,
    SPECIES_KIND,
    build_anchor_schema,
)
from seedsmith.adapters.creatures.dump_ctx import load_creature_dump_ctx
from seedsmith.adapters.creatures.power.measured import (
    TYPE_BASE_STATS_FILE,
    load_measured_base_stats,
    resolves_natively,
)
from seedsmith.adapters.creatures.power.parse import parse_power_seed

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

REAL_DUMP_DIR = _owned("data/seed/creatures/_dump")
REAL_ANCHORS_DIR = _owned("data/seed/creatures/species")


# --- the closed vocabulary itself (a declaration — pinning it IS the contract) ------------------


def test_species_kind_is_a_closed_three_value_vocabulary():
    # R-CS4: a mark vocabulary is a closed set the code owns and a human changes by review — the
    # mirror image of the species roster, which is a population and must never be an enum. Adding a
    # fourth value is a reviewed change to this line, which is exactly why it is pinned here.
    assert SPECIES_KIND == ("creature", "mimic", "excluded")


def test_species_kind_is_derived_and_therefore_never_model_authored():
    assert OWNERSHIP["speciesKind"] == "DERIVED"
    assert "speciesKind" in DERIVED_FIELDS
    assert "speciesKind" in build_anchor_schema()["properties"]


def test_species_kind_is_a_separate_field_from_basis():
    # Collapsing them would lose the distinction R-CS3 exists to preserve: `basis: blocked` means
    # "no text to derive power from" — a real creature can legitimately be blocked — which is a
    # different statement from "not a creature". No value may appear in both vocabularies.
    assert set(SPECIES_KIND).isdisjoint(set(BASIS))


# --- the derivation rule (R-CS2/R-CS3) ---------------------------------------------------------


def test_a_natively_resolving_row_is_a_creature():
    assert derive_species_kind(resolves_natively=True) == "creature"


def test_a_row_that_resolves_to_nothing_and_declares_nothing_is_excluded():
    assert derive_species_kind(resolves_natively=False) == "excluded"


def test_a_declared_mimic_is_a_mimic_even_though_its_id_is_not_natively_its_own():
    # R-CS2's whole point: a species is valid when it has a resolvable id by EITHER route. A
    # borrowed id is a legitimate route, not a defect — refusing it would close the corpus to
    # authored content.
    assert derive_species_kind(resolves_natively=False, mimic_of=17) == "mimic"


def test_an_existing_mimic_declaration_survives_re_derivation():
    # A mimic is a DELIBERATE declaration. A pass that re-derived it away because the borrowed id
    # happens to resolve natively would erase the one thing the declaration records.
    assert derive_species_kind(resolves_natively=True, current="mimic") == "mimic"
    assert derive_species_kind(resolves_natively=False, current="mimic") == "mimic"


def test_marking_never_refuses_a_row():
    # R-CS3: marking is tracking, deleting is untracking. Every input produces a mark; nothing here
    # raises, drops, or otherwise removes a row from the corpus.
    for natively in (True, False):
        for mimic in (None, 3):
            assert derive_species_kind(resolves_natively=natively, mimic_of=mimic) in SPECIES_KIND


# --- the measured-stat basis upgrade (R-CS1) ---------------------------------------------------


def test_measured_stats_outrank_a_spawn_sample_on_the_observed_rung():
    # Not a fifth basis — a second, better supplier to the rung that already exists. The static
    # table is the number the game defines; a sample is one observation of one spawn.
    seed = parse_power_seed(
        side="plant", type_id=1, stats_observed=True, hp=111, attack=222,
        flavor_text="韧性：999\n伤害：888", measured_hp=300, measured_attack=20)
    assert seed.basis == "observed"
    assert (seed.toughness, seed.damage) == (300, 20)


def test_measured_stats_upgrade_a_species_that_had_no_observation_at_all():
    seed = parse_power_seed(
        side="plant", type_id=1, stats_observed=False, hp=None, attack=None,
        flavor_text="lore only, no numbers", measured_hp=640000, measured_attack=0)
    assert seed.basis == "observed"
    assert seed.toughness == 640000


def test_absent_measured_stats_leave_every_pre_capture_path_exactly_as_it_was():
    # Every fixture and every pre-2026-09-17 dump tree keeps its previous behaviour.
    stated = parse_power_seed(
        side="plant", type_id=1, stats_observed=False, hp=None, attack=None,
        flavor_text="韧性：400")
    assert stated.basis == "stated" and stated.toughness == 400
    blocked = parse_power_seed(
        side="plant", type_id=2, stats_observed=False, hp=None, attack=None, flavor_text=None)
    assert blocked.basis == "blocked"


def test_a_text_number_disagreeing_with_the_measured_one_is_recorded_not_resolved():
    seed = parse_power_seed(
        side="plant", type_id=1, stats_observed=False, hp=None, attack=None,
        flavor_text="韧性：20000", measured_hp=4000, measured_attack=0)
    assert seed.toughness == 4000              # the measurement wins
    assert seed.text_toughness == 20000        # the claim is kept
    assert seed.disagreement_toughness is True


# --- the loader's own refusals -----------------------------------------------------------------


def test_a_dump_tree_with_no_capture_yields_no_oracle_rather_than_no_resolution(tmp_path):
    # The failure this guards: reading an absent capture as "nothing resolves" would mark an entire
    # corpus `excluded` in one pass.
    assert load_measured_base_stats(tmp_path) == {}
    assert resolves_natively("plant", 0, {}) is False


def test_a_malformed_capture_is_dropped_never_half_read(tmp_path):
    (tmp_path / TYPE_BASE_STATS_FILE).write_text("{ not json", encoding="utf-8")
    assert load_measured_base_stats(tmp_path) == {}


def test_a_fractional_magnitude_is_dropped_rather_than_truncated_into_a_smaller_one(tmp_path):
    (tmp_path / TYPE_BASE_STATS_FILE).write_text(json.dumps({
        "entries": [{
            "side": "plant", "typeId": 7, "typeName": "Frac", "capturedUtc": "t",
            "statsJson": json.dumps({"hpBase": 300.5, "attackBase": 20.0}),
        }]}), encoding="utf-8")
    row = load_measured_base_stats(tmp_path)[("plant", 7)]
    assert row.hp is None        # 300.5 is a capture defect, not "300"
    assert row.attack == 20      # 20.0 is exactly 20


# --- against the real committed corpus (joins and closure, never counts) ------------------------


def _real_anchors() -> "list[dict]":
    rows: "list[dict]" = []
    for path in sorted(REAL_ANCHORS_DIR.rglob("*.json")):
        if path.name.startswith("_"):
            continue
        rows.extend(json.loads(path.read_text(encoding="utf-8")))
    return rows


def test_the_real_capture_is_keyed_uniquely_and_carries_a_stamp_per_row():
    measured = load_measured_base_stats(REAL_DUMP_DIR)
    if not measured:
        return  # no capture committed in this tree — a supported state, not a failure
    for key, row in measured.items():
        assert key == (row.side, row.type_id)
        assert row.side in ("plant", "zombie")
        assert row.captured_utc, f"{key} has no capture stamp"


def test_every_real_anchor_carries_a_kind_from_the_closed_vocabulary():
    anchors = _real_anchors()
    if not anchors or "speciesKind" not in anchors[0]:
        return  # pre-re-derivation tree
    for a in anchors:
        assert a["speciesKind"] in SPECIES_KIND, f"{a['speciesId']} has an unknown speciesKind"


def test_every_real_creature_row_actually_resolves_and_every_excluded_row_actually_does_not():
    # The closure check R-CS4 says falls out of the enum: an id is legitimate when
    # `kind == "creature"` resolves natively or `kind == "mimic"` names the id it borrows. This is a
    # join, not a count — it holds at 904 species and at 9,004.
    measured = load_measured_base_stats(REAL_DUMP_DIR)
    anchors = _real_anchors()
    if not measured or not anchors or "speciesKind" not in anchors[0]:
        return
    for a in anchors:
        resolved = resolves_natively(a["side"], a["gameTypeId"], measured)
        if a["speciesKind"] == "creature":
            assert resolved, f"{a['speciesId']} is marked `creature` but resolves to no game type"
        elif a["speciesKind"] == "excluded":
            assert not resolved, f"{a['speciesId']} is marked `excluded` but resolves natively"


def test_an_excluded_row_is_still_present_and_joinable():
    # R-CS3's load-bearing property: excluded from roster READINGS, never from the corpus, so
    # type-weights / build plans / family memberships that already reference the id keep working.
    anchors = _real_anchors()
    if not anchors or "speciesKind" not in anchors[0]:
        return
    excluded = [a for a in anchors if a["speciesKind"] == "excluded"]
    for a in excluded:
        assert a.get("speciesId")
        assert isinstance(a.get("gameTypeId"), int)
        assert a.get("side") in ("plant", "zombie")


def test_the_real_dump_context_exposes_the_capture_it_overlaid():
    ctx = load_creature_dump_ctx(REAL_DUMP_DIR)
    if ctx is None:
        return
    # One place decides what the dump says about a species' power: every seed backed by the capture
    # must read `observed`, or two consumers could disagree about the same species.
    for seed in ctx.seeds:
        if (seed.side, seed.type_id) in ctx.measured:
            m = ctx.measured[(seed.side, seed.type_id)]
            if m.hp is not None or m.attack is not None:
                assert seed.basis == "observed"
