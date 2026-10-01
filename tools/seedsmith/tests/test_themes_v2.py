"""themes.v2.json publication (species-gear-chain T16): closure properties, never counts.

904 rows and 84 retired inputs are READINGS, not constants — the corpus grows. What is pinned:
every emitted rarity is current, every non-rarity field is byte-identical to v1, no key moved,
retired inputs map forward with disagreements reported, and the refresh is idempotent.

⚠ **Every write in this module goes to a PRIVATE COPY of the corpus root** (todo row T51). These tests
used to call `publish_v2(write=True)` against the production registry and assert the bytes were
unchanged, which (a) rewrote a committed corpus file from a unit test and (b) made the assertion depend
on the checkout's line endings: the writers emitted the OS default, so it failed on a fresh LF checkout
and passed only when an earlier test in the same run had already dirtied the file. The writers now pin
`newline="\\n"` and a publication into a copy is compared against the committed bytes instead.
"""
import json
import shutil
from pathlib import Path

from seedsmith.adapters.creatures import generate_themes as themes_mod

REPO_ROOT = Path(__file__).resolve().parents[3]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from seedsmith.workspace_roots import owning_base, seed_root  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

CREATURES = seed_root() / "creatures"
REGISTRY = CREATURES / "_registry"

CURRENT = set(themes_mod.CURRENT_RUNGS)


def _v1():
    return json.loads((REGISTRY / "themes.v1.json").read_text(encoding="utf-8"))["themes"]


def _v2():
    return json.loads((REGISTRY / "themes.v2.json").read_text(encoding="utf-8"))["themes"]


def _private_corpus(tmp_path: Path) -> Path:
    """The two inputs `publish_v2` reads — `_registry/themes.v1.json` and the species anchors — in a
    temp root, so no test in this module can write into `gk-data/packs/fusion/data/seed/creatures/**`. A committed corpus
    file rewritten by a unit test is the substrate rule `docs/contributing/testing-standard.md`
    forbids, and it is what made this module's own idempotence assertion order-dependent."""
    root = tmp_path / "creatures"
    (root / "_registry").mkdir(parents=True)
    shutil.copy2(REGISTRY / "themes.v1.json", root / "_registry" / "themes.v1.json")
    shutil.copytree(CREATURES / "species", root / "species")
    return root


def test_v2_carries_current_rarities_only():
    for key, row in _v2().items():
        assert row["rarity"] in CURRENT, f"{key} carries retired id {row['rarity']!r}"


def test_v2_changes_exactly_one_field():
    v1, v2 = _v1(), _v2()
    assert set(v1) == set(v2), "a themeKey moved — bindings would break"
    for key in v1:
        assert {k: v for k, v in v1[key].items() if k != "rarity"} == \
               {k: v for k, v in v2[key].items() if k != "rarity"}, \
               f"{key} changed more than rarity"


def test_retired_inputs_map_forward_with_disagreements_reported():
    report = themes_mod.publish_v2(write=False)
    assert report["retiredInputs"] > 0, "no retired input found — the migration has nothing to migrate"
    for d in report["disagreements"]:
        assert themes_mod.FORWARD_MAP, "forward map went missing"
        assert d["forwardMap"] != d["anchor"], "agreement misreported as disagreement"
        assert d["theme"] in _v1()


def test_publish_is_idempotent(tmp_path):
    """Two publications into the same private copy are byte-identical, and the writer emits LF — not
    the OS default. Read-only with respect to `gk-data/packs/fusion/data/seed/creatures/**` by construction."""
    root = _private_corpus(tmp_path)
    target = root / "_registry" / "themes.v2.json"

    themes_mod.publish_v2(root=root, write=True)
    first = target.read_bytes()
    assert b"\r\n" not in first, "the writer emitted the OS line ending, not LF (todo row T51)"

    themes_mod.publish_v2(root=root, write=True)
    assert target.read_bytes() == first


def test_a_fresh_publish_reproduces_the_committed_registry(tmp_path):
    """⭐ Read-only closure, and the check that would have caught the CRLF writers WITHOUT writing to
    the production tree: publishing into a private copy must reproduce the committed
    `themes.v2.json` byte for byte. A drifted writer fails here instead of silently dirtying the
    working tree on every test run."""
    root = _private_corpus(tmp_path)
    themes_mod.publish_v2(root=root, write=True)
    assert (root / "_registry" / "themes.v2.json").read_bytes() == \
        (REGISTRY / "themes.v2.json").read_bytes()
