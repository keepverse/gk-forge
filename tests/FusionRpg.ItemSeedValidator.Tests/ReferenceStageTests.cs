using FusionRpg.Tools.ItemSeedValidator;
using FusionRpg.Tools.ItemSeedValidator.Model;
using Xunit;

namespace FusionRpg.ItemSeedValidator.Tests;

/// <summary>
/// seed-contract.md §7.1 and the fleet plan's staged wave 1: 1a defines, 1b references, and
/// nothing inside a stage references anything else inside it. That restriction is what makes
/// "independent" true rather than aspirational, so it is worth a test.
/// </summary>
public class ReferenceStageTests
{
    const string UniqueFile = """
    {
      "schemaVersion": 1,
      "kind": "unique",
      "_meta": {
        "batch": "test", "partition": "uniques/ember-harvest/70", "contractVersion": 1,
        "registryVersions": { "tags": 1, "naming": 1 },
        "exemplarVersion": 1, "promptVersion": 1,
        "model": "test", "authoredUtc": "2026-08-22T00:00:00Z", "sourceRef": "test"
      },
      "entries": [
        {
          "id": "unique.ember-harvest-70-001",
          "nameKey": "unique.thornmantle",
          "name": "Thornmantle",
          "frame": "plant",
          "baseType": "item.plant-crown-a-001",
          "rarity": "heirloom",
          "fixedAtoms": [{ "family": "atom.vitality", "powerBand": "high" }],
          "counterPressure": { "kind": "conditional", "note": "only below half health" },
          "tags": []
        }
      ]
    }
    """;

    static ValidationResult Validate(params (string Json, string Dir, string Path)[] files) =>
        Validator.Run(SeedFixture.Registries(),
            files.Select(f => SeedFile.Parse(f.Json, f.Path, f.Dir)).ToList());

    [Fact]
    public void Stage_1b_may_reference_frozen_stage_1a_output()
    {
        var result = Validate(
            (SeedFixture.BaseTypeFile(SeedFixture.BaseTypeEntry()), "base-types", "base-types/a.json"),
            (UniqueFile, "uniques", "uniques/ember.json"));

        Assert.DoesNotContain("SameStageReference", SeedFixture.ErrorCodes(result));
        Assert.DoesNotContain("ForwardReference", SeedFixture.ErrorCodes(result));
        Assert.DoesNotContain("ReferenceUnresolved", SeedFixture.ErrorCodes(result));
    }

    [Fact]
    public void A_stage_1a_file_referencing_another_stage_1a_file_is_an_error()
    {
        var json = SeedFixture.BaseTypeFile(
            SeedFixture.BaseTypeEntry(id: "item.plant-crown-a-001", name: "Heartbloom Crown",
                nameKey: "base.heartbloom-crown"),
            SeedFixture.BaseTypeEntry(id: "item.plant-crown-a-002", name: "Emberleaf Sheath",
                nameKey: "base.emberleaf-sheath",
                extra: "\"implicit\": { \"family\": \"item.plant-crown-a-001\" }"));

        Assert.Contains("SameStageReference", SeedFixture.ErrorCodes(Validate((json, "base-types", "base-types/a.json"))));
    }

    [Fact]
    public void A_successor_edge_between_two_stage_1b_base_types_is_legal()
    {
        var json = SeedFixture.BaseTypeFile(
            SeedFixture.BaseTypeEntry(id: "item.plant-crown-a-001", name: "Heartbloom Crown",
                nameKey: "base.heartbloom-crown",
                extra: "\"successorOf\": \"item.plant-crown-a-002\""),
            SeedFixture.BaseTypeEntry(id: "item.plant-crown-a-002", name: "Emberleaf Sheath",
                nameKey: "base.emberleaf-sheath"));

        var codes = SeedFixture.ErrorCodes(Validate((json, "base-types", "base-types/a.json")));

        // species-gear-chain T37/T38: `successorOf` is the ONE documented same-stage reference — a
        // base type's successor is a peer base type by the owner's 2026-09-21 ruling, authored as a
        // reviewed table after the corpus exists, with its own closure gate in the generator
        // (`basetypegen/successor_edges.py::violations_in_corpus`).
        Assert.DoesNotContain("SameStageReference", codes);
        Assert.DoesNotContain("ReferenceUnresolved", codes);
    }

    [Fact]
    public void A_successor_edge_to_a_typo_is_still_unresolved()
    {
        // Resolution is NOT relaxed: only the stage rule is exempt, so a bad target still reports.
        var json = SeedFixture.BaseTypeFile(
            SeedFixture.BaseTypeEntry(id: "item.plant-crown-a-001", name: "Heartbloom Crown",
                nameKey: "base.heartbloom-crown",
                extra: "\"successorOf\": \"item.plant-crown-a-999\""));

        Assert.Contains("ReferenceUnresolved",
            SeedFixture.ErrorCodes(Validate((json, "base-types", "base-types/a.json"))));
    }

    [Fact]
    public void An_entry_referencing_itself_is_cyclic()
    {
        var json = SeedFixture.BaseTypeFile(SeedFixture.BaseTypeEntry(
            extra: "\"implicit\": { \"family\": \"item.plant-crown-a-001\" }"));

        Assert.Contains("CyclicReference", SeedFixture.ErrorCodes(Validate((json, "base-types", "base-types/a.json"))));
    }
}
