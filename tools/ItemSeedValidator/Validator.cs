using System.Text.Json.Nodes;
using FusionRpg.Tools.ItemSeedValidator.Checks;
using FusionRpg.Tools.ItemSeedValidator.Model;
using FusionRpg.Tools.ItemSeedValidator.Naming;
using FusionRpg.Tools.ItemSeedValidator.Registries;

namespace FusionRpg.Tools.ItemSeedValidator;

public sealed record ValidationResult(
    IReadOnlyList<Finding> Findings,
    int FilesScanned,
    int EntriesScanned,
    RegistrySet Registries,
    NamespaceAllocation Allocation)
{
    public int ErrorCount => Findings.Count(f => f.Severity == Severity.Error);
    public int WarningCount => Findings.Count(f => f.Severity == Severity.Warning);

    /// <summary>
    /// A validator that passes because it found nothing is worse than no validator. Zero files
    /// scanned is never success.
    /// </summary>
    public bool ScannedNothing => FilesScanned == 0;
}

public static class Validator
{
    /// <summary>Directory under the seed root holding the wave-0 registries.</summary>
    public const string RegistryDirName = "_registry";

    /// <summary>
    /// species-gear-chain T34 (manager finding, 2026-09-20): `_meta.kind` values that mark a file as
    /// GENERATED REGISTRY output — a closed catalog of ids a tool minted (here, the deterministic
    /// trophy planner's `gk-data/packs/fusion/data/seed/items/materials/trophy-registry.json`, 3600 rows), never authored
    /// seed content. It has no `id`/`nameKey`/`name` per row and no top-level `kind`/`schemaVersion`
    /// (seed-contract.md §9 is an AUTHORED-entry contract; this is a flat id list), so scanning it
    /// through <see cref="Checks.OwnershipCheck"/> read every `slot` integer as an author-typed
    /// magnitude — 3600 false `MagnitudeAuthored` findings, one per row, none of them real. The
    /// `_registry/` directory is the OTHER shape of this same idea (wave-0 INPUT registries this very
    /// validator reads); this is the same posture for generator OUTPUT that happens to live inside a
    /// content directory instead. Never hand-edit the file to fit the seed-contract envelope — it is
    /// `gk-forge/tools/seedsmith/seedsmith/adapters/items/trophyplan/run.py`'s own output shape.
    /// </summary>
    public static readonly IReadOnlySet<string> GeneratedRegistryKinds =
        new HashSet<string>(StringComparer.Ordinal) { "trophy-registry" };

    public static ValidationResult Run(string seedRoot)
    {
        var registries = RegistrySet.Load(Path.Combine(seedRoot, RegistryDirName));
        var files = Discover(seedRoot);
        return Run(registries, files);
    }

    public static ValidationResult Run(RegistrySet registries, IReadOnlyList<SeedFile> files)
    {
        var allocation = NamespaceAllocation.Build(registries);
        var ctx = new ValidationContext
        {
            Registries = registries,
            Allocation = allocation,
            Files = files,
            Normalizer = new NameNormalizer(registries),
        };

        // Registry health first. A namespace nothing validates, or a registry that is not frozen,
        // is a fleet-level problem and the report should lead with it.
        foreach (var missing in KindCatalog.MissingNamespaces(registries))
            ctx.CorpusError("NamespaceUncovered", "naming.v1.json idNamespaces",
                $"idNamespaces.{missing} is allocated but this validator has no kind for it; "
                + "ids under it would be validated against nothing");
        foreach (var problem in allocation.Problems)
            ctx.CorpusError("NamespaceUnexpandable", "naming.v1.json idNamespaces", problem);
        foreach (var unfrozen in registries.Unfrozen)
            ctx.CorpusWarn("RegistryNotFrozen", "authoring-fleet-plan.md §7.1",
                $"{unfrozen} still carries frozen:false; the freeze gate is not closed");
        if (registries.Words is null)
            ctx.CorpusWarn("WordPoolAbsent", "naming.v1.json collisionNormalization",
                "words.v1.json (F1's reserved word pools) is absent, so surface forms cannot be "
                + "collapsed onto canonical ids and fusions cannot be decomposed — the collision "
                + "check runs on raw tokens and will miss Ashen/Ash");

        StructuralCheck.Run(ctx);
        IdentityCheck.Run(ctx);
        OwnershipCheck.Run(ctx);
        NamingCheck.Run(ctx);
        ReferenceCheck.Run(ctx);
        UniqueRuleCheck.Run(ctx);
        SetRuleCheck.Run(ctx);
        DropTableCheck.Run(ctx);
        FrameDirectionCheck.Run(ctx);
        SocketMaxCheck.Run(ctx);
        GemAffinityCheck.Run(ctx);
        UniqueFrameCheck.Run(ctx);
        RoleFamilyCheck.Run(ctx);
        NameWordCheck.Run(ctx);
        // spec-item-card.md's four display reason codes, raised through Core's own
        // ContentRuleViolated{display.*} namespace -- see Checks/DisplayCheck.cs.
        DisplayCheck.Run(ctx);
        LintCheck.Run(ctx);

        // Partitions are assigned by IdentityCheck, after some findings were already recorded.
        // Backfill so every finding lands in the right group.
        var byFile = files.ToDictionary(f => f.RelativePath, StringComparer.Ordinal);
        var findings = ctx.Findings.Select(f =>
        {
            if (f.Partition != Finding.NoPartition) return f;
            if (!byFile.TryGetValue(f.File, out var file)) return f;
            var partition = f.EntryId is not null
                ? file.Entries.FirstOrDefault(e => e.Label == f.EntryId)?.Partition ?? Finding.NoPartition
                : ValidationContext.FilePartition(file);
            return partition == Finding.NoPartition ? f : f with { Partition = partition };
        }).ToList();

        return new ValidationResult(findings, files.Count, files.Sum(f => f.Entries.Count),
            registries, allocation);
    }

    /// <summary>
    /// Top-level directories that hold pipeline machinery, never authored or demonstration content —
    /// currently just tuning curve tables (`_tuning/tier-bands.v*.json`: `baseSharePermille`/
    /// `channelWeightPermille`/`opWeightPermille`, a different schema entirely; the sibling
    /// `_runs/*.ledger.json` ledgers are caught by the filename rule below, since a `*-gen.ledger.json`
    /// is also authored directly INSIDE a content directory — `charms/set-charm-gen.ledger.json`,
    /// `sets/set-charm-gen.ledger.json`, `combinations/combination-gen.ledger.json`). `_exemplars` is
    /// deliberately NOT here — an exemplar demonstrates a real partition's shape and several checks
    /// (<see cref="SeedFile.IsExemplar"/> consumers) still validate its structure, just not its
    /// global uniqueness.
    /// </summary>
    static readonly string[] NonContentDirs = { "_tuning" };

    /// <summary>Filename suffixes for pipeline artefacts that sit directly inside a real content
    /// directory. A run ledger tracks generation progress (`done`, `version`); the combination
    /// generator's still-blocked report (`combination-still-blocked.json`, `spec-combination-regen.md`
    /// R13 — "a JSON artefact beside the run ledger") carries `schemaVersion` + `rows` and its own
    /// `blockedReason`, and is a read over that same ledger. Neither declares `entries` or a
    /// recognized `kind`, because neither is authored identity.
    ///
    /// The suffix stays a CURATED list, matching <see cref="NonContentDirs"/>: a bare "has no
    /// `kind`" rule would silently stop validating a genuinely malformed content file.</summary>
    static readonly string[] NonContentFileSuffixes = { ".ledger.json", "-still-blocked.json" };

    /// <summary>Every .json under the seed root except the registry directory, pipeline-machinery
    /// directories/files (<see cref="NonContentDirs"/> and <see cref="NonContentFileSuffixes"/>),
    /// and a generated registry file (<see cref="GeneratedRegistryKinds"/>) wherever it lives. Found
    /// live (item-seed-regen cause 7, 2026-09-20): 17 files were being scanned as seed content despite
    /// never carrying `entries`/a recognized `kind` at all — a run ledger tracks generation progress
    /// (`done`, `version`), not authored identity.</summary>
    public static List<SeedFile> Discover(string seedRoot)
    {
        var files = new List<SeedFile>();
        if (!Directory.Exists(seedRoot)) return files;

        foreach (var path in Directory.EnumerateFiles(seedRoot, "*.json", SearchOption.AllDirectories)
                     .OrderBy(p => p, StringComparer.Ordinal))
        {
            if (NonContentFileSuffixes.Any(s => path.EndsWith(s, StringComparison.Ordinal))) continue;
            var relative = Path.GetRelativePath(seedRoot, path).Replace('\\', '/');
            var segments = relative.Split('/');
            if (segments[0] == RegistryDirName) continue;
            if (NonContentDirs.Contains(segments[0], StringComparer.Ordinal)) continue;
            var directory = segments.Length > 1 ? segments[0] : "";
            var file = SeedFile.Load(path, relative, directory);
            if (file.Meta?["kind"] is JsonValue kindValue && kindValue.TryGetValue<string>(out var metaKind)
                && GeneratedRegistryKinds.Contains(metaKind))
                continue;
            files.Add(file);
        }

        return files;
    }
}
