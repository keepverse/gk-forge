using FusionRpg.Tools.ItemSeedValidator;
using Xunit;

namespace FusionRpg.ItemSeedValidator.Tests;

/// <summary>
/// item-seed-regen cause 7 (2026-09-20): `Validator.Discover` scanned pipeline-machinery files as
/// if they were seed content — a run ledger tracks generation progress (`done`, `version`), a
/// tuning table carries `baseSharePermille`/`channelWeightPermille`/`opWeightPermille`, neither ever
/// declares `entries`/a recognized `kind`. This is a real disk scan (`Directory.EnumerateFiles`), so
/// the test substrate is disk on purpose (docs/contributing/testing-standard.md) — one temp
/// directory per test, deleted in `finally`, and a failed delete is a test FAILURE, never swallowed.
/// </summary>
public class ValidatorDiscoverTests
{
    static string NewTempRoot()
    {
        var root = Path.Combine(Path.GetTempPath(), "fusionrpg-discover-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        return root;
    }

    [Fact]
    public void A_tuning_directory_file_is_never_discovered()
    {
        var root = NewTempRoot();
        try
        {
            Directory.CreateDirectory(Path.Combine(root, "_tuning"));
            File.WriteAllText(Path.Combine(root, "_tuning", "tier-bands.v1.json"),
                """{ "baseSharePermille": 100, "channelWeightPermille": 200 }""");

            var files = Validator.Discover(root);

            Assert.Empty(files);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void A_ledger_file_is_never_discovered_regardless_of_directory()
    {
        var root = NewTempRoot();
        try
        {
            Directory.CreateDirectory(Path.Combine(root, "_runs"));
            File.WriteAllText(Path.Combine(root, "_runs", "base-types-gen.ledger.json"),
                """{ "version": 1, "done": [] }""");

            Directory.CreateDirectory(Path.Combine(root, "sets"));
            File.WriteAllText(Path.Combine(root, "sets", "set-charm-gen.ledger.json"),
                """{ "version": 1, "done": [] }""");

            var files = Validator.Discover(root);

            Assert.Empty(files);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void A_real_content_file_next_to_a_ledger_is_still_discovered()
    {
        var root = NewTempRoot();
        try
        {
            Directory.CreateDirectory(Path.Combine(root, "sets"));
            File.WriteAllText(Path.Combine(root, "sets", "set-charm-gen.ledger.json"),
                """{ "version": 1, "done": [] }""");
            File.WriteAllText(Path.Combine(root, "sets", "real-set.json"), SeedFixture.BaseTypeFile());

            var files = Validator.Discover(root);

            var file = Assert.Single(files);
            Assert.Equal("sets/real-set.json", file.RelativePath);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }
}
