using FusionRpg.Tools.ItemSeedValidator.Naming;
using Xunit;

namespace FusionRpg.ItemSeedValidator.Tests;

/// <summary>
/// naming.v1.json's collision normalizer. The whole point is that Ashen Fang / Ash Fang /
/// Fang of Ash / Ashfang are four names and one idea — if these tests pass, a reviewer never has
/// to spot an anagram again.
/// </summary>
public class NameNormalizerTests
{
    static NameNormalizer WithPool() => new(SeedFixture.Registries(withWords: true));
    static NameNormalizer WithoutPool() => new(SeedFixture.Registries());

    [Theory]
    [InlineData("Ashen Fang")]
    [InlineData("Ash Fang")]
    [InlineData("Fang of Ash")]
    [InlineData("Ashfang")]
    [InlineData("Fang of the Ash")]
    public void Four_spellings_of_one_idea_share_a_key(string name)
    {
        var normalizer = WithPool();
        Assert.Equal("ash fang", normalizer.Normalize(name).Key);
    }

    [Fact]
    public void Adjective_surface_form_collapses_onto_its_canonical_id()
    {
        // Step 3: a canonical id is invariant across the pattern slot the word appears in.
        var normalizer = WithPool();
        Assert.Equal(new[] { "ash" }, normalizer.Normalize("Ashen").Canonical);
    }

    [Fact]
    public void Connectives_are_dropped()
    {
        var normalizer = WithPool();
        var normalized = normalizer.Normalize("Fang of the Ash");
        Assert.Contains("the", normalized.Canonical);
        Assert.DoesNotContain("the", normalized.Key);
        Assert.DoesNotContain("of", normalized.Key);
    }

    [Fact]
    public void Tokens_are_sorted_so_word_order_does_not_matter()
    {
        var normalizer = WithPool();
        Assert.Equal(normalizer.Normalize("Ash Fang").Key, normalizer.Normalize("Fang Ash").Key);
    }

    [Fact]
    public void Whole_token_resolution_precedes_fusion_decomposition()
    {
        // Rule 2a, which naming.v1.json calls load-bearing: Thistledown is a registered atomic
        // seed word, so it must NOT decompose into thistle + down and collide with "Thistle Down".
        var normalizer = WithPool();
        var atomic = normalizer.Normalize("Thistledown");

        Assert.False(atomic.FusionSplit);
        Assert.Equal("thistledown", atomic.Key);
        Assert.NotEqual(normalizer.Normalize("Thistle Down").Key, atomic.Key);
    }

    [Fact]
    public void Unregistered_token_resolves_to_itself()
    {
        // Step 3: an ordinary base-type noun with no pool entry is its own canonical id.
        var normalizer = WithPool();
        Assert.Equal("ash crown", normalizer.Normalize("Ashen Crown").Key);
    }

    [Fact]
    public void Fusion_with_no_pool_is_reported_undecidable_rather_than_guessed()
    {
        var normalizer = WithoutPool();
        var normalized = normalizer.Normalize("Ashfang");

        Assert.True(normalized.FusionUndecidable);
        Assert.False(normalized.FusionSplit);
        Assert.Equal("ashfang", normalized.Key);
    }

    [Fact]
    public void Fusion_matching_no_known_pair_does_not_split()
    {
        var normalizer = WithPool();
        Assert.Null(normalizer.SplitFusion("ashfangash"));
    }

    [Fact]
    public void Fusion_with_two_legal_splits_does_not_split()
    {
        // The registry caps a fusion at exactly two words so the split is unambiguous. When it
        // is not, the answer is "no split", never a guess: "ember" + "stone" and "embers" +
        // "tone" are both legal readings of "emberstone".
        var surfaces = new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["ember"] = "ember", ["embers"] = "embers", ["stone"] = "stone", ["tone"] = "tone",
        };
        var normalizer = new NameNormalizer(
            surfaces, surfaces.Values.ToHashSet(StringComparer.Ordinal), new[] { "of", "the", "a", "and" });

        Assert.Null(normalizer.SplitFusion("emberstone"));
    }

    [Fact]
    public void Punctuation_and_case_are_stripped_before_comparison()
    {
        var normalizer = WithPool();
        Assert.Equal(normalizer.Normalize("Ash Fang").Key, normalizer.Normalize("ash-fang").Key);
    }
}
