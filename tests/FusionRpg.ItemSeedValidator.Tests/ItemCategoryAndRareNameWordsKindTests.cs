using System.Linq;
using FusionRpg.Tools.ItemSeedValidator;
using FusionRpg.Tools.ItemSeedValidator.Model;
using FusionRpg.Tools.ItemSeedValidator.Registries;
using Xunit;

namespace FusionRpg.ItemSeedValidator.Tests;

/// <summary>
/// item-seed-regen coordinator item 3 (2026-09-20): `item-category` and `rare-name-words` shipped
/// content years before either was onboarded into <see cref="KindCatalog"/>, so every file under
/// them read as <c>KindUnknown</c> and (`rare-name-words` only) <c>IdGrammar</c>/<c>IdOutsideNamespace</c>
/// on top. Neither kind uses the common id/nameKey/name identity triad, which is why
/// <see cref="KindCatalog.All"/> needed a new <c>DefinedTable</c> factory rather than reusing
/// <c>Defined</c>/<c>Undefined</c> (both of which always require it).
/// </summary>
public class ItemCategoryAndRareNameWordsKindTests
{
    [Fact]
    public void Item_category_requires_its_own_fields_never_the_common_identity_triad()
    {
        var kind = KindCatalog.All["item-category"];
        Assert.True(kind.ShapeDefined);
        Assert.Equal("_seed", kind.Directory);
        Assert.Contains("categoryId", kind.RequiredFields);
        Assert.Contains("consumer", kind.RequiredFields);
        // Unlike every Defined()/Undefined() kind, id/nameKey/name are NOT required here -- the
        // real shipped rows (`_seed/item-category.v1.json`) carry none of the three.
        Assert.DoesNotContain("id", kind.RequiredFields);
        Assert.DoesNotContain("nameKey", kind.RequiredFields);
        Assert.DoesNotContain("name", kind.RequiredFields);
    }

    [Fact]
    public void A_conforming_item_category_file_produces_no_errors()
    {
        var result = Validator.Run(SeedFixture.Registries(), new[]
        {
            SeedFile.Parse(SeedFixture.ItemCategoryFile(SeedFixture.ItemCategoryEntry()),
                "_seed/item-category.v1.json", "_seed"),
        });
        Assert.Equal(0, result.ErrorCount);
    }

    [Fact]
    public void Rare_name_words_requires_id_but_never_nameKey_or_name()
    {
        var kind = KindCatalog.All["rare-name-words"];
        Assert.True(kind.ShapeDefined);
        Assert.Equal("rare-names", kind.Directory);
        Assert.Equal("rareNameWords", kind.NamespaceKey);
        Assert.Contains("id", kind.RequiredFields);
        Assert.Contains("slot", kind.RequiredFields);
        Assert.Contains("words", kind.RequiredFields);
        Assert.DoesNotContain("nameKey", kind.RequiredFields);
        Assert.DoesNotContain("name", kind.RequiredFields);
    }

    [Fact]
    public void A_conforming_rare_name_words_file_with_both_slots_produces_no_errors()
    {
        // Both slots in ONE file is the real shipped shape (rare-names.json carries head AND
        // tail together) -- this is the regression case for PartitionMixed: an earlier version of
        // ExpandRareNameWords allocated a SEPARATE partition id per slot, which made this exact
        // file (one authored unit, two slots) look like it spanned two agents' partitions.
        var result = Validator.Run(SeedFixture.Registries(), new[]
        {
            SeedFile.Parse(SeedFixture.RareNameWordsFile(
                SeedFixture.RareNameWordsEntry("head"), SeedFixture.RareNameWordsEntry("tail")),
                "rare-names/rare-names.json", "rare-names"),
        });
        Assert.Equal(0, result.ErrorCount);
    }

    [Fact]
    public void Rarename_ids_resolve_their_own_namespace_not_outside_it()
    {
        var result = Validator.Run(SeedFixture.Registries(), new[]
        {
            SeedFile.Parse(SeedFixture.RareNameWordsFile(
                SeedFixture.RareNameWordsEntry("head"), SeedFixture.RareNameWordsEntry("tail")),
                "rare-names/rare-names.json", "rare-names"),
        });
        var codes = SeedFixture.ErrorCodes(result).ToList();
        Assert.DoesNotContain("IdGrammar", codes);
        Assert.DoesNotContain("IdOutsideNamespace", codes);
        Assert.DoesNotContain("PartitionMixed", codes);
    }

    [Fact]
    public void An_id_outside_the_rarename_namespace_still_refuses()
    {
        // The allocation is real, not a blanket pass for the whole kind.
        var result = Validator.Run(SeedFixture.Registries(), new[]
        {
            SeedFile.Parse(SeedFixture.RareNameWordsFile(
                SeedFixture.RareNameWordsEntry("head").Replace("rarename.head", "rareword.head")),
                "rare-names/rare-names.json", "rare-names"),
        });
        Assert.Contains("IdOutsideNamespace", SeedFixture.ErrorCodes(result));
    }

    const string AffixFamilyFile = """
    {
      "schemaVersion": 1,
      "kind": "affix-family",
      "_meta": {
        "batch": "test", "partition": "test/g.punisher", "contractVersion": 1,
        "registryVersions": { "naming": 1 },
        "exemplarVersion": 1, "promptVersion": 1,
        "model": "test", "authoredUtc": "2026-08-22T00:00:00Z", "sourceRef": "test"
      },
      "entries": [ {{ENTRY}} ]
    }
    """;

    static string AffixFamilyEntry(string id, string nameKey) => $$"""
        {
          "id": "{{id}}", "nameKey": "{{nameKey}}", "name": "Test",
          "kindId": "stat.modify", "roles": [ "head-guard" ], "powerBand": "medium", "tags": []
        }
        """;

    static ValidationResult ValidateAffixFamily(string entryJson) =>
        Validator.Run(SeedFixture.Registries(), new[]
        {
            SeedFile.Parse(AffixFamilyFile.Replace("{{ENTRY}}", entryJson),
                "affix-families/g-punisher.json", "affix-families"),
        });

    [Fact]
    public void A_family_id_already_a_key_in_the_real_enabler_payoff_pairings_table_is_exempt()
    {
        // item-seed-regen coordinator item 3 (2026-09-20): `atom.chill-punisher` is a real, KEY in
        // the COMMITTED `gk-data/packs/fusion/data/seed/actions/pairings.json` (EnablerPayoffPairings.IsPayoff matches
        // it by this exact literal string) -- confirmed live via RegistrySet.EnablerPayoffPairingFamilyIds,
        // not hardcoded here. Renaming it to fit atom.{stem}-{word} would silently orphan that
        // lookup, so IdentityCheck must accept it outside the ordinary namespace rule.
        var registries = SeedFixture.Registries();
        Assert.True(registries.EnablerPayoffPairingsRegistryFound);
        Assert.Contains("atom.chill-punisher", registries.EnablerPayoffPairingFamilyIds);

        var result = ValidateAffixFamily(AffixFamilyEntry("atom.chill-punisher", "affix.chill-punisher"));
        Assert.DoesNotContain("IdOutsideNamespace", SeedFixture.ErrorCodes(result));
    }

    [Fact]
    public void A_hyphenated_family_id_not_in_the_pairings_table_still_refuses()
    {
        // The exemption is scoped to real pairings-table keys, never a blanket "any hyphenated
        // atom.* id is fine now" widening -- a genuinely wrong new mint must still be caught.
        var registries = SeedFixture.Registries();
        Assert.DoesNotContain("atom.mystery-madeup", registries.EnablerPayoffPairingFamilyIds);

        var result = ValidateAffixFamily(AffixFamilyEntry("atom.mystery-madeup", "affix.mystery-madeup"));
        Assert.Contains("IdOutsideNamespace", SeedFixture.ErrorCodes(result));
    }
}
