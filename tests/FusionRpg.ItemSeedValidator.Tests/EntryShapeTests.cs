using FusionRpg.Tools.ItemSeedValidator;
using FusionRpg.Tools.ItemSeedValidator.Model;
using Xunit;

namespace FusionRpg.ItemSeedValidator.Tests;

/// <summary>
/// docs/architecture/item/entry-shapes.md closed the gap seed-contract.md §10 left open for ten
/// kinds. Before this, an extra key on any of them produced a shrug (UnknownKeyShapeUndefined,
/// a warning); now it must reject outright (UnknownKey, an error) the same way base-type or
/// unique already do. One test per kind proves the shape actually took.
/// </summary>
public class EntryShapeTests
{
    static ValidationResult Validate(string kind, string directory, string idNamespaceHint, string entryJson)
    {
        var json = $$"""
        {
          "schemaVersion": 1,
          "kind": "{{kind}}",
          "_meta": {
            "batch": "test", "partition": "test/{{idNamespaceHint}}", "contractVersion": 1,
            "registryVersions": { "naming": 1 },
            "exemplarVersion": 1, "promptVersion": 1,
            "model": "test", "authoredUtc": "2026-08-22T00:00:00Z", "sourceRef": "test"
          },
          "entries": [ {{entryJson}} ]
        }
        """;
        return Validator.Run(SeedFixture.Registries(),
            new[] { SeedFile.Parse(json, $"{directory}/test.json", directory) });
    }

    static IEnumerable<string> AllCodes(ValidationResult r) => r.Findings.Select(f => f.Code);

    [Fact]
    public void Gem_rejects_an_unknown_field()
    {
        var result = Validate("gem", "gems", "gems", """
            {
              "id": "gem.g1-001", "nameKey": "gem.ember-shard", "name": "Ember Shard",
              "family": "atom.vitality", "powerBand": "medium",
              "surprise": "value"
            }
            """);
        Assert.Contains("UnknownKey", AllCodes(result));
        Assert.DoesNotContain("UnknownKeyShapeUndefined", AllCodes(result));
    }

    [Fact]
    public void Material_rejects_an_unknown_field()
    {
        var result = Validate("material", "materials", "materials", """
            {
              "id": "material.001", "nameKey": "material.test", "name": "Test Material",
              "runtimeId": "essence.fire", "materialClass": "essence", "element": "fire",
              "surprise": "value"
            }
            """);
        Assert.Contains("UnknownKey", AllCodes(result));
        Assert.DoesNotContain("UnknownKeyShapeUndefined", AllCodes(result));
    }

    [Fact]
    public void Curve_rejects_an_unknown_field()
    {
        var result = Validate("curve", "curves", "curves", """
            {
              "id": "curve.001", "nameKey": "curve.test", "name": "Test Curve",
              "input": "level",
              "points": [ { "atOrdinal": 1, "multiplierPerMille": 1000 },
                          { "atOrdinal": 2, "multiplierPerMille": 2000 } ],
              "surprise": "value"
            }
            """);
        Assert.Contains("UnknownKey", AllCodes(result));
        Assert.DoesNotContain("UnknownKeyShapeUndefined", AllCodes(result));
    }

    [Fact]
    public void Curve_points_atOrdinal_is_not_a_magnitude_violation()
    {
        var result = Validate("curve", "curves", "curves", """
            {
              "id": "curve.001", "nameKey": "curve.test", "name": "Test Curve",
              "input": "level",
              "points": [ { "atOrdinal": 1, "multiplierPerMille": 1000 },
                          { "atOrdinal": 2, "multiplierPerMille": 2000 } ]
            }
            """);
        Assert.DoesNotContain("MagnitudeAuthored", AllCodes(result));
    }

    [Fact]
    public void Charm_rejects_an_unknown_field()
    {
        var result = Validate("charm", "charms", "charms", """
            {
              "id": "charm.econ-001", "nameKey": "charm.test", "name": "Test Charm",
              "charmClass": "minor", "apCost": 1, "axis": "survivability", "frameHint": "any",
              "fixedAtoms": [ { "family": "atom.vitality", "powerBand": "medium" } ],
              "surprise": "value"
            }
            """);
        Assert.Contains("UnknownKey", AllCodes(result));
        Assert.DoesNotContain("UnknownKeyShapeUndefined", AllCodes(result));
    }

    [Fact]
    public void Recipe_rejects_an_unknown_field()
    {
        var result = Validate("recipe", "recipes", "recipes", """
            {
              "id": "recipe.001", "nameKey": "recipe.test", "name": "Test Recipe",
              "operation": "forge", "outputKind": "material", "frame": "plant",
              "costLines": [ { "material": "essence.fire", "costBand": "cheap" } ],
              "surprise": "value"
            }
            """);
        Assert.Contains("UnknownKey", AllCodes(result));
        Assert.DoesNotContain("UnknownKeyShapeUndefined", AllCodes(result));
    }

    [Fact]
    public void EnhancementMilestone_rejects_an_unknown_field()
    {
        var result = Validate("enhancement-milestone", "enhancement-milestones", "enhancementMilestones", """
            {
              "id": "enh.001", "nameKey": "affix.enhance-test", "name": "Test Enhancement",
              "runtimeFamily": "atom.enhance-test", "kindId": "stat.modify",
              "params": { "channel": "maxHp", "op": "Flat" }, "powerBand": "medium",
              "surprise": "value"
            }
            """);
        Assert.Contains("UnknownKey", AllCodes(result));
        Assert.DoesNotContain("UnknownKeyShapeUndefined", AllCodes(result));
    }

    [Fact]
    public void Consumable_rejects_an_unknown_field()
    {
        var result = Validate("consumable", "consumables", "consumables", """
            {
              "id": "consumable.k1-001", "nameKey": "consumable.test", "name": "Test Consumable",
              "classId": "draught", "useContext": [ "dispatch" ],
              "family": "atom.vitality", "powerBand": "medium",
              "surprise": "value"
            }
            """);
        Assert.Contains("UnknownKey", AllCodes(result));
        Assert.DoesNotContain("UnknownKeyShapeUndefined", AllCodes(result));
    }

    [Fact]
    public void DropTable_rejects_an_unknown_field()
    {
        var result = Validate("drop-table", "drop-tables", "dropTables", """
            {
              "id": "droptable.d1-001", "nameKey": "droptable.test", "name": "Test Drop Table",
              "sourceAllow": [ "web" ],
              "groups": [ { "groupKey": "gear",
                            "entries": [ { "entryKind": "nothing", "dropBand": "staple" } ] } ],
              "surprise": "value"
            }
            """);
        Assert.Contains("UnknownKey", AllCodes(result));
        Assert.DoesNotContain("UnknownKeyShapeUndefined", AllCodes(result));
    }

    [Fact]
    public void DisplayTemplate_rejects_an_unknown_field()
    {
        var result = Validate("display-template", "display-templates", "displayTemplates", """
            {
              "id": "disptpl.p1-001", "nameKey": "tpl.test", "name": "+{value} test",
              "runtimeFamily": "atom.vitality", "groupId": "g.life", "status": "live",
              "surprise": "value"
            }
            """);
        Assert.Contains("UnknownKey", AllCodes(result));
        Assert.DoesNotContain("UnknownKeyShapeUndefined", AllCodes(result));
    }

    [Fact]
    public void Attribute_is_still_undefined_and_only_warns()
    {
        // attribute stays deferred/unauthored per the brief — its gap must not have closed.
        var result = Validate("attribute", "attributes", "attributes", """
            {
              "id": "attr.001", "nameKey": "attr.test", "name": "Test Attribute",
              "surprise": "value"
            }
            """);
        Assert.Contains("UnknownKeyShapeUndefined", AllCodes(result));
        Assert.DoesNotContain("UnknownKey", AllCodes(result));
    }

    const string AffixFamilyFile = """
    {
      "schemaVersion": 1,
      "kind": "affix-family",
      "_meta": {
        "batch": "test", "partition": "test/g.life", "contractVersion": 1,
        "registryVersions": { "naming": 1 },
        "exemplarVersion": 1, "promptVersion": 1,
        "model": "test", "authoredUtc": "2026-08-22T00:00:00Z", "sourceRef": "test"
      },
      "entries": [ {{ENTRY}} ]
    }
    """;

    static ValidationResult ValidateAffixFamily(string entryJson) =>
        Validator.Run(SeedFixture.Registries(), new[]
        {
            SeedFile.Parse(AffixFamilyFile.Replace("{{ENTRY}}", entryJson),
                "affix-families/test.json", "affix-families"),
        });

    [Fact]
    public void Roles_is_accepted_with_no_errors()
    {
        var result = ValidateAffixFamily("""
            {
              "id": "atom.life-vigor", "nameKey": "affix.vigor", "name": "Vigor",
              "kindId": "stat.modify", "roles": [ "head-guard" ], "powerBand": "medium", "tags": []
            }
            """);
        Assert.Equal(0, result.ErrorCount);
    }

    [Fact]
    public void RoleGroups_the_pre_rename_name_still_validates_but_warns()
    {
        var result = ValidateAffixFamily("""
            {
              "id": "atom.life-vigor", "nameKey": "affix.vigor", "name": "Vigor",
              "kindId": "stat.modify", "roleGroups": [ "head-guard" ], "powerBand": "medium", "tags": []
            }
            """);
        Assert.Equal(0, result.ErrorCount);
        Assert.Contains("RoleGroupsRenamed", result.Findings.Select(f => f.Code));
    }

    [Fact]
    public void Neither_roles_nor_roleGroups_is_a_required_field_error()
    {
        var result = ValidateAffixFamily("""
            {
              "id": "atom.life-vigor", "nameKey": "affix.vigor", "name": "Vigor",
              "kindId": "stat.modify", "powerBand": "medium", "tags": []
            }
            """);
        Assert.Contains("RequiredFieldMissing", SeedFixture.ErrorCodes(result));
    }
}
