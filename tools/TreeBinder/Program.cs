using FusionRpg.Core.Effects.Atoms;
using FusionRpg.Core.PassiveTree.Binding;
using FusionRpg.Core.PassiveTree.State;
using FusionRpg.Core.Power;
using FusionRpg.Tools.TreeBinder;
using FusionRpg.Core.Workspace;

// gk-forge/tools/TreeBinder (task D2, spec-tree-binder.md §Commands):
//   dotnet run --project gk-forge/tools/TreeBinder -- --seed gk-data/packs/fusion/data/seed/passive-tree --out gk-data/packs/fusion/data/generated/passive-tree
//   dotnet run --project gk-forge/tools/TreeBinder -- --check
//   dotnet run --project gk-forge/tools/TreeBinder -- --explain <nodeId>
//
// A thin wrapper: every load-bearing rule lives in gk-core/src/FusionRpg.Core/PassiveTree/Binding/
// (TreeBinderRun, TreeBinderExplain) or this project's own PlanReader/ReportWriter, both unit-tested
// directly in gk-forge/tests/FusionRpg.TreeBinder.Tests. This file's only job is argument parsing, real-content
// wiring, and printing the report.
//
// 2026-09-06: `tree-language` (H9) now ships real content for 12 trees at
// `gk-data/packs/fusion/data/seed/passive-tree/nodes/<treeId>.json` -- this CLI reads it via `PlanReader
// .ReadPlanNodesWithSeed` (`--seed`'s own `nodes/` subfolder, matched by tree id), the fix for the
// gap the note below used to describe. A tree tree-language has not touched at all still refuses
// every node, correctly -- and a PARTIALLY generated tree (most real trees today) binds every
// already-accepted node and refuses only the not-yet-generated ones, each with its own unspent
// budget reported, exactly as a genuine content gap should read.
//
// Exit codes: 0 clean/Pass, 1 Fail/stale/mismatch, 2 could not start.

var mode = "run";
string? explainNodeId = null;
string? seedRoot = null;
string? outRoot = null;

for (var i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--check": mode = "check"; break;
        case "--explain" when i + 1 < args.Length: mode = "explain"; explainNodeId = args[++i]; break;
        case "--seed" when i + 1 < args.Length: seedRoot = args[++i]; break;
        case "--out" when i + 1 < args.Length: outRoot = args[++i]; break;
    }
}

    // One resolver, not a private copy. This tool needs TWO roots and used to assume they were one
    // directory: gk-core/data/tuning is in gk-core, while gk-data/packs/fusion/data/seed and gk-data/packs/fusion/data/generated are in a gk-data pack,
    // and both are siblings of gk-forge after the split. A CONTRIBUTING.md walk therefore lands on the
    // workspace root and finds neither, which is why TreeBinder exited 2 on a gk-core/data/tuning path that
    // exists one level down in gk-core. Roots() answers [content, core] in a workspace and a single
    // directory in a legacy checkout, so one expression serves both layouts; the walk is kept below so
    // a legacy tree still works unchanged.
    // NAMED accessors, never Roots() indexed. Roots() is "the roots a relative path should be tried
    // against, in order, deduplicated", and it says so deliberately: no convention is encoded there, so
    // trying content then core is correct FOR A PROBE. It adds authored content (gk-content) first, then
    // the corpus pack, then gk-core — so `detected[0]` was gk-content and `detected[1]` was
    // gk-data/packs/fusion. This tool therefore read gk-core/data/tuning from inside the private pack and
    // exited 2 on 202 files that exist. A data-flow search over all nine repositories found this to be the
    // ONLY positional claim on Roots(); the other thirteen call sites use roots[0] as try-order, which is
    // what the accessor is for.
    //
    // Both accessors honour KEEPVERSE_CONTENT_ROOT / KEEPVERSE_CORE_ROOT and both return the legacy root in
    // a pre-split checkout, so the CONTRIBUTING.md walk this replaces was redundant as well as wrong.
    string contentRoot;
    string coreRoot;
    try
    {
        contentRoot = KeepverseRoots.Content(Directory.GetCurrentDirectory());
        coreRoot = KeepverseRoots.Core(Directory.GetCurrentDirectory());
    }
    catch (DirectoryNotFoundException ex)
    {
        Console.Error.WriteLine($"could not locate the workspace roots: {ex.Message}");
        return 2;
    }

    seedRoot ??= Path.Combine(contentRoot, "data", "seed", "passive-tree");
    outRoot ??= Path.Combine(contentRoot, "data", "generated", "passive-tree");

PowerTuning powerTuning;
PassiveTreeTuning treeTuning;
IReadOnlyDictionary<string, AffixRow> affixesById;
IReadOnlyDictionary<string, AtomRow> atomsById;
try
{
    powerTuning = PowerTuningLoader.Parse(File.ReadAllText(Path.Combine(coreRoot, "data", "tuning", "power-scale.v2.json")));
    treeTuning = PassiveTreeTuningLoader.Parse(File.ReadAllText(Path.Combine(coreRoot, "data", "tuning", "passive-tree.v1.json")));
    (affixesById, atomsById) = LoadSeedContent(contentRoot);
}
catch (Exception ex)
{
    Console.Error.WriteLine($"EXIT_CANNOT_RUN: {ex.Message}");
    return 2;
}

var planDir = Path.Combine(seedRoot, "plan");
var planFiles = Directory.Exists(planDir) ? Directory.GetFiles(planDir, "*.v*.json") : Array.Empty<string>();

if (planFiles.Length == 0)
{
    Console.Error.WriteLine($"EXIT_CANNOT_RUN: no plan files under {planDir}");
    return 2;
}

var nodesDir = Path.Combine(seedRoot, "nodes");
// seedsmith-content-standard, passive-tree-identity-content (2026-09-08): a SEPARATE per-tree
// file from nodes/plan, matching this program's own established per-stage-per-file convention.
var identityDir = Path.Combine(seedRoot, "identity");
var allNodesByTree = new Dictionary<string, List<BindInputNode>>(StringComparer.Ordinal);
var allMetaByTree = new Dictionary<string, TreeCatalogMeta>(StringComparer.Ordinal);
foreach (var planFile in planFiles)
{
    var treeId = PlanReader.TreeIdFromPlanFileName(Path.GetFileNameWithoutExtension(planFile));
    var seedFile = Path.Combine(nodesDir, $"{treeId}.json");
    var seedJson = File.Exists(seedFile) ? File.ReadAllText(seedFile) : null;
    var planJson = File.ReadAllText(planFile);
    allNodesByTree[treeId] = PlanReader.ReadPlanNodesWithSeed(planJson, seedJson, treeTuning);

    var identityFile = Path.Combine(identityDir, $"{treeId}.json");
    var identityJson = File.Exists(identityFile) ? File.ReadAllText(identityFile) : null;
    var (treeName, treeDescription) = PlanReader.ReadTreeIdentity(identityJson);
    allMetaByTree[treeId] = PlanReader.ReadTreeMeta(planJson) with { Name = treeName, Description = treeDescription };
}

if (mode == "explain")
{
    foreach (var (_, nodes) in allNodesByTree)
    {
        var node = nodes.FirstOrDefault(n => n.NodeId == explainNodeId);
        if (node is null) continue;
        Console.WriteLine(TreeBinderExplain.Explain(node, affixesById, atomsById, powerTuning));
        return 0;
    }
    Console.Error.WriteLine($"node '{explainNodeId}' was not found in any plan under {seedRoot}");
    return 2;
}

var anyFail = false;
var anyStale = false;
foreach (var (treeId, nodes) in allNodesByTree)
{
    var report = TreeBinderRun.BindTree(nodes, affixesById, atomsById, powerTuning);
    var json = ReportWriter.Serialize(treeId, allMetaByTree[treeId], nodes, report);

    Console.WriteLine($"tree-binder: {treeId}  verdict={report.Verdict}  bound={report.Bound.Count} " +
                       $"refused={report.Refused.Count} unspentBudgetShareMilli={report.TotalUnspentBudgetShareMilli}");
    foreach (var r in report.Refused)
        Console.WriteLine($"  REFUSED  {r.NodeId}  unspent={r.UnspentBudgetShareMilli}‰" +
                           $"{(r.DeliberateHole ? " (deliberate hole)" : "")}  {r.Reason}");

    if (report.Verdict == RunVerdict.Fail) anyFail = true;

    var outPath = Path.Combine(outRoot, $"{treeId}.json");
    // Deterministic LF endings: System.Text.Json indents with Environment.NewLine (CRLF on
    // Windows), but committed seed files are LF — the same byte-compare class as the dungeon
    // loot CRLF failure. Normalize once, here, so --check compares what --out writes.
    json = json.Replace("\r\n", "\n");
    if (mode == "check")
    {
        if (!File.Exists(outPath) || File.ReadAllText(outPath) != json)
        {
            Console.Error.WriteLine($"STALE  {outPath} does not match a fresh regeneration from {seedRoot}");
            anyStale = true;
        }
        continue;
    }

    Directory.CreateDirectory(outRoot);
    File.WriteAllText(outPath, json);
    Console.WriteLine($"wrote {outPath}");
}

if (mode == "check") return anyStale ? 1 : 0;
return anyFail ? 1 : 0;

static (IReadOnlyDictionary<string, AffixRow>, IReadOnlyDictionary<string, AtomRow>) LoadSeedContent(string contentRoot)
{
    // 2026-09-06 real-run finding: `gk-data/packs/fusion/data/seed/effects/affixes/all.json` is a DIFFERENT subsystem's
    // vocabulary entirely (the Delve "elite affix" system -- 10 entries, ids like
    // `affix.authored.affix-draw-000`; see `gk-core/src/FusionRpg.Core/Delve/Encounter/EliteAffix.cs`), never
    // the passive-tree affix-family system tree-language actually draws its `affixIds[]` from
    // (confirmed: it contains zero of the ~109 real family ids, e.g. `atom.might`). The real,
    // GENERATED atom rows for those families live under `gk-data/packs/fusion/data/seed/atoms/generated/` (E43's
    // `FamilyExpandGen`, one `family-expand.<stem>.json` per source family file) -- globbed here
    // instead of the wrong fixed path.
    var generatedDir = Path.Combine(contentRoot, "data", "seed", "atoms", "generated");
    var files = new[]
    {
        Path.Combine(contentRoot, "data", "seed", "atoms", "fx-board.json"),
        Path.Combine(contentRoot, "data", "seed", "atoms", "fx-core.json"),
        Path.Combine(contentRoot, "data", "seed", "atoms", "fx-status.json"),
    }.Concat(Directory.Exists(generatedDir)
        ? Directory.GetFiles(generatedDir, "family-expand.*.json")
        : Array.Empty<string>())
     .Where(File.Exists).Select(f => (f, File.ReadAllText(f))).ToArray();

    var collected = AtomSeedFile.Collect(files);
    if (!collected.IsOk)
        throw new InvalidOperationException("seed content did not parse: " + string.Join("; ", collected.Errors));

    var atomsById = collected.Content.Atoms.ToDictionary(a => a.AtomId);
    var explicitAffixesById = collected.Content.Affixes.ToDictionary(a => a.AffixId);

    // 2026-09-06, owner-decided design (spec-tree-binder.md's own filed note): no `kind: "affix"`
    // wrapper at the bare family id exists anywhere in the committed seed data for the real
    // ~109-family vocabulary, so one is synthesized -- see `AffixFamilySynthesis`'s own doc comment
    // for the full reasoning (one canonical shape per family, the numeric band is irrelevant here).
    var affixesById = AffixFamilySynthesis.WithSynthesizedFamilyAffixes(explicitAffixesById, atomsById);

    return (affixesById, atomsById);
}
