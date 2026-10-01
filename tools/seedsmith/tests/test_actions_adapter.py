"""Tests for seedsmith.adapters.actions (spec-corpus-loader.md, module A-C1).

    python -m pytest gk-forge/tools/seedsmith/tests/test_actions_adapter.py -v

Structural tests only (KindSpecs, closed vocabularies, registries, dimensions/legal_combinations) —
the load algorithm itself (Corpus.load wiring, findings, edges) is covered separately in
test_corpus_loader.py, mirroring the split test_items_adapter.py / test_corpus.py already use.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.actions import ActionsAdapter  # noqa: E402
from seedsmith.adapters.actions.kinds import KINDS  # noqa: E402
from seedsmith.adapters.actions.vocab import (  # noqa: E402
    ACTION_KINDS, AREA_SHAPES, CATEGORIES, PAIRING_ROLES, RELATIONS, SCOPES, STATUSES, TAGS,
    TARGET_MODES, load_accepted_family_ids, load_family_ids, load_family_map_keys,
)
from seedsmith.adapters.registry import known_adapter_names, resolve_adapter  # noqa: E402

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


# solid-enforcement vocabulary-mirror (SE2.7, 2026-09-19): the checker lives in scripts/, not the
# seedsmith package, so it is loaded by file path (its hyphenated filename is not a valid Python
# module name). ClosedVocabularyTests below asserts each mirror against this manifest-resolved,
# transform-applied OWNER set -- never a transcribed literal. A test that compares a copy to a copy
# of itself (the old `test_nine_tags`/`test_twenty_one_statuses` shape) proves nothing about the
# original; this reads the real C# enum / the real status-catalog file every run.
_GVM_SPEC = importlib.util.spec_from_file_location(
    "guard_vocabulary_mirror", _owned("scripts/guard-vocabulary-mirror.py"))
assert _GVM_SPEC is not None and _GVM_SPEC.loader is not None
_gvm = importlib.util.module_from_spec(_GVM_SPEC)
_GVM_SPEC.loader.exec_module(_gvm)

_VOCAB_MANIFEST = json.loads((_owned("scripts/vocabulary-mirrors.v1.json")).read_text(encoding="utf-8"))
_VOCAB_PAIRS_BY_ID = {p["id"]: p for p in _VOCAB_MANIFEST["pairs"]}


def _owner_expected(pair_id: str) -> "set[str]":
    pair = _VOCAB_PAIRS_BY_ID[pair_id]
    owner_members = _gvm.resolve_owner_members(REPO_ROOT, pair["owner"])
    transform = _gvm.TRANSFORMS[pair["transform"]]
    return {transform(m) for m in owner_members}


class RegistryWiringTests(unittest.TestCase):
    """Acceptance #5."""

    def test_actions_is_registered(self) -> None:
        self.assertIn("actions", known_adapter_names())

    def test_resolve_adapter_returns_the_adapter(self) -> None:
        self.assertIsInstance(resolve_adapter("actions"), ActionsAdapter)


class KindSpecTests(unittest.TestCase):
    """Acceptance #6b — every one of the ten kinds carries its OWN id_pattern, never one shared
    `action.`-only pattern (the spec's own F-correction)."""

    def test_ten_kinds(self) -> None:
        # The count is fully implied by the set equality below -- never pinned separately
        # (population-pin SE3.5, 2026-09-20).
        self.assertEqual({k.kind for k in KINDS}, {
            "action-seed", "action-brief", "action-reject", "action-review", "action-coverage",
            "action-innate", "action-type-weights", "action-role-lean",
            "action-characteristic-pool", "action-config",
        })

    def test_every_kind_except_config_has_its_own_id_pattern(self) -> None:
        for kind_spec in KINDS:
            if kind_spec.kind == "action-config":
                self.assertIsNone(kind_spec.id_pattern)
            else:
                self.assertIsNotNone(kind_spec.id_pattern, kind_spec.kind)

    def test_id_patterns_are_pairwise_distinct(self) -> None:
        patterns = [k.id_pattern.pattern for k in KINDS if k.id_pattern is not None]
        self.assertEqual(len(patterns), len(set(patterns)))

    def test_action_seed_ids_do_not_match_the_other_kinds_patterns(self) -> None:
        # The exact defect the F-correction fixes: a brief id, an innate pick id, a weights row id
        # must NOT be swallowed by action-seed's own pattern (and vice versa).
        action_seed = next(k for k in KINDS if k.kind == "action-seed")
        other_ids = {
            "action-brief": "brief.species.cherrybomb.002",
            "action-type-weights": "weights.species.cherrybomb",
            "action-role-lean": "lean.cherrybomb",
            "action-coverage": "cell.species.attack.5-10.enabler",
            "action-innate": "innate.cherrybomb",
        }
        for kind, sample_id in other_ids.items():
            with self.subTest(kind=kind):
                self.assertIsNone(action_seed.id_pattern.match(sample_id))
                own_pattern = next(k for k in KINDS if k.kind == kind).id_pattern
                self.assertIsNotNone(own_pattern.match(sample_id))

    def test_action_seed_schema_matches_spec_step_4_exactly(self) -> None:
        action_seed = next(k for k in KINDS if k.kind == "action-seed")
        self.assertEqual(action_seed.required, {
            "id", "scope", "category", "rungBand", "targetMode", "relation", "atomFamilies",
            "pairingRole",
        })
        # `description` added 2026-09-08 (`seedsmith-content-standard`, `content-completeness-
        # actions`, Task 8) -- a real, additive widening of spec-corpus-loader.md §3 step 4's own
        # transcribed shape, not a drift from it: `kinds.py`'s own comment on the field cites the
        # reviewed-change precedent (`candidate_assembly/derive.py`'s 2026-09-04 note that a
        # `flavor`/`flavorKey`-style split for actions would need exactly this).
        self.assertEqual(action_seed.optional, {
            "scopeKey", "areaShape", "tags", "kindHint", "structureAxes", "pairedPayoffFamily",
            "motifsUsed", "name", "description",
        })
        self.assertEqual(action_seed.reference_fields, {"atomFamilies", "pairedPayoffFamily", "scopeKey"})

    def test_action_seed_sample_ids_match_its_own_pattern(self) -> None:
        action_seed = next(k for k in KINDS if k.kind == "action-seed")
        for sample in ("action.general.0001", "action.family.cherry.001", "action.species.cherrybomb.001"):
            with self.subTest(sample=sample):
                self.assertIsNotNone(action_seed.id_pattern.match(sample))


class ClosedVocabularyTests(unittest.TestCase):
    """Acceptance #6 — every wire string, checked against the owner's OWN current declaration, never
    a transcribed literal (solid-enforcement `vocabulary-mirror`, SE2.7 — the `test_nine_tags`/
    `test_twenty_one_statuses` shape this replaces pinned a copy against a copy of itself, which is
    exactly why the `construct` and `nerve.*` drifts went uncaught for as long as they did). Each
    closed vocabulary's SIZE and membership are pinned once, at the C# owner (its own enum/tests);
    this file only asserts the mirror still agrees with whatever that owner currently says."""

    def test_action_kinds_match_the_owner_enum(self) -> None:
        self.assertEqual(ACTION_KINDS, _owner_expected("action-kind"))

    def test_action_categories_match_the_owner_enum(self) -> None:
        self.assertEqual(CATEGORIES, _owner_expected("action-category"))

    def test_action_tags_match_the_owner_enum(self) -> None:
        self.assertEqual(TAGS, _owner_expected("action-tag"))

    def test_action_target_modes_match_the_owner_enum(self) -> None:
        self.assertEqual(TARGET_MODES, _owner_expected("action-target-mode"))

    def test_action_area_shapes_match_the_owner_enum(self) -> None:
        self.assertEqual(AREA_SHAPES, _owner_expected("action-area-shape"))

    def test_action_relations_match_the_owner_enum(self) -> None:
        self.assertEqual(RELATIONS, _owner_expected("action-relation"))

    def test_action_eligibility_scopes_match_the_owner_enum(self) -> None:
        self.assertEqual(SCOPES, _owner_expected("action-eligibility-scope"))

    def test_action_pairing_roles_match_the_owner_enum(self) -> None:
        self.assertEqual(PAIRING_ROLES, _owner_expected("action-pairing-role"))

    def test_action_statuses_match_the_owner_catalog(self) -> None:
        # Resolved SE2.7: relation=equal, the mirror gained the three nerve.* ids that
        # gk-core/data/tuning/status-catalog.v1.json already names -- no exclusion was ever deliberate.
        self.assertEqual(STATUSES, _owner_expected("action-status"))

    def test_no_vocabulary_carries_a_pascal_case_member(self) -> None:
        # The exact shape the spec's own pre-correction example carried ("Area"/"Row"/"Enemy") —
        # every wire string starts lower-case (some are legitimately camelCase, e.g.
        # "rolledTarget", so the check is "first letter", not "the whole string is lower-case").
        for vocab in (ACTION_KINDS, CATEGORIES, TAGS, TARGET_MODES, AREA_SHAPES, RELATIONS,
                     STATUSES, SCOPES, PAIRING_ROLES):
            for value in vocab:
                self.assertEqual(value[0], value[0].lower(), value)

    def test_status_wire_strings_match_the_live_registration_calls(self) -> None:
        # Read the live file, not a re-typed copy — the registration TEXT is the source of truth.
        path = _owned("src/FusionRpg.Core/Status/StatusCatalogBootstrap.cs")
        text = path.read_text(encoding="utf-8")
        for status_id in STATUSES:
            self.assertIn(f'"{status_id}"', text, status_id)


class FamilyAndPairingVocabularyTests(unittest.TestCase):
    """The two data-derived (not C#-derived) vocabularies §2's "DECIDED" section adds."""

    def test_atom_family_count_tracks_the_live_corpus(self) -> None:
        # A JOIN to the live affix-family corpus, never a pinned count — the owner's item seed
        # commits grow it as content ships (validation-ssot.md). nodegen's own
        # test_nodegen_vocab sentinel tracks the same source, so the two stay in step.
        # AC-F1 (2026-09-24): the ADAPTER's accepted namespace is the affix families PLUS the fx
        # effect families (a committed row may name either); the GENERATOR pool `load_family_ids`
        # stays affix-only. Assert the registry equals the accepted union, never re-derive it.
        regs = ActionsAdapter().registries()
        self.assertEqual(regs.vocabularies["atomFamily"], load_accepted_family_ids())
        print(f"atom families (accepted namespace): {len(regs.vocabularies['atomFamily'])}")

    def test_pairing_keys_match_the_live_pairings_file(self) -> None:
        pairings_path = _owned("data/seed/actions/pairings.json")
        doc = json.loads(pairings_path.read_text(encoding="utf-8"))
        regs = ActionsAdapter().registries()
        self.assertEqual(regs.vocabularies["pairingKey"], frozenset(doc.keys()))

    def test_family_map_keys_are_exactly_the_live_family_map(self) -> None:
        # The vocabulary IS the live `family-map.json` family values. That map is a population
        # derived from the species roster (it grows per shipped species), so its size is a reading —
        # the contract is the join to the loader, never a pinned 242 (validation-ssot.md).
        regs = ActionsAdapter().registries()
        self.assertEqual(regs.vocabularies["familyMapKey"], load_family_map_keys())
        for family_id in regs.vocabularies["familyMapKey"]:
            self.assertTrue(family_id and isinstance(family_id, str))
        print(f"familyMapKey: {len(regs.vocabularies['familyMapKey'])} family ids")


class LegalCombinationsTests(unittest.TestCase):
    """base.py's own trap: a `LegalityFn` returning True unconditionally silently disables the
    check. `areaShape` is real-rule-not-invented-example: `ActionTargetSpec.Shape` is documented
    `Area`-only (`ActionTargetSpec.cs:86`)."""

    def setUp(self) -> None:
        self.legal = ActionsAdapter().legal_combinations()

    def test_area_shape_illegal_outside_area_target_mode(self) -> None:
        self.assertFalse(self.legal("targetMode", "single", "areaShape", "row"))

    def test_area_shape_legal_under_area_target_mode(self) -> None:
        self.assertTrue(self.legal("targetMode", "area", "areaShape", "row"))

    def test_unrelated_pairs_are_legal(self) -> None:
        self.assertTrue(self.legal("category", "attack", "relation", "enemy"))


class ChannelsTests(unittest.TestCase):
    def test_no_channels_seeds_carry_no_magnitude(self) -> None:
        # Constraint 1: an atom names a POOL; a generated action-seed carries no number at all.
        self.assertEqual(ActionsAdapter().channels(), [])


if __name__ == "__main__":
    unittest.main()
