using System.Text.Json.Nodes;
using FusionRpg.Tools.ItemSeedValidator.Model;

namespace FusionRpg.Tools.ItemSeedValidator.Checks;

/// <summary>
/// `item_role_family` legality at seed time (item-ideal.md, `affix-legality` module 8): the two new
/// override artefacts (`family-overrides.v1.json`, `role-relocation.v1.json`) must name only families
/// and roles that genuinely exist in the corpus — an override for a typo'd family id would silently
/// do nothing, which is worse than an error.
///
/// <para>Reads both through <see cref="Registries.RegistrySet"/>'s already-parsed optional
/// properties, not raw disk I/O against <c>RegistryDir</c> — every other check in this tool does the
/// same, and it is what makes the in-memory <c>RegistrySet.FromNodes</c> test seam actually work
/// (its <c>RegistryDir</c> is the literal string <c>"(in-memory)"</c>, so a check that stats a real
/// path off it can never find anything, in a test or otherwise). Found and fixed by running this
/// tool's own test suite in full for the first time this session — every prior scoped test that
/// loaded even one affix-family entry silently failed this check for a reason that had nothing to do
/// with what it was testing.</para>
/// </summary>
public static class RoleFamilyCheck
{
    public static void Run(ValidationContext ctx)
    {
        var familyRoles = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
        foreach (var entry in ctx.Entries)
        {
            if (entry.File.Kind != "affix-family") continue;
            if (entry.File.IsExemplar) continue; // a pattern, not corpus content
            if (entry.Id is not { } id) continue;
            var roles = (entry.Node["roles"] as JsonArray)?
                .OfType<JsonValue>()
                .Select(v => v.TryGetValue<string>(out var s) ? s : null)
                .OfType<string>().ToHashSet(StringComparer.Ordinal) ?? new HashSet<string>();
            familyRoles[id] = roles;
        }

        if (familyRoles.Count == 0) return; // no affix-family corpus loaded (e.g. a scoped test run)

        CheckOverrides(ctx, familyRoles);
        CheckRelocation(ctx, familyRoles);
    }

    static void CheckOverrides(ValidationContext ctx, Dictionary<string, HashSet<string>> familyRoles)
    {
        // Same "absence degrades, never blocks" rule every other optional registry here follows
        // (Words, BuildThemes, RetiredIds) — a scoped run over a handful of hand-built entries has
        // no reason to supply this file at all.
        if (ctx.Registries.FamilyOverrides is not { } doc) return;

        if (doc["removedFamilies"] is JsonArray removed)
            foreach (var r in removed.OfType<JsonObject>())
            {
                var role = r["role"]!.GetValue<string>();
                var familyId = r["familyId"]!.GetValue<string>();
                if (!familyRoles.TryGetValue(familyId, out var roles))
                    ctx.CorpusError("RoleFamilyOverrideUnknownFamily", "family-overrides.v1.json",
                        $"removedFamilies names '{familyId}', which is not a family in the corpus");
                else if (!roles.Contains(role))
                    ctx.CorpusError("RoleFamilyOverrideNotLegal", "family-overrides.v1.json",
                        $"removedFamilies names '{familyId}' on role '{role}', but that family is not legal there to begin with");
            }
    }

    static void CheckRelocation(ValidationContext ctx, Dictionary<string, HashSet<string>> familyRoles)
    {
        if (ctx.Registries.RoleRelocation is not { } doc)
        {
            // A WARNING, not a blocking error -- matching WordPoolAbsent/SocketCeilingTableAbsent's
            // own precedent for every other optional registry. A real production sweep still needs
            // to see this (D3's relocation genuinely must be recorded there), but a scoped test run
            // that never supplied the file is not evidence of that defect.
            ctx.CorpusWarn("RoleRelocationArtefactMissing", "spec-affix-legality.md",
                "role-relocation.v1.json was not supplied -- D3's relocation (ward-array/head-guard/sense) is unrecorded here");
            return;
        }

        var rows = (doc["relocations"] as JsonArray)?.OfType<JsonObject>().ToList() ?? new List<JsonObject>();
        var relocatedFamilies = rows.Select(r => r["familyId"]!.GetValue<string>()).ToHashSet(StringComparer.Ordinal);

        // "Family must exist in the loaded corpus" is only a meaningful check against the REAL sweep
        // -- a scoped run (a single-fixture unit test, most obviously) loads far fewer distinct
        // families than this file itself names, which would flag every one of them as "unknown"
        // purely from being partial, not from a typo. Comparing against the relocation file's OWN
        // family count (not a hardcoded number) is what keeps this self-consistent: the real corpus
        // always contains at least as many distinct families as this file references by construction
        // (every relocated family is, definitionally, a family that exists), so a loaded set smaller
        // than that can only be a partial one.
        var isLikelyFullSweep = familyRoles.Count >= relocatedFamilies.Count;

        foreach (var row in rows)
        {
            var familyId = row["familyId"]!.GetValue<string>();
            var hostRole = row["hostRole"]!.GetValue<string>();
            if (!familyRoles.TryGetValue(familyId, out var roles))
            {
                if (isLikelyFullSweep)
                    ctx.CorpusError("RoleRelocationUnknownFamily", "role-relocation.v1.json",
                        $"relocation names '{familyId}', which is not a family in the corpus");
                continue;
            }

            if (!roles.Contains(hostRole))
                ctx.CorpusError("RoleRelocationHostNotLegal", "role-relocation.v1.json",
                    $"relocation moves '{familyId}' onto host '{hostRole}', but that family is not legal on that role");
        }

        CheckRelocationCoverage(ctx, familyRoles, doc, rows, isLikelyFullSweep);
    }

    /// <summary>
    /// The REVERSE direction of the loop above, and the one that was missing until 2026-09-06: every
    /// check here walked the relocation file and asked "does the corpus still have this?", so a family
    /// the corpus GAINED after the file was computed had no row and nothing said so. Found by a
    /// final-proof pass when the affix-authoring lane shipped `g-punisher.json` — two families legal on
    /// the dropped `sense` role, zero relocation rows, so both silently kept `max_tier = 5` on their
    /// surviving hybrid-core hosts while every other `sense`-legal family sits at 3.
    ///
    /// <para>The relocation table is DERIVED (`_meta.source`: "computed from
    /// gk-data/packs/fusion/data/seed/items/affix-families/**"), so its completeness is a corpus fact, not an authoring
    /// choice — which makes it checkable rather than a matter of taste. Same `isLikelyFullSweep` guard
    /// as above: a scoped run loads a handful of families and must not be told its own partial corpus
    /// is missing rows.</para>
    /// </summary>
    static void CheckRelocationCoverage(
        ValidationContext ctx,
        Dictionary<string, HashSet<string>> familyRoles,
        JsonObject doc,
        List<JsonObject> rows,
        bool isLikelyFullSweep)
    {
        if (!isLikelyFullSweep) return;

        // Read the dropped roles from the file's own `_meta`, never a second hardcoded list here --
        // D3's three roles are that file's declaration and a copy would drift away from it silently.
        var dropped = (doc["_meta"]?["droppedRoles"] as JsonArray)?
            .OfType<JsonValue>()
            .Select(v => v.TryGetValue<string>(out var s) ? s : null)
            .OfType<string>()
            .ToHashSet(StringComparer.Ordinal) ?? new HashSet<string>(StringComparer.Ordinal);
        if (dropped.Count == 0) return;

        var covered = rows
            .Select(r => (Dropped: r["droppedRole"]!.GetValue<string>(), Family: r["familyId"]!.GetValue<string>()))
            .ToHashSet();

        foreach (var (familyId, roles) in familyRoles.OrderBy(kv => kv.Key, StringComparer.Ordinal))
            foreach (var droppedRole in roles.Where(dropped.Contains).OrderBy(r => r, StringComparer.Ordinal))
                if (!covered.Contains((droppedRole, familyId)))
                    ctx.CorpusError("RoleRelocationRowMissing", "role-relocation.v1.json",
                        $"'{familyId}' is legal on the dropped role '{droppedRole}' but no relocation row "
                        + "covers it -- it would keep its full max_tier on every surviving hybrid-core host");
    }
}
