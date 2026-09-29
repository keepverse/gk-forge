"""Resolver contract (tasks/keepverse-split-plan.md): env override, legacy layout, workspace layout."""

from __future__ import annotations

from pathlib import Path

import pytest

from seedsmith import workspace_roots as wr

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("KEEPVERSE_CONTENT_ROOT", "KEEPVERSE_CORE_ROOT", "KEEPVERSE_WORKSPACE_ROOT", "KEEPVERSE_PACK"):
        monkeypatch.delenv(k, raising=False)


def test_legacy_layout_resolves_every_root_to_the_repo():
    assert wr.content_root() == REPO
    assert wr.core_root() == REPO
    assert wr.workspace_root() == REPO
    assert (wr.content_root() / "data" / "seed").is_dir()


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
