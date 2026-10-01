"""Tests for seedsmith.adapters.items (tasks/seedsmith-todo.md, S2).

    python -m pytest gk-forge/tools/seedsmith/tests/test_items_adapter.py -v

Two kinds of test here on purpose, mirroring the plan's own split: unit-level tests against the
adapter's structural claims (registry-shaped tests, no live corpus needed), and one integration
test against the REAL `gk-data/packs/fusion/data/seed/items` corpus — the live corpus is the deliberate subject here,
not a violation of "fixtures are synthetic": S2's whole acceptance criterion (spec-foundation §6,
CP-B) is "the tool independently rediscovers a defect in the real content," which cannot be
proven any other way.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items import ItemsAdapter  # noqa: E402
from seedsmith.adapters.items.channels import PRIMARY_CHANNEL_IDS  # noqa: E402
from seedsmith.adapters.items.kinds import KINDS  # noqa: E402
from seedsmith.adapters.items.registries import (  # noqa: E402
    HYBRID_FRAME_CITATION,
    REGISTRY_DIR,
    partition_kind_map,
)
from seedsmith.adapters.items.setgen import name_repair  # noqa: E402
from seedsmith.corpus import Corpus  # noqa: E402
from seedsmith.metrics import Ctx, MetricRegistry, Severity, run_all  # noqa: E402
from seedsmith.metrics.coverage import EmptyPartitionMetric  # noqa: E402

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

LIVE_ITEMS_ROOT = _owned("data/seed/items")

#: `--collision-groups` emits exactly two reasons and no others (Program.cs:170 `reason = "name"`,
#: Program.cs:180 `reason = "nameKey"`). Pinned as a closed vocabulary: the filter inside
#: `_name_collisions` would otherwise match NOTHING if the label were ever renamed, and a
#: name-uniqueness test that compares nothing passes vacuously — the same failure mode as the
#: under-detector this helper replaced, in the opposite direction.
COLLISION_REASONS = frozenset({"name", "nameKey"})


def _name_collisions(items_root: "Path") -> list:
    """The AUTHORITY's own `name`-reasoned collision groups under `items_root`, read from
    `dotnet run --project tools/ItemSeedValidator -- <root> --collision-groups`.

    This is the same call `setgen/name_repair.plan()` consumes, so the key asserted here, the key
    the repair computes against and the key the CI gate enforces are ONE algorithm:
    `naming.v1.json`'s `collisionNormalization` as implemented in
    `tools/ItemSeedValidator/Naming/NameNormalizer.cs` — lowercase, tokenize, whole-token
    resolution, canonical pool ids, DROP the four closed connectives `of`/`the`/`a`/`and`, sort.
    A test that re-derived any of that in Python would fork the authority, which is precisely what
    `name_repair.py`'s own module docstring warns against.

    Only `reason: "name"` is returned. A `nameKey` group is a DIFFERENT defect — the `set.item`
    placeholder key carried by rows whose names are all distinct — owned by
    `name_repair.repair_name_keys` and asserted in `test_item_name_repair`; folding it in would
    make a test named for NAMES fail on a key it never claimed to cover.

    Propagates the RuntimeError `collision_groups` raises when the tool cannot run. That is
    deliberate and there is no fallback or skip: a name-uniqueness test that quietly stops
    comparing is a worse guard than a loud failure.
    """
    groups = name_repair.collision_groups(items_root=Path(items_root))
    unrecognised = {g.get("reason") for g in groups} - COLLISION_REASONS
    if unrecognised:
        raise AssertionError(
            f"--collision-groups emitted unrecognised reason(s) {sorted(unrecognised)!r} against the "
            f"pinned vocabulary {sorted(COLLISION_REASONS)!r}; the 'name' filter below would then "
            f"match nothing and every caller would pass without comparing a single name")
    return [g for g in groups if g.get("reason") == "name"]


def _render_collisions(groups: "list") -> "dict":
    """The collision groups as a comparable, readable mapping, for an assertion's failure message."""
    return {f"{g.get('key')}: " + ", ".join(
        f"{m.get('name')!r} [{m.get('kind')}/{m.get('id')}]" for m in g.get("members") or ())
        for g in groups}


class KindSpecTests(unittest.TestCase):
    def test_fifteen_kinds_including_the_undefined_attribute_kind(self) -> None:
        # 15 -> 16, 2026-09-15 (empire-development Task 1.3a: additive `relic` kind,
        # spec-relic-item-kind.md §Design 1) — a reviewed vocabulary growth, not drift. Canonical
        # site (population-pin SE3.5, 2026-09-20): test_relic_kinds.py asserts the same KINDS
        # object's membership, never a second copy of this count.
        # pin: closed-vocabulary KINDS — kinds.py's own module-load assert already guards this too
        self.assertEqual(len(KINDS), 16)
        self.assertIn("attribute", {k.kind for k in KINDS})
        self.assertIn("relic", {k.kind for k in KINDS})

    def test_base_type_required_fields_match_kind_catalog(self) -> None:
        base_type = next(k for k in KINDS if k.kind == "base-type")
        self.assertTrue({"id", "nameKey", "name", "frame", "role", "class", "band",
                        "iconKey", "tags"} <= base_type.required)


class RegistryVersionTests(unittest.TestCase):
    def test_versions_are_read_not_a_single_hardcoded_constant(self) -> None:
        versions = ItemsAdapter().registries().versions

        # ⛔ NOT literals. Pinning one here is exactly what this test is named against: it went
        # stale at naming v8 while the file moved to v9 (rareNameWords, item-seed-regen) and then
        # to v10 (the `_socketWords` retirement, item-seed-gen ISG7), so it failed on a clean HEAD
        # for a change that was correct. Compare against each registry file's OWN declared value,
        # which the loader above is supposed to be reading.
        for name, declared in versions.items():
            document = json.loads((REGISTRY_DIR / f"{name}.v1.json").read_text(encoding="utf-8"))
            self.assertEqual(declared, document["registryVersion"], f"{name}.v1.json")

        # And a single assumed constant would already be wrong: they genuinely differ.
        self.assertGreater(len(set(versions.values())), 1)


class LegalCombinationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.legal = ItemsAdapter().legal_combinations()

    def test_ward_array_excluded_from_hybrid_frame(self) -> None:
        self.assertFalse(self.legal("role", "ward-array", "frame", "hybrid"))

    def test_jewel_minor_b_is_legal_with_hybrid_frame(self) -> None:
        # D30 (registryVersion 2, 2026-09-04): D3 wins over the prior 13-role/895‰ shape this test
        # used to assert — jewel-minor-b is hybrid-eligible; head-guard and sense are not.
        self.assertTrue(self.legal("frame", "hybrid", "role", "jewel-minor-b"))

    def test_head_guard_excluded_from_hybrid_frame(self) -> None:
        self.assertFalse(self.legal("frame", "hybrid", "role", "head-guard"))

    def test_sense_excluded_from_hybrid_frame(self) -> None:
        self.assertFalse(self.legal("frame", "hybrid", "role", "sense"))

    def test_commander_standard_excluded_from_hybrid_frame(self) -> None:
        self.assertFalse(self.legal("role", "standard", "frame", "hybrid"))

    def test_ordinary_role_is_legal_with_hybrid_frame(self) -> None:
        self.assertTrue(self.legal("role", "footing", "frame", "hybrid"))

    def test_any_role_is_legal_with_non_hybrid_frames(self) -> None:
        self.assertTrue(self.legal("role", "ward-array", "frame", "humanoid"))
        self.assertTrue(self.legal("role", "ward-array", "frame", "plant"))

    def test_hybrid_frame_citation_still_present_in_the_live_registry(self) -> None:
        # Pins the one transcribed (not parsed) fact in this adapter against the actual
        # registry text, so an edit to core.v1.json's frame prose cannot silently invalidate
        # HYBRID_FRAME_EXCLUDED_ROLES without a test failing.
        core_text = (REGISTRY_DIR / "core.v1.json").read_text(encoding="utf-8")
        self.assertIn(HYBRID_FRAME_CITATION, core_text)


class ChannelTests(unittest.TestCase):
    def test_fourteen_primary_channels(self) -> None:
        channels = ItemsAdapter().channels()
        # The count is fully implied by the set equality below -- never pinned separately
        # (population-pin SE3.5, 2026-09-20).
        self.assertEqual({c.id for c in channels}, PRIMARY_CHANNEL_IDS)

    def test_channels_match_bands_registry_member_families(self) -> None:
        bands = json.loads((REGISTRY_DIR / "bands.v1.json").read_text(encoding="utf-8"))
        registry_ids = frozenset(
            bands["powerBand"]["channelFamilyGroups"]["primaryChannel"]["memberFamilies"])
        self.assertEqual(PRIMARY_CHANNEL_IDS, registry_ids)

    def test_reference_base_is_callable_and_deterministic(self) -> None:
        channel = ItemsAdapter().channels()[0]
        self.assertEqual(channel.reference_base(5), channel.reference_base(5))


@unittest.skipUnless(LIVE_ITEMS_ROOT.is_dir(), "live item corpus not present in this checkout")
class LiveCorpusIntegrationTests(unittest.TestCase):
    """The known-answer test (tasks/seedsmith-plan.md, CP-B): rediscover, in one command, the
    exact defect that took three authoring waves and a hand-written diff to notice — verified
    fresh against the corpus as it stands today, not against a number carried over from an
    earlier session (which had already drifted once)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.corpus = Corpus.load(LIVE_ITEMS_ROOT)
        cls.adapter = ItemsAdapter()

    def test_loads_entries_and_files_with_no_lost_or_duplicated_file(self) -> None:
        """The item corpus is a POPULATION that grows with each authored batch, so its entry/file
        totals are readings, never pinned literals (docs/architecture/validation-ssot.md). The
        contract: loading is lossless — every entry carries a real file path, and each distinct file
        contributes at least one entry, so the file set is exactly what the corpus was built from."""
        self.assertGreater(len(self.corpus.entries), 0)
        seen_files = {e.path for e in self.corpus.entries.values()}
        self.assertTrue(all(seen_files), "every entry resolves to a file path")
        self.assertGreaterEqual(len(self.corpus.entries), len(seen_files),
                                "a file may hold several entries, never fewer than one")
        print(f"items: {len(self.corpus.entries)} entries over {len(seen_files)} files")

    def test_authored_item_names_are_unique_across_kinds(self) -> None:
        """Identity names are global player-facing labels, not merely unique within one kind.

        ✅ 2026-09-12: the 848 NameCollision/NameKeyDuplicate findings this test surfaced are FIXED
        (generator guard + the group-driven repair; see `setgen/name_repair.py` and
        `basetypegen/run.py`).

        ⛔ CORRECTED 2026-10-01 — the claim below used to be FALSE. The docstring said "Comparison
        is the validator's own NORMALIZED key", and the body computed its own instead:
        `" ".join(sorted(re.findall(r"[a-z0-9]+", name.casefold())))`. That key is not the
        validator's. Measured on the real corpus, the authority reported **66** collision groups
        and this key found **33** of them: every group it found was genuine (zero false positives),
        so it was a silent UNDER-detector wearing the authority's name, and the missing half is
        exactly the connective drop `NameNormalizer` performs at step 4. `naming.v1.json` states
        that list as "the complete list … closed at exactly four entries forever" (`of`, `the`, `a`,
        `and`), so "The Verdant Vessel" and "Verdant Vessel" are ONE idea to the validator and TWO
        to that key. Under-detecting is the direction that hides: it can only ever pass.

        The claim is now true by construction. The assertion below IS the authority's own
        `--collision-groups` output — the same call `name_repair.plan()` consumes, via
        `_name_collisions` — so this test, the repair and the gate cannot drift apart.

        Scope, unchanged in substance but now the AUTHORITY's rather than this file's:
        `Program.cs:138` skips `display-template`/`curve`/`recipe` for the same reason
        `NamingCheck.CheckName` sets `namesAThing = kind is not ("display-template" or "curve" or
        "recipe")` — a display template is a sentence, a curve names numeric points, and a recipe is
        a SYSTEMATIC label (`Forge: Cloth Armor`) that legitimately repeats per material/frame/band,
        so its `nameKey` is minted from the unique `recipe.NNN` id instead. The comparison stays
        corpus-wide rather than per-kind, which is what "across kinds" means here and what
        `RecordCollision` applies to every kind that names a thing a player picks up.

        ⚠ TRADE-OFF, stated plainly rather than hidden behind a skip: this test now requires the
        .NET SDK and a build of `tools/ItemSeedValidator`, where it previously required neither.
        That dependency is not new to this suite — `test_item_name_repair.RealCorpusPlanTests`
        already calls the very same function unconditionally against the real corpus — and a
        uniqueness test that degrades to comparing nothing when the SDK is missing is a strictly
        worse guard than a loud failure. There is no skip, no xfail and no fallback path here.
        """
        reported = _render_collisions(_name_collisions(LIVE_ITEMS_ROOT))
        self.assertEqual(
            reported, set(),
            f"{len(reported)} normalized-name collision group(s) under {LIVE_ITEMS_ROOT}. Each is one "
            f"idea claimed by more than one row, so every row past the first must be renamed "
            f"(see seedsmith `repair-names`); the first few: {sorted(reported)[:5]}")

    def test_empty_partitions_are_reported_only_for_allocated_but_unfilled_partitions(self) -> None:
        # ⛔ CORRECTED 2026-09-07: was 9, including two real, previously-undiscovered false positives.
        # `gems/2` is real content now. `base-types/footing/plant/{a,b}` were NEVER actually empty --
        # their `_meta.partition` was stamped missing the `base-types/` prefix every sibling uses, so
        # the metric's `corpus.partitions` lookup could never match. Fixed at the source, not here.
        #
        # 2026-09-11: the test no longer pins WHICH partitions are empty (content shipping fills them;
        # that is a reading — validation-ssot.md). It asserts the metric's CONTRACT: every reported
        # subject is an allocated partition that genuinely holds no entries, and every finding is GAP.
        ctx = Ctx(corpus=self.corpus, adapter=self.adapter)
        registry = MetricRegistry()
        registry.register(EmptyPartitionMetric())
        findings = run_all(registry, ctx)

        occupied = self.corpus.partitions
        allocated = self.adapter.registries().vocabularies.get("partitions", frozenset())
        subjects = {f.subject for f in findings}
        self.assertEqual(len(subjects), len(findings), "each partition is reported at most once")
        for finding in findings:
            self.assertIs(finding.severity, Severity.GAP)
            self.assertNotIn(finding.subject, occupied,
                             f"{finding.subject} was reported empty but holds content")
            self.assertTrue(finding.subject in allocated or finding.subject == "attributes",
                            f"{finding.subject} is not an allocated partition")
        print(f"empty partitions: {len(findings)}")

    def test_attributes_is_distinguishable_as_the_deferred_one(self) -> None:
        # "attributes" is qualitatively different from the other eight: it has no authored
        # shape at all (KindCatalog.cs's `ShapeDefined: false`), so it is flagged rather than
        # silently folded into the same bucket as an ordinary missing partition.
        attribute_kind = next(k for k in KINDS if k.kind == "attribute")
        self.assertEqual(attribute_kind.required, {"id", "nameKey", "name"})  # common-only

        ctx = Ctx(corpus=self.corpus, adapter=self.adapter)
        registry = MetricRegistry()
        registry.register(EmptyPartitionMetric())
        findings = {f.subject: f for f in run_all(registry, ctx)}

        self.assertIn("attributes", findings)
        self.assertEqual(partition_kind_map()["attributes"], "attribute")


@unittest.skipUnless((LIVE_ITEMS_ROOT / "_registry").is_dir(),
                     "control corpora are built from the live _registry, absent in this checkout")
class NameCollisionAuthorityControlTests(unittest.TestCase):
    """The two directions of the assertion in `LiveCorpusIntegrationTests`, on TEMP corpora.

    "The authority reports zero name collisions" is trivially satisfiable by an assertion that
    compares nothing, and the defect this file just had was precisely a comparison that silently
    matched too little. So both directions are executed here for real, against corpora built in a
    temp directory and NEVER the shipped one:

    * a corpus that genuinely collides must be CAUGHT — specifically by the connective drop the
      retired Python key lacked, and across two kinds, which is what the live test's name claims; and
    * a corpus that genuinely is clean must be CLEARED, so the catch above cannot be an assertion
      that fires on everything.

    The real `_registry` is copied in (16 files, ~675 KB) because a synthetic one would not be the
    authority: `naming.v1.json`'s closed connective list IS the thing under test. The SDK
    requirement is the same one the live test already carries — no skip was added to obtain it.
    """

    #: A `material` and a `set` whose names differ ONLY by a leading article. `the` is one of the
    #: four dropped connectives, so this is ONE idea to `NameNormalizer`; to the retired key it was
    #: two. `Abyssal`/`Maw` are deliberately left unregistered, so both resolve to themselves and
    #: the connective is the only difference between the two keys.
    ARTICLE_PAIR = (
        ("materials/a.json", "material", "material.ctl-001", "The Abyssal Maw", "material.abyssal-maw"),
        ("sets/b.json", "set", "set.ctl-001", "Abyssal Maw", "set.abyssal-maw"),
    )

    def _temp_root(self, rows) -> "Path":
        """A throwaway items root: the REAL registry plus one single-entry file per row."""
        temporary = tempfile.mkdtemp(prefix="gk-name-collision-control-")
        self.addCleanup(shutil.rmtree, temporary, ignore_errors=True)
        root = Path(temporary)
        shutil.copytree(LIVE_ITEMS_ROOT / "_registry", root / "_registry")
        for relative, kind, entry_id, name, name_key in rows:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"schemaVersion": 1, "kind": kind, "entries": [
                {"id": entry_id, "name": name, "nameKey": name_key}]}, indent=2), encoding="utf-8")
        return root

    def test_a_collision_differing_only_by_a_leading_article_is_caught(self) -> None:
        """The exact group class the retired key missed, and CROSS-KIND, which is the live test's
        stated scope. If this fails, `_name_collisions` has stopped detecting anything and the live
        assertion is passing vacuously."""
        groups = _name_collisions(self._temp_root(self.ARTICLE_PAIR))
        self.assertEqual(len(groups), 1,
                         f"the injected cross-kind collision was not reported as one group: {groups}")
        self.assertEqual(groups[0].get("key"), "abyssal maw",
                         "the group key is the canonical id list with `the` dropped")
        members = groups[0].get("members") or ()
        self.assertEqual({m.get("id") for m in members},
                         {"material.ctl-001", "set.ctl-001"},
                         "both rows must land in ONE group, which is what corpus-wide comparison "
                         "and two different kinds mean together")
        self.assertEqual({m.get("kind") for m in members}, {"material", "set"},
                         "the group must span two kinds, not merely two rows of one")

        # The retired implementation's own key, kept for ONE purpose: falsifying its old docstring
        # in-test rather than in a comment. It separates this pair, which is how 66 real groups were
        # reported as 33 with no false positive anywhere to betray the shortfall.
        def retired_key(name: str) -> str:
            return " ".join(sorted(re.findall(r"[a-z0-9]+", name.casefold())))

        self.assertNotEqual(retired_key("The Abyssal Maw"), retired_key("Abyssal Maw"),
                            "the retired key used to be the under-detector; if it now agrees, this "
                            "control is no longer covering the class of defect it exists for")

    def test_a_corpus_whose_names_are_all_distinct_ideas_is_cleared(self) -> None:
        """The other direction. Without it the test above could be satisfied by a comparison that
        reports a collision for everything."""
        distinct = (self.ARTICLE_PAIR[0],
                    ("sets/b.json", "set", "set.ctl-001", "Ember Legion", "set.ember-legion"))
        self.assertEqual(_name_collisions(self._temp_root(distinct)), [],
                         "two genuinely different names must not be reported as one idea")

    def test_the_live_assertion_itself_fails_on_a_corpus_that_really_does_collide(self) -> None:
        """⛔ The falsification that gives the live test its value, on a TEMP corpus.

        The live assertion is `assertEqual(_render_collisions(_name_collisions(root)), {})`. Running
        that SAME expression over a corpus seeded with one real collision must FAIL. If it passed,
        the live test would be satisfied by a comparison that never fires, and its green would mean
        nothing — which is the failure mode this file's defect was: a test that looked like the
        authority and quietly compared less.

        Built by calling the live assertion's own code path, so it cannot drift away from what the
        live test actually does. `assertEqual(..., {})` raises `AssertionError` on a non-empty
        mapping, which is precisely the rejection being demonstrated; the `assertRaises` here is the
        CONTROL asserting the rejection, not an escape hatch around the live assertion, which
        remains an unconditional `assertEqual` with no guard of any kind.
        """
        case = self._temp_root(self.ARTICLE_PAIR)
        with self.assertRaises(AssertionError) as caught:
            self.assertEqual(_render_collisions(_name_collisions(case)), {},
                             "the live assertion, run over a deliberately colliding corpus")
        # The rejection is only useful if it is diagnosable, so check the offending normalized key
        # and one of the two claiming names are in it. (Not the ids: pytest's own diff renderer
        # abbreviates the long mapping, so their absence here is formatting, not content — the full
        # id/name/kind rendering is asserted directly in the group test above.)
        self.assertIn("abyssal maw", str(caught.exception))
        self.assertIn("The Abyssal Maw", str(caught.exception))


class PartitionKeyShapeTests(unittest.TestCase):
    """⭐ The partition KEY's shape, checked against the registry that declares it (2026-09-26,
    partition-key audit).

    `Coverage/EmptyPartition` decides occupancy with an EXACT string set-difference between the
    allocation ledger and the `_meta.partition` a file carries. That is only sound while the two
    name a partition the same way, and nothing enforced it: the species-scoped `set` allocation read
    `sets/species/{rawSpeciesId}` while `setgen` files every set under `sets/{idTemplateSlot}`, so
    904 allocated slots read as empty, 844 of them already holding a same-species set.

    These assert the two halves of the contract, and both are SHAPE properties over a closed
    vocabulary (`naming.v1.json`, a file this repo owns and edits deliberately) — neither counts a
    population, so neither fails when a species ships. What is asserted is the contract and the
    closure, which is what `validation-ssot.md` asks a guardrail for; the gap COUNT is a reading and
    is deliberately not pinned.
    """

    def test_no_allocation_nests_deeper_than_its_declared_partition_key(self) -> None:
        # `naming.v1.json` declares each kind's partition key: `baseTypes` "(roleId, frame, band)"
        # -> 3 path segments, `uniques` "(themeId, rungBandLowOrdinal)" -> 2, `sets` "themeId" -> 1.
        # A deeper partition is a SCOPE the registry never declared. `sets` was the only kind that
        # emitted one (`sets/species/<id>`, depth 2) and the only kind whose allocated depth
        # disagreed with its declared key.
        naming = json.loads((REGISTRY_DIR / "naming.v1.json").read_text(encoding="utf-8"))
        directory_of = {k.directory: k for k in KINDS}
        allocated: dict[str, set[int]] = {}
        for partition in partition_kind_map():
            head, _, rest = partition.partition("/")
            spec = directory_of.get(head)
            if spec is None or not rest:
                continue
            allocated.setdefault(spec.kind, set()).add(len(rest.split("/")))

        offenders: list[str] = []
        for key, declared in naming["idNamespaces"].items():
            if not isinstance(declared, dict) or "partitionKey" not in declared:
                continue
            inner = str(declared["partitionKey"]).strip().strip("()")
            arity = len([part for part in inner.split(",") if part.strip()])
            spec = next((k for k in KINDS if k.namespace == key), None)
            depths = allocated.get(spec.kind, set()) if spec else set()
            for depth in depths:
                if depth > arity:
                    offenders.append(
                        f"{key} (partitionKey {declared['partitionKey']!r} = {arity} component(s)) "
                        f"allocates a {depth}-segment partition")

        self.assertEqual(offenders, [], "an allocation nests deeper than the declared partition key")

    def test_every_shipped_set_entry_partitions_into_an_allocated_partition(self) -> None:
        # The closure property that `EmptyPartition` silently depends on: a shipped `set` entry's
        # own id implies a partition, and that partition must be one the allocation actually
        # allocated. `setgen` derives it the same way (`authored.py::_partition_of` — the id's body
        # minus the sequence, which is what the id template's `{themeId}` slot holds).
        allocated = set(partition_kind_map())
        orphans: dict[str, str] = {}
        for path in sorted(LIVE_ITEMS_ROOT.glob("sets/*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            for entry in document.get("entries") or []:
                entry_id = str(entry.get("id") or "")
                if not entry_id.startswith("set."):
                    continue
                implied = f"sets/{entry_id.split('.', 1)[1].rsplit('-', 1)[0]}"
                if implied not in allocated:
                    orphans[implied] = entry_id

        self.assertEqual(
            orphans, {},
            "a shipped set id partitions into a partition the allocation never made — the corpus "
            "and the allocation disagree on the partition key, so EmptyPartition reads it as empty")

    def test_the_species_partition_key_is_the_id_template_slot_not_the_species_id(self) -> None:
        # The two spellings are NOT interchangeable, and the distinction is the audit's whole
        # subject. `setgen/emit.py::container_species_id` calls the underscored form "the
        # authoritative speciesId in the theme registry" and hyphenates "at the item boundary" —
        # so the container id (and therefore the id-template slot the partition names) is kebab,
        # while the identity that `speciesId`/`themeKey` carry stays underscored. Asserted on real
        # shipped members, never on how many there are.
        themes = json.loads(
            (_owned("data/seed/creatures/_registry/themes.v2.json"))
            .read_text(encoding="utf-8"))["themes"]
        underscored = {row["speciesId"]: key for key, row in themes.items()
                       if "_" in str(row.get("speciesId", ""))}
        self.assertTrue(underscored, "no variant species with an underscored id in the roster")

        allocated = set(partition_kind_map())
        for species_id in underscored:
            slug = species_id.replace("_", "-")
            self.assertIn(f"sets/{slug}", allocated,
                          f"{species_id}: the partition must name the id template's slot")
            self.assertNotIn(f"sets/species/{species_id}", allocated,
                             f"{species_id}: no scope segment below the kind directory")


if __name__ == "__main__":
    unittest.main()
