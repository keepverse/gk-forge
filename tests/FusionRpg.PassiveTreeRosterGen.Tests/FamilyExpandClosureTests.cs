using FusionRpg.Core.Effects.Atoms;
using FusionRpg.Core.Effects.Atoms.Generation;
using FusionRpg.Tools.FamilyExpandGen;
using Xunit;

namespace FusionRpg.PassiveTreeRosterGen.Tests;

public class FamilyExpandClosureTests
{
    [Fact]
    public void Versioned_status_anchor_selection_uses_numeric_order_not_filename_order()
    {
        var dir = Path.Combine(Path.GetTempPath(), "family-expand-version-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        try
        {
            foreach (var name in new[]
                     {
                         "status-anchor.v2.json",
                         "status-anchor.v9.json",
                         "status-anchor.v10.json",
                         "status-anchor.json",
                     })
                File.WriteAllText(Path.Combine(dir, name), "{}");

            Assert.Equal(
                Path.Combine(dir, "status-anchor.v10.json"),
                VersionedInputFile.FindLatestPath(dir, "status-anchor"));
            Assert.Equal(10, VersionedInputFile.VersionOf(
                Path.Combine(dir, "status-anchor.v10.json"), "status-anchor"));
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }

    [Fact]
    public void Manifest_round_trips_with_input_output_and_refusal_provenance()
    {
        var manifest = FamilyExpandManifest.Create(
            new[]
            {
                new FamilyExpandInputDescriptor(
                    "data/seed/items/_tuning/tier-bands.v10.json", 10, new string('a', 64), true, null),
            },
            new[]
            {
                new FamilyExpandOutputDescriptor(
                    "data/seed/atoms/generated/family-expand.g-test.json", new string('b', 64), 5),
            },
            new[]
            {
                new FamilyRefusal("atom.test", "no referenceBaseGameUnits for channel 'test'"),
            });

        var text = manifest.ToCanonicalJson();
        var roundTripped = FamilyExpandManifest.Parse(text);

        Assert.Equal(text, roundTripped.ToCanonicalJson());
        Assert.Equal(manifest.InputHash, roundTripped.InputHash);
        Assert.Equal(manifest.OutputHash, roundTripped.OutputHash);
        Assert.True(FamilyExpandManifest.Reconcile(text, manifest).IsClean);
    }

    [Fact]
    public void Manifest_reconciliation_names_missing_and_changed_refusal_state()
    {
        var expected = FamilyExpandManifest.Create(
            Array.Empty<FamilyExpandInputDescriptor>(),
            Array.Empty<FamilyExpandOutputDescriptor>(),
            new[] { new FamilyRefusal("atom.test", "reason-a") });

        var missing = FamilyExpandManifest.Reconcile(null, expected);
        Assert.Equal(FamilyExpandManifestReconciliationStatus.Missing, missing.Status);
        Assert.False(missing.IsClean);

        var changed = FamilyExpandManifest.Create(
            Array.Empty<FamilyExpandInputDescriptor>(),
            Array.Empty<FamilyExpandOutputDescriptor>(),
            new[] { new FamilyRefusal("atom.test", "reason-b") });
        var drift = FamilyExpandManifest.Reconcile(expected.ToCanonicalJson(), changed);
        Assert.Equal(FamilyExpandManifestReconciliationStatus.Drifted, drift.Status);
        Assert.Contains("refusal", drift.Detail, StringComparison.OrdinalIgnoreCase);
        Assert.False(drift.IsClean);
    }

    [Fact]
    public void Manifest_is_a_zero_row_seed_envelope_for_existing_closed_kind_readers()
    {
        var manifest = FamilyExpandManifest.Create(
            new[]
            {
                new FamilyExpandInputDescriptor(
                    "data/seed/items/affix-families/g-test.json", null, new string('a', 64), true, "authored affix family"),
            },
            new[]
            {
                new FamilyExpandOutputDescriptor(
                    "data/seed/atoms/generated/family-expand.g-test.json", new string('b', 64), 0),
            },
            new[]
            {
                new FamilyRefusal("atom.test", "no referenceBaseGameUnits for channel 'test'"),
            });

        var collected = AtomSeedFile.Collect(new[]
        {
            ("_family-expand.manifest.json", manifest.ToCanonicalJson()),
        });

        Assert.True(collected.IsOk, string.Join("; ", collected.Errors));
        Assert.Equal(0, collected.Content.Count);
    }

    [Fact]
    public void Pool_closure_rejects_a_generated_reference_missing_from_the_live_pool_file()
    {
        const string poolJson = """
        {
          "entries": [
            {
              "id": "pool.element-power",
              "members": [
                { "channel": "combat.power.fire", "weight": 1000 }
              ]
            }
          ]
        }
        """;

        var catalog = FamilyExpandPoolCatalog.FromJson("data/seed/channel-pools/pools.v1.json", poolJson);
        var row = new AtomRow
        {
            AtomId = "atom.pool-test.t1",
            ParamsJson = """{"channel":{"pool":"pool.not-shipped","count":1,"allowRepeat":false}}""",
        };

        var errors = catalog.Validate(new[] { row });

        var error = Assert.Single(errors);
        Assert.Contains(row.AtomId, error, StringComparison.Ordinal);
        Assert.Contains("pool.not-shipped", error, StringComparison.Ordinal);
    }

    [Fact]
    public void Pool_closure_accepts_a_reference_to_a_live_pool()
    {
        const string poolJson = """
        {
          "entries": [
            {
              "id": "pool.element-power",
              "members": [
                { "channel": "combat.power.fire", "weight": 1000 }
              ]
            }
          ]
        }
        """;

        var catalog = FamilyExpandPoolCatalog.FromJson("data/seed/channel-pools/pools.v1.json", poolJson);
        var row = new AtomRow
        {
            AtomId = "atom.pool-test.t1",
            ParamsJson = """{"channel":{"pool":"pool.element-power","count":1,"allowRepeat":false}}""",
        };

        Assert.Empty(catalog.Validate(new[] { row }));
    }
}
