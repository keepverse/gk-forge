"""build-favor labels resolve to legal aptitude ids; magnitudes in classification are blocked."""
import json
from pathlib import Path

import pytest

from seedsmith.adapters.items import buildfavor
from seedsmith.adapters.items.buildfavor import Blocked

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_postures_resolve_to_their_four_aptitudes():
    assert buildfavor.resolve("force") == ("Might", "Fortitude", "Vigor", "Onslaught")
    assert buildfavor.resolve("finesse") == ("Agility", "Composure", "Pierce", "Focus")
    assert buildfavor.resolve("bastion") == ("Bulwark", "Retribution", "Precision", "Ferocity")


def test_every_aptitude_id_is_its_own_focused_label():
    for aptitude in buildfavor.APTITUDES:
        assert buildfavor.resolve(aptitude) == (aptitude,)


def test_unknown_labels_are_blocked_not_defaulted():
    with pytest.raises(Blocked):
        buildfavor.resolve("might")  # case matters: labels are exact, never normalized
    with pytest.raises(Blocked):
        buildfavor.resolve("everything")


def test_check_classification_returns_the_pool_for_a_clean_answer():
    assert buildfavor.check_classification({"buildFavor": "force"}) == (
        "Might", "Fortitude", "Vigor", "Onslaught")


def test_check_classification_blocks_magnitudes_anywhere():
    # A model never supplies a threshold, weight, share, reserve, cost, period, or input.
    with pytest.raises(Blocked):
        buildfavor.check_classification({"buildFavor": "force", "minimumShareMilli": 250})
    with pytest.raises(Blocked):
        buildfavor.check_classification({"buildFavor": {"label": "force", "weight": 3}})
    with pytest.raises(Blocked):
        buildfavor.check_classification({"noLabel": "force"})


def test_labels_match_the_checked_in_aptitude_mirror():
    # Aptitude ids are ported verbatim (Aptitude.cs: a spelling drift silently breaks the
    # residual-fit comparison) — the mirror and this module agree as sets, never counts.
    mirror = json.loads(
        (REPO_ROOT / "data" / "seed" / "aptitudes" / "roster.json").read_text(encoding="utf-8"))
    mirrored = sorted(e["id"] for e in mirror["entries"])
    assert sorted(buildfavor.APTITUDES) == mirrored
