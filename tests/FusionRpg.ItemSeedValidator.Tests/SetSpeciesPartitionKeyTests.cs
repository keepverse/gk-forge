using FusionRpg.Tools.ItemSeedValidator.Registries;
using Xunit;

namespace FusionRpg.ItemSeedValidator.Tests;

/// <summary>
/// The species-scoped <c>set</c> partition key (partition-key audit, 2026-09-26).
///
/// <para><b>What broke.</b> <c>NamespaceAllocation.ExpandSpeciesThemes</c> allocated
/// <c>sets/species/{rawSpeciesId}</c> while <c>setgen</c> files every set under the partition its own
/// id implies (<c>sets/{idTemplateSlot}</c>). Those are different strings, so the exact-string
/// occupancy set-difference in <c>Coverage/EmptyPartition</c> read all 904 species slots as empty —
/// 844 of which already held a same-species set — and <c>CheckPartitionCohesion</c> emitted 65
/// <c>PartitionMetaMismatch</c> warnings, one per underscored variant species.</para>
///
/// <para><b>Which spelling is the partition.</b> The id TEMPLATE's slot value, not the species id.
/// <c>naming.v1.json</c>'s <c>idNamespaces.sets</c> declares one partition key — <c>"partitionKey":
/// "themeId"</c>, a single component — against one <c>"idTemplate": "set.{themeId}-{seq:03}"</c>.
/// A partition is derived from an id, so it names the id's token.</para>
///
/// <para><b>What these assert.</b> The contract, never a population: each case names a REAL member of
/// the shipped species roster (<c>RegistrySet.CreatureSpeciesIds</c> reads
/// <c>gk-data/packs/fusion/data/seed/creatures/_registry/themes.v2.json</c> by walking up from the test process, the
/// convention <c>SetSpeciesBindingCheckTests</c> already establishes) and asserts its partition's
/// SHAPE. None of them counts species, so none fails when a species ships — the rule this repo
/// states for a derived population vs a closed vocabulary.</para>
/// </summary>
public class SetSpeciesPartitionKeyTests
{
    static NamespaceAllocation Allocation() => NamespaceAllocation.Build(SeedFixture.Registries());

    /// <summary>
    /// Path segments BELOW the kind directory — i.e. the partition KEY's own arity, which is what
    /// <c>naming.v1.json</c>'s <c>partitionKey</c> declares. <c>"sets/might-offense"</c> is 1
    /// (<c>themeId</c>); <c>"sets/species/might-offense"</c> would be 2 (a scope the registry never
    /// declared); <c>"base-types/footing/humanoid/a"</c> is 3 (<c>(roleId, frame, band)</c>).
    /// </summary>
    static int Depth(string partitionId) => partitionId.Count(c => c == '/');

    [Fact]
    public void The_species_roster_the_allocation_reads_is_the_real_one()
    {
        // Without this the three cases below could pass vacuously on an empty roster.
        var registries = SeedFixture.Registries();
        Assert.True(registries.CreatureSpeciesRegistryFound,
            "the real creature theme registry was not found above the test working directory");
        Assert.NotEmpty(registries.CreatureSpeciesIds);
    }

    [Fact]
    public void A_species_set_partition_is_named_by_the_id_template_slot()
    {
        // `abyssswordstar` is a real shipped species, not an invented one.
        var species = Allocation().All.SingleOrDefault(a => a.Prefix == "set.abyssswordstar-");
        Assert.NotNull(species);
        Assert.Equal("sets/abyssswordstar", species!.PartitionId);
        Assert.Equal(1, Depth(species.PartitionId));
    }

    [Fact]
    public void No_species_partition_nests_under_a_scope_segment()
    {
        // The specific regression: a second path segment (`species/`) that `naming.v1.json` never
        // declares. Asserted over the WHOLE roster, because the defect was uniform across it.
        var nested = Allocation().All
            .Where(a => a.Kind == "set" && a.PartitionId.StartsWith("sets/species/", StringComparison.Ordinal))
            .Select(a => a.PartitionId)
            .ToList();
        Assert.Empty(nested);
    }

    [Fact]
    public void An_underscored_variant_species_partitions_on_the_kebab_id_slot()
    {
        // `elephantzombie_a` is a real variant species: its own speciesId carries an UNDERSCORE,
        // because the authored container id is kebab-case only. The partition names the id's token.
        var species = Allocation().All.SingleOrDefault(a => a.Prefix == "set.elephantzombie-a-");
        Assert.NotNull(species);
        Assert.Equal("sets/elephantzombie-a", species!.PartitionId);

        // ...and the underscored IDENTITY is not lost: both spellings stay in the token set, which is
        // what `CheckPartitionCohesion` compares a free-form label against.
        Assert.Contains("elephantzombie_a", species.Tokens);
        Assert.Contains("elephantzombie-a", species.Tokens);
    }

    [Fact]
    public void A_species_set_labelled_the_way_setgen_labels_it_raises_no_PartitionMetaMismatch()
    {
        // The lint that was firing 65 times. `setgen` writes `_meta.partition` as the id's body minus
        // the sequence, so the shipped corpus label is `sets/elephantzombie-a`.
        var json = $$"""
            {
              "schemaVersion": 1, "kind": "set",
              "_meta": { "promptVersion": 1, "model": "test", "batch": "b",
                         "partition": "sets/elephantzombie-a" },
              "entries": [
                {
                  "id": "set.elephantzombie-a-001", "nameKey": "set.elephantzombie-a",
                  "name": "Test Set", "themeKey": "creature.elephantzombie_a",
                  "speciesId": "elephantzombie_a",
                  "members": [ { "role": "head-guard", "frame": "humanoid",
                                 "baseType": "item.humanoid-head-guard-a-001" } ],
                  "thresholds": [ { "pieces": 1, "atoms": [] } ]
                }
              ]
            }
            """;

        var result = Tools.ItemSeedValidator.Validator.Run(SeedFixture.Registries(),
            new[] { Tools.ItemSeedValidator.Model.SeedFile.Parse(json, "sets/elephantzombie-a.json", "sets") });

        Assert.DoesNotContain("PartitionMetaMismatch", SeedFixture.WarningCodes(result));
        // And the id still resolves inside its namespace — the original 2026-09-20 allocation stays.
        Assert.DoesNotContain("IdOutsideNamespace", SeedFixture.ErrorCodes(result));
    }
}
