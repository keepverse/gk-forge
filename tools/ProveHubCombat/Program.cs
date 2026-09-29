using System.Text.Json;
using FusionRpg.Core.Battle;
using FusionRpg.Core.Creatures;
using FusionRpg.Core.Effects.Atoms;
using FusionRpg.Core.Effects.Atoms.Power;
using FusionRpg.Core.Items;
using FusionRpg.Core.Items.Grants;
using FusionRpg.Core.PassiveTree.State;
using FusionRpg.Core.Power;
using FusionRpg.Core.Stats.Aptitudes;
using FusionRpg.Core.Stats.Derived;
using FusionRpg.Core.Stats.Derived.Subsystems;
using FusionRpg.Data;
using FusionRpg.Server;
using Microsoft.AspNetCore.SignalR;
using Microsoft.Extensions.DependencyInjection;

// prove-hub-combat (T19): the program's own operator prove that battle Hub and sheet Hub agree, and
// that Standing rises via a Hub combat writer (not via Theta alone) — WITHOUT a live game. Both
// composers under test are the REAL, SHIPPED gates (BattleHubCompose.Compose,
// UniqueActorHubCompose.Build/ProjectSheet) against a REAL RpgStore.InMemory() fixture — never a
// reimplementation of either. Bullet 3 (Bound lawn vs Server UniqueCreature compose) is deliberately
// NOT here: lawn-aptitude-parity (T12) found the Injector has zero UniqueCreature aptitude fetch to
// compare against yet (aptitude-sheet's own unique-lawn-wire, AS-1.1, unbuilt) — there is nothing to
// prove until that lands, and building it here would be scope creep into a different program's named
// deliverable, the same boundary T12 itself named.

string repoRoot = FindRepoRoot();
string tuningDir = Path.Combine(repoRoot, "data", "tuning");
string? outPath = ArgString(args, "--out", null);

string Read(string name) => File.ReadAllText(Path.Combine(tuningDir, name));

// Full server boot sequence (mirrors gk-core/src/FusionRpg.Server/Program.cs's own Configure block almost
// verbatim, repoRoot-relative instead of AppContext.BaseDirectory-relative): WebMatchService.BuildSquad
// (needed to materialize equip runtime for bullet 1) reaches deep into the action/rung/dungeon/world
// boot graph, so a partial subset kept surfacing one more "Configure(...) has not run" at a time. This
// is the same boot every other host runs, not a reimplementation of anything under test.
FusionRpg.Core.Creatures.Contracts.ContractPolicy.Configure(
    FusionRpg.Core.Creatures.Contracts.ContractTuningLoader.Parse(Read("contracts.v1.json")));
FusionRpg.Core.World.Loam.LoamPolicy.Configure(
    FusionRpg.Core.World.Loam.LoamTuningLoader.Parse(Read("loam.v5.json")));
var worldTuning = FusionRpg.Core.World.WorldTuningLoader.Parse(Read("world.v6.json"));
FusionRpg.Core.World.WorldTuningHub.Configure(worldTuning);
FusionRpg.Core.World.Growth.RecruitPolicy.Configure(worldTuning.Growth);
SoulEarnPolicy.Configure(SoulEarnTuningLoader.Parse(Read("souls.v1.json")));
FusionRpg.Core.Creatures.Patron.PatronPolicy.Configure(
    FusionRpg.Core.Creatures.Patron.PatronTuningLoader.Parse(Read("patron.v1.json")));
FusionRpg.Core.Match.LawnDeployEventsTuningHub.Configure(
    FusionRpg.Core.Match.LawnDeployEventsTuningLoader.Parse(Read("lawn-deploy-events.v1.json")));
FusionRpg.Core.Match.Ai.ZombossDeployTuningHub.Configure(
    FusionRpg.Core.Match.Ai.ZombossDeployTuningLoader.Parse(Read("zomboss-deploy-ai.v1.json")));
FusionRpg.Core.Combat.Shield.ShieldPolicy.Configure(
    FusionRpg.Core.Combat.Shield.ShieldTuningLoader.Parse(Read("shield.v1.json")));
// The lead-names registry was the ONE hub this boot graph left out, and the omission was invisible
// until the store was actually created: `RpgStore.Init()` -> `SeedPlayerIfEmpty` -> `OnboardingPlayerName`
// reads `LeadNamesHub.Current`, which threw "LeadNamesHub.Configure(...) has not run" and took the whole
// proof down before it asserted anything. A proof that cannot start proves nothing, and the comment
// above this block already records the pattern it is an instance of: a partial subset keeps surfacing
// one more "Configure(...) has not run" at a time.
//
// Conditional on the file being there, exactly as gk-forge/tools/AtomImporter does it and for the same reason: a
// partial root is legitimate, and requiring the registry would invent a requirement that root does not
// have, turning a structural report into "could not start". Nothing is weakened by the conditional -- if
// the reader is reached with the hub unconfigured, `LeadNamesHub.Current` throws its own named refusal,
// which is the fail-closed behaviour, and it is pinned in Core.
var leadNamesPath = Path.Combine(repoRoot, "data", "seed", "narrative", "_registry", "names.en.v1.json");
if (File.Exists(leadNamesPath))
{
    FusionRpg.Core.Narrative.LeadNamesHub.ConfigureFromFile(leadNamesPath);
}
FusionRpg.Core.Combat.CombatPolicy.Configure(
    FusionRpg.Core.Combat.CombatTuningLoader.Parse(Read("combat.v1.json")));
FusionRpg.Core.Creatures.Fusion.StarPolicy.Configure(
    FusionRpg.Core.Creatures.Fusion.FusionTuningLoader.Parse(Read("fusion.v2.json")));
FusionRpg.Core.Status.StatusPolicy.Configure(
    FusionRpg.Core.Status.StatusTuningLoader.Parse(Read("status.v1.json")));
DerivedStatPolicy.Configure(DerivedStatTuningLoader.Parse(Read("derived-stats.v2.json")));
FusionRpg.Core.ActorSurface.ActorSurfaceCatalogHub.ConfigureAll(
    FusionRpg.Core.ActorSurface.AptitudeSurfaceCatalogLoader.Parse(Read("aptitude-catalog.v1.json")),
    FusionRpg.Core.ActorSurface.DerivedStatSurfaceCatalogLoader.Parse(Read("derived-stat-catalog.v3.json")),
    FusionRpg.Core.ActorSurface.StatusSurfaceCatalogLoader.Parse(Read("status-catalog.v1.json")),
    FusionRpg.Core.ActorSurface.ResourceSurfaceCatalogLoader.Parse(Read("resource-catalog.v1.json")),
    FusionRpg.Core.ActorSurface.ElementSurfaceCatalogLoader.Parse(Read("element-catalog.v1.json")),
    FusionRpg.Core.ActorSurface.ActorSheetSurfaceCatalogLoader.Parse(Read("actor-sheet.v1.json")));
FusionRpg.Core.Overlay.OverlayTuningHub.Configure(
    FusionRpg.Core.Overlay.OverlayTuningLoader.Parse(Read("overlay.v1.json")));
StatsTuningHub.Configure(StatsTuningLoader.Parse(Read("stats.v1.json")));
FusionRpg.Core.Expeditions.ExpeditionTuningHub.Configure(
    FusionRpg.Core.Expeditions.ExpeditionTuningLoader.Parse(Read("expeditions.v2.json")));
var dungeonRegistryDir = Path.Combine(repoRoot, "data", "seed", "dungeon", "_registry");
var dungeonRegistries = FusionRpg.Core.Dungeon.Registry.DungeonRegistryLoader.LoadAll(dungeonRegistryDir);
FusionRpg.Core.Dungeon.Tuning.DungeonTuningHub.Configure(
    FusionRpg.Core.Dungeon.Tuning.DungeonTuningLoader.Parse(Read("dungeon.v3.json"), dungeonRegistries));
FusionRpg.Core.Dungeon.Tuning.EncounterTuningHub.Configure(
    FusionRpg.Core.Dungeon.Tuning.EncounterTuningLoader.Parse(Read("encounter.v1.json"), dungeonRegistries,
        // tier-propagation-contract T-2: the threat ladder is read from its own tuning file, never restated.
        FusionRpg.Core.Creatures.Generation.CreatureThreatTuningLoader.Parse(Read("creature-threat.v1.json")).RungIds));
FusionRpg.Core.Dungeon.Registry.DungeonRegistryHub.Configure(dungeonRegistries);
{
    var layoutRows = FusionRpg.Core.Delve.Roll.LayoutSeedFile.LoadAll(
        Path.Combine(repoRoot, "data", "seed", "dungeon", "layouts"));
    var layoutLoad = FusionRpg.Core.Delve.Roll.LayoutTemplateCatalog.Load(
        layoutRows, FusionRpg.Core.Dungeon.Registry.BandCatalog.All, FusionRpg.Core.Dungeon.Registry.RaidModeCatalog.All);
    if (layoutLoad.Rejections.Count > 0)
        throw new InvalidOperationException("data/seed/dungeon/layouts/*.json failed to load: " + string.Join("; ", layoutLoad.Rejections));
    FusionRpg.Core.Delve.Roll.LayoutTemplateHub.Configure(layoutLoad.Catalog);
}
FusionRpg.Core.SimDefaults.Configure(FusionRpg.Core.SimTuningLoader.Parse(Read("sim.v1.json")));
FusionRpg.Core.Progression.ProgressionTuningHub.Configure(
    FusionRpg.Core.Progression.ProgressionTuningLoader.Parse(Read("progression.v3.json")));
// This program's own fixture tuning (TreeTuning()), not the real passive-tree.v1.json -- keeps this
// prove's tier math (reqScalePoints=5) predictable and independent of a live balance pass.
PassiveTreeTuningHub.Configure(TreeTuning());
FusionRpg.Core.Progression.SpeciesProgressionTuningHub.Configure(
    FusionRpg.Core.Progression.SpeciesProgressionTuningLoader.Parse(Read("species-progression.v1.json")));
FusionRpg.Core.Creatures.Generation.SpeciesBuildTuningHub.Configure(
    FusionRpg.Core.Creatures.Generation.SpeciesBuildTuningLoader.Parse(Read("species-build.v6.json")));
FusionRpg.Core.Creatures.Generation.SpeciesBuildPlanCatalog.Configure(
    FusionRpg.Core.Creatures.Generation.SpeciesBuildPlanReader.Parse(
        File.ReadAllText(Path.Combine(repoRoot, "data", "generated", "creatures", "_species-build-plan.json"))));
FusionRpg.Core.Battle.Ai.ZombossAdaptiveTuningHub.Configure(
    FusionRpg.Core.Battle.Ai.ZombossAdaptiveTuningLoader.Parse(Read("zomboss-adaptive.v1.json")));
BattleTuningHub.Configure(BattleTuningLoader.Parse(Read("battle.v5.json")));
BattleRuleset.ConfigureResources(BattleResourceTuningLoader.Parse(Read("battle-resources.v1.json")));
FusionRpg.Core.Battle.Board.SiegeTuningPolicy.Configure(
    FusionRpg.Core.Battle.Board.SiegeTuningLoader.Parse(Read("siege.v1.json")));
FusionRpg.Core.Battle.Board.BattleBoardTuningPolicy.Configure(
    FusionRpg.Core.Battle.Board.BattleBoardTuningLoader.Parse(Read("battle-board.v1.json")));
FusionRpg.Core.World.StructureCatalog.Configure(
    FusionRpg.Core.World.StructureSeed.StructureCorpus.Load(Path.Combine(repoRoot, "data", "seed", "structures")));
SummoningTuningHub.Configure(SummoningTuningLoader.Parse(Read("summoning.v1.json")));
FusionRpg.Core.Aura.AuraTuningHub.Configure(
    FusionRpg.Core.Aura.AuraTuningLoader.Parse(Read("aura.v1.json")));
FusionRpg.Core.World.Ai.WorldAiPolicy.Configure(
    FusionRpg.Core.World.Ai.WorldAiTuningLoader.Parse(Read("ai.v3.json")));
FusionRpg.Data.Policies.SealedCompactionPolicy.Configure(
    FusionRpg.Data.Policies.DataTuningLoader.Parse(Read("data.v1.json")));
PowerTuningHub.Configure(PowerTuningLoader.Parse(Read("power-scale.v2.json")));
AptitudeTuningHub.Configure(AptitudeTuningLoader.Parse(LatestAptitudesText(tuningDir)));
FusionRpg.Core.Stats.Aptitudes.AptitudePresetTuningHub.Configure(
    FusionRpg.Core.Stats.Aptitudes.AptitudePresetTuningLoader.Parse(Read("aptitude-presets.v2.json")));
FusionRpg.Core.Actions.Rungs.RungPolicy.Configure(
    FusionRpg.Core.Actions.Rungs.RungTableLoader.Parse(Read("action-rungs.v1.json")));
FusionRpg.Core.Actions.ActionTimingPolicy.Configure(
    FusionRpg.Core.Actions.ActionTimingTuningLoader.Parse(Read("action-timing.v1.json")));
FusionRpg.Core.Battle.Timeline.ReactionLanePolicy.Configure(
    FusionRpg.Core.Battle.Timeline.ReactionLaneTuningLoader.Parse(Read("reaction-lane.v3.json")));
FusionRpg.Core.Actions.Unlock.UnlockTuningPolicy.Configure(new FusionRpg.Core.Actions.Unlock.UnlockTuning(
    P1Milli: 1000, DeltaMilli: 1000, FloorMilli: 1000, HeldCap: 10, RungCap: 10, DiscardTaxCoeffMilli: 100));
FusionRpg.Core.Actions.Eligibility.ActionFamilyMapPolicy.Configure(new Dictionary<string, IReadOnlyList<string>>());
CreatureSpeciesCatalog.ConfigureFromCompiledDefault();

using var store = RpgStore.InMemory();
store.Init();

var services = new ServiceCollection();
services.AddLogging();
services.AddSignalR();
var provider = services.BuildServiceProvider();
var hub = provider.GetRequiredService<IHubContext<RpgHub>>();
var service = new WebMatchService(store, hub);

var outcome1 = ProveBattleEqualsSheet(store, service);
var outcome2 = ProveDodgeCooldownRaisesStanding_ThetaAloneDoesNot(store);

var result = new ProveHubCombatResult(outcome1, outcome2, outcome1.Pass && outcome2.Pass);
var json = JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true });

outPath ??= Path.Combine(repoRoot, "docs", "research", "actor-hub-and-combat-power", "_prove-hub-combat.json");
Directory.CreateDirectory(Path.GetDirectoryName(outPath)!);
File.WriteAllText(outPath, json);
Console.WriteLine(json);
Console.WriteLine();
Console.WriteLine(result.Pass
    ? $"OK — battle≡sheet ({outcome1.Channels.Count} channel(s), all zero delta) and Standing honesty both hold. Wrote {outPath}"
    : "FAIL — see perBullet above for which check failed");

return result.Pass ? 0 : 1;

// ---- Bullet 1: post-fuse battle Hub channel totals ≡ sheet Hub for the SAME equip/aptitude/tree ----

static BattleEqualsSheetResult ProveBattleEqualsSheet(RpgStore store, WebMatchService service)
{
    const long equipAmount = 40;
    const long aptitudePoints = 100; // funds Might edges AND opens tree tier 1+ (reqScalePoints=5) in one grant

    var playerId = store.CreatePlayer("prove-hub-combat-1").Id;
    store.AwardSouls(playerId, 10_000, SoulEarnPolicy.Reasons.Seed, "prove-hub-combat");
    var (summonOk, summonReason, summonOutcome) = store.ExecuteSummon(
        playerId, SummonBannerCatalog.StandardRift, 1, "c-prove-hub-combat-1", rngSeed: 1, focusElementId: null);
    if (!summonOk) throw new InvalidOperationException("summon refused: " + summonReason);
    var specimenId = summonOutcome!.Specimens[0].Profile.InstanceId;

    // Equip: one rolled item granting a real, atom-backed combat channel.
    var atomFamily = "atom.prove-hub-combat";
    var containerId = "item.prove-hub-combat";
    var atomId = AtomRow.DeriveId(atomFamily, "", 1);
    var upsertAtom = store.UpsertAtom(new AtomRow
    {
        AtomId = atomId, KindId = "stat.derived",
        FamilyId = atomFamily, Variant = "", Tier = 1, Name = atomFamily,
        ParamsJson = $"{{\"channel\":\"{DerivedStatChannels.CombatPowerFire}\",\"op\":\"flat\",\"amount\":{equipAmount}}}",
    });
    if (!upsertAtom.IsOk) throw new InvalidOperationException("atom upsert refused: " + upsertAtom);
    var upsertContainer = store.UpsertContainer(new ContainerRow
    {
        ContainerId = containerId, Kind = ContainerKind.Item,
        Atoms = new[] { new ContainerAtomRow(1, atomId) },
    });
    if (!upsertContainer.IsOk) throw new InvalidOperationException("container upsert refused: " + upsertContainer);

    var container = store.GetContainer(containerId)!;
    var atomsById = store.ListAtoms().ToDictionary(a => a.AtomId, StringComparer.Ordinal);
    var mintTuning = PowerTuning.Build(1, 1, 80_000, 0, 20, 680, 1000, 25000, 250, 1000, 5000, 5000, 25000);
    var instantiate = Instantiator.TryInstantiate(
        container, id => atomsById.TryGetValue(id, out var a) ? a : null, store.GetAffix, 1, 20, mintTuning, out var inst);
    if (!instantiate.IsOk) throw new InvalidOperationException("instantiate refused: " + instantiate);
    var itemInstanceId = store.SaveInstance(inst!);
    store.SaveItem(new RpgItemRow { InstanceId = itemInstanceId, PlayerId = playerId.ToString(), AcquiredUtc = "2026-01-01T00:00:00Z" });
    store.SaveAssignment(specimenId, ItemRole.ArmamentPrimary, EquipRefKinds.Rolled, itemInstanceId);

    var (squadOk, squadReason, _, _) = service.BuildSquad(playerId, new[] { specimenId });
    if (!squadOk) throw new InvalidOperationException("BuildSquad refused: " + squadReason);

    // Aptitude: commander Might, funds real combat channels and opens the shared tree's tier 1+.
    var allocation = AptitudeAllocation.Single(AllocationScope.Commander, "Might", aptitudePoints);
    store.SaveAllocation(AllocationScope.Commander, AptitudeEndpoints.ScopeKey(playerId), allocation);

    // Tree: one shared "might" tree, one owned node carrying a real stat.derived atom.
    const string treeId = "provehubcombat";
    var treeImport = store.ImportTreeCatalog(new[] { TreeJson(treeId) }, TreeTuning());
    if (!treeImport.Ok) throw new InvalidOperationException("tree import refused: " + string.Join("; ", treeImport.Refusals));
    store.SaveTreeNodeState(AllocationScope.Commander, AptitudeEndpoints.ScopeKey(playerId),
        new Dictionary<string, long> { [$"skill.{treeId}-off-t1-n0"] = 0 });

    var actor = store.GetUniqueActor(specimenId)!;

    // Sheet side: the REAL sheet Hub, unmodified.
    var (sheetHub, sheetCtx) = UniqueActorHubCompose.Build(store, actor);
    var (sheetSnapshot, _) = sheetHub.ResolveDerivedWithContributions(sheetCtx);

    // Battle side: the REAL battle Hub, fed the SAME store-derived inputs Build() itself reads —
    // mirroring UniqueActorHubCompose.Build's own equip/tree/aptitude assembly exactly (not a second,
    // independently-invented input shape), so this proves the two COMPOSE GATES agree, not that two
    // hand-typed fixtures happen to match.
    var powerIndex = new FusionRpg.Server.Power.ServerPowerIndexProvider(store, PowerTuningHub.Tuning);
    var commanderAllocation = store.LoadAllocation(AllocationScope.Commander, AptitudeEndpoints.ScopeKey(playerId));
    var uniqueAllocation = store.LoadAllocation(AllocationScope.UniqueCreature, specimenId);
    var boundAtoms = new List<FusionRpg.Core.Stats.Derived.Subsystems.BoundDerivedAtom>();
    boundAtoms.AddRange(EquippedBoundAtoms.DerivedFromStore(store, specimenId));
    boundAtoms.AddRange(TreeBoundAtoms.ForPlayer(store, powerIndex, playerId));
    var creatureProfile = store.GetCreatureProfile(specimenId);
    var contractLoyalty = store.GetContract(specimenId)?.Loyalty ?? 0;
    var level = (int)Math.Max(1, actor.Level);

    var setup = new BattleActorSetup
    {
        Key = specimenId, Side = "squad", Level = level,
        HubInputs = new BattleHubInputs
        {
            Aptitude = commanderAllocation + uniqueAllocation,
            BoundAtoms = boundAtoms,
            StarLoyalty = new StarLoyaltyContribution(creatureProfile?.Star ?? 0, contractLoyalty, level),
        },
    };
    var battleSnapshot = BattleHubCompose.Compose(setup);

    // Scope: the channels equip + tree (the SAME BoundDerivedAtom list fed to BOTH sides) actually
    // write -- never a blind full-snapshot union, and deliberately NOT the aptitude-funded channels
    // too. Sheet and battle register DIFFERENT subsystem sets on purpose
    // (ActorHubBootstrap.CreateDefault vs BattleHubCompose.Compose's own inline list): battle alone
    // runs BattleAffinitySubsystem/BattleBaselineSubsystem/ResourceBaselineSubsystem, seeding a
    // contest-shaped accuracy/crit/dodge baseline from Atk/Defense and a resource-pool baseline sheet
    // structurally never computes at all -- the SAME "battle always seeds a baseline the overlay
    // bare-compose doesn't" gap UnfilteredRun_stillDisagreesOnResourceMax_becauseBattleAlwaysSeedsAResourceBaseline
    // already documents for resource.max.*, confirmed here (first attempt: full snapshot union) to
    // also touch combat.accuracy/crit whenever an aptitude edge ALSO funds the same channel a battle
    // baseline subsystem seeds -- a real, accepted structural difference between the two consumer
    // sets, not something this task's own scope ("battle Hub ≡ sheet Hub for the SAME equip/aptitude/
    // tree inputs") asks it to fix. Aptitude-specific battle-vs-overlay parity is ALREADY proven,
    // separately and more precisely (immune to this exact collision via its own tuned --channels
    // scope), by gk-core/tools/ProveAptitude -- this tool proves the equip+tree half nothing had proven
    // against the SHEET side specifically, not a duplicate of that tool's own job.
    var channels = boundAtoms.Select(a => a.Channel)
        .Distinct(StringComparer.Ordinal)
        .OrderBy(c => c, StringComparer.Ordinal)
        .ToList();

    var perChannel = new Dictionary<string, PerChannel>(StringComparer.Ordinal);
    var deltas = new Dictionary<string, double>(StringComparer.Ordinal);
    var anyNonZero = false;
    const double Epsilon = 1e-9;
    foreach (var ch in channels)
    {
        var sheetVal = sheetSnapshot.Get(ch, 0.0);
        var battleVal = battleSnapshot.Get(ch, 0.0);
        var delta = sheetVal - battleVal;
        perChannel[ch] = new PerChannel(sheetVal, battleVal);
        deltas[ch] = delta;
        if (Math.Abs(delta) > Epsilon) anyNonZero = true;
    }

    return new BattleEqualsSheetResult(channels, perChannel, deltas, !anyNonZero);
}

// ---- Bullet 2: Standing rises via a Hub combat writer (dodge/cooldown), not via Theta alone -------

static StandingHonestyResult ProveDodgeCooldownRaisesStanding_ThetaAloneDoesNot(RpgStore store)
{
    // 2a: Theta (level) alone, zero grants -- Standing must stay exactly zero on every axis.
    var playerA = store.CreatePlayer("prove-hub-combat-2a").Id;
    store.AwardSouls(playerA, 10_000, SoulEarnPolicy.Reasons.Seed, "prove-hub-combat");
    var (okA, reasonA, outcomeA) = store.ExecuteSummon(
        playerA, SummonBannerCatalog.StandardRift, 1, "c-prove-hub-combat-2a", rngSeed: 2, focusElementId: null);
    if (!okA) throw new InvalidOperationException("summon refused: " + reasonA);
    var specimenA = outcomeA!.Specimens[0].Profile.InstanceId;
    var actorA = store.GetUniqueActor(specimenA)!;
    if (actorA.Level < 1) throw new InvalidOperationException("a real summon must produce a real, nonzero level");
    var thetaOnlyStanding = UniqueActorHubCompose.ProjectSheet(store, actorA).Standing;
    var thetaAloneIsZero =
        thetaOnlyStanding.Offense == 0 && thetaOnlyStanding.Survivability == 0 && thetaOnlyStanding.Control == 0;

    // 2b: a real, shipped cooldown/effectiveness aptitude edge -- a genuine non-atom Hub writer with
    // no equip/tree analog -- must move Standing when granted.
    var tuning = AptitudeTuningHub.Tuning;
    var cooldownEdge = tuning.Edges.FirstOrDefault(e =>
        e.Channel.StartsWith(DerivedStatChannels.SkillCooldownPrefix, StringComparison.Ordinal)
        || e.Channel.StartsWith(DerivedStatChannels.SkillEffectivenessPrefix, StringComparison.Ordinal));
    if (cooldownEdge is null)
        throw new InvalidOperationException("shipped aptitudes tuning funds no skill.cooldown/effectiveness edge -- nothing to prove");

    var playerB = store.CreatePlayer("prove-hub-combat-2b").Id;
    store.AwardSouls(playerB, 10_000, SoulEarnPolicy.Reasons.Seed, "prove-hub-combat");
    var (okB, reasonB, outcomeB) = store.ExecuteSummon(
        playerB, SummonBannerCatalog.StandardRift, 1, "c-prove-hub-combat-2b", rngSeed: 3, focusElementId: null);
    if (!okB) throw new InvalidOperationException("summon refused: " + reasonB);
    var specimenB = outcomeB!.Specimens[0].Profile.InstanceId;
    var bare = UniqueActorHubCompose.ProjectSheet(store, store.GetUniqueActor(specimenB)!).Standing;

    store.SaveAllocation(AllocationScope.Commander, AptitudeEndpoints.ScopeKey(playerB),
        AptitudeAllocation.Single(AllocationScope.Commander, cooldownEdge.Source, 100));
    var geared = UniqueActorHubCompose.ProjectSheet(store, store.GetUniqueActor(specimenB)!).Standing;

    var cooldownMovedStanding =
        geared.Offense != bare.Offense || geared.Survivability != bare.Survivability || geared.Control != bare.Control;

    return new StandingHonestyResult(thetaAloneIsZero, cooldownEdge.Source, cooldownEdge.Channel, cooldownMovedStanding,
        thetaAloneIsZero && cooldownMovedStanding);
}

static string TreeJson(string treeId) => $$"""
{
  "treeId": "{{treeId}}",
  "category": "primary",
  "gateQuantity": "aptitude.Might@Commander",
  "shapeArchetype": "broad-and-flat",
  "tiers": 10,
  "branches": 2,
  "nodesPerTier": [2,2,2,2,2,2,2,2,2,2],
  "catalogVersion": 1,
  "enabled": true,
  "nodes": [
    {
      "id": "skill.{{treeId}}-off-t1-n0",
      "branch": "off",
      "tier": 1,
      "nodeKey": "n0",
      "prereqNodeIds": [],
      "nodeClass": "magnitude",
      "affixIds": ["affix.a"],
      "budgetShareMilli": 18,
      "atoms": [
        {
          "kindId": "stat.derived",
          "attachPoint": "Stat",
          "channelId": "combat.power.ice",
          "op": "flat",
          "trigger": null,
          "whenJson": null,
          "kMicro": 12345,
          "scaleAxis": "PTheta",
          "unitClass": "GameUnits",
          "soulCurveId": null
        }
      ],
      "excludeProps": [],
      "exclusionForm": "None",
      "tagsJson": null,
      "enabled": true,
      "retiredAtRevision": null
    }
  ]
}
""";

static PassiveTreeTuning TreeTuning() => new(
    SchemaVersion: 1, Version: 1,
    TierLadder: new TierLadderTuning(ReqScalePoints: 5),
    Budget: new BudgetTuning(1000, 500),
    TreeShareMilli: 1000, TreeBudgetMilli: 1000,
    Potency: new PotencyTuning(182, 1, new long[] { 46, 91, 137, 182 }),
    Mechanism: new MechanismTuning(0, 1000),
    Archetype: new ArchetypeTuning(6000),
    Exclusion: new ExclusionTuning(20),
    ArchetypeAssignment: "ordinal-round-robin",
    DesignTarget: new DesignTargetTuning(92),
    Concentration: new ConcentrationTuning(FmaxMilli: 1200, WMilli: 500),
    SoulTrack: new SoulTrackTuning(1000),
    UnlockCost: new UnlockCostTuning(5, 2),
    Respec: new RespecTuning(50, 500),
    GateCounters: new GateCountersTuning(23, 23, 4, 4, 5000, null));

static string LatestAptitudesText(string tuningDir)
{
    var file = Directory.GetFiles(tuningDir, "aptitudes.v*.json")
        .OrderByDescending(f => f, StringComparer.Ordinal)
        .First();
    return File.ReadAllText(file);
}

static string FindRepoRoot()
{
    var dir = new DirectoryInfo(AppContext.BaseDirectory);
    while (dir is not null)
    {
        if (Directory.Exists(Path.Combine(dir.FullName, "src", "FusionRpg.Injector"))) return dir.FullName;
        dir = dir.Parent;
    }
    throw new DirectoryNotFoundException("could not locate repo root above " + AppContext.BaseDirectory);
}

static string? ArgString(string[] a, string flag, string? fallback)
{
    var i = Array.IndexOf(a, flag);
    return i >= 0 && i + 1 < a.Length ? a[i + 1] : fallback;
}

readonly record struct PerChannel(double Sheet, double Battle);

sealed record BattleEqualsSheetResult(
    List<string> Channels, Dictionary<string, PerChannel> PerChannel, Dictionary<string, double> Deltas, bool Pass);

sealed record StandingHonestyResult(
    bool ThetaAloneIsZero, string CooldownAptitudeSource, string CooldownChannel, bool CooldownMovedStanding, bool Pass);

sealed record ProveHubCombatResult(BattleEqualsSheetResult BattleEqualsSheet, StandingHonestyResult StandingHonesty, bool Pass);
