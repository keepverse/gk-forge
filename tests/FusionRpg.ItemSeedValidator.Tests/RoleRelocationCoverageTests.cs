using FusionRpg.Tools.ItemSeedValidator;
using FusionRpg.Tools.ItemSeedValidator.Model;
using Xunit;

namespace FusionRpg.ItemSeedValidator.Tests;

/// <summary>
/// `RoleFamilyCheck`'s reverse direction (item module 8, `affix-legality`). Every other assertion in
/// that check walks `role-relocation.v1.json` and asks whether the corpus still has what the file
/// names. Nothing asked the opposite — whether the corpus has gained a family the file does not
/// cover — so when the affix-authoring lane shipped two `sense`-legal families on 2026-09-06 they
/// silently kept `max_tier = 5` on every surviving hybrid-core host, against D3's own reduce-to-3
/// rule. These two tests are the control pair for the check that now refuses it.
/// </summary>
public class RoleRelocationCoverageTests
{
    const string DroppedRolesMeta = """
      "_meta": {
        "purpose": "test",
        "droppedRoles": [ "head-guard", "sense", "ward-array" ]
      }
    """;

    /// <summary>One family legal on the dropped `sense` role and on one surviving hybrid-core host.</summary>
    const string SenseLegalFamilyFile = """
    {
      "schemaVersion": 1,
      "kind": "affix-family",
      "_meta": {
        "batch": "test", "partition": "test/g.life", "contractVersion": 1,
        "registryVersions": { "naming": 1 },
        "exemplarVersion": 1, "promptVersion": 1,
        "model": "test", "authoredUtc": "2026-08-22T00:00:00Z", "sourceRef": "test"
      },
      "entries": [
        {
          "id": "atom.life-vigor", "nameKey": "affix.vigor", "name": "Vigor",
          "kindId": "stat.modify", "roles": [ "sense", "armament-primary" ],
          "powerBand": "medium", "tags": []
        }
      ]
    }
    """;

    static ValidationResult Run(string roleRelocationJson) =>
        Validator.Run(SeedFixture.RegistriesWithRelocation(roleRelocationJson), new[]
        {
            SeedFile.Parse(SenseLegalFamilyFile, "affix-families/test.json", "affix-families"),
        });

    [Fact]
    public void A_corpus_family_on_a_dropped_role_with_no_relocation_row_is_an_error()
    {
        var result = Run($$"""
        {
          "schemaVersion": 1,
        {{DroppedRolesMeta}},
          "relocations": []
        }
        """);

        Assert.Contains("RoleRelocationRowMissing", SeedFixture.ErrorCodes(result));
    }

    [Fact]
    public void A_covered_family_raises_nothing()
    {
        var result = Run($$"""
        {
          "schemaVersion": 1,
        {{DroppedRolesMeta}},
          "relocations": [
            {
              "droppedRole": "sense",
              "familyId": "atom.life-vigor",
              "hostRole": "armament-primary",
              "maxTier": 3
            }
          ]
        }
        """);

        Assert.DoesNotContain("RoleRelocationRowMissing", SeedFixture.ErrorCodes(result));
    }
}
