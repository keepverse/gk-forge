using System.Text.Json.Nodes;
using FusionRpg.Tools.ItemSeedValidator.Model;
using FusionRpg.Tools.ItemSeedValidator.Registries;

namespace FusionRpg.Tools.ItemSeedValidator.Checks;

/// <summary>
/// The envelope: does it parse, is the schemaVersion one we know, does <c>kind</c> agree with the
/// directory, is <c>_meta</c> complete, and does every key belong. Unknown keys reject — forward
/// compatibility comes from schemaVersion, not from lenient parsing (seed-contract.md §9).
/// </summary>
public static class StructuralCheck
{
    /// <summary>schemaVersions this validator understands.</summary>
    public static readonly int[] KnownSchemaVersions = { 1 };

    static readonly string[] TopLevelKeys = { "schemaVersion", "kind", "_meta", "entries" };

    public static void Run(ValidationContext ctx)
    {
        foreach (var file in ctx.Files) RunFile(ctx, file);
    }

    static void RunFile(ValidationContext ctx, SeedFile file)
    {
        if (file.ParseError is not null || file.Root is null)
        {
            ctx.FileError(file, "ParseFailed", "seed-contract.md §9",
                $"file does not parse as JSON: {file.ParseError}");
            return;
        }

        foreach (var path in file.DuplicateKeyPaths)
            ctx.FileError(file, "DuplicateKey", "seed-contract.md §9",
                $"key '{path}' appears twice; the first value is silently discarded by every JSON reader");

        // schemaVersion
        var schema = file.Root["schemaVersion"];
        if (schema is null)
            ctx.FileError(file, "SchemaVersionMissing", "seed-contract.md §9", "no schemaVersion");
        else if (schema is not JsonValue sv || !sv.TryGetValue<int>(out var version))
            ctx.FileError(file, "SchemaVersionInvalid", "seed-contract.md §9", "schemaVersion is not an integer");
        else if (!KnownSchemaVersions.Contains(version))
            ctx.FileError(file, "SchemaVersionUnknown", "seed-contract.md §9",
                $"schemaVersion {version} is unknown; this validator knows "
                + string.Join(", ", KnownSchemaVersions));

        // unknown top-level keys
        foreach (var (key, _) in file.Root)
            if (!TopLevelKeys.Contains(key, StringComparer.Ordinal))
                ctx.FileError(file, "UnknownKey", "seed-contract.md §9",
                    $"unknown top-level key '{key}'; the envelope is "
                    + string.Join(", ", TopLevelKeys));

        // kind must exist, be known, and match the directory it sits in
        var kindId = file.Kind;
        SeedKind? kind = null;
        if (kindId is null)
        {
            ctx.FileError(file, "KindMissing", "seed-contract.md §9", "no kind");
        }
        else if (!KindCatalog.All.TryGetValue(kindId, out kind))
        {
            // Count derived from KindCatalog.All itself, not a literal -- item-seed-regen cause 3
            // (2026-09-20) found this hardcoded at "15" while the catalog had long since grown to
            // 16 (relic/combination onboarded earlier); a stale count in a message body is not
            // itself a validator defect, but a literal that drifts from the thing it describes
            // is exactly the drive-by this file was already being edited for.
            ctx.FileError(file, "KindUnknown", "seed-contract.md §9",
                $"kind '{kindId}' is not one of the {KindCatalog.All.Count} partition kinds "
                + "naming.v1.json allocates");
        }
        else
        {
            var byDir = KindCatalog.ByDirectory(file.Directory);
            // _exemplars/ holds one worked file per kind — the pattern 124 agents copy. They must
            // validate like real content (that is the whole point of an exemplar), but they do not
            // live in a kind directory, so the kind comes from the file's own declaration.
            if (file.IsExemplar)
            {
                // no directory constraint
            }
            else if (byDir is null)
                ctx.FileError(file, "DirectoryUnknown", "seed-contract.md §9",
                    $"directory '{file.Directory}/' matches no kind; expected one of "
                    + string.Join(", ", KindCatalog.All.Values.Select(k => k.Directory).Order(StringComparer.Ordinal)));
            else if (!string.Equals(byDir.Kind, kind.Kind, StringComparison.Ordinal))
                ctx.FileError(file, "KindDirectoryMismatch", "seed-contract.md §9",
                    $"kind '{kind.Kind}' sits in '{file.Directory}/', which is the '{byDir.Kind}' directory");
        }

        CheckMeta(ctx, file);

        if (file.Root["entries"] is not JsonArray entries)
        {
            ctx.FileError(file, "EntriesMissing", "seed-contract.md §9", "no entries array");
            return;
        }
        for (var i = 0; i < entries.Count; i++)
            if (entries[i] is not JsonObject)
                ctx.FileError(file, "EntryNotObject", "seed-contract.md §9", $"entries[{i}] is not an object");
        if (entries.Count == 0)
            ctx.FileWarn(file, "EntriesEmpty", "authoring-fleet-plan.md §8.1",
                "file declares zero entries; a partition that produced nothing is worth a look");

        if (kind is null) return;
        foreach (var entry in file.Entries) CheckEntryShape(ctx, entry, kind);
    }

    static void CheckMeta(ValidationContext ctx, SeedFile file)
    {
        if (file.Meta is not JsonObject meta)
        {
            ctx.FileError(file, "MetaMissing", "seed-contract.md §9",
                "no _meta; without it a rerun six weeks later is a guess");
            return;
        }

        foreach (var required in KindCatalog.RequiredMeta)
            if (meta[required] is null)
                ctx.FileError(file, "MetaIncomplete", "seed-contract.md §9",
                    $"_meta.{required} is missing; provenance must record contract, registry, "
                    + "exemplar, prompt and model versions");

        if (meta["sourceRef"] is null)
            ctx.FileWarn(file, "MetaSourceRefMissing", "seed-contract.md §9",
                "_meta.sourceRef is absent; the design source a rerun would read is unrecorded");

        if (meta["registryVersions"] is JsonObject versions)
        {
            foreach (var (name, value) in versions)
            {
                if (!ctx.Registries.Versions.TryGetValue(name, out var loaded))
                {
                    ctx.FileError(file, "MetaRegistryUnknown", "seed-contract.md §9",
                        $"_meta.registryVersions names '{name}', which is not a loaded registry "
                        + $"({string.Join(", ", ctx.Registries.Versions.Keys.Order(StringComparer.Ordinal))})");
                    continue;
                }
                if (value is JsonValue v && v.TryGetValue<int>(out var declared) && declared != loaded)
                {
                    // Not every bump invalidates what came before. A registry that only ADDS —
                    // a new pool, a widened appliesTo, a role that did not exist — leaves every
                    // earlier file exactly as valid as it was. Only a bump that changes or
                    // removes meaning forces a re-run, and each registry declares where that
                    // line falls via minCompatibleVersion.
                    //
                    // Without this distinction a 125-agent build cannot converge: any fix during
                    // the run invalidates everything authored before it, and the corpus chases a
                    // moving target forever.
                    var floor = ctx.Registries.MinCompatible.TryGetValue(name, out var m) ? m : loaded;
                    if (declared < floor)
                        ctx.FileError(file, "MetaRegistryVersionMismatch", "authoring-fleet-plan.md §7.1",
                            $"authored against {name} v{declared}, but v{floor} is the oldest version "
                            + $"still compatible (v{loaded} loaded); this partition must re-run");
                    else
                        ctx.FileWarn(file, "MetaRegistryVersionBehind", "authoring-fleet-plan.md §7.1",
                            $"authored against {name} v{declared}, v{loaded} is loaded; the change "
                            + "since then was additive, so this file stays valid");
                }
            }
        }
        else if (meta["registryVersions"] is not null)
        {
            ctx.FileError(file, "MetaIncomplete", "seed-contract.md §9",
                "_meta.registryVersions is not an object");
        }
    }

    static void CheckEntryShape(ValidationContext ctx, SeedEntry entry, SeedKind kind)
    {
        foreach (var required in kind.RequiredFields)
            if (entry.Node[required] is null)
                ctx.Error(entry, "RequiredFieldMissing", "seed-contract.md §9/§10",
                    $"kind '{kind.Kind}' requires '{required}'");

        foreach (var (key, _) in entry.Node)
        {
            if (kind.AllowedFields.Contains(key, StringComparer.Ordinal)) continue;

            if (kind.ShapeDefined)
                ctx.Error(entry, "UnknownKey", "seed-contract.md §9",
                    $"unknown key '{key}' on kind '{kind.Kind}'; unknown keys reject");
            else
                // seed-contract.md §10 gives no shape for this kind, so rejecting an extra key
                // would be the validator inventing a schema. Say so instead of guessing.
                ctx.Warn(entry, "UnknownKeyShapeUndefined", "seed-contract.md §10 (gap)",
                    $"key '{key}' is outside the common envelope and kind '{kind.Kind}' has no "
                    + "shape in §10; the contract cannot say whether this rejects");
        }

        // `overrides` each require a note (seed-contract.md §9).
        if (entry.Node["overrides"] is JsonObject overrides)
            foreach (var (key, value) in overrides)
                if (value is not JsonObject o || o["note"] is null)
                    ctx.Error(entry, "OverrideWithoutNote", "seed-contract.md §9",
                        $"override '{key}' carries no note");

        if (entry.Node["enabled"] is JsonValue en && !en.TryGetValue<bool>(out _))
            ctx.Error(entry, "EnabledNotBoolean", "seed-contract.md §7.2", "enabled must be a boolean");
    }
}
