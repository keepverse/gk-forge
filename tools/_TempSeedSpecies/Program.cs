using FusionRpg.Core.Creatures.Generation;
using FusionRpg.Core.Workspace;
using FusionRpg.Data;

// Temporary, throwaway tool (NOT committed): seed the real dist DB's species roster directly from
// the committed gk-data/packs/fusion/data/generated/creatures corpus, the SAME way RpgApiFactory.SeedSpeciesRoster
// (gk-core/tests/FusionRpg.E2E.Tests) does for E2E -- bypassing CreatureSpeciesImport's own re-derivation
// staleness gate (which needs a full CreatureSpeciesGen regen this session has no reason to run).
// Mirrors the exact tuning-configure prefix of FusionRpg.Server/Program.cs (everything RpgStore's
// static ctor + ImportSpecies could touch) so RpgStore.Init() does not throw on an unconfigured hub.
// Usage: dotnet run --project gk-forge/tools/_TempSeedSpecies -- dbDir generatedCreaturesDir repoRoot

if (args.Length < 3)
{
    Console.Error.WriteLine("usage: dbDir generatedCreaturesDir repoRoot");
    return 2;
}

var dbDir = args[0];
var dir = args[1];
var repoRoot = args[2];
var tuningDir = Path.Combine(KeepverseRoots.Core(), "data", "tuning");

FusionRpg.Core.Creatures.Contracts.ContractPolicy.Configure(
    FusionRpg.Core.Creatures.Contracts.ContractTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "contracts.v1.json"))));
FusionRpg.Core.World.Loam.LoamPolicy.Configure(
    FusionRpg.Core.World.Loam.LoamTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "loam.v5.json"))));
var worldTuning = FusionRpg.Core.World.WorldTuningLoader.Parse(
    File.ReadAllText(Path.Combine(tuningDir, "world.v6.json")));
FusionRpg.Core.World.WorldTuningHub.Configure(worldTuning);
FusionRpg.Core.World.Loam.WorldSpawnTuningHub.Configure(
    FusionRpg.Core.World.Loam.WorldSpawnTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "world-spawn.v1.json"))));
FusionRpg.Core.World.Growth.RecruitPolicy.Configure(worldTuning.Growth);
FusionRpg.Core.Creatures.SoulEarnPolicy.Configure(
    FusionRpg.Core.Creatures.SoulEarnTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "souls.v1.json"))));
FusionRpg.Core.Creatures.Patron.PatronPolicy.Configure(
    FusionRpg.Core.Creatures.Patron.PatronTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "patron.v1.json"))));
FusionRpg.Core.Match.LawnDeployEventsTuningHub.Configure(
    FusionRpg.Core.Match.LawnDeployEventsTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "lawn-deploy-events.v1.json"))));
FusionRpg.Core.Match.Ai.ZombossDeployTuningHub.Configure(
    FusionRpg.Core.Match.Ai.ZombossDeployTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "zomboss-deploy-ai.v1.json"))));
FusionRpg.Core.Combat.Shield.ShieldPolicy.Configure(
    FusionRpg.Core.Combat.Shield.ShieldTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "shield.v1.json"))));
FusionRpg.Core.Combat.CombatPolicy.Configure(
    FusionRpg.Core.Combat.CombatTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "combat.v1.json"))));
FusionRpg.Core.Creatures.Fusion.StarPolicy.Configure(
    FusionRpg.Core.Creatures.Fusion.FusionTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "fusion.v2.json"))));
FusionRpg.Core.Status.StatusPolicy.Configure(
    FusionRpg.Core.Status.StatusTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "status.v1.json"))));
FusionRpg.Core.Stats.Derived.DerivedStatPolicy.Configure(
    FusionRpg.Core.Stats.Derived.DerivedStatTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "derived-stats.v2.json"))));
FusionRpg.Core.ActorSurface.ActorSurfaceCatalogHub.ConfigureAll(
    FusionRpg.Core.ActorSurface.AptitudeSurfaceCatalogLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "aptitude-catalog.v1.json"))),
    FusionRpg.Core.ActorSurface.DerivedStatSurfaceCatalogLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "derived-stat-catalog.v3.json"))),
    FusionRpg.Core.ActorSurface.StatusSurfaceCatalogLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "status-catalog.v1.json"))),
    FusionRpg.Core.ActorSurface.ResourceSurfaceCatalogLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "resource-catalog.v1.json"))),
    FusionRpg.Core.ActorSurface.ElementSurfaceCatalogLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "element-catalog.v1.json"))),
    FusionRpg.Core.ActorSurface.ActorSheetSurfaceCatalogLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "actor-sheet.v1.json"))));
FusionRpg.Core.Overlay.OverlayTuningHub.Configure(
    FusionRpg.Core.Overlay.OverlayTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "overlay.v1.json"))));
FusionRpg.Core.Stats.Derived.StatsTuningHub.Configure(
    FusionRpg.Core.Stats.Derived.StatsTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "stats.v1.json"))));
FusionRpg.Core.Expeditions.ExpeditionTuningHub.Configure(
    FusionRpg.Core.Expeditions.ExpeditionTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "expeditions.v2.json"))));
var dungeonRegistryDir = Path.Combine(KeepverseRoots.Content(), "data", "seed", "dungeon", "_registry");
var dungeonRegistries = FusionRpg.Core.Dungeon.Registry.DungeonRegistryLoader.LoadAll(dungeonRegistryDir);
FusionRpg.Core.Dungeon.Tuning.DungeonTuningHub.Configure(
    FusionRpg.Core.Dungeon.Tuning.DungeonTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "dungeon.v3.json")), dungeonRegistries));
FusionRpg.Core.Dungeon.Tuning.EncounterTuningHub.Configure(
    FusionRpg.Core.Dungeon.Tuning.EncounterTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "encounter.v1.json")), dungeonRegistries,
        // tier-propagation-contract T-2: the threat ladder is read from its own tuning file, never restated.
        FusionRpg.Core.Creatures.Generation.CreatureThreatTuningLoader.Parse(
            File.ReadAllText(Path.Combine(tuningDir, "creature-threat.v1.json"))).RungIds));
FusionRpg.Core.Dungeon.Registry.DungeonRegistryHub.Configure(dungeonRegistries);
{
    var layoutRows = FusionRpg.Core.Delve.Roll.LayoutSeedFile.LoadAll(
        Path.Combine(KeepverseRoots.Content(), "data", "seed", "dungeon", "layouts"));
    var layoutLoad = FusionRpg.Core.Delve.Roll.LayoutTemplateCatalog.Load(
        layoutRows, FusionRpg.Core.Dungeon.Registry.BandCatalog.All, FusionRpg.Core.Dungeon.Registry.RaidModeCatalog.All);
    if (layoutLoad.Rejections.Count > 0)
        throw new InvalidOperationException(
            "data/seed/dungeon/layouts/*.json failed to load: " + string.Join("; ", layoutLoad.Rejections));
    FusionRpg.Core.Delve.Roll.LayoutTemplateHub.Configure(layoutLoad.Catalog);
}
FusionRpg.Core.SimDefaults.Configure(
    FusionRpg.Core.SimTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "sim.v1.json"))));
FusionRpg.Core.Progression.ProgressionTuningHub.Configure(
    FusionRpg.Core.Progression.ProgressionTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "progression.v3.json"))));
FusionRpg.Core.PassiveTree.State.PassiveTreeTuningHub.Configure(
    FusionRpg.Core.PassiveTree.State.PassiveTreeTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "passive-tree.v1.json"))));
FusionRpg.Core.Progression.SpeciesProgressionTuningHub.Configure(
    FusionRpg.Core.Progression.SpeciesProgressionTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "species-progression.v1.json"))));
FusionRpg.Core.Creatures.Generation.SpeciesBuildTuningHub.Configure(
    FusionRpg.Core.Creatures.Generation.SpeciesBuildTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "species-build.v6.json"))));
FusionRpg.Core.Creatures.Generation.SpeciesBuildPlanCatalog.Configure(
    FusionRpg.Core.Creatures.Generation.SpeciesBuildPlanReader.Parse(
        File.ReadAllText(Path.Combine(
            Directory.GetParent(tuningDir)!.FullName, "generated", "creatures", "_species-build-plan.json"))));
FusionRpg.Core.Battle.Ai.ZombossAdaptiveTuningHub.Configure(
    FusionRpg.Core.Battle.Ai.ZombossAdaptiveTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "zomboss-adaptive.v1.json"))));
FusionRpg.Core.Battle.BattleTuningHub.Configure(
    FusionRpg.Core.Battle.BattleTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "battle.v5.json"))));
FusionRpg.Core.Battle.BattleRuleset.ConfigureResources(
    FusionRpg.Core.Battle.BattleResourceTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "battle-resources.v1.json"))));
FusionRpg.Core.Battle.Board.SiegeTuningPolicy.Configure(
    FusionRpg.Core.Battle.Board.SiegeTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "siege.v1.json"))));
FusionRpg.Core.Battle.Board.BattleBoardTuningPolicy.Configure(
    FusionRpg.Core.Battle.Board.BattleBoardTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "battle-board.v1.json"))));
FusionRpg.Core.World.StructureCatalog.Configure(
    FusionRpg.Core.World.StructureSeed.StructureCorpus.Load(
        Path.Combine(KeepverseRoots.Content(), "data", "seed", "structures")));
FusionRpg.Core.Creatures.SummoningTuningHub.Configure(
    FusionRpg.Core.Creatures.SummoningTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "summoning.v1.json"))));
FusionRpg.Core.Aura.AuraTuningHub.Configure(
    FusionRpg.Core.Aura.AuraTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "aura.v1.json"))));
FusionRpg.Core.World.Ai.WorldAiPolicy.Configure(
    FusionRpg.Core.World.Ai.WorldAiTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "ai.v3.json"))));
FusionRpg.Data.Policies.SealedCompactionPolicy.Configure(
    FusionRpg.Data.Policies.DataTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "data.v1.json"))));
FusionRpg.Core.Power.PowerTuningHub.Configure(
    FusionRpg.Core.Power.PowerTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "power-scale.v2.json"))));
FusionRpg.Core.Stats.Aptitudes.AptitudeTuningHub.Configure(
    FusionRpg.Core.Stats.Aptitudes.AptitudeTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "aptitudes.v10.json"))));
FusionRpg.Core.Stats.Aptitudes.AptitudePresetTuningHub.Configure(
    FusionRpg.Core.Stats.Aptitudes.AptitudePresetTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "aptitude-presets.v2.json"))));
FusionRpg.Core.Actions.Rungs.RungPolicy.Configure(
    FusionRpg.Core.Actions.Rungs.RungTableLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "action-rungs.v1.json"))));
FusionRpg.Core.Actions.ActionTimingPolicy.Configure(
    FusionRpg.Core.Actions.ActionTimingTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "action-timing.v1.json"))));
FusionRpg.Core.Battle.Timeline.ReactionLanePolicy.Configure(
    FusionRpg.Core.Battle.Timeline.ReactionLaneTuningLoader.Parse(
        File.ReadAllText(Path.Combine(tuningDir, "reaction-lane.v3.json"))));

var files = Directory.EnumerateFiles(dir, "*.json")
    .Where(p => !Path.GetFileName(p).StartsWith('_'));
var species = files.Select(ConcreteSpeciesSeedReader.ParseFile).ToList();
if (species.Count == 0)
{
    Console.Error.WriteLine("no real committed species found under " + dir);
    return 2;
}

var store = new RpgStore(dbDir);
store.Init();
var outcome = store.ImportSpecies(species);
if (!outcome.IsOk)
{
    Console.Error.WriteLine("SeedSpeciesRoster failed: " + string.Join("; ", outcome.Errors));
    return 1;
}

Console.WriteLine("Imported " + species.Count + " species into " + dbDir);
return 0;
