using System.Text.Json;
using FusionRpg.Core.Workspace;
using FusionRpg.Core.Effects.Atoms;
using FusionRpg.Core.Items.Materials;
using FusionRpg.Core.Items.Sockets;

namespace FusionRpg.Tools.ItemSeedValidator;

/// <summary>
/// `--combo-budget-dump` (strain-splice-host SSH6.4, spec-combo-budget §3): the ONE C# computation,
/// printed as JSON for the readable Python report to render.
///
/// <para>⛔ <b>Why the report does not compute this itself.</b> `power(c, k)` is
/// `ActorPowerCache.Compose` over the atoms `ComboContainerBuild` mints. Re-deriving that in Python
/// would be a second implementation of the price of an atom — the defect this dump exists to make
/// impossible — so the report shells out to this mode exactly the way `items repair-names` shells out
/// to `--collision-groups`, and prints what comes back.</para>
///
/// <para><b>Every input is the shipped one, read off disk through the shipped readers:</b> the sockets
/// revision <see cref="SocketTuningFiles.Current"/> names, the newest `materials.v{n}.json` and
/// `strain-splice.v{n}.json`, the recipe corpus, the combination corpus, and the atom + rarity seed
/// files through <see cref="AtomSeedFile.Collect"/> (the same reader the importer uses). Core reads no
/// file; this host does, and Core parses.</para>
///
/// <para><b>A cell that cannot be priced is REPORTED, not thrown.</b> A combination whose grants do not
/// resolve to atoms in the shipped catalog raises `ComboPricingRejection` — SSH4.4's own finding, and
/// exactly what the owner needs to see by name — so this mode catches it per cell and lists it under
/// `refused` rather than dying on the first one.</para>
/// </summary>
public static class ComboBudgetDump
{
    /// <summary>
    /// `comboPricing.maxRatioToRarityRouteMilli` is published into the sockets tuning by SSH6.8; until
    /// it is, the plan's own Defaults row applies — 1000, which is D23 written as arithmetic ("a word
    /// may equal, never undercut, the rarity route"). The published key WINS the moment it exists, so
    /// this is a floor for the value a balance pass moves, never a second source of truth for it.
    /// </summary>
    const long DefaultMaxRatioToRarityRouteMilli = 1000;

    public static int Run(string seedRoot)
    {
        var repoRoot = RepoRootOf(seedRoot);
        var tuningDir = Path.Combine(KeepverseRoots.Core(), "data", "tuning");
        var seedDir = Path.GetDirectoryName(seedRoot)!;

        var sockets = SocketTuning.Parse(
            File.ReadAllText(Path.Combine(tuningDir, SocketTuningFiles.Current)));
        // The published bound wins over the plan's default the moment SSH6.8 publishes `comboPricing`;
        // the parser is the one place that reads it (SSH6.6), so this never re-reads the raw JSON.
        var maxRatio = sockets.ComboPricingMaxRatioToRarityRouteMilli ?? DefaultMaxRatioToRarityRouteMilli;

        var materialsTuning = MaterialTuning.Parse(File.ReadAllText(LatestRevision(tuningDir, "materials")));
        var materials = MaterialRecipeCatalog.Load(
            JsonFiles(Path.Combine(seedRoot, "recipes")), materialsTuning);
        var strainSplice = StrainSpliceTuning.Parse(
            File.ReadAllText(LatestRevision(tuningDir, "strain-splice")), sockets);

        // Atoms and the rarity ladder through the importer's own reader: `gk-data/packs/fusion/data/seed/atoms/**` carries
        // the generated rows and `data/seed/rarity/ladder.v{n}.json` the ten rungs.
        var collected = AtomSeedFile.Collect(
            SeedFiles(Path.Combine(seedDir, "atoms")).Concat(SeedFiles(Path.Combine(seedDir, "rarity"))));
        var atoms = collected.Content.Atoms.ToDictionary(a => a.AtomId, StringComparer.Ordinal);
        var lookups = new ComboContainerBuild.ComboContainerLookups(
            id => atoms.TryGetValue(id, out var atom) ? atom : null);

        // The combination corpus: recipes for the firing rules, the raw documents for the grants.
        var entries = new List<CombinationEntry>();
        var grants = new Dictionary<string, IReadOnlyList<string>>(StringComparer.Ordinal);
        foreach (var file in Directory.GetFiles(Path.Combine(seedRoot, "combinations"), "*.json")
                     .OrderBy(f => f, StringComparer.Ordinal))
        {
            var json = File.ReadAllText(file);
            entries.AddRange(CombinationCorpus.Parse(json));
            foreach (var (id, list) in CombinationCorpus.ReadGrants(json)) grants[id] = list;
        }
        var (recipes, refusals) = CombinationCorpus.ToRecipes(entries, strainSplice);

        var inputs = new ComboPricingInputs(
            sockets, collected.Content.Rarities, materials, lookups, maxRatio);
        var steps = ComboPricing.Steps(inputs.RarityLadder, materials);
        var reference = ComboPricing.ChosenStep(steps);

        var measured = new List<ComboPricingCell>();
        var cells = new List<object>();
        var refused = new List<object>();

        foreach (var recipe in recipes.OrderBy(r => r.ComboId, StringComparer.Ordinal))
        {
            var comboGrants = grants.TryGetValue(recipe.ComboId, out var list)
                ? list
                : Array.Empty<string>();
            // ⛔ The floors come from the LADDER, not from the ingredient rows (strain-splice-host
            // SSH7.5/SSH7.6): since the re-emit every row's `MinTier` is 0, so pricing off the rows
            // priced four tier-0 gems and made every cell look free. `BaseFloors` is rung 1's floors,
            // read from the tuning at import — exactly the floors the matcher compares against.
            var tiers = recipe.BaseFloors?.ToList() ?? new List<int>();

            foreach (var attuned in new[] { false, true })
            {
                if (tiers.Count != sockets.StrainSpliceIngredientCount)
                {
                    refused.Add(new
                    {
                        comboId = recipe.ComboId,
                        attuned,
                        reason = $"'{recipe.ComboId}' carries {tiers.Count} rung-1 floor(s); a recipe " +
                                 $"is {sockets.StrainSpliceIngredientCount} inserts wide",
                    });
                    continue;
                }

                var request = new ComboPricingRequest(
                    ComboId: recipe.ComboId,
                    Grants: comboGrants,
                    Tier: attuned ? recipe.BaseTier + sockets.AttunedTierBonus : recipe.BaseTier,
                    IngredientTiers: tiers,
                    HostRole: string.IsNullOrEmpty(recipe.HostRole) ? null : recipe.HostRole,
                    Attuned: attuned);
                try
                {
                    var cell = ComboPricing.MeasureCell(request, inputs, reference);
                    measured.Add(cell);
                    cells.Add(Cell(cell));
                }
                catch (ComboPricingRejection refusal)
                {
                    refused.Add(new
                    {
                        comboId = recipe.ComboId,
                        attuned,
                        reason = refusal.Message,
                    });
                }
            }
        }

        var report = new ComboPricingReport(measured, reference, steps);
        var derivation = ComboPricing.Derive(report, inputs);

        // SSH6.8: the `measuredAgainst` object the passing report prints for publication (spec-combo-budget
        // §4). The digest is over the SAME accepted set and reads the SAME helper the boot calls
        // (`CombinationCorpus.Digest`), so the published value cannot drift from what boot recomputes. The
        // revisions are FILENAME revisions (never the internal `version` field). `socketsVersion` is the
        // revision the pricing is published INTO — the next sockets revision, since the report runs before
        // `publish.py` bumps it (H7: the readers switch in the same commit).
        var measuredAgainst = new
        {
            socketsVersion = SocketTuningFiles.RevisionOf(SocketTuningFiles.Current) + 1,
            strainSpliceVersion = SocketTuningFiles.RevisionOf(Path.GetFileName(LatestRevision(tuningDir, "strain-splice"))),
            materialsVersion = SocketTuningFiles.RevisionOf(Path.GetFileName(LatestRevision(tuningDir, "materials"))),
            circuitSize = SocketLimits.SocketCircuitSize,
            combinationCorpusDigest = CombinationCorpus.Digest(recipes, grants),
        };

        var payload = new
        {
            maxRatioToRarityRouteMilli = maxRatio,
            measuredAgainst,
            geometry = new
            {
                allRoles = SocketGeometry.GeometricCombinationCeiling(
                    sockets, sockets.SocketCeiling.Keys),
                reachable = SocketGeometry.ReachableCombinationCeiling(sockets, recipes),
                byRole = sockets.SocketCeiling
                    .OrderBy(kv => FusionRpg.Core.Items.ItemRoles.Id(kv.Key), StringComparer.Ordinal)
                    .Select(kv => new
                    {
                        role = FusionRpg.Core.Items.ItemRoles.Id(kv.Key),
                        ceiling = kv.Value,
                        circuits = kv.Value / SocketLimits.SocketCircuitSize,
                    })
                    .ToList(),
            },
            reference = new
            {
                fromRung = reference.FromRungId,
                toRung = reference.ToRungId,
                deltaPower = reference.DeltaPower,
                elevateSouls = reference.ElevateSouls,
            },
            excludedSteps = steps.Where(s => s.Excluded).Select(s => new
            {
                fromRung = s.FromRungId, toRung = s.ToRungId, deltaPower = s.DeltaPower, reason = s.Reason,
            }).ToList(),
            recipeRefusals = refusals.Select(r => new
            {
                reason = r.Reason.ToString(), detail = r.Detail,
            }).ToList(),
            cells,
            refused,
            derivation = new
            {
                levers = derivation.Levers.Select(l => new
                {
                    lever = LeverId(l.Lever),
                    currentCoefficient = l.CurrentCoefficient,
                    derivedCoefficient = l.DerivedCoefficient,
                }).ToList(),
                cells = derivation.Cells.Select(c => new
                {
                    comboId = c.ComboId,
                    levers = c.Levers.Select(LeverId).ToList(),
                    smallestLever = c.SmallestLever is { } smallest ? LeverId(smallest) : null,
                    requiredCoefficient = c.RequiredCoefficient,
                }).ToList(),
                unfixable = derivation.UnfixableCellIds,
            },
        };

        Console.WriteLine(JsonSerializer.Serialize(payload,
            new JsonSerializerOptions { WriteIndented = true }));
        return 0;
    }

    static object Cell(ComboPricingCell cell) => new
    {
        comboId = cell.ComboId,
        tier = cell.Tier,
        attuned = cell.Attuned,
        power = cell.Power,
        priceFloorSouls = cell.PriceFloorSouls,
        legs = cell.Legs.Select(l => new
        {
            name = l.Name,
            quantity = l.Quantity,
            souls = l.Souls,
            rungIndex = l.RungIndex,
            lever = l.Lever is { } lever ? LeverId(lever) : null,
        }).ToList(),
        floorRungIndex = cell.FloorRungIndex,
        ratioMilli = cell.RatioMilli,
        referenceMilli = cell.ReferenceMilli,
        passes = cell.Passes,
    };

    static string LeverId(ComboPricingLever lever) => lever switch
    {
        ComboPricingLever.Bore => "bore",
        ComboPricingLever.Imbue => "imbue",
        ComboPricingLever.ForgeGem => "forge-gem",
        _ => throw new ArgumentOutOfRangeException(nameof(lever), lever, null),
    };

    /// <summary>The seed root's grandparent: `gk-data/packs/fusion/data/seed/items` → the repo root (tuning lives in
    /// `gk-core/data/tuning`, the atom and rarity seeds in `gk-data/packs/fusion/data/seed`).</summary>
    static string RepoRootOf(string seedRoot)
    {
        var data = Directory.GetParent(seedRoot)?.Parent
            ?? throw new InvalidOperationException($"cannot walk up from {seedRoot}");
        return data.Parent?.FullName
            ?? throw new InvalidOperationException($"cannot find the repo root above {seedRoot}");
    }

    /// <summary>The highest `{domain}.v{n}.json` by the FILENAME revision — what
    /// `gk-core/tools/tuning/publish.py`'s own `latest_version` reads, and never the file's internal
    /// `version` field (which disagrees for `sockets`: v1 carries 3, v2 carries 2).</summary>
    static string LatestRevision(string tuningDir, string domain)
    {
        var candidates = Directory.GetFiles(tuningDir, $"{domain}.v*.json")
            .Select(path => (Path: path, Revision: RevisionOf(Path.GetFileName(path), domain)))
            .Where(c => c.Revision > 0)
            .OrderByDescending(c => c.Revision)
            .ToList();
        if (candidates.Count == 0)
            throw new InvalidOperationException($"no {domain}.v*.json in {tuningDir}");
        return candidates[0].Path;
    }

    static int RevisionOf(string fileName, string domain)
    {
        var stem = $"{domain}.v";
        if (!fileName.StartsWith(stem, StringComparison.Ordinal) ||
            !fileName.EndsWith(".json", StringComparison.Ordinal)) return -1;
        var middle = fileName[stem.Length..^".json".Length];
        return int.TryParse(middle, out var revision) ? revision : -1;
    }

    static IEnumerable<(string Path, string Json)> SeedFiles(string directory) =>
        Directory.Exists(directory)
            ? Directory.GetFiles(directory, "*.json", SearchOption.AllDirectories)
                .OrderBy(f => f, StringComparer.Ordinal)
                .Select(f => (Path: f, Json: File.ReadAllText(f)))
            : Enumerable.Empty<(string Path, string Json)>();

    static IEnumerable<string> JsonFiles(string directory) =>
        Directory.Exists(directory)
            ? Directory.GetFiles(directory, "*.json", SearchOption.AllDirectories)
                .OrderBy(f => f, StringComparer.Ordinal)
                .Select(File.ReadAllText)
            : Enumerable.Empty<string>();
}
