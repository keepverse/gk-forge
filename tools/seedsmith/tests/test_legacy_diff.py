"""Tests for seedsmith.adapters.creatures.anchor.legacy_diff (spec-anchor-emit.md §6, T2.7)."""
from __future__ import annotations

import json

from seedsmith.adapters.creatures.anchor.legacy_diff import diff_legacy, format_report
from seedsmith.report.cli import build_parser, cmd_creatures


def test_legacy_diff_reports_per_field_agreement():
    new_anchors = [
        {"speciesId": "a", "elementPrimary": "fire", "deployMode": "PlantAvatar",
         "acquisition": ["Summonable"], "variants": ["normal", "shiny"]},
        {"speciesId": "b", "elementPrimary": "ice", "deployMode": "HypnoAlly",
         "acquisition": ["Summonable"], "variants": ["normal"]},
    ]
    legacy = [
        {"id": "a", "elementPrimary": "fire", "deployMode": "PlantAvatar",
         "acquisition": ["Summonable"], "variants": ["shiny", "normal"]},  # same set, diff order
        {"id": "b", "elementPrimary": "earth", "deployMode": "HypnoAlly",
         "acquisition": ["CaptureOnly"], "variants": ["normal"]},
    ]
    report = diff_legacy(new_anchors, legacy)

    assert report["elementPrimary"].total == 2
    assert report["elementPrimary"].agree == 1   # a agrees, b disagrees
    assert report["deployMode"].agree == 2         # both agree
    assert report["acquisition"].agree == 1        # a agrees, b disagrees
    assert report["variants"].agree == 2           # order-insensitive — both agree


def test_species_absent_from_legacy_are_excluded_not_counted_as_disagreement():
    new_anchors = [{"speciesId": "brand-new", "elementPrimary": "fire", "deployMode": "PlantAvatar",
                    "acquisition": ["Summonable"], "variants": ["normal"]}]
    report = diff_legacy(new_anchors, legacy_entries=[])
    for fa in report.values():
        assert fa.total == 0
        assert fa.agree_rate == 0.0


def test_only_the_named_fields_are_compared():
    from seedsmith.adapters.creatures.anchor.legacy_diff import COMPARED_FIELDS
    assert set(COMPARED_FIELDS) == {"elementPrimary", "deployMode", "acquisition", "variants"}
    assert "attackTempo" not in COMPARED_FIELDS  # no old counterpart to compare against


def test_format_report_reads_as_a_percentage():
    new_anchors = [{"speciesId": "a", "elementPrimary": "fire", "deployMode": "PlantAvatar",
                    "acquisition": ["Summonable"], "variants": ["normal"]}]
    legacy = [{"id": "a", "elementPrimary": "fire", "deployMode": "PlantAvatar",
              "acquisition": ["Summonable"], "variants": ["normal"]}]
    text = format_report(diff_legacy(new_anchors, legacy))
    assert "100.0%" in text


# ---- `seedsmith creatures diff-legacy` -- the real CLI entrypoint (T2.7, closed 2026-09-02) --------
#
# `legacy_diff.py`'s own docstring named the gap: "a small future export step (or a one-off read)
# produces those [legacy dicts]... this module only computes and reports." Closed by
# `CreatureSpeciesGen --export-legacy` (C#, reads the real compiled catalog) feeding this CLI command,
# which never reads C# source itself, matching the module's own stated boundary.


def _anchor_tree(tmp_path, side="plant"):
    root = tmp_path / "species"
    (root / side).mkdir(parents=True)
    entries = [
        {"speciesId": "Alpha", "side": side, "elementPrimary": "fire", "deployMode": "PlantAvatar",
         "acquisition": ["Summonable"], "variants": ["normal"]},
        {"speciesId": "Beta", "side": side, "elementPrimary": "ice", "deployMode": "PlantAvatar",
         "acquisition": ["Summonable"], "variants": ["normal", "shiny"]},
    ]
    (root / side / "family.json").write_text(json.dumps(entries), encoding="utf-8")
    (root / "_index.json").write_text(
        json.dumps({"Alpha": f"{side}/family.json", "Beta": f"{side}/family.json"}), encoding="utf-8")
    return root


def _legacy_file(tmp_path):
    # Lowercase ids, matching CreatureSpeciesCatalog's own real casing convention -- proves the CLI
    # normalizes case itself rather than requiring the caller to pre-lowercase.
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps([
        {"id": "alpha", "elementPrimary": "fire", "deployMode": "PlantAvatar",
         "acquisition": ["Summonable"], "variants": ["normal"]},
        {"id": "beta", "elementPrimary": "earth", "deployMode": "PlantAvatar",
         "acquisition": ["CaptureOnly"], "variants": ["normal", "shiny"]},
    ]), encoding="utf-8")
    return path


def test_cli_parses_creatures_diff_legacy():
    parser = build_parser()
    args = parser.parse_args(
        ["creatures", "diff-legacy", "--legacy", "some/path.json", "--anchors", "some/anchors"])
    assert args.func is cmd_creatures
    assert args.creature_command == "diff-legacy"
    assert args.legacy == "some/path.json"
    assert args.anchors == "some/anchors"


def test_diff_legacy_end_to_end_through_the_real_cli_normalizes_case_and_reports(tmp_path, capsys):
    anchors_root = _anchor_tree(tmp_path)
    legacy_path = _legacy_file(tmp_path)

    parser = build_parser()
    args = parser.parse_args([
        "creatures", "diff-legacy", "--legacy", str(legacy_path), "--anchors", str(anchors_root)])
    exit_code = args.func(args)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "species present in both sets: 2" in out
    # Alpha agrees on elementPrimary/deployMode/acquisition/variants; Beta disagrees on
    # elementPrimary and acquisition -- 2 fields at 2/2, 2 fields at 1/2.
    assert "elementPrimary: 1/2 agree" in out
    assert "acquisition: 1/2 agree" in out
    assert "deployMode: 2/2 agree" in out
    assert "variants: 2/2 agree" in out


def test_diff_legacy_without_legacy_flag_refuses_naming_the_fix():
    parser = build_parser()
    args = parser.parse_args(["creatures", "diff-legacy"])
    exit_code = args.func(args)
    assert exit_code == 2  # EXIT_CANNOT_RUN


def test_diff_legacy_with_a_missing_legacy_file_refuses():
    parser = build_parser()
    args = parser.parse_args(["creatures", "diff-legacy", "--legacy", "/nowhere/at/all.json"])
    exit_code = args.func(args)
    assert exit_code == 2
