using FusionRpg.Tools.ItemSeedValidator.Registries;
using FusionRpg.Tools.ItemSeedValidator;

// The deterministic gate on the 125-agent item seed build. Reads files, resolves them against the
// six wave-0 registries, and reports. It opens no database and issues no SQL — this tool validates
// content, and `scripts/guard-dal.ps1` does not scan tools/.
//
// Usage: dotnet run --project gk-forge/tools/ItemSeedValidator -- [seed root] [--warnings-as-errors]
//        [--list-partitions] [--list-partitions-json] [--collision-groups] [--normalize-names] [--combo-budget-dump] [--check-names] [--findings-json [--codes=A,B,C]]
//        default seed root: gk-data/packs/fusion/data/seed/items, found by walking up from the working directory.

var warningsAsErrors = args.Contains("--warnings-as-errors", StringComparer.Ordinal);
// Briefs are generated from the allocation, and every partition-id defect this build has hit came
// from a brief transcribing it by hand instead. --list-partitions makes the authority readable.
var listPartitions = args.Contains("--list-partitions", StringComparer.Ordinal);
// The SAME partition -> kind allocation as `--list-partitions`, structured rather than scraped
// from the human table -- the exact reason `--collision-groups` exists below. Added 2026-09-21
// (`seed-corpus` ISG7-F2): `seedsmith`'s committed `_registry_snapshot/allocated_partitions.json`
// is DERIVED from this allocation, and its own `_meta.regenerate` names only the human `--list-
// partitions` command, so the JSON had been assembled by hand and still carried `socket-words`
// after that kind was retired.
var listPartitionsJson = args.Contains("--list-partitions-json", StringComparer.Ordinal);
// The name-collision repair (seedsmith `items repair-names`) needs the SAME grouping the validator
// enforces. Reimplementing the collision normalizer in Python would fork it, so this mode prints the
// authoritative groups as JSON for that tool to consume.
var collisionGroups = args.Contains("--collision-groups", StringComparer.Ordinal);
// strain-splice-host SSH6.4 (spec-combo-budget §3): the ONE C# pricing computation, dumped as JSON for
// the readable Python report (`python -m seedsmith items combo-budget --report`) to render. The report
// must never re-implement `ActorPowerCache.Compose`, so it reads this instead.
var comboBudgetDump = args.Contains("--combo-budget-dump", StringComparer.Ordinal);
// strain-splice-host SSH5.13-P1: a GENERATOR's own pre-write check on a candidate display name. It runs
// the validator's own grammar (never a Python mirror of the patterns), reading the names as a JSON array
// on stdin and printing each name's defects.
var checkNames = args.Contains("--check-names", StringComparer.Ordinal);

// A repair's REPLACEMENT name needs the same authority the collision gate uses. `name_repair.
// validate_answers` compared casefolded full strings only, so it accepted "Ferocity Bulwark" for a
// combination whose keeper idea was the shipped set "Bulwark of Ferocity" (2026-09-21) and minted a
// fresh collision. This mode prints the authoritative normalized key for every name on stdin, so a
// repair can refuse a candidate before it writes instead of forking the normalizer in Python.
var normalizeNames = args.Contains("--normalize-names", StringComparer.Ordinal);
// A repair pipeline needs the SAME findings the CI gate itself produces, structured rather than
// scraped from the human-readable report -- the same reason --collision-groups exists. Optional
// --codes=A,B,C narrows to the codes a given repair batch cares about; omitted prints every finding.
var findingsJson = args.Contains("--findings-json", StringComparer.Ordinal);
var codesArg = args.FirstOrDefault(a => a.StartsWith("--codes=", StringComparison.Ordinal));
var positional = args.Where(a => !a.StartsWith("--", StringComparison.Ordinal)).ToList();

var seedRoot = positional.Count > 0 ? Path.GetFullPath(positional[0]) : FindDefaultSeedRoot();
if (seedRoot is null)
{
    Console.Error.WriteLine("could not locate data/seed/items; pass the seed root explicitly");
    return 2;
}

if (!Directory.Exists(Path.Combine(seedRoot, Validator.RegistryDirName)))
{
    Console.Error.WriteLine($"no {Validator.RegistryDirName}/ under {seedRoot}; "
                            + "the validator cannot run without the wave-0 registries");
    return 2;
}

if (comboBudgetDump) return FusionRpg.Tools.ItemSeedValidator.ComboBudgetDump.Run(seedRoot);

if (listPartitions)
{
    var registries = RegistrySet.Load(Path.Combine(seedRoot, Validator.RegistryDirName));
    var allocation = NamespaceAllocation.Build(registries);
    Console.WriteLine($"{"partition",-42} {"stage",-6} {"kind",-22} idPrefix");
    foreach (var a in allocation.All.OrderBy(a => a.Stage).ThenBy(a => a.PartitionId, StringComparer.Ordinal))
        Console.WriteLine($"{a.PartitionId,-42} {a.Stage,-6} {a.Kind,-22} {a.Prefix}{ShapeHint(a.Shape)}");
    foreach (var problem in allocation.Problems) Console.Error.WriteLine($"! {problem}");
    return 0;

    static string ShapeHint(SequenceShape shape) => shape switch
    {
        SequenceShape.ThreeDigit => "{seq:03}",
        SequenceShape.Fixed => "",
        SequenceShape.Derived => "{gridCellTokens}",
        _ => "{seq}",
    };
}

if (checkNames)
{
    var registries = RegistrySet.Load(Path.Combine(seedRoot, Validator.RegistryDirName));
    var normalizer = new FusionRpg.Tools.ItemSeedValidator.Naming.NameNormalizer(registries);
    var names = System.Text.Json.JsonSerializer.Deserialize<List<string>>(Console.In.ReadToEnd())
                ?? new List<string>();
    var results = names
        .Where(name => name is not null)
        .Select(name => new
        {
            name,
            defects = FusionRpg.Tools.ItemSeedValidator.Checks.NamingCheck.CandidateNameDefects(
                name, normalizer, registries.SurfaceForms.ContainsKey(name.ToLowerInvariant())),
        })
        .ToList();
    Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(
        new { names = results },
        new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
    return 0;
}

if (listPartitionsJson)
{
    var registries = RegistrySet.Load(Path.Combine(seedRoot, Validator.RegistryDirName));
    var allocation = NamespaceAllocation.Build(registries);
    var partitionKind = new SortedDictionary<string, string>(StringComparer.Ordinal);
    foreach (var a in allocation.All) partitionKind[a.PartitionId] = a.Kind;
    Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(
        new { partitionKind },
        new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
    foreach (var problem in allocation.Problems) Console.Error.WriteLine($"! {problem}");
    return 0;
}

if (collisionGroups)
{
    var registries = RegistrySet.Load(Path.Combine(seedRoot, Validator.RegistryDirName));
    var normalizer = new FusionRpg.Tools.ItemSeedValidator.Naming.NameNormalizer(registries);
    var files = FusionRpg.Tools.ItemSeedValidator.Validator.Discover(seedRoot);

    // Group every player-facing name by the validator's own normalized key. A group of 2+ is one
    // collision; the winner is the lexically first id, and every other row must be renamed.
    var groups = new Dictionary<string, List<object>>(StringComparer.Ordinal);
    // nameKey collisions are a SEPARATE axis: the six `set.item` placeholder rows have DIFFERENT
    // Chinese names (so no name collision) yet share one key, which the name-based grouping cannot
    // see. Emitting them makes that defect reachable by the same repair.
    var byNameKey = new Dictionary<string, List<object>>(StringComparer.Ordinal);
    foreach (var file in files)
    {
        if (file.Root is null) continue;
        // An exemplar is a PATTERN, not corpus content, and the validator exempts it from the
        // global-uniqueness rules (NamingCheck.ExemptFromGlobalUniqueness). Including it here would
        // make the repair rename a real row to avoid colliding with a demonstration that never ships.
        if (file.IsExemplar) continue;
        if (file.Kind is "display-template" or "curve" or "recipe") continue; // no player-facing name
        foreach (var entry in file.Entries)
        {
            var name = entry.AsString("name");
            if (string.IsNullOrWhiteSpace(name)) continue;
            var descriptor = new
            {
                id = entry.Id, name, kind = file.Kind, file = file.RelativePath,
                nameKey = entry.NameKey, partition = file.Directory,
            };
            var key = normalizer.Normalize(name).Key;
            if (key.Length > 0)
            {
                if (!groups.TryGetValue(key, out var list))
                    groups[key] = list = new List<object>();
                list.Add(descriptor);
            }
            var nameKey = entry.NameKey;
            if (!string.IsNullOrWhiteSpace(nameKey))
            {
                if (!byNameKey.TryGetValue(nameKey, out var keyList))
                    byNameKey[nameKey] = keyList = new List<object>();
                keyList.Add(descriptor);
            }
        }
    }

    var payload = groups
        .Where(g => g.Value.Count > 1)
        .OrderBy(g => g.Key, StringComparer.Ordinal)
        .Select(g => new
        {
            reason = "name",
            key = g.Key,
            members = g.Value.OrderBy(m => (string)m.GetType().GetProperty("id")!.GetValue(m)!,
                                             StringComparer.Ordinal).ToList(),
        })
        .Concat(byNameKey
            .Where(k => k.Value.Count > 1)
            .OrderBy(k => k.Key, StringComparer.Ordinal)
            .Select(k => new
            {
                reason = "nameKey",
                key = k.Key,
                members = k.Value.OrderBy(m => (string)m.GetType().GetProperty("id")!.GetValue(m)!,
                                                StringComparer.Ordinal).ToList(),
            }))
        .ToList();

    Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(
        new { collisionGroups = payload.Count, groups = payload },
        new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
    return 0;
}

if (normalizeNames)
{
    var registries = RegistrySet.Load(Path.Combine(seedRoot, Validator.RegistryDirName));
    var normalizer = new FusionRpg.Tools.ItemSeedValidator.Naming.NameNormalizer(registries);
    var names = System.Text.Json.JsonSerializer.Deserialize<List<string>>(Console.In.ReadToEnd())
                ?? new List<string>();
    var keys = new Dictionary<string, string>(StringComparer.Ordinal);
    foreach (var name in names)
    {
        if (name is null) continue;
        keys[name] = normalizer.Normalize(name).Key;
    }
    Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(
        new { keys },
        new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
    return 0;
}

ValidationResult result;
try
{
    result = Validator.Run(seedRoot);
}
catch (Exception ex) when (ex is FileNotFoundException or InvalidDataException or System.Text.Json.JsonException)
{
    Console.Error.WriteLine($"registry load failed: {ex.Message}");
    return 2;
}

if (findingsJson)
{
    var codes = codesArg is null
        ? null
        : codesArg["--codes=".Length..].Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
            .ToHashSet(StringComparer.Ordinal);

    var findings = result.Findings
        .Where(f => codes is null || codes.Contains(f.Code))
        .OrderBy(f => f.File, StringComparer.Ordinal).ThenBy(f => f.EntryId, StringComparer.Ordinal)
        .Select(f => new
        {
            severity = f.Severity.ToString(),
            code = f.Code,
            id = f.EntryId,
            file = f.File,
            partition = f.Partition,
            rule = f.Rule,
            message = f.Message,
        })
        .ToList();

    Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(
        new { count = findings.Count, findings },
        new System.Text.Json.JsonSerializerOptions { WriteIndented = true }));
    return 0;
}

Console.Write(Report.Render(result, seedRoot));

if (result.ScannedNothing) return 1;
if (result.ErrorCount > 0) return 1;
if (warningsAsErrors && result.WarningCount > 0) return 1;
return 0;

static string? FindDefaultSeedRoot()
{
    var dir = new DirectoryInfo(Directory.GetCurrentDirectory());
    while (dir is not null)
    {
        var candidate = Path.Combine(dir.FullName, "data", "seed", "items");
        if (Directory.Exists(candidate)) return candidate;
        dir = dir.Parent;
    }
    return null;
}
