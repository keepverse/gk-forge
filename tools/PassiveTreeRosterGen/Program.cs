using System.Text.Json;
using FusionRpg.Tools.PassiveTreeRosterGen;

// Task A3 (tasks/passive-tree-todo.md) — the two roster mirrors `tree-plan` owes:
//   gk-data/packs/fusion/data/seed/statuses/roster.json     (21 statuses, from StatusCategoryRegistry)
//   gk-data/packs/fusion/data/seed/passive-tree/vocabulary.json (9 attach points / 18 kinds / 13 triggers, 11 authorable)
//
// Same --check/--emit contract as gk-forge/tools/ElementEnumGen: the mirror is GENERATED FROM the live C#
// registry (which is authoritative); --check compares an existing mirror against the live registry
// and fails on drift, so seedsmith's Python side never reads a stale count.
//
// Usage: dotnet run --project gk-forge/tools/PassiveTreeRosterGen -- [--status-check|--status-emit <path>|
//                                                              --atom-vocab-check|--atom-vocab-emit <path>]
//                                                             [seed root]
// Exit codes: 0 clean, 1 mismatch found, 2 could not start (EXIT_CANNOT_RUN).

var mode = "status-check";
string? emitPath = null;
var positional = new List<string>();

for (var i = 0; i < args.Length; i++)
{
    if (args[i] == "--status-check") { mode = "status-check"; continue; }
    if (args[i] == "--atom-vocab-check") { mode = "atom-vocab-check"; continue; }
    if (args[i] == "--status-emit" && i + 1 < args.Length) { mode = "status-emit"; emitPath = args[++i]; continue; }
    if (args[i] == "--atom-vocab-emit" && i + 1 < args.Length) { mode = "atom-vocab-emit"; emitPath = args[++i]; continue; }
    positional.Add(args[i]);
}

var seedRoot = positional.Count > 0 ? Path.GetFullPath(positional[0]) : FindUp("data", "seed");
if (seedRoot is null || !Directory.Exists(seedRoot))
{
    Console.Error.WriteLine("could not locate data/seed; pass the seed root explicitly");
    return 2;
}

if (mode == "status-emit")
{
    var rows = StatusRosterCheck.LiveRows();
    var json = StatusRosterCheck.GenerateJson(rows);
    Directory.CreateDirectory(Path.GetDirectoryName(emitPath!)!);
    File.WriteAllText(emitPath!, json);
    Console.WriteLine($"wrote {emitPath} ({rows.Count} status(es))");
    return 0;
}

if (mode == "atom-vocab-emit")
{
    var vocab = AtomVocabCheck.LiveVocab();
    var json = AtomVocabCheck.GenerateJson(vocab);
    Directory.CreateDirectory(Path.GetDirectoryName(emitPath!)!);
    File.WriteAllText(emitPath!, json);
    Console.WriteLine($"wrote {emitPath} ({vocab.AttachPoints.Count} attach point(s), " +
                       $"{vocab.Kinds.Count} kind(s), {vocab.Triggers.Count} trigger(s))");
    return 0;
}

if (mode == "status-check")
{
    var statusFile = Path.Combine(seedRoot, "statuses", "roster.json");
    if (!File.Exists(statusFile))
    {
        Console.Error.WriteLine($"EXIT_CANNOT_RUN: missing {statusFile}");
        return 2;
    }

    List<StatusRosterRow> mirrorRows;
    try
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(statusFile));
        mirrorRows = doc.RootElement.GetProperty("entries").EnumerateArray()
            .Select(e => new StatusRosterRow(
                e.GetProperty("id").GetString()!,
                e.GetProperty("category").GetString()!,
                e.GetProperty("ordinal").GetInt32()))
            .ToList();
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"EXIT_CANNOT_RUN: {statusFile} did not parse — {ex.Message}");
        return 2;
    }

    var report = StatusRosterCheck.Run(mirrorRows);
    if (report.IsOk)
    {
        Console.WriteLine($"data/seed/statuses/roster.json agrees with StatusCategoryRegistry ({mirrorRows.Count} status(es)).");
        return 0;
    }
    Console.Error.WriteLine($"{report.Mismatches.Count} disagreement(s):");
    foreach (var m in report.Mismatches) Console.Error.WriteLine("  " + m);
    return 1;
}

if (mode == "atom-vocab-check")
{
    var vocabFile = Path.Combine(seedRoot, "passive-tree", "vocabulary.json");
    if (!File.Exists(vocabFile))
    {
        Console.Error.WriteLine($"EXIT_CANNOT_RUN: missing {vocabFile}");
        return 2;
    }

    AtomVocabMirror mirror;
    try
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(vocabFile));
        var attachPoints = doc.RootElement.GetProperty("attachPoints").EnumerateArray()
            .Select(e => e.GetString()!).ToList();
        var kinds = doc.RootElement.GetProperty("kinds").EnumerateArray()
            .Select(e => (e.GetProperty("id").GetString()!, e.GetProperty("attach").GetString()!)).ToList();
        var triggers = doc.RootElement.GetProperty("triggers").EnumerateArray()
            .Select(e => (e.GetProperty("id").GetString()!, e.GetProperty("authorable").GetBoolean())).ToList();
        mirror = new AtomVocabMirror(attachPoints, kinds, triggers);
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"EXIT_CANNOT_RUN: {vocabFile} did not parse — {ex.Message}");
        return 2;
    }

    var report = AtomVocabCheck.Run(mirror);
    if (report.IsOk)
    {
        // Generate from the live registry, not from the parsed mirror: semantic set parity alone
        // would accept a reordered mirror, and then re-emitting that same order would falsely bless
        // non-canonical generated bytes.
        var expectedJson = AtomVocabCheck.GenerateJson(AtomVocabCheck.LiveVocab());
        var actualJson = File.ReadAllText(vocabFile).Replace("\r\n", "\n", StringComparison.Ordinal);
        if (!string.Equals(actualJson, expectedJson, StringComparison.Ordinal))
        {
            Console.Error.WriteLine(
                $"{vocabFile} is semantically current but not byte-identical to the generator output — " +
                "run --atom-vocab-emit to restore the canonical mirror");
            return 1;
        }

        Console.WriteLine($"data/seed/passive-tree/vocabulary.json agrees with the live registries " +
                           $"({mirror.AttachPoints.Count} attach point(s), {mirror.Kinds.Count} kind(s), " +
                           $"{mirror.Triggers.Count} trigger(s)).");
        return 0;
    }
    Console.Error.WriteLine($"{report.Mismatches.Count} disagreement(s):");
    foreach (var m in report.Mismatches) Console.Error.WriteLine("  " + m);
    return 1;
}

Console.Error.WriteLine($"unknown mode '{mode}'");
return 2;

static string? FindUp(params string[] segments)
{
    var dir = new DirectoryInfo(Directory.GetCurrentDirectory());
    while (dir is not null)
    {
        var candidate = Path.Combine(new[] { dir.FullName }.Concat(segments).ToArray());
        if (Directory.Exists(candidate)) return candidate;
        dir = dir.Parent;
    }
    return null;
}
