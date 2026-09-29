using System.Text;
using System.Text.RegularExpressions;
using FusionRpg.Tools.ItemSeedValidator.Registries;

namespace FusionRpg.Tools.ItemSeedValidator.Naming;

/// <param name="Key">The sorted canonical-id list, joined — two names sharing this collide.</param>
/// <param name="Tokens">Surface tokens after step 2.</param>
/// <param name="Canonical">Canonical ids after step 3, before the connective drop.</param>
/// <param name="FusionSplit">True when a single-word name was decomposed into two pool words.</param>
/// <param name="FusionUndecidable">
/// True for a single-word name that could not be decomposed because F1's word pool is absent.
/// The name still normalizes (to itself), but the collision check cannot see through the fusion.
/// </param>
public sealed record NormalizedName(
    string Key,
    IReadOnlyList<string> Tokens,
    IReadOnlyList<string> Canonical,
    bool FusionSplit,
    bool FusionUndecidable);

/// <summary>
/// naming.v1.json's collision-normalization algorithm, implemented step for step. Four legal
/// spellings of one idea — Ashen Fang / Ash Fang / Fang of Ash / Ashfang — must land on the same
/// key, because that is the whole point: the corpus dedupes by meaning, not by string.
/// </summary>
public sealed class NameNormalizer
{
    readonly IReadOnlyDictionary<string, string> _surfaceForms;
    readonly IReadOnlySet<string> _canonicalWords;
    readonly HashSet<string> _connectives;

    public NameNormalizer(RegistrySet registries)
        : this(registries.SurfaceForms, registries.CanonicalWords, registries.Connectives) { }

    public NameNormalizer(
        IReadOnlyDictionary<string, string> surfaceForms,
        IReadOnlySet<string> canonicalWords,
        IEnumerable<string> connectives)
    {
        _surfaceForms = surfaceForms;
        _canonicalWords = canonicalWords;
        _connectives = new HashSet<string>(connectives, StringComparer.Ordinal);
    }

    /// <summary>True when F1's word pool is loaded; without it, fusions cannot be decomposed.</summary>
    public bool HasWordPool => _canonicalWords.Count > 0;

    public NormalizedName Normalize(string name)
    {
        // 1. lowercase.
        var lowered = name.ToLowerInvariant();

        // 2. tokenize on whitespace and punctuation boundaries.
        var tokens = Regex.Split(lowered, @"[^a-z0-9]+")
            .Where(t => t.Length > 0)
            .ToList();

        // 2a. WHOLE-TOKEN RESOLUTION PRECEDES FUSION DECOMPOSITION. A token that resolves whole
        //     is atomic and is never split — without this, an atomic seed word such as
        //     Thistledown decomposes into unrelated halves and collides with names sharing
        //     neither idea. naming.v1.json calls this rule load-bearing, and it is.
        var fusionSplit = false;
        var fusionUndecidable = false;
        if (tokens.Count == 1 && !_surfaceForms.ContainsKey(tokens[0]))
        {
            var split = SplitFusion(tokens[0]);
            if (split is not null) { tokens = split.ToList(); fusionSplit = true; }
            else if (!HasWordPool) fusionUndecidable = true;
        }

        // 3. resolve every surface token to its canonical pool id; an unregistered token is its
        //    own canonical id, lowercased.
        var canonical = tokens
            .Select(t => _surfaceForms.TryGetValue(t, out var id) ? id : t)
            .ToList();

        // 4. drop the closed connective list.
        var kept = canonical.Where(t => !_connectives.Contains(t)).ToList();

        // 5. sort, ordinal ascending.
        kept.Sort(StringComparer.Ordinal);

        // 6. the caller compares these keys corpus-wide.
        return new NormalizedName(string.Join(' ', kept), tokens, canonical, fusionSplit, fusionUndecidable);
    }

    /// <summary>
    /// Splits a fused word into exactly two known pool words. Ambiguous (more than one legal
    /// split) or undecidable returns null — a fusion that does not decompose to exactly one
    /// known pair is rejected at authoring time, never guessed at comparison time.
    /// </summary>
    public string[]? SplitFusion(string token)
    {
        if (!HasWordPool) return null;
        string[]? found = null;
        for (var i = 1; i < token.Length; i++)
        {
            var left = token[..i];
            var right = token[i..];
            if (!_surfaceForms.ContainsKey(left) || !_surfaceForms.ContainsKey(right)) continue;
            if (found is not null) return null; // ambiguous: two legal splits.
            found = new[] { left, right };
        }
        return found;
    }

    /// <summary>Human-readable canonical key for a report line.</summary>
    public static string Describe(NormalizedName n) =>
        n.Key.Length == 0 ? "(empty)" : new StringBuilder("[").Append(n.Key.Replace(" ", ", ")).Append(']').ToString();
}
