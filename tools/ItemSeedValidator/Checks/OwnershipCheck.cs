using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using FusionRpg.Core.Effects.Atoms;
using FusionRpg.Tools.ItemSeedValidator.Model;

namespace FusionRpg.Tools.ItemSeedValidator.Checks;

/// <summary>
/// seed-contract.md §2 and §3 — the two rules the whole build rests on.
///
/// §2: a DERIVED or GENERATED field present in a seed file is an error, because two sources of
/// truth for one value diverge and nothing downstream can tell which one was read.
///
/// §3: an author writes a count, a reference, an enum, or a band. Never a magnitude. This is what
/// stops 125 independent agents inventing 125 balance systems, each file individually valid and
/// the corpus collectively incoherent.
/// </summary>
public static class OwnershipCheck
{
    /// <summary>
    /// Field names that are DERIVED or GENERATED. Present in a seed file at any depth is an
    /// error, with the reason the ownership matrix gives.
    /// </summary>
    public static readonly IReadOnlyDictionary<string, string> ForbiddenFields =
        new Dictionary<string, string>(StringComparer.Ordinal)
        {
            ["affixClass"] = "DERIVED from kindId — permanent-modifier kinds are prefixes, triggered kinds are suffixes",
            ["atom_id"] = "DERIVED — computed from columns and validated as IdMismatch",
            ["atomId"] = "DERIVED — computed from columns and validated as IdMismatch",
            ["container_id"] = "DERIVED — computed from columns and validated as IdMismatch",
            ["containerId"] = "DERIVED — computed from columns and validated as IdMismatch",
            ["tiers"] = "GENERATED — tier magnitudes come from powerBand x the channel family's curve",
            ["tierMagnitudes"] = "GENERATED — tier magnitudes come from powerBand x the channel family's curve",
            ["tierAnchors"] = "GENERATED — tier magnitudes come from powerBand x the channel family's curve",
            ["bandMin"] = "GENERATED — band min/max come from powerBand x the channel family's curve",
            ["bandMax"] = "GENERATED — band min/max come from powerBand x the channel family's curve",
            ["magnitude"] = "DERIVED — every magnitude is derived; author a band",
            ["magnitudes"] = "DERIVED — every magnitude is derived; author a band",
            ["weight"] = "DERIVED — pool weights are generated from the role x group matrix; author a dropBand",
            ["weights"] = "DERIVED — pool weights are generated from the role x group matrix; author a dropBand",
            ["poolWeight"] = "GENERATED — pool rows and weights come from the role x group matrix",
            ["poolWeights"] = "GENERATED — pool rows and weights come from the role x group matrix",
            ["power"] = "DERIVED — the power model owns the power vector",
            ["powerVector"] = "DERIVED — the power model owns the power vector",
            ["powerCoefficient"] = "DERIVED — the power model owns the power vector",
            ["price"] = "DERIVED — §8, arrives from rarity ordinal, ilvl, affix count and class",
            ["sellPrice"] = "DERIVED — §8",
            ["buyPrice"] = "DERIVED — §8",
            ["durability"] = "DERIVED — §8, arrives from class, rarity and tags",
            ["salvageYield"] = "DERIVED — §8, arrives from rarity band, ilvl and enhancement level",
            ["encumbrance"] = "DERIVED — §8, arrives from class, role, frame and tags",
            ["roleLegality"] = "DERIVED — role x family legality comes from each family's declared roleGroups",
            ["legalRoles"] = "DERIVED — role x family legality comes from each family's declared roleGroups",
            ["resonances"] = "GENERATED — all 25 socket resonances are rule-derived",
            ["probability"] = "DERIVED — an author may never type a probability",
            ["chance"] = "DERIVED — an author may never type a probability",
            ["quantity"] = "DERIVED — an author may never type a quantity; author a costBand",
        };

    /// <summary>
    /// The only keys that may carry a number. A count is structure; everything else is balance.
    /// (seed-contract.md §2.1 "structural counts", §3's allowlist.)
    /// </summary>
    public static readonly string[] StructuralCountFields =
    {
        "socketMax", "pieces", "pool_rolls", "poolRolls", "prefixRolls", "suffixRolls",
        "rung", "ordinal", "seq", "sequence",
        // Added after entry-shapes.md shaped the remaining ten kinds. Each is the same species of
        // field as socketMax — it counts a structural thing, it is not a balance magnitude.
        "minSockets", "maxSockets", "apCost", "apCapacity", "manifestCost", "outputQty", "inputQty",
        "charges", "maxCharges", "slots", "count", "tier", "band", "threshold",
        // `atLevel` is an enhancement milestone rung — one of the five fixed steps
        // +4/+8/+12/+16/+20 (ssot-enhancement.md §5.4), the same species of value as a set
        // threshold's `pieces`. It names a rung; it does not scale anything.
        "atLevel",
        // entry-shapes.md's own field tables name these "AUTHORED (structural count)" too:
        // a curve's points[].atOrdinal (§5 — explicitly NOT covered by the curve's
        // multiplierPerMille exemption below), a socket-word's ingredients[].position (§2), and a
        // substrate material's grade rung 1-4 (§3).
        "atOrdinal", "position", "grade",
    };

    /// <summary>
    /// The one deliberate exception to §3. A curve file's entire content is (input, multiplier)
    /// points — it is where the numbers the whole corpus references actually live, authored by a
    /// single reviewed partition rather than the fleet. Narrow on purpose: only this key, only in
    /// a curve file. Everything else still writes a band or a curveId.
    /// </summary>
    static bool IsCurvePoint(SeedEntry entry, string key) =>
        string.Equals(entry.File.Kind, "curve", StringComparison.Ordinal)
        && key is "multiplierPerMille" or "input" or "x" or "y";

    /// <summary>
    /// A second, equally narrow exception, same shape as <see cref="IsCurvePoint"/>: `combination`'s
    /// `ingredients[].minTier` and `grantedTier` (item-seedgen `combination-write-unblock`, 2026-09-07)
    /// are code-derived, never model-authored — `combogen/emit.py`'s own `assemble_entry`/
    /// `ingredient_rows` compute both from `ComboTuning` alone (D22's attunement bonus, the per-index
    /// `min_tier_plan`), the same P1 split ("model picks identity, code picks magnitude") this whole
    /// file exists to enforce, not a violation of it. Legacy `socket-word` never needed this exception
    /// because its own `ingredients[].position` shape (one row per slot, no repeat-folding) carries no
    /// per-row tier or count at all — `combination`'s ingredients are a genuine unordered MULTISET
    /// (D41), so `emit.ingredient_rows` folds repeats into `(family, minTier, quantity)` rows instead
    /// of re-introducing position by the back door (`emit.py`'s own doc comment). Narrow on purpose:
    /// only these two keys, only in a `combination` file.
    /// </summary>
    static bool IsCombinationDerivedTier(SeedEntry entry, string key) =>
        string.Equals(entry.File.Kind, "combination", StringComparison.Ordinal)
        && key is "minTier" or "grantedTier";

    /// <summary>
    /// The `quantity` half of the same exception, checked separately because `quantity` is a global
    /// <see cref="ForbiddenFields"/> entry (an `OwnershipViolation`, not a `CheckMagnitude` allowlist
    /// miss) elsewhere in the corpus — a recipe/workbench quantity is a genuine balance lever an
    /// author must never type, priced instead as a `costBand`. A `combination`'s
    /// `ingredients[].quantity` is a different fact: how many of the fixed four ingredient slots
    /// (D20 as amended) share one family, in a MULTISET with no position — a structural count, the
    /// same species as `pieces`/`socketMax`, not a balance magnitude. Scoped to the one kind and the
    /// one path, same discipline as <see cref="IsCombinationDerivedTier"/>.
    /// </summary>
    static bool IsCombinationIngredientQuantity(SeedEntry entry, string path, string key) =>
        string.Equals(entry.File.Kind, "combination", StringComparison.Ordinal)
        && key == "quantity" && path.Contains("ingredients[", StringComparison.Ordinal);

    /// <summary>Fields whose value must be a member of the matching bands.v1.json enum.</summary>
    public static readonly string[] BandFields = { "powerBand", "costBand", "dropBand", "variance" };

    static readonly Regex NumericString = new(@"^\s*[-+]?\d+([.,]\d+)?\s*$", RegexOptions.Compiled);

    public static void Run(ValidationContext ctx)
    {
        foreach (var entry in ctx.Entries) RunEntry(ctx, entry);
    }

    static void RunEntry(ValidationContext ctx, SeedEntry entry)
    {
        foreach (var (path, key, value) in ValidationContext.Walk(entry.Node))
        {
            if (ForbiddenFields.TryGetValue(key, out var why) && !IsCombinationIngredientQuantity(entry, path, key))
            {
                ctx.Error(entry, "OwnershipViolation", "seed-contract.md §2.1",
                    $"'{path}' is not the author's to write: {why}");
                continue;
            }

            CheckMagnitude(ctx, entry, path, key, value);
            CheckBand(ctx, entry, path, key, value);
        }

        CheckAtomKind(ctx, entry);
    }

    static void CheckMagnitude(ValidationContext ctx, SeedEntry entry, string path, string key, JsonNode? value)
    {
        if (value is not JsonValue jv) return;
        var allowed = StructuralCountFields.Contains(key, StringComparer.Ordinal)
                      || IsCurvePoint(entry, key)
                      || IsCombinationDerivedTier(entry, key)
                      || IsCombinationIngredientQuantity(entry, path, key);

        if (jv.TryGetValue<double>(out var number) && jv.GetValueKind() == System.Text.Json.JsonValueKind.Number)
        {
            if (!allowed)
            {
                ctx.Error(entry, "MagnitudeAuthored", "seed-contract.md §3",
                    $"'{path}' holds the number {jv.ToJsonString()}; an author writes a count, a "
                    + "reference, an enum or a band, never a magnitude. Allowed numeric fields: "
                    + string.Join(", ", StructuralCountFields));
                return;
            }
            if (number < 0 || number != Math.Floor(number))
                ctx.Error(entry, "StructuralCountInvalid", "seed-contract.md §2.1",
                    $"'{path}' is a structural count and must be a non-negative integer, not {jv.ToJsonString()}");
            return;
        }

        // A number typed as a string evades the JSON-type check and would land in the same column.
        if (!allowed && jv.TryGetValue<string>(out var text) && NumericString.IsMatch(text))
            ctx.Error(entry, "MagnitudeAuthored", "seed-contract.md §3",
                $"'{path}' holds \"{text}\", a magnitude written as a string; the no-magnitudes "
                + "rule is about the value, not the JSON type");
    }

    static void CheckBand(ValidationContext ctx, SeedEntry entry, string path, string key, JsonNode? value)
    {
        if (!BandFields.Contains(key, StringComparer.Ordinal)) return;
        if (!ctx.Registries.BandEnums.TryGetValue(key, out var members))
        {
            ctx.Error(entry, "BandEnumMissing", "bands.v1.json",
                $"'{path}' is a band field but bands.v1.json declares no enum for '{key}'");
            return;
        }
        if (value is not JsonValue jv || !jv.TryGetValue<string>(out var band))
        {
            ctx.Error(entry, "BandNotString", "seed-contract.md §3",
                $"'{path}' must be one of the {key} band names, not {value?.ToJsonString() ?? "null"}");
            return;
        }
        if (!members.Contains(band, StringComparer.Ordinal))
            ctx.Error(entry, "BandUnknown", "bands.v1.json",
                $"'{path}' is '{band}', which is not a {key} value; the closed enum is "
                + string.Join(", ", members));
    }

    /// <summary>
    /// kindId is VALIDATED against the atom layer's closed vocabulary — the same registry the
    /// importer will use, so a family that passes here cannot fail on kind at import.
    /// </summary>
    static void CheckAtomKind(ValidationContext ctx, SeedEntry entry)
    {
        if (entry.AsString("kindId") is not { } kindId) return;
        if (AtomKindRegistry.Get(kindId) is not null) return;
        ctx.Error(entry, "AtomKindUnknown", "definitions.md §1 / AtomKindRegistry",
            $"kindId '{kindId}' is not one of the {AtomKindRegistry.KindCount} atom kinds: "
            + string.Join(", ", AtomKindRegistry.All.Select(k => k.KindId).Order(StringComparer.Ordinal)));
    }
}
