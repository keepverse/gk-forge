using Xunit;

namespace FusionRpg.ItemSeedValidator.Tests;

/// <summary>
/// species-gear-chain T28 (set-species-binding b, spec-set-species-binding.md Success criterion
/// 4/7): `SetRuleCheck`'s `speciesId` closure guard. Reads the REAL creature theme registry (the
/// same file `species_repair.py` joins against), found by walking up from the test process's own
/// working directory — the same convention `DisplayCheck.FindUpwards` already establishes for an
/// optional sibling registry. Real ids below (`abyssswordstar`) are drawn from the shipped 904-row
/// registry, not invented — this repo's own hard rule against pinning a population count, applied
/// here as "assert against a real member of the population, never its size".
/// </summary>
public class SetSpeciesBindingCheckTests
{
    static string SetJson(string themeKey, string? speciesId) => $$"""
        {
          "schemaVersion": 1, "kind": "set",
          "_meta": { "promptVersion": 1, "model": "test", "batch": "b", "partition": "p" },
          "entries": [
            {
              "id": "set.test-001", "nameKey": "set.test", "name": "Test Set",
              "themeKey": "{{themeKey}}",
              {{(speciesId is null ? "" : $"\"speciesId\": \"{speciesId}\",")}}
              "members": [
                { "role": "head-guard", "frame": "humanoid", "baseType": "item.humanoid-head-guard-a-001" }
              ],
              "thresholds": [ { "pieces": 1, "atoms": [] } ]
            }
          ]
        }
        """;

    static Tools.ItemSeedValidator.ValidationResult ValidateSet(string json) =>
        Tools.ItemSeedValidator.Validator.Run(SeedFixture.Registries(),
            new[] { Tools.ItemSeedValidator.Model.SeedFile.Parse(json, "sets/test.json", "sets") });

    [Fact]
    public void A_real_speciesId_resolves_without_error()
    {
        var result = ValidateSet(SetJson("creature.abyssswordstar", "abyssswordstar"));
        var codes = SeedFixture.ErrorCodes(result).ToList();
        Assert.DoesNotContain("SetSpeciesUnresolved", codes);
    }

    [Fact]
    public void An_invented_speciesId_is_an_error()
    {
        var result = ValidateSet(SetJson("creature.abyssswordstar", "not-a-real-species-xyz"));
        Assert.Contains("SetSpeciesUnresolved", SeedFixture.ErrorCodes(result));
    }

    [Fact]
    public void An_absent_speciesId_is_never_an_error()
    {
        var result = ValidateSet(SetJson("build.might-berserker", null));
        Assert.DoesNotContain("SetSpeciesUnresolved", SeedFixture.ErrorCodes(result));
    }
}
