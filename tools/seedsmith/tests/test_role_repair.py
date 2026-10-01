"""ISG-gap-1 — the deterministic backward pass over D30's dropped hybrid roles in the `set` corpus.

    python -m pytest gk-forge/tools/seedsmith/tests/test_role_repair.py -q

⛔ **Nothing here pins a population.** How many entries needed a re-placement, and where each landed,
is a READING that moves whenever content ships; `test_the_legacy_batch_relocation_reading_prints`
prints it and asserts only the closure property (every relocation goes from a dropped role to a
hybrid-core one). The write-path assertions run against a PRIVATE COPY of the real corpus, so a test
can never rewrite the committed tree — the rule this repo spent a 65.5 GB temp-dir leak learning
(`docs/contributing/testing-standard.md`).

The fixture cases are the ones the real corpus cannot produce on demand: a dropped role whose named
hosts are ALL already claimed, a two-frame entry whose two rows must move together, and a registry
whose own hand-off sentence cannot be read.
"""
from __future__ import annotations

import collections
import glob
import json
import shutil
import tempfile
from pathlib import Path

import pytest
from seedsmith.adapters.items.setgen import role_repair as repair_mod
from seedsmith.adapters.items.setgen import roles as roles_mod
from seedsmith.adapters.items.setgen import seedfile as seedfile_mod
from seedsmith.adapters.items.setgen import species_repair as species_repair_mod
from seedsmith.report.cli import EXIT_CLEAN, EXIT_REFUSED, main

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

ITEMS_ROOT = _owned("data/seed/items")
SETS_DIR = ITEMS_ROOT / "sets"


def _entries(directory: Path) -> "list[dict]":
    out: "list[dict]" = []
    for name in sorted(glob.glob(str(directory / "*.json"))):
        document = json.loads(Path(name).read_text(encoding="utf-8"))
        out.extend(document.get("entries") or ())
    return out


def _defective_count(directory: Path) -> int:
    """How many entries still name a dropped role — computed from the partition rather than pinned:
    on the pre-repair corpus every defective entry counts, on the committed (repaired) one none does.
    A test that hard-coded the pre-repair number would only pass on the day it was written."""
    return sum(1 for entry in _entries(directory)
               if any(m.get("role") in roles_mod.DROPPED_ROLES
                      for m in entry.get("members") or ()))


def _copied_corpus(root: Path) -> Path:
    target = root / "sets"
    shutil.copytree(SETS_DIR, target)
    return target


def _unrepaired_copy(root: Path) -> Path:
    """A copy of the corpus with the repair UNDONE, using each file's own amendment as the exact
    inverse. `from`/`to` are recorded per entry, so the reverse move needs no guess about which role
    was there before — which is what makes the legacy reading below a measurement and not a fixture."""
    sets = _copied_corpus(root)
    for path in sorted(sets.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        inverses: "dict[str, dict[str, str]]" = {}
        for amendment in (document.get("_meta") or {}).get("amendments") or ():
            for row in amendment.get("entries") or ():
                inverses[row["entryId"]] = {r["to"]: r["from"] for r in row["relocations"]}
        if isinstance(document.get("_meta"), dict):
            document["_meta"].pop("amendments", None)
        for entry in document.get("entries") or ():
            back = inverses.get(entry["id"], {})
            for member in entry.get("members") or ():
                if member["role"] in back:
                    member["role"] = back[member["role"]]
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8", newline="\n")
    return sets


def _partition(entries: "list[dict]", *, meta: "dict | None" = None) -> dict:
    return {"schemaVersion": 1, "kind": "set",
            "_meta": meta if meta is not None else {"partition": "sets/fixture"},
            "entries": entries}


def _fixture_entry(entry_id: str, member_roles: "list[str]") -> dict:
    """One member row per (role, frame) — the shape every composable shipped set actually uses."""
    return {
        "id": entry_id,
        "nameKey": f"set.{entry_id.split('.', 1)[1]}",
        "name": "Fixture",
        "themeKey": "theme.verdant-graft",
        "setClass": "general",
        "members": [{"role": role, "frame": frame}
                    for role in member_roles for frame in ("humanoid", "plant")],
        "thresholds": [{"pieces": 2}, {"pieces": 4}],
        "notes": "authored notes that a mechanical repair must not touch",
        "flavor": "an authored flavour line that a mechanical repair must not touch",
    }


def _fixture_partition(root: Path, document: dict) -> Path:
    sets = root / "sets"
    sets.mkdir(parents=True, exist_ok=True)
    (sets / "fixture.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sets


def _author_meta(path: Path) -> dict:
    """Every `_meta` key except `amendments` — the provenance a repair must not touch.

    A handful of shipped partitions carry no `_meta` at all (they predate the contract's §9 stamp),
    and a repair must not mint one for them either.
    """
    meta = json.loads(path.read_text(encoding="utf-8")).get("_meta") or {}
    return {k: v for k, v in meta.items() if k != "amendments"}


def _core_with(mutate) -> dict:
    document = json.loads((ITEMS_ROOT / "_registry" / "core.v1.json").read_text(encoding="utf-8"))
    mutate(document)
    return document


# --------------------------------------------------------------------------------------------
# the registry is the authority on where a dropped role's content went
# --------------------------------------------------------------------------------------------


def test_the_registry_names_a_hybrid_core_host_for_every_dropped_role():
    """A pin on a CLOSED, frozen vocabulary — `core.v1.json` is `registryVersion 2`, `frozen: true`,
    and its own note says a change is v3 plus an explicit decision on which partitions re-run. The
    mapping is stable enough to pin, and pinning it is what stops a v3 edit to `hybridDropReason`
    from silently re-pointing this repair at a different slot."""
    hosts = repair_mod.migration_hosts()
    assert hosts == {
        "head-guard": ("core-guard", "mantle"),
        "sense": ("manipulator", "jewel-major"),
        "ward-array": ("core-guard",),
    }
    assert set(hosts) == set(roles_mod.DROPPED_ROLES)
    for role, named in hosts.items():
        assert named, role
        for host in named:
            assert host in roles_mod.HYBRID_CORE_ROLES, (role, host)


def test_an_unreadable_hand_off_sentence_refuses_rather_than_guessing():
    """Three refusals, each of which would otherwise become a silently wrong host: a role with no
    `hybridDropReason`, a reason the sentence pattern cannot read, and a named host outside the core."""
    def _drop_reason(document: dict) -> None:
        for row in document["roles"]["list"]:
            if row["roleId"] == "sense":
                row.pop("hybridDropReason")

    def _rewrite_reason(document: dict) -> None:
        for row in document["roles"]["list"]:
            if row["roleId"] == "ward-array":
                row["hybridDropReason"] = "its shield families simply stop existing."

    def _off_core_host(document: dict) -> None:
        for row in document["roles"]["list"]:
            if row["roleId"] == "head-guard":
                row["hybridDropReason"] = ("its families migrate to ward-array at a reduced tier cap "
                                           "instead.")

    with tempfile.TemporaryDirectory() as temp:
        for index, mutate in enumerate((_drop_reason, _rewrite_reason, _off_core_host)):
            path = Path(temp) / f"core-{index}.json"
            path.write_text(json.dumps(_core_with(mutate)), encoding="utf-8")
            with pytest.raises(repair_mod.SetRoleRepairError):
                repair_mod.migration_hosts(path)


def test_a_role_table_that_calls_a_dropped_role_eligible_refuses():
    """The other direction of drift: the registry and `roles.DROPPED_ROLES` must agree about who is
    dropped, or this repair would re-place a role the core actually hosts."""
    def _revive(document: dict) -> None:
        for row in document["roles"]["list"]:
            if row["roleId"] == "sense":
                row["hybridEligible"] = True

    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "core.json"
        path.write_text(json.dumps(_core_with(_revive)), encoding="utf-8")
        with pytest.raises(repair_mod.SetRoleRepairError):
            repair_mod.migration_hosts(path)


# --------------------------------------------------------------------------------------------
# the real corpus — closure, a printed reading, and the properties a repair must preserve
# --------------------------------------------------------------------------------------------


def test_no_shipped_set_entry_names_a_role_outside_the_hybrid_core():
    """⭐ THE regression assertion this whole task exists for: the `Linkage/SetCompletability` GAP
    fires on exactly this, so a corpus that passes here cannot fail there. A membership assertion
    over a closed vocabulary, never a count — a species shipping a new set is the normal case and
    does not touch it."""
    checked = 0
    for entry in _entries(SETS_DIR):
        distinct = sorted({m.get("role") for m in entry.get("members") or ()})
        assert roles_mod.refuse_roles(distinct) == [], entry["id"]
        for member in entry["members"]:
            assert member["role"] in roles_mod.HYBRID_CORE_ROLES, entry["id"]
        checked += len(distinct)
    assert checked > 0


def test_the_committed_corpus_is_a_fixed_point_of_the_repair():
    """The committed tree IS the repaired tree, so the plan reports zero work. This is the assertion
    that failed before the fix — with the 18 entries the BCU2.11 run named."""
    result = repair_mod.repair_set_roles(sets_dir=SETS_DIR, write=False)
    assert result.entries > 0
    assert result.changed_entries == 0
    assert result.changed_files == 0
    assert result.changed_members == 0
    assert result.relocations == {}


def test_the_legacy_batch_relocation_reading_prints():
    """⭐ A READING, printed and never asserted. The pre-D30 `sets-1c` batch is the only population
    that ever carried this defect (every `set-charm-gen/*` partition is authored under the capped
    brief), so the count is a fact about a dated batch and the fix for a future failure is never to
    bump it. Read from each file's own amendment rather than from a stored constant."""
    files = 0
    moves: "collections.Counter[tuple[str, str]]" = collections.Counter()
    for path in sorted(SETS_DIR.glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        amendments = [a for a in (document.get("_meta") or {}).get("amendments") or ()
                      if a.get("batch") == repair_mod.AMENDMENT_BATCH]
        if not amendments:
            continue
        files += 1
        for amendment in amendments:
            for row in amendment.get("entries") or ():
                for relocation in row.get("relocations") or ():
                    assert relocation["from"] in roles_mod.DROPPED_ROLES
                    assert relocation["to"] in roles_mod.HYBRID_CORE_ROLES
                    moves[(relocation["from"], relocation["to"])] += 1
    print(f"\nlegacy-role repair reading (printed, not asserted): {files} partitions, "
          f"{sum(moves.values())} distinct-role relocations")
    for (old, new), count in sorted(moves.items()):
        print(f"  {old:<12} -> {new:<18} {count}")
    assert files > 0, "no partition carries the amendment — this test is dead"


def test_the_unrepaired_corpus_is_what_the_repair_fixes():
    """The inverse of the test above on a private copy: undo every amendment and the pre-D30 defect
    is back, at exactly the entries the amendment names. This is what proves the corpus assertion
    above is load-bearing rather than trivially true of any corpus."""
    with tempfile.TemporaryDirectory() as temp:
        sets = _unrepaired_copy(Path(temp))
        defective = _defective_count(sets)
        assert defective > 0
        result = repair_mod.repair_set_roles(sets_dir=sets, base_types_dir=ITEMS_ROOT, write=True)
        assert result.changed_entries == defective
        assert _defective_count(sets) == 0


# --------------------------------------------------------------------------------------------
# the write path — private copy, idempotence, and what must be preserved
# --------------------------------------------------------------------------------------------


def test_applying_the_plan_moves_only_roles_and_bindings_and_keeps_every_other_key():
    with tempfile.TemporaryDirectory() as temp:
        sets = _unrepaired_copy(Path(temp))
        expected = _defective_count(sets)
        assert expected > 0, "the corpus no longer has a defective entry — this test is dead"
        before = {entry["id"]: json.loads(json.dumps(entry)) for entry in _entries(sets)}

        result = repair_mod.repair_set_roles(sets_dir=sets, base_types_dir=ITEMS_ROOT, write=True)
        assert result.changed_entries == expected

        after = _entries(sets)
        assert len(after) == len(before)
        for entry in after:
            original = before[entry["id"]]
            for key in ("nameKey", "name", "themeKey", "thresholds", "notes", "flavor", "tags"):
                if key in original:
                    assert entry.get(key) == original[key], (entry["id"], key)
            # Cardinality and the ladder, unchanged: membership is counted per ROLE, so a repair that
            # shortened the role list would have traded SetRoleNotUniversal for SetShortOfThreshold.
            assert (len({m["role"] for m in entry["members"]})
                    == len({m["role"] for m in original["members"]}))
            assert ([t["pieces"] for t in entry["thresholds"]]
                    == [t["pieces"] for t in original["thresholds"]])
            # Every member is legal, carries a base type, and no (role, frame) pair repeats.
            assert roles_mod.refuse_roles(sorted({m["role"] for m in entry["members"]})) == []
            pairs = [(m["role"], m["frame"]) for m in entry["members"]]
            assert len(pairs) == len(set(pairs))
            for member in entry["members"]:
                assert isinstance(member.get("baseType"), str) and member["baseType"]
            # The role and its re-bound base type are the ONLY things that may move.
            for member, previous in zip(entry["members"], original["members"]):
                if member["role"] == previous["role"]:
                    assert member == previous, entry["id"]


def test_the_move_is_recorded_in_the_files_own_provenance_and_the_author_fields_survive():
    with tempfile.TemporaryDirectory() as temp:
        sets = _unrepaired_copy(Path(temp))
        author_meta = {path.name: _author_meta(path) for path in sorted(sets.glob("*.json"))}

        repair_mod.repair_set_roles(sets_dir=sets, base_types_dir=ITEMS_ROOT, write=True)

        amended = 0
        for path in sorted(sets.glob("*.json")):
            document = json.loads(path.read_text(encoding="utf-8"))
            meta = document.get("_meta") or {}
            # The required provenance keys still name the batch that AUTHORED the entry, untouched:
            # overwriting them would make the file's own ledger describe a run that never happened.
            assert {k: v for k, v in meta.items() if k != "amendments"} == author_meta[path.name]
            amendments = meta.get("amendments") or ()
            assert len(amendments) <= 1, f"{path.name} was amended twice by one run"
            for amendment in amendments:
                amended += 1
                assert amendment["batch"] == repair_mod.AMENDMENT_BATCH
                assert amendment["model"] == repair_mod.AMENDMENT_MODEL
                assert amendment["promptVersion"] == repair_mod.AMENDMENT_PROMPT_VERSION
                assert amendment["authoredUtc"] == repair_mod.AMENDMENT_AUTHORED_UTC
                assert amendment["sourceRef"] == repair_mod.AMENDMENT_SOURCE_REF
                assert amendment["entries"]
                # One row per changed entry, each naming a role pair that really is in that entry:
                # the row is checked against the file, not against a second copy of the move.
                by_id = {entry["id"]: entry for entry in document["entries"]}
                for row in amendment["entries"]:
                    assert row["entryId"] in by_id
                    present = {m["role"] for m in by_id[row["entryId"]]["members"]}
                    for relocation in row["relocations"]:
                        assert relocation["to"] in present, (row["entryId"], relocation)
                        assert relocation["from"] not in present, (row["entryId"], relocation)
                assert len(amendment["entries"]) <= len(document["entries"])
        assert amended > 0


def test_a_second_apply_changes_nothing_and_is_byte_identical():
    with tempfile.TemporaryDirectory() as temp:
        sets = _unrepaired_copy(Path(temp))
        repair_mod.repair_set_roles(sets_dir=sets, base_types_dir=ITEMS_ROOT, write=True)
        first = {p.name: p.read_bytes() for p in sorted(sets.glob("*.json"))}

        second = repair_mod.repair_set_roles(sets_dir=sets, base_types_dir=ITEMS_ROOT, write=True)
        assert second.changed_entries == 0
        assert second.changed_files == 0
        assert {p.name: p.read_bytes() for p in sorted(sets.glob("*.json"))} == first
        assert list(sets.glob("*.tmp")) == []


def test_the_plan_writes_nothing_without_write():
    before = {p: p.read_bytes() for p in sorted(SETS_DIR.glob("*.json"))}
    repair_mod.repair_set_roles(sets_dir=SETS_DIR, write=False)
    assert {p: p.read_bytes() for p in sorted(SETS_DIR.glob("*.json"))} == before


def test_written_partitions_are_lf_only():
    """The sibling creature-theme writers shipped CRLF on Windows and dirtied 17,491 lines of a file
    they meant to touch once; this repair must not repeat it.

    Scoped to the files this run WROTE, not to the whole copy: a handful of older partitions already
    ship CRLF in the committed corpus (measured — `abyssswordstar.json` among them), and a no-op
    repair must not be blamed for bytes it never touched. Rewriting them here would be a corpus-wide
    reformat smuggled in behind a role fix.
    """
    with tempfile.TemporaryDirectory() as temp:
        sets = _unrepaired_copy(Path(temp))
        result = repair_mod.repair_set_roles(sets_dir=sets, base_types_dir=ITEMS_ROOT, write=True)
        written = [Path(f.path) for f in result.files]
        assert written, "the repair wrote nothing — this test is dead"
        for path in written:
            assert b"\r\n" not in path.read_bytes(), path.name


def test_the_shared_writer_is_the_one_species_repair_uses():
    """All three set repairs write the same corpus, so they must agree byte for byte about
    serialisation — otherwise running them in sequence produces a diff line nobody asked for."""
    assert species_repair_mod.write_document is repair_mod.write_document
    assert seedfile_mod.ITEM_SEED_ROOT.is_dir()


# --------------------------------------------------------------------------------------------
# fixture cases the real corpus cannot produce on demand
# --------------------------------------------------------------------------------------------


def test_both_frames_of_one_dropped_role_move_to_the_same_replacement():
    """⚠ Regression, found by diffing the write against the plan on the real corpus: a two-frame entry
    lists its dropped role TWICE, and iterating the raw member rows re-ran the candidate search for
    the second row — walking one step further down the preference list and landing
    `set.verdant-graft-001`'s `head-guard` on `girdle` instead of its named host `mantle`. The two
    rows of one role must move together, or the entry gains a role it never declared."""
    with tempfile.TemporaryDirectory() as temp:
        sets = _fixture_partition(Path(temp), _partition([
            _fixture_entry("set.fixture-001",
                           ["core-guard", "manipulator", "head-guard", "footing"])]))
        result = repair_mod.repair_set_roles(sets_dir=sets, base_types_dir=ITEMS_ROOT, write=True)
        assert result.changed_entries == 1
        assert result.relocations == {("head-guard", "mantle"): 1}

        entry = _entries(sets)[0]
        assert len(entry["members"]) == 8
        # Both rows of the moved role carry the SAME role: the registry's first named host.
        moved = {m["role"] for m in entry["members"]} - {"core-guard", "manipulator", "footing"}
        assert moved == {"mantle"}
        # And the two-frame shape survived: one row per (role, frame), both frames present for each.
        for role in {m["role"] for m in entry["members"]}:
            assert {m["frame"] for m in entry["members"] if m["role"] == role} == {
                "humanoid", "plant"}
        assert len({m["role"] for m in entry["members"]}) == 4


def test_a_dropped_role_whose_named_hosts_are_all_claimed_falls_back_to_a_legal_role():
    """`set.thorned-chassis-002` already claims both hosts `head-guard` names. Refusing there would
    leave a repairable entry unrepairable, so tier 2 exists — and it must still be a NON-armament
    hybrid-core role: a head slot becoming the main hand is the repair inventing the one decision
    `ssot-sets.md` §3.5 rule 4 reserves for the author."""
    with tempfile.TemporaryDirectory() as temp:
        sets = _fixture_partition(Path(temp), _partition([
            _fixture_entry("set.fixture-002",
                           ["core-guard", "mantle", "girdle", "head-guard"])]))
        result = repair_mod.repair_set_roles(sets_dir=sets, base_types_dir=ITEMS_ROOT, write=True)
        assert result.changed_entries == 1
        assert result.relocations == {("head-guard", "footing"): 1}

        entry = _entries(sets)[0]
        distinct = sorted({m["role"] for m in entry["members"]})
        assert distinct == sorted({"core-guard", "mantle", "girdle", "footing"})
        assert not ({m["role"] for m in entry["members"]} & repair_mod.ARMAMENT_ROLES)
        assert roles_mod.refuse_roles(distinct) == []


def test_the_preference_pool_never_offers_an_armament_role():
    hosts = repair_mod.migration_hosts()
    weights = repair_mod._role_weights()
    for role in sorted(roles_mod.DROPPED_ROLES):
        pool = repair_mod._preference_pool(role, hosts, weights)
        assert set(pool) == set(roles_mod.HYBRID_CORE_ROLES) - repair_mod.ARMAMENT_ROLES, role
        # Named hosts first, in the registry's own order, then tier 2 by distance from the dropped
        # role's own weight with the lighter role first on a tie.
        assert pool[:len(hosts[role])] == hosts[role], role
        rest = pool[len(hosts[role]):]
        keys = [(abs(weights[r] - weights[role]), weights[r]) for r in rest]
        assert keys == sorted(keys), role


def test_an_entry_already_legal_is_left_byte_identical():
    with tempfile.TemporaryDirectory() as temp:
        sets = _fixture_partition(Path(temp), _partition([
            _fixture_entry("set.fixture-003",
                           ["core-guard", "mantle", "girdle", "footing"])], meta={
                "partition": "sets/fixture", "batch": "fixture", "promptVersion": 1,
                "model": "none", "authoredUtc": "1970-01-01T00:00:00Z"}))
        before = (sets / "fixture.json").read_bytes()
        result = repair_mod.repair_set_roles(sets_dir=sets, base_types_dir=ITEMS_ROOT, write=True)
        assert result.changed_entries == 0
        assert (sets / "fixture.json").read_bytes() == before


# --------------------------------------------------------------------------------------------
# the CLI verb
# --------------------------------------------------------------------------------------------


def test_the_cli_dry_run_plans_without_writing(capsys):
    assert main(["items", "repair-set-roles"]) == EXIT_CLEAN
    report = json.loads(capsys.readouterr().out)
    assert report["write"] is False
    assert report["entries"] > 0
    assert report["changedEntries"] == 0


def test_the_cli_refuses_a_production_write_without_the_explicit_flag(capsys):
    assert main(["items", "repair-set-roles", "--write"]) == EXIT_REFUSED
    assert "allow-production-tree" in capsys.readouterr().err


def test_the_cli_writes_a_private_tree_and_is_idempotent(capsys):
    with tempfile.TemporaryDirectory() as temp:
        sets = _unrepaired_copy(Path(temp))
        expected = _defective_count(sets)
        assert expected > 0
        assert main(["items", "repair-set-roles", "--write", "--sets-dir", str(sets)]) == EXIT_CLEAN
        first = json.loads(capsys.readouterr().out)
        assert first["changedEntries"] == expected
        assert first["relocations"], "a repair that moved nothing must not report a relocation table"
        assert _defective_count(sets) == 0

        assert main(["items", "repair-set-roles", "--write", "--sets-dir", str(sets)]) == EXIT_CLEAN
        second = json.loads(capsys.readouterr().out)
        assert second["changedEntries"] == 0
        assert second["changedFiles"] == 0
