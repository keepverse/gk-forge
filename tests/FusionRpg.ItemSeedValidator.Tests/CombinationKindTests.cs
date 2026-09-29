using FusionRpg.Tools.ItemSeedValidator.Registries;
using Xunit;

namespace FusionRpg.ItemSeedValidator.Tests;

/// <summary>
/// item-seedgen `combination-write-unblock` (2026-09-07) — the real, previously-undiscovered gaps
/// found by running the real validator against a real generated `combination` entry for the first
/// time (its own Python-side `deps.validate_entries` only ever checked cross-corpus references, never
/// the full seed-contract). Three fixes, three regressions pinned here: the `combination` `SeedKind`
/// itself (`KindCatalog.cs`), the `SequenceShape.Derived` id-prefix allocation (`NamespaceAllocation.cs`),
/// and the kind-scoped ownership exception for `combogen`'s own code-derived
/// `minTier`/`quantity`/`grantedTier` fields (`OwnershipCheck.cs`).
/// </summary>
public class CombinationKindTests
{
    static IEnumerable<string> Codes(string json) =>
        SeedFixture.ErrorCodes(SeedFixture.Validate(json, kindDirectory: "combinations",
            path: "combinations/strains.json"));

    [Fact]
    public void A_conforming_combination_entry_produces_no_errors()
    {
        var result = SeedFixture.Validate(
            SeedFixture.CombinationFile(SeedFixture.CombinationEntry()),
            kindDirectory: "combinations", path: "combinations/strains.json");
        Assert.Equal(0, result.ErrorCount);
        Assert.False(result.ScannedNothing);
    }

    [Fact]
    public void A_combo_id_resolves_against_the_new_namespace_not_outside_it()
    {
        // The real bug: ExpandSlotOrFlat hard-assumed every idNamespaces group has a {seq:03}
        // template. `combinations` genuinely has none (combogen mints ids from a deterministic grid
        // cell), so it needs its own expansion case rather than falling through to a Problem.
        var codes = Codes(SeedFixture.CombinationFile(SeedFixture.CombinationEntry())).ToList();
        Assert.DoesNotContain("IdOutsideNamespace", codes);
    }

    [Fact]
    public void A_splice_id_resolves_too_not_only_strain()
    {
        var codes = Codes(SeedFixture.CombinationFile(
            SeedFixture.CombinationEntry(id: "combo.splice-verify-001",
                nameKey: "combination.splice-verify-001"))).ToList();
        Assert.DoesNotContain("IdOutsideNamespace", codes);
    }

    [Fact]
    public void An_id_with_neither_allocated_combo_prefix_still_refuses()
    {
        // The allowlist is real, not a blanket pass for the whole kind -- an id that names neither
        // combogen shape must still be caught.
        var codes = Codes(SeedFixture.CombinationFile(
            SeedFixture.CombinationEntry(id: "combo.mystery-verify-001"))).ToList();
        Assert.Contains("IdOutsideNamespace", codes);
    }

    [Fact]
    public void The_nameKey_prefix_is_registered_not_refused()
    {
        var codes = Codes(SeedFixture.CombinationFile(SeedFixture.CombinationEntry())).ToList();
        Assert.DoesNotContain("NameKeyPrefix", codes);
    }

    [Fact]
    public void Quantity_is_never_MagnitudeAuthored_or_OwnershipViolation_on_a_combination()
    {
        // `quantity` is combogen's own structural field (emit.ingredient_rows), never model-authored --
        // the same P1 split ("model picks identity, code picks magnitude") the whole seed-contract
        // enforces, not a violation of it.
        var codes = Codes(SeedFixture.CombinationFile(SeedFixture.CombinationEntry())).ToList();
        Assert.DoesNotContain("MagnitudeAuthored", codes);
        Assert.DoesNotContain("OwnershipViolation", codes);
    }

    [Fact]
    public void A_combination_row_carrying_a_tier_number_is_refused_by_name()
    {
        // SSH7.6 (spec-tier-ladder §3): the re-emitted corpus carries no tier and the kind's allowed
        // fields were narrowed with it, so a row that reintroduces `grantedTier` -- or an ingredient's
        // `minTier` -- is a real finding rather than a tolerated legacy shape. The tier is TUNING's
        // now: baseTier[shape] + ladder[rung].grantDelta + attunement.
        var grantedTier = Codes(SeedFixture.CombinationFile(SeedFixture.CombinationEntry(
            extra: "\"grantedTier\": 1"))).ToList();
        Assert.Contains("UnknownKey", grantedTier);

        // The ingredient rows are proven tier-free by the fixture's own template (which no longer
        // emits `minTier`) and by `A_conforming_combination_entry_produces_no_errors` above: a row
        // passes only when every ingredient is exactly `{family, quantity}`.
    }

    [Fact]
    public void The_quantity_exception_is_scoped_to_combination_ingredients_only()
    {
        // Regression for the narrowness of the fix: a `quantity` field OUTSIDE combinations/ingredients
        // (a recipe's cost line, say) must still be refused -- this is a recipe-shaped balance lever,
        // not combogen's structural ingredient count, and the exception must not leak past its own kind
        // and path.
        var codes = SeedFixture.ErrorCodes(SeedFixture.Validate(
            SeedFixture.BaseTypeFile(SeedFixture.BaseTypeEntry(
                extra: "\"costLines\": [{ \"material\": \"substrate.humanoid.crude\", \"quantity\": 3 }]"))))
            .ToList();
        Assert.Contains("OwnershipViolation", codes);
    }

    [Fact]
    public void The_minTier_exception_is_scoped_to_the_combination_kind_only()
    {
        // Same narrowness check: a base-type entry carrying `minTier` (not a real base-type field, but
        // the point is the SHAPE) must not silently pass just because an exception exists elsewhere in
        // the codebase.
        var codes = SeedFixture.ErrorCodes(SeedFixture.Validate(
            SeedFixture.BaseTypeFile(SeedFixture.BaseTypeEntry(extra: "\"minTier\": 2"))))
            .ToList();
        Assert.Contains("MagnitudeAuthored", codes);
    }

    [Fact]
    public void No_combination_contract_carries_a_base_or_slot_key()
    {
        // strain-splice-host SSH1.4, host-gate ruling 2 (§4 row 2): a combination pins ROLE/FRAME/
        // SIZE (hostRole/hostFrame/minSockets) and never a specific base type or a slot -- pinning
        // either would let one combination target one chassis instead of a whole role/frame class,
        // which is the "a rune belongs to a specific rune*word*, not a specific sword" property the
        // whole feature exists to have.
        var kind = Assert.Contains("combination", (IReadOnlyDictionary<string, SeedKind>)KindCatalog.All);
        foreach (var field in kind.AllowedFields)
        {
            Assert.DoesNotContain("basetype", field.ToLowerInvariant());
            Assert.DoesNotContain("slot", field.ToLowerInvariant());
        }
    }
}
