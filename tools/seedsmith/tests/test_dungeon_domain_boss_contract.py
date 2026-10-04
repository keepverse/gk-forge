"""The boss contract every shipped dungeon domain must satisfy, asserted over ALL of them.

    python -m pytest tests/test_dungeon_domain_boss_contract.py -v      # from gk-forge/tools/seedsmith

WHERE IT LIVES, AND WHY IT IS HERE RATHER THAN BESIDE THE CONTENT. The domains are content, so they
live in gk-data; this gate lives in gk-forge, beside every other reader and gate over that content
(`ItemSeedValidator` included, which the workspace ownership rules route here precisely because it
"validates private content"). It first landed in `gk-data/tests/` and that was wrong, and the reason
is structural rather than a matter of taste. gk-data has no `.github`, no `pyproject.toml` and no
`conftest.py`, and NO workflow anywhere in this workspace declares a CI step with a working
directory inside it. A test in that repository is code no CI job ever executes: it passes locally for
whoever typed it and is invisible to everyone else. Here, `python -m pytest tests` in
`gk-forge/tools/seedsmith` is a wired CI step, so this file is a gate rather than a note. It also now
sits in the same directory as the older domain gate whose reporting it replaces, which is where a
reader looking for "what checks the domains" will look first.

WHY THIS FILE EXISTS. Five of the six first-ship domains named a `bossSpeciesRef` that was neither
boss-eligible nor of the domain's own climate, and nothing caught it. The gate that should have caught
it, `test_dungeon_domain_content.py`, asserts inside a plain `for` loop with no subtest, so it reported
the FIRST failure and under-reported a five-domain defect by four. That gate's assertion is left
exactly as it is; this file is the replacement for the reporting, not an edit of it.

THE CONTRACT IS THREE PARTS, AND MAXIMALITY IS NOT ONE OF THEM:

    1. `bossSpeciesRef` names a species that exists in the real corpus;
    2. that species' `threatBand` is at or above the floor rung;
    3. that species' `elementPrimary` equals the domain's own `climate`.

WHAT WAS REMOVED FROM THIS FILE, AND WHY THAT IS NOT A SILENCED DEFECT. An earlier version also
asserted that no two domains may name the same `bossSpeciesRef`. That assertion is gone, and it was
removed on purpose rather than struck under pressure, because it was never a claim about the contract
above. Three reasons, in order of weight.

    1. IT WAS NOT DERIVABLE FROM THE CONTRACT. Distinctness is not a consequence of clauses 1-3. The
       three clauses constrain a domain's boss against the corpus and the tuning; a fourth constraint
       about how two domains relate to EACH OTHER is a different kind of statement, and pretending it
       belongs to the contract is how a file ends up asserting three things while its docstring
       describes one.

    2. IT IS A STATEMENT ABOUT AUTHORED CONTENT THAT KEEPS GROWING. The corpus and the domain set are
       both populations: climates are added, species are added, and the space of valid (climate,
       boss) pairs is not something a test can enumerate. An assertion with no stated contract behind
       it eventually blocks a legitimate content decision -- a seventh climate that genuinely reuses a
       boss, say -- and the only available "fix" in that moment is to edit the content to satisfy a
       rule no one can now state the reason for.

    3. ITS LATER REMOVAL WOULD READ AS WEAKENING. That is the cost that decides it. An assertion added
       with a rationale and deleted with a rationale is maintenance. An assertion added because it
       seemed obviously true and deleted later, under pressure, from a file that has since acquired a
       reputation, is indistinguishable from a test quietly relaxed to let bad data through -- and the
       reader has no way to tell the two apart. Better never to have had it than to remove it later
       under a deadline.

So this file asserts a contract and only a contract. If one-boss-per-climate is ever a real rule, it
belongs as a stated rule with a stated owner and a decision behind it -- and the honest place for it is
`test_dungeon_domain_content.py`, which already reasons per climate. It does not belong here, in a file
whose value is that its every assertion traces to a clause.

"PICK THE HIGHEST AVAILABLE RUNG, TIES BROKEN BY speciesId ORDINAL ASCENDING" was the mechanical
TIEBREAK used to pick replacements for five broken refs. It was never a contract, it is not applied
uniformly, and `domain.light-001` satisfies this contract at `harbinger` without satisfying it.
MAXIMALITY IS THEREFORE DELIBERATELY NOT ASSERTED HERE. Asserting it would force a balance decision
nobody asked for -- it would demand that every domain's boss be the single strongest species its
climate can offer, which is an authored-content call. A gate that encodes an editorial preference as a
contract is a gate that gets "fixed" by editing good content, so it is left out on purpose. Do not
add it without that decision being made deliberately.

THE FLOOR IS READ FROM TUNING, NEVER HARD-CODED AND NEVER SLICED. `data/tuning/encounter.v1.json`
publishes `threatWindow.bossFloorRung`, and that is the production floor, enforced in the engine as
`domain.boss-below-floor`. A sibling reader declared the floor instead as a fixed slice of the threat
ladder (`_THREAT_BAND[6:]`), which silently froze it at rung 7 while the tuning said otherwise; the
owner has ruled that the tuning is the source and the slice goes away. This file is written against
the ruling, so the two agree the day that lands instead of contradicting it. `boss_floor_rung()`
REFUSES when the tuning file is absent or the key is missing, because a plausible default would let
the whole gate pass against a floor nobody chose.

NOTHING HERE COUNTS A POPULATION. The corpus grows and the domain set grows; an assertion built on
either number fails the moment normal content ships, and the only available "fix" would be to edit the
number. What is asserted instead is stable as content is added: referential closure, rung ordering
against a floor read from tuning, element agreement, and id-space integrity.

RESOLUTION IS CWD-INDEPENDENT ON PURPOSE. The repository roots are read through seedsmith's own
cross-repo resolver (`core_root()` / `content_root()`), never by walking up from the current
directory. That is not fastidiousness: a legacy monorepo checkout sitting beside the split workspace
also carries `data/tuning` AND a `data/seed/creatures/species` corpus, and resolving from the working
directory silently reads THAT tree instead. Measured on this machine, the two species corpora differ
(549 files beside the workspace, 464 inside the pack), so a cwd-relative read produces a different
eligible set and a different verdict while looking perfectly healthy.

THE LADDER IS A DECLARING READ, NOT A TRANSCRIPTION. The ten rung ids are never restated here; they
come from `seedsmith.ladders.THREAT_BAND`, which reads the current published
`creature-threat.v{n}.json` and is itself gated against falling behind a new version. Rungs are derived
by position from that ladder's own declared "lowest first" order and compared numerically, so a ladder
that gains, loses or renames a rung moves this contract with it instead of quietly stranding it on a
stale vocabulary.
"""
from __future__ import annotations

import functools
import json
import sys
import unittest
from pathlib import Path


def _seedsmith_importable() -> None:
    """Put seedsmith on the import path, locating it by a file that actually exists.

    Nothing is guessed here. Two routes, in order of preference, and both measured rather than
    assumed:

    The FIRST is the import itself. From this directory's own project root, `pyproject.toml` declares
    `pythonpath = ["."]`, so the suite CI runs (`python -m pytest tests` in
    `gk-forge/tools/seedsmith`) already resolves `seedsmith` and this function returns without
    touching `sys.path`. That is the normal case and the reason the file needs no wiring of its own.

    The SECOND exists for every other invocation -- a pytest run launched from the workspace root, a
    bare `python tests/test_dungeon_domain_boss_contract.py`, an editor's runner with no project
    root. There, the probe asks for `gk-forge/tools/seedsmith/seedsmith/workspace_roots.py` -- the
    resolver module itself -- so a directory that merely shares the name cannot satisfy it. From this
    file's own location the workspace root is four levels up and `gk-forge/tools/seedsmith` hangs off
    it, so the probe still succeeds from the new home; it did not have to be rewritten to move, which
    is why it still reads `gk-forge/tools/seedsmith` rather than a path relative to this file.

    Every root used afterwards is resolved by the resolver rather than by this loop, so neither route
    can leave the gate reading a different tree than the one CI reads.
    """
    try:
        import seedsmith  # noqa: F401
    except ImportError:
        pass
    else:
        return
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "gk-forge" / "tools" / "seedsmith"
        if (candidate / "seedsmith" / "workspace_roots.py").is_file():
            sys.path.insert(0, str(candidate))
            return
    raise RuntimeError(
        "seedsmith is not importable and no gk-forge/tools/seedsmith was found above "
        f"{Path(__file__).resolve()}. Set PYTHONPATH to the seedsmith package parent, or set "
        "KEEPVERSE_FORGE_ROOT and run from a checkout where the split workspace is laid out."
    )


_seedsmith_importable()

from seedsmith.ladders import THREAT_BAND                     # noqa: E402
from seedsmith.workspace_roots import content_root, core_root  # noqa: E402

#: `data/seed/**` is the content pack; `data/tuning/**` is the engine repository. Two different
#: repositories, which is why both accessors appear -- `content_root()` for the domains and the
#: species corpus, `core_root()` for the tuning that publishes the floor.
SEED_DIR = content_root() / "data" / "seed"
DOMAINS_DIR = SEED_DIR / "dungeon" / "domains"
SPECIES_DIR = SEED_DIR / "creatures" / "species"
ENCOUNTER_TUNING = core_root() / "data" / "tuning" / "encounter.v1.json"


@functools.lru_cache(maxsize=1)
def threat_rank() -> "dict[str, int]":
    """Rung number per threat band id, derived from the ladder's declared "lowest first" order.

    A band id absent from the ladder gets NO entry, and `None` is therefore what a caller sees for a
    species carrying a band this ladder does not know. That is fail-closed on purpose: an unbanded
    species cannot be shown to clear a floor, so it fails the floor clause rather than passing by
    default.
    """
    if len(set(THREAT_BAND)) != len(THREAT_BAND):
        raise AssertionError(
            f"the threat ladder repeats a band id, so rungs are ambiguous: {THREAT_BAND!r}")
    return {band: rank for rank, band in enumerate(THREAT_BAND, start=1)}


@functools.lru_cache(maxsize=1)
def boss_floor_rung() -> int:
    """The boss floor, read from `encounter.v1.json`'s own `threatWindow.bossFloorRung`.

    No default and no fallback: a tuning file that lost the key, or names a band the ladder does not
    carry, is a refusal rather than a guess. Returning a plausible number here would let the whole
    gate pass against a floor nobody chose, which is the failure this file exists to prevent.
    """
    if not ENCOUNTER_TUNING.is_file():
        raise AssertionError(
            f"the boss floor's declaring tuning file is absent: {ENCOUNTER_TUNING}. Every claim "
            "about boss eligibility rests on it, so this gate refuses rather than assuming a floor."
        )
    doc = json.loads(ENCOUNTER_TUNING.read_text(encoding="utf-8"))
    try:
        band = doc["threatWindow"]["bossFloorRung"]
    except (KeyError, TypeError) as exc:
        raise AssertionError(
            f"{ENCOUNTER_TUNING} publishes no threatWindow.bossFloorRung ({exc!r}); the boss "
            "eligibility floor is undefined and cannot be defaulted."
        ) from None
    rank = threat_rank().get(band)
    if rank is None:
        raise AssertionError(
            f"encounter.v1.json sets bossFloorRung={band!r}, which is not a band on the current "
            f"threat ladder {THREAT_BAND!r}. The tuning and the ladder disagree about the "
            "vocabulary, so no floor can be computed from either alone."
        )
    return rank


@functools.lru_cache(maxsize=1)
def species_index() -> "dict[str, tuple[str, str]]":
    """`speciesId -> (threatBand, elementPrimary)` over the real corpus.

    Underscore-prefixed files are registry/index documents rather than species records, and each
    file's entries live under whichever of the three array shapes the generator emitted, so all
    three are read and anything without a string `speciesId` is skipped. Cached because the walk
    touches the whole corpus and every test below needs the same answer.
    """
    if not SPECIES_DIR.is_dir():
        raise AssertionError(f"the species corpus directory is absent: {SPECIES_DIR}")
    index: "dict[str, tuple[str, str]]" = {}
    for path in sorted(SPECIES_DIR.rglob("*.json")):
        if path.name.startswith("_"):
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        entries = doc if isinstance(doc, list) else doc.get("entries", doc.get("anchors", []))
        for entry in entries:
            species_id = entry.get("speciesId")
            if isinstance(species_id, str):
                index[species_id] = (entry.get("threatBand"), entry.get("elementPrimary"))
    return index


def shipped_domains() -> "dict[str, dict]":
    """Every shipped domain file, keyed by its filename stem.

    `_index.json` is the directory's own index rather than a domain and is excluded by name, the
    same way the existing domain gate excludes it. Nothing here counts domains: an assertion built
    on how many exist would fail the moment a seventh climate ships, which is the normal case, and
    the only "fix" available would be to edit the number.
    """
    if not DOMAINS_DIR.is_dir():
        raise AssertionError(f"the shipped domain directory is absent: {DOMAINS_DIR}")
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(DOMAINS_DIR.glob("*.json"))
        if path.name != "_index.json"
    }


class DungeonDomainBossContractTests(unittest.TestCase):
    """One method per clause, so any single clause can be struck without touching the others."""

    def test_every_domain_boss_species_ref_names_a_real_species(self) -> None:
        """Clause 1: referential closure -- the ref resolves to a species that exists."""
        known = species_index()
        for domain_id, domain in shipped_domains().items():
            with self.subTest(domain=domain_id):
                boss = domain.get("bossSpeciesRef")
                self.assertIsInstance(
                    boss, str,
                    f"{domain_id}: bossSpeciesRef is absent or not a string, so it names nothing")
                self.assertIn(
                    boss, known,
                    f"{domain_id}: bossSpeciesRef {boss!r} is not a species in the corpus "
                    f"({len(known)} species read from {SPECIES_DIR})")

    def test_every_domain_boss_meets_the_tuning_boss_floor_rung(self) -> None:
        """Clause 2: the boss' rung is at or above `encounter.v1.json`'s `bossFloorRung`."""
        known = species_index()
        rank = threat_rank()
        floor = boss_floor_rung()
        for domain_id, domain in shipped_domains().items():
            with self.subTest(domain=domain_id):
                boss = domain["bossSpeciesRef"]
                if boss not in known:
                    self.fail(f"{domain_id}: bossSpeciesRef {boss!r} is not a species, so its rung "
                              f"cannot clear floor rung {floor}")
                band, _ = known[boss]
                boss_rung = rank.get(band)
                self.assertIsNotNone(
                    boss_rung,
                    f"{domain_id}: bossSpeciesRef {boss!r} carries threatBand {band!r}, which is not "
                    f"a band on the current ladder {THREAT_BAND!r}, so it cannot be shown to meet "
                    f"floor rung {floor}")
                self.assertGreaterEqual(
                    boss_rung, floor,
                    f"{domain_id}: bossSpeciesRef {boss!r} is {band!r} (rung {boss_rung}), below "
                    f"the floor rung {floor} published by {ENCOUNTER_TUNING.name}")

    def test_every_domain_boss_primary_element_is_the_domain_climate(self) -> None:
        """Clause 3: the boss' own `elementPrimary` is the domain's `climate`."""
        known = species_index()
        for domain_id, domain in shipped_domains().items():
            with self.subTest(domain=domain_id):
                boss = domain["bossSpeciesRef"]
                if boss not in known:
                    self.fail(f"{domain_id}: bossSpeciesRef {boss!r} is not a species, so it has no "
                              f"elementPrimary to compare against the domain's climate")
                _, element = known[boss]
                self.assertEqual(
                    element, domain.get("climate"),
                    f"{domain_id}: bossSpeciesRef {boss!r} has elementPrimary {element!r} but the "
                    f"domain's climate is {domain.get('climate')!r}")

    def test_every_domain_id_matches_its_filename_and_is_shipped_once(self) -> None:
        """Referential integrity of the id space: filename, `domainId`, and uniqueness agree.

        This is the closure the boss clauses hang off -- a `bossSpeciesRef` is only attributable to
        a domain if the domain's own id identifies exactly one shipped file.
        """
        domains = shipped_domains()
        for domain_id, domain in domains.items():
            with self.subTest(domain=domain_id):
                self.assertEqual(
                    domain.get("domainId"), domain_id,
                    f"the file {domain_id}.json declares domainId {domain.get('domainId')!r}")
        declared = [d.get("domainId") for d in domains.values()]
        self.assertEqual(
            len(declared), len(set(declared)),
            f"two shipped domain files declare the same domainId: {sorted(declared)}")


if __name__ == "__main__":
    unittest.main()
