using Xunit;

namespace FusionRpg.ItemSeedValidator.Tests;

/// <summary>
/// seed-contract.md §2 and §3. These are the checks the corpus cannot ship without: a derived
/// field in a seed file is two sources of truth, and a hand-typed magnitude is one agent's
/// private balance system.
/// </summary>
public class OwnershipCheckTests
{
    static IEnumerable<string> Codes(string entryExtra) =>
        SeedFixture.ErrorCodes(SeedFixture.Validate(
            SeedFixture.BaseTypeFile(SeedFixture.BaseTypeEntry(extra: entryExtra))));

    [Fact]
    public void A_conforming_entry_produces_no_errors()
    {
        var result = SeedFixture.Validate(SeedFixture.BaseTypeFile(SeedFixture.BaseTypeEntry()));
        Assert.Equal(0, result.ErrorCount);
        Assert.False(result.ScannedNothing);
    }

    [Theory]
    [InlineData("\"affixClass\": \"prefix\"")]
    [InlineData("\"atom_id\": \"atom.vitality.t3\"")]
    [InlineData("\"container_id\": \"item.plant-crown-a-001\"")]
    [InlineData("\"powerVector\": { \"offense\": \"high\" }")]
    [InlineData("\"tiers\": { \"note\": \"anything\" }")]
    public void A_derived_or_generated_field_is_an_error(string extra) =>
        Assert.Contains("OwnershipViolation", Codes(extra));

    [Fact]
    public void A_pool_weight_is_an_error_even_nested()
    {
        // pool rows and weights are GENERATED from the role x group matrix.
        Assert.Contains("OwnershipViolation", Codes("\"implicit\": { \"weight\": \"heavy\" }"));
    }

    [Fact]
    public void A_numeric_literal_outside_the_count_allowlist_is_an_error()
    {
        var codes = Codes("\"implicit\": { \"family\": \"atom.vitality\", \"t1\": 10 }").ToList();
        Assert.Contains("MagnitudeAuthored", codes);
    }

    [Fact]
    public void A_magnitude_written_as_a_string_is_still_a_magnitude()
    {
        // The rule is about the value, not the JSON type — "150" would land in the same column.
        Assert.Contains("MagnitudeAuthored",
            Codes("\"implicit\": { \"family\": \"atom.vitality\", \"spreadMilli\": \"150\" }"));
    }

    [Fact]
    public void A_structural_count_may_carry_a_number()
    {
        var codes = Codes("\"socketMax\": 2").ToList();
        Assert.DoesNotContain("MagnitudeAuthored", codes);
        Assert.DoesNotContain("StructuralCountInvalid", codes);
    }

    [Fact]
    public void A_structural_count_must_be_a_non_negative_integer()
    {
        Assert.Contains("StructuralCountInvalid", Codes("\"socketMax\": -1"));
        Assert.Contains("StructuralCountInvalid", Codes("\"socketMax\": 1.5"));
    }

    [Fact]
    public void A_band_value_must_exist_in_bands_registry()
    {
        Assert.Contains("BandUnknown",
            Codes("\"implicit\": { \"family\": \"atom.vitality\", \"powerBand\": \"gigantic\" }"));
        Assert.DoesNotContain("BandUnknown",
            Codes("\"implicit\": { \"family\": \"atom.vitality\", \"powerBand\": \"medium\" }"));
    }

    [Fact]
    public void An_unknown_key_rejects_on_a_kind_the_contract_specifies()
    {
        Assert.Contains("UnknownKey", Codes("\"surprise\": \"value\""));
    }

    [Fact]
    public void A_container_id_body_may_not_contain_a_dot()
    {
        var result = SeedFixture.Validate(SeedFixture.BaseTypeFile(
            SeedFixture.BaseTypeEntry(id: "item.plant.crown.a.001")));
        Assert.Contains("ContainerIdDotInBody", SeedFixture.ErrorCodes(result));
    }

    [Fact]
    public void An_id_outside_its_allocated_namespace_is_an_error()
    {
        var result = SeedFixture.Validate(SeedFixture.BaseTypeFile(
            SeedFixture.BaseTypeEntry(id: "item.plant-elbow-a-001")));
        Assert.Contains("IdOutsideNamespace", SeedFixture.ErrorCodes(result));
    }

    [Fact]
    public void A_sequence_in_the_reserved_range_is_an_error()
    {
        var result = SeedFixture.Validate(SeedFixture.BaseTypeFile(
            SeedFixture.BaseTypeEntry(id: "item.plant-crown-a-901")));
        Assert.Contains("SequenceReserved", SeedFixture.ErrorCodes(result));
    }

    [Fact]
    public void Duplicate_ids_and_name_keys_are_errors()
    {
        var result = SeedFixture.Validate(SeedFixture.BaseTypeFile(
            SeedFixture.BaseTypeEntry(),
            SeedFixture.BaseTypeEntry(name: "Emberleaf Crown")));
        var codes = SeedFixture.ErrorCodes(result).ToList();
        Assert.Contains("IdDuplicate", codes);
        Assert.Contains("NameKeyDuplicate", codes);
    }

    [Fact]
    public void Two_spellings_of_one_name_collide()
    {
        var result = SeedFixture.Validate(SeedFixture.BaseTypeFile(
            SeedFixture.BaseTypeEntry(id: "item.plant-crown-a-001", name: "Heartbloom Crown",
                nameKey: "base.heartbloom-crown"),
            SeedFixture.BaseTypeEntry(id: "item.plant-crown-a-002", name: "Crown of Heartbloom",
                nameKey: "base.crown-of-heartbloom")));
        Assert.Contains("NameCollision", SeedFixture.ErrorCodes(result));
    }

    [Fact]
    public void An_unknown_registry_value_is_an_error_never_a_warning()
    {
        var json = SeedFixture.BaseTypeFile(SeedFixture.BaseTypeEntry()
            .Replace("\"class\": \"heartwood\"", "\"class\": \"kryptonite\""));
        var result = SeedFixture.Validate(json);
        Assert.Contains("RegistryValueUnknown", SeedFixture.ErrorCodes(result));
    }

    [Fact]
    public void Two_tags_on_one_exclusive_axis_is_an_error()
    {
        var json = SeedFixture.BaseTypeFile(SeedFixture.BaseTypeEntry()
            .Replace("\"tags\": [\"organic\"]", "\"tags\": [\"organic\", \"metal\"]"));
        Assert.Contains("TagAxisExclusive", SeedFixture.ErrorCodes(SeedFixture.Validate(json)));
    }

    [Fact]
    public void An_unresolvable_reference_is_an_error()
    {
        Assert.Contains("ReferenceUnresolved",
            Codes("\"implicit\": { \"family\": \"atom.nonexistent\" }"));
    }

    [Fact]
    public void Incomplete_meta_provenance_is_an_error()
    {
        var json = SeedFixture.BaseTypeFile(SeedFixture.BaseTypeEntry())
            .Replace("\"promptVersion\": 1,", "");
        Assert.Contains("MetaIncomplete", SeedFixture.ErrorCodes(SeedFixture.Validate(json)));
    }

    [Fact]
    public void Kind_must_match_its_directory()
    {
        var result = SeedFixture.Validate(
            SeedFixture.BaseTypeFile(SeedFixture.BaseTypeEntry()),
            kindDirectory: "uniques", path: "uniques/test.json");
        Assert.Contains("KindDirectoryMismatch", SeedFixture.ErrorCodes(result));
    }

    [Fact]
    public void Scanning_zero_files_is_never_success()
    {
        var result = Tools.ItemSeedValidator.Validator.Run(
            SeedFixture.Registries(), Array.Empty<Tools.ItemSeedValidator.Model.SeedFile>());
        Assert.True(result.ScannedNothing);
        Assert.Contains("NO SEED FILES WERE SCANNED",
            Tools.ItemSeedValidator.Report.Render(result, "(nowhere)"));
    }
}
