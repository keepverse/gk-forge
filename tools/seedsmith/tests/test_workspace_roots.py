"""Resolver contract (tasks/keepverse-split-plan.md): env override, legacy layout, workspace layout."""

from __future__ import annotations

from pathlib import Path

import pytest

from seedsmith import workspace_roots as wr


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("KEEPVERSE_CONTENT_ROOT", "KEEPVERSE_CORE_ROOT", "KEEPVERSE_WORKSPACE_ROOT", "KEEPVERSE_PACK"):
        monkeypatch.delenv(k, raising=False)


def _plant_legacy_repo(base: Path) -> Path:
    """A PRE-SPLIT monorepo, planted: one directory that is content, core and workspace at once.

    The legacy probe needs BOTH `data/seed` AND `data/tuning` beside the solution file, because
    gk-forge satisfies `FusionRpg.slnx` + `data/seed` by ITSELF (the split left a repository's
    generator inputs where the generator is) and matching there is what stopped the walk one
    directory short. So all three markers, or it is not a legacy layout.
    """
    root = base / "legacy-repo"
    (root / "data" / "seed").mkdir(parents=True)
    (root / "data" / "tuning").mkdir(parents=True)
    (root / "FusionRpg.slnx").write_text("", encoding="utf-8")
    return root


def test_legacy_layout_resolves_every_root_to_the_repo(tmp_path):
    # PLANTED, and started from a subdirectory, because the alternative was asserting the AMBIENT
    # machine. Called with no argument the accessors walk up from the module's own directory, so
    # this test could only pass in a pre-split clone -- the one layout where the walk reaches a
    # legacy root. On a split workspace it walked on to the Keepverse root and correctly answered
    # gk-data's pack, gk-core and the workspace, which is right and is not what the test claims to
    # check. Nothing was wrong with the contract being asserted; nothing was planted for it to be
    # asserted against. A planted layout is the same rule on any machine, and it exercises the
    # legacy DETECTION rather than the env override (which `test_env_override_wins` already owns).
    legacy = _plant_legacy_repo(tmp_path)
    nested = legacy / "tools" / "seedsmith"
    nested.mkdir(parents=True)
    assert wr.content_root(nested) == legacy
    assert wr.core_root(nested) == legacy
    assert wr.workspace_root(nested) == legacy
    assert (wr.content_root(nested) / "data" / "seed").is_dir()


def test_a_legacy_repo_nested_in_a_workspace_resolves_against_itself(tmp_path):
    # NEAREST MATCH WINS, whichever kind it is, and the walk's order is the whole contract: a
    # legacy clone inside the workspace must answer for itself, because returning the outer
    # workspace would resolve content into a pack the caller never asked for. The outer workspace
    # is planted too, so this discriminates walk order from probe precision -- a fixture with only
    # the workspace cannot tell the two apart, because the nearest is the workspace either way.
    (tmp_path / "gk-core").mkdir()
    (tmp_path / "gk-data").mkdir()
    nested = _plant_legacy_repo(tmp_path) / "tools" / "seedsmith"
    nested.mkdir(parents=True)
    assert wr.content_root(nested) == tmp_path / "legacy-repo"
    assert wr.core_root(nested) == tmp_path / "legacy-repo"
    assert wr.workspace_root(nested) == tmp_path / "legacy-repo"


def test_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("KEEPVERSE_CONTENT_ROOT", str(tmp_path))
    assert wr.content_root() == tmp_path


def test_workspace_layout(tmp_path):
    (tmp_path / "gk-core" / "src").mkdir(parents=True)
    (tmp_path / "gk-data" / "packs" / "fusion" / "data" / "seed").mkdir(parents=True)
    start = tmp_path / "gk-core" / "src"
    assert wr.core_root(start) == tmp_path / "gk-core"
    assert wr.workspace_root(start) == tmp_path
    assert wr.content_root(start) == tmp_path / "gk-data" / "packs" / "fusion"


def test_pack_env_selects_the_pack_and_a_missing_pack_throws(monkeypatch, tmp_path):
    (tmp_path / "gk-core").mkdir()
    (tmp_path / "gk-data" / "packs" / "fusion").mkdir(parents=True)
    monkeypatch.setenv("KEEPVERSE_PACK", "keepverse")
    with pytest.raises(wr.RootNotFound):
        wr.content_root(tmp_path / "gk-core")


def test_nothing_found_throws(tmp_path):
    with pytest.raises(wr.RootNotFound):
        wr.core_root(tmp_path)
