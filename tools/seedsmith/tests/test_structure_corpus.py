"""Tests for `seedsmith.adapters.structures.generate_corpus` (spec-structure-corpus.md, base-defense
module 24). Zero model calls anywhere in the module under test — this file itself never imports an
LLM client, and asserts the module under test does not either (`test_zero_model_calls_in_this_module`).

    python -m pytest gk-forge/tools/seedsmith/tests/test_structure_corpus.py -v
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.structures.anchor.schema import build_structure_anchor_schema  # noqa: E402
from seedsmith.adapters.structures.generate_corpus import (  # noqa: E402
    ALL_ROWS,
    AUTHORED_ROWS,
    DUMPED_ROWS,
    file_tree,
    write_corpus,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
TUNING_PATH = REPO_ROOT / "data" / "tuning" / "structure-seed.v1.json"

_KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SCHEMA_FIELDS = frozenset(build_structure_anchor_schema()["properties"].keys())


def test_every_row_validates_against_the_real_anchor_schema():
    # generate_corpus._row() already calls jsonschema.validate at construction time, so a defect
    # here would fail at IMPORT time -- this test exists so a future refactor that stops calling
    # _row() (e.g. building the dict by hand) cannot silently skip validation.
    for row in ALL_ROWS:
        assert set(row["anchor"].keys()) == _SCHEMA_FIELDS


_MAGNITUDE_FIELDS = frozenset({
    "structureKind", "cost", "yieldMultiplierMilli", "buildTurns", "capacityBonus",
    "flatYieldPerTurn", "constructRubbleCost", "constructIronworkCost", "materialTier",
    "blocksMovement", "blocksLineOfFire", "obstacleKind", "coverPowerMilli", "coverRadius",
    "entryStaminaMultiplierMilli", "visionRangeTiles", "containerId",
})


def test_no_row_has_a_container_yet():
    # structure-instantiate (module 26): giving a structure real traits/actions is
    # structure-planner/-pipeline's (27/28) own content decision, not this corpus's. Every row
    # today correctly has containerId=None -- asserted directly so a future accidental assignment
    # here (rather than through 27/28's own real process) is caught.
    for row in DUMPED_ROWS:
        assert row["magnitudes"]["containerId"] is None, row["id"]


def test_only_dumped_rows_carry_magnitudes():
    # module 25's own gap (see generate_corpus.py's top-of-file note): a `magnitudes` block makes
    # a row catalog-loadable. Only the 8 dumped rows have real, pre-existing numbers to carry;
    # the 17 new anchor-only rows stay identity-registered until structure-planner (27) assigns
    # each a real number -- asserted here so that boundary cannot silently blur.
    for row in DUMPED_ROWS:
        assert set(row["magnitudes"].keys()) == _MAGNITUDE_FIELDS, row["id"]
    for row in AUTHORED_ROWS:
        assert "magnitudes" not in row, f"{row['id']} should not yet have real magnitudes"


def test_dumped_magnitudes_match_the_real_tuning_files_not_a_hand_copied_number():
    # A genuine regression guard, not a duplicated literal: reads gk-core/data/tuning/loam.v4.json and
    # siege.v1.json directly (the SAME files StructureCatalog.cs's own Loam.LoamPolicy/
    # SiegeTuningPolicy wrappers read) rather than re-asserting the numbers this test file would
    # otherwise just be trusting generate_corpus.py to have copied correctly.
    loam = json.loads((REPO_ROOT / "data" / "tuning" / "loam.v4.json").read_text(encoding="utf-8"))["structures"]
    siege = json.loads((REPO_ROOT / "data" / "tuning" / "siege.v1.json").read_text(encoding="utf-8"))
    by_id = {row["id"]: row["magnitudes"] for row in DUMPED_ROWS}

    assert by_id["well"]["cost"] == loam["wellCost"]
    assert by_id["well"]["yieldMultiplierMilli"] == loam["wellYieldMultiplierMilli"]
    assert by_id["well"]["buildTurns"] == loam["wellBuildTurns"]
    assert by_id["waystation"]["cost"] == loam["waystationCost"]
    assert by_id["waystation"]["buildTurns"] == loam["waystationBuildTurns"]
    assert by_id["granary"]["cost"] == loam["granaryCost"]
    assert by_id["granary"]["capacityBonus"] == loam["granaryCapacityBonus"]
    assert by_id["granary"]["buildTurns"] == loam["granaryBuildTurns"]
    assert by_id["soul-conduit"]["cost"] == loam["soulConduitCost"]
    assert by_id["soul-conduit"]["flatYieldPerTurn"] == loam["soulConduitFlatYieldPerTurn"]
    assert by_id["soul-conduit"]["buildTurns"] == loam["soulConduitBuildTurns"]
    assert by_id["extractor"]["cost"] == loam["extractorCost"]
    assert by_id["extractor"]["flatYieldPerTurn"] == loam["extractorFlatYieldPerTurn"]
    assert by_id["extractor"]["buildTurns"] == loam["extractorBuildTurns"]
    assert by_id["hatchery"]["cost"] == loam["hatcheryCost"]
    assert by_id["hatchery"]["yieldMultiplierMilli"] == loam["hatcheryYieldMultiplierMilli"]
    assert by_id["hatchery"]["buildTurns"] == loam["hatcheryBuildTurns"]

    # structureKind: an AUTHORED fact, never derived from role -- anchor/schema.py's own
    # ROLE_TO_STRUCTURE_KIND dict (Extract/Multiply -> LoamSource, Bank -> Storage) is wrong
    # against these three real shipped rows, all of which are really StructureKind.Yield. Checked
    # here directly rather than trusting that dict, per this module's own Correction 2.
    assert by_id["well"]["structureKind"] == "LoamSource"
    assert by_id["waystation"]["structureKind"] == "LoamSource"
    assert by_id["granary"]["structureKind"] == "Storage"
    assert by_id["soul-conduit"]["structureKind"] == "Yield"
    assert by_id["extractor"]["structureKind"] == "Yield"
    assert by_id["hatchery"]["structureKind"] == "Yield"
    assert by_id["moat"]["structureKind"] == "Obstacle"

    assert by_id["moat"]["buildTurns"] == siege["construction"]["labourMoatTurns"]
    assert by_id["moat"]["constructRubbleCost"] == siege["construction"]["refineRubblePerIronwork"]
    assert by_id["moat"]["materialTier"] == 1
    assert by_id["moat"]["blocksMovement"] is True
    assert by_id["moat"]["blocksLineOfFire"] is True
    assert by_id["moat"]["obstacleKind"] == "Rampart"

    # The seven pre-siege loam rows stay indestructible -- spec-structure-catalog-import.md §4's
    # own explicit byte-identity requirement ("the four loam rows author tier zero").
    for sid in ("loam-source-placeholder", "well", "waystation", "granary",
                "soul-conduit", "extractor", "hatchery"):
        assert by_id[sid]["materialTier"] == 0, sid


def test_dumped_row_names_are_byte_identical_to_structurecatalog_cs():
    # `Name` is a real gap alongside `magnitudes`: the anchor schema has no display-name field at
    # all. Checked against StructureCatalog.cs's own literal `Name = "..."` strings directly here
    # (not a title-case assumption) so a future rename in either place is caught by drift.
    expected = {
        "loam-source-placeholder": "Loam Source (placeholder)",
        "well": "Well", "waystation": "Waystation", "granary": "Granary",
        "soul-conduit": "Soul Conduit", "extractor": "Extractor", "hatchery": "Hatchery",
        "moat": "Moat",
    }
    by_id = {row["id"]: row["name"] for row in DUMPED_ROWS}
    assert by_id == expected


def test_every_row_has_a_name():
    for row in ALL_ROWS:
        assert row["name"].strip(), f"{row['id']} has an empty name"


def test_the_shipped_rows_round_trip_through_the_schema():
    # Spec's own test name says "the four shipped rows" (written 2026-09-04) -- by the time this
    # module was built (2026-09-06) StructureCatalog.cs shipped EIGHT rows, not four (soul-conduit/
    # extractor/hatchery are Yield-kind rows the spec's own "what already exists" section never
    # mentions, and moat was added the same day by siege-construction 15.3b). Verified against code,
    # not the spec's stale text -- all eight are dumped and round-trip; asserting exactly 8 (not
    # "at least 4") so a future drift is caught rather than silently tolerated.
    assert len(DUMPED_ROWS) == 8
    dumped_ids = {row["id"] for row in DUMPED_ROWS}
    assert dumped_ids == {
        "loam-source-placeholder", "well", "waystation", "granary",
        "soul-conduit", "extractor", "hatchery", "moat",
    }
    for row in DUMPED_ROWS:
        assert row["_provenance"]["source"] == "AUTHORED"
        assert "StructureCatalog.cs" in row["_provenance"]["citation"]


def test_every_row_cites_a_source():
    for row in ALL_ROWS:
        citation = row["_provenance"]["citation"]
        assert citation.strip(), f"{row['id']} has an empty citation"
        cites_research_section = "§" in citation  # §5.18 / §5.21 / spec-siege-fog.md §2, etc.
        cites_shipped_code = "StructureCatalog.cs" in citation
        assert cites_research_section or cites_shipped_code, (
            f"{row['id']}'s citation names no section reference and no dumped shipped row: "
            f"{citation!r}")


def test_per_role_counts_meet_declared_targets():
    budget = json.loads(TUNING_PATH.read_text(encoding="utf-8"))["budget"]
    counts: "dict[str, int]" = {}
    for row in ALL_ROWS:
        role = row["anchor"]["role"]
        counts[role] = counts.get(role, 0) + 1
    for role, target in budget.items():
        assert counts.get(role, 0) >= target, (
            f"role {role!r} has {counts.get(role, 0)} rows, below its declared budget of {target}")


def test_no_role_has_zero_rows():
    from seedsmith.adapters.structures.anchor.schema import ROLE
    counts: "dict[str, int]" = {}
    for row in ALL_ROWS:
        role = row["anchor"]["role"]
        counts[role] = counts.get(role, 0) + 1
    for role in ROLE:
        assert counts.get(role, 0) > 0, f"role {role!r} has zero rows -- a hole in the taxonomy"


def test_grid_density_is_between_2_4_and_4_0():
    from seedsmith.adapters.structures.anchor.schema import ROLE
    density = len(ALL_ROWS) / len(ROLE)
    assert 2.4 <= density <= 4.0, f"density {density} outside the safe 2.4-4.0 band"


def test_rerun_is_byte_identical_proven_by_hash():
    def _hash_tree(root: Path) -> str:
        h = hashlib.sha256()
        for path in sorted(root.rglob("*.json")):
            h.update(path.relative_to(root).as_posix().encode("utf-8"))
            h.update(path.read_bytes())
        return h.hexdigest()

    with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
        write_corpus(Path(d1))
        write_corpus(Path(d2))
        hash1 = _hash_tree(Path(d1))
        hash2 = _hash_tree(Path(d2))
        assert hash1 == hash2
        # A THIRD run into the first directory again (overwriting in place) must reproduce the
        # exact same bytes too -- proves idempotency under overwrite, not just under a fresh dir.
        write_corpus(Path(d1))
        assert _hash_tree(Path(d1)) == hash1


def _walk_no_numbers(node, path: str = "$") -> "list[str]":
    if isinstance(node, bool):
        return []  # bool is a subclass of int in Python -- explicitly not a numeric-smuggling case
    if isinstance(node, (int, float)):
        return [path]
    if isinstance(node, dict):
        defects = []
        for k, v in node.items():
            defects += _walk_no_numbers(v, f"{path}.{k}")
        return defects
    if isinstance(node, list):
        defects = []
        for i, v in enumerate(node):
            defects += _walk_no_numbers(v, f"{path}[{i}]")
        return defects
    return []


def test_corpus_holds_no_numbers():
    # Scoped to `anchor` specifically -- structure-schema's own rule ("the anchor holds no numbers
    # at all") governs the identity/ordinal contract a model could one day author, not the sibling
    # `magnitudes` block (deterministic, human/tool-authored only, never model-touched — see
    # generate_corpus.py's own top-of-file note on why that split exists).
    for row in ALL_ROWS:
        defects = _walk_no_numbers(row["anchor"])
        assert defects == [], f"{row['id']}'s anchor has numeric field(s): {defects}"


ALMANAC_ROOT = REPO_ROOT / "data" / "seed" / "creatures" / "_dump" / "almanac"


def _normalize(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _real_pvz_type_names() -> "set[str]":
    # The REAL almanac dump (`typeName`, e.g. "Peashooter", "PotatoMine") -- decision 43's actual
    # concern is reusing an EXISTING PLANT'S IDENTITY, not any incidental English-word overlap.
    # Whole-identity, normalized-EXACT matching (not substring, not word-token): an earlier draft
    # of this test checked the repo's own GENERATED creature-species corpus by decomposed word, and
    # produced two real false positives ("convoy-depot" flagged via "pot", "mine" flagged via
    # itself) because that corpus is this repo's OWN invented content abstracted from PvZ, drawing
    # on generic English words ("Pot", "Mine" are real SPECIES ids there) -- not "the PvZ corpus"
    # decision 43 actually means. §5.18's own research explicitly and correctly uses "Mine" as a
    # generic siege-warfare term (a landmine), independent of any single game's plant roster.
    names: "set[str]" = set()
    for fname in ("plant.json", "zombie.json"):
        for row in json.loads((ALMANAC_ROOT / fname).read_text(encoding="utf-8")):
            type_name = row.get("typeName")
            if type_name:
                names.add(_normalize(type_name))
    return names


def test_no_pvz_plant_appears_in_the_corpus():
    # decision 43: static plants stay creatures: "the PvZ corpus is not available for reuse here."
    # Checked against the REAL PvZ Fusion almanac dump (not a hand-typed guess-list, and not this
    # repo's own generated creature-species corpus, which is a different, already-abstracted thing).
    real_names = _real_pvz_type_names()
    assert real_names, "sanity check: the almanac dump should not be empty"
    for row in ALL_ROWS:
        normalized_id = _normalize(row["id"])
        assert normalized_id not in real_names, (
            f"{row['id']!r} is a real, shipped PvZ Fusion plant/zombie type name")


def test_every_id_is_kebab_case():
    # WorldIds.RequireKebab's own strict rule (lowercase letters, digits, hyphens only) -- checked
    # here, Python-side, before structure-catalog-import ever tries to load these ids into C#.
    for row in ALL_ROWS:
        assert _KEBAB.match(row["id"]), f"{row['id']!r} is not pure kebab-case"


def test_no_duplicate_ids():
    ids = [row["id"] for row in ALL_ROWS]
    assert len(ids) == len(set(ids))


def test_file_tree_groups_by_role_directory():
    tree = file_tree()
    assert len(tree) == len(ALL_ROWS)
    for rel, doc in tree.items():
        role_dir = rel.split("/")[0]
        assert role_dir == doc["_meta"]["partition"].lower()
        assert doc["kind"] == "structure-anchor"


def test_zero_model_calls_in_this_module():
    src = (Path(__file__).resolve().parent.parent / "seedsmith" / "adapters" / "structures"
           / "generate_corpus.py").read_text(encoding="utf-8")
    for banned in ("openai", "anthropic", "lmstudio", "requests.post", "httpx", "urllib"):
        assert banned not in src.lower(), f"generate_corpus.py appears to reference {banned!r}"


def test_authored_rows_count_matches_the_stated_seventeen():
    # Documents the actual, honestly-grounded corpus size against this module's own top-of-file
    # note (17 new, not spec's literal '~36') -- a tripwire so a future edit that silently drifts
    # the count gets caught by name, not just by the density-band test passing coincidentally.
    assert len(AUTHORED_ROWS) == 17
    assert len(ALL_ROWS) == 25


def test_relic_vault_row_is_a_catalog_loadable_item_storage_row():
    # empire-inventory-surfaces `storage-content` §Design 1-2 (task 4B.2): the hand-authored
    # `relic-vault` content row. Deliberately NOT part of generate_corpus.ALL_ROWS (ruling
    # 2026-09-15 §Design 2: rows are hand-authored, no generator fix owed — write_corpus only
    # writes file_tree() entries without deleting, so this file survives regen), hence asserted
    # against the COMMITTED corpus on disk, never the in-memory generator tree. No count pin
    # (validation-ssot): presence + closed-enum membership + the authored value, not a total.
    doc = json.loads(
        (REPO_ROOT / "data" / "seed" / "structures" / "store" / "relic-vault.json")
        .read_text(encoding="utf-8"))
    assert doc["kind"] == "structure-anchor"
    (row,) = doc["entries"]
    assert row["id"] == "relic-vault" == row["anchor"]["structureId"]
    assert row["name"] == "Relic Vault"
    assert row["_provenance"]["source"] == "AUTHORED"
    # The anchor keeps the generator's own contract even though no generator emitted it.
    import jsonschema

    jsonschema.validate(row["anchor"], build_structure_anchor_schema())
    assert row["anchor"]["role"] == "Store"
    assert row["anchor"]["requiredSlotKind"] == "Vault"
    magnitudes = row["magnitudes"]
    assert magnitudes["structureKind"] == "ItemStorage"
    assert magnitudes["itemStorageCapacityBonus"] == 20
    # The two capacity axes never bleed: the item vault grants zero loam capacity.
    assert magnitudes["capacityBonus"] == 0
