"""forge-gem rows are DERIVED, never authored — every assertion here recomputes the
derivation from the gem corpus rather than pinning today's one row (that row exists only
because atom.elemental-power is the one shipped family spanning two tiers; gemgen growing a
second multi-tier family must grow the plan with no code change)."""
from seedsmith.adapters.items.recipegen import emit as emit_mod
from seedsmith.adapters.items.recipegen import forgegem
from seedsmith.adapters.items.recipegen import opvocab
from seedsmith.adapters.items.recipegen import run as run_mod


def test_forge_gem_is_a_supported_operation_with_a_gem_output_kind():
    assert "forge-gem" in opvocab.SUPPORTED_FOR_GENERATION
    assert opvocab.output_kind_for("forge-gem") == "gem"
    # forge-gem spends exactly the operation's own three priced classes (+souls, legal always).
    assert opvocab.ALLOWED_CLASSES["forge-gem"] == frozenset({"shard", "essence", "catalyst"})
    assert opvocab.catalyst_for("forge-gem") == "catalyst.forge"


def test_plan_steps_cover_every_consecutive_tier_pair():
    entries = forgegem.load_gem_entries()
    by_family_tier = {}
    for entry in entries:
        by_family_tier.setdefault((entry["family"], forgegem.BAND_TIER[entry["powerBand"]]), []).append(entry["id"])
    expected = sorted(
        (family, tier + 1)
        for (family, tier) in by_family_tier
        if (family, tier + 1) in by_family_tier)
    planned = [(family, tier) for family, tier, _ in forgegem.plan_steps(entries)]
    assert planned == expected


def test_planned_outputs_are_the_lowest_container_id_on_the_upper_tier():
    entries = forgegem.load_gem_entries()
    for family, tier, output in forgegem.plan_steps(entries):
        contenders = sorted(
            e["id"] for e in entries
            if e["family"] == family and forgegem.BAND_TIER[e["powerBand"]] == tier)
        assert output["id"] == contenders[0]


def _synthetic_entries():
    return [
        {"id": "gem.syn-001", "family": "atom.synthetic", "powerBand": "low", "element": "fire"},
        {"id": "gem.syn-002", "family": "atom.synthetic", "powerBand": "medium", "element": "fire"},
        {"id": "gem.syn-003", "family": "atom.synthetic", "powerBand": "medium", "element": "ice"},
        {"id": "gem.lone-001", "family": "atom.lone", "powerBand": "medium", "element": "fire"},
    ]


def test_built_rows_validate_against_the_real_cost_classes():
    # Synthetic family (not the real corpus — the real corpus is already covered, which the
    # idempotence test below proves): one step syn t2->t3, output the lowest id on t3.
    rows = forgegem.plan_rows(_synthetic_entries(), existing={}, start_seq=10_000)
    assert rows, "the real corpus plans at least one step today"
    for row in rows:
        assert row["operation"] == "forge-gem"
        assert row["outputKind"] == "gem"
        assert row["outputQty"] == 1
        # Every cost line re-validates here (issuable + cost-class legal) — the C# loader must
        # accept what this module emits, proven without a C# process.
        for line in row["costLines"]:
            material = line["material"]
            material_cls = emit_mod.material_vocab.ISSUABLE_BY_ID[material].material_class
            opvocab.check_cost_class("forge-gem", material_cls, material)


def test_planning_is_idempotent_against_the_shipped_corpus():
    entries = forgegem.load_gem_entries()
    existing = run_mod.load_entries()
    covered = {e.get("outputRef") for e in existing.values() if e.get("operation") == "forge-gem"}
    assert covered, "the shipped corpus carries forge-gem rows (T9 regen)"
    rows = forgegem.plan_rows(
        entries, existing=existing, start_seq=emit_mod.next_seq(tuple(existing)))
    assert rows == []
