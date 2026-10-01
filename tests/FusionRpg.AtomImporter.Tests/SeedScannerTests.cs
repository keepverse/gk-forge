using FusionRpg.Data.Seed;
using Xunit;
// The `using FusionRpg.TestSupport;` that used to stand here is gone with the cross-repository
// Compile Include that provided it. gk-core's tests/Shared/KeepverseRoots.cs declared four
// INTERNAL root helpers in that namespace; the public FusionRpg.Core.Workspace.KeepverseRoots
// already in this assembly does the same job, and it is named explicitly at each call site so a
// reader can tell WHICH repository a path is resolved against.
using FusionRpg.Core.Workspace;

namespace FusionRpg.AtomImporter.Tests;

/// <summary>
/// Which files an import sweeps (E14a).
///
/// <para>The headline case is the collision that is already in the tree: <c>gk-data/packs/fusion/data/seed/items/</c>
/// holds ~125 files in a different format read by <c>gk-forge/tools/ItemSeedValidator</c>. If the atom
/// importer ever sweeps the seed root recursively it refuses every one of them and reports the
/// import broken — a failure that looks like bad content and is not.</para>
/// </summary>
public class SeedScannerTests : IDisposable
{
    readonly string _root;

    public SeedScannerTests()
    {
        _root = Path.Combine(Path.GetTempPath(), "fusionrpg-scan-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_root);
    }

    public void Dispose()
    {
        try { Directory.Delete(_root, recursive: true); } catch { /* temp dir */ }
    }

    string Dir(params string[] parts)
    {
        var p = Path.Combine(new[] { _root }.Concat(parts).ToArray());
        Directory.CreateDirectory(p);
        return p;
    }

    string File_(string dir, string name)
    {
        var p = Path.Combine(dir, name);
        File.WriteAllText(p, "{}");
        return p;
    }

    // ---- roots ------------------------------------------------------------------------------------

    [Fact]
    public void The_default_sweep_takes_the_four_owned_folders_and_nothing_else()
    {
        Dir("atoms"); Dir("containers"); Dir("curves"); Dir("rarity"); Dir("items");

        var roots = SeedScanner.Roots(_root, explicitRoot: false, Directory.Exists);

        Assert.Equal(4, roots.Count);
        Assert.DoesNotContain(roots, r => r.EndsWith("items", StringComparison.Ordinal));
    }

    [Fact]
    public void The_item_seed_corpus_is_never_swept_by_the_default_root()
    {
        // The whole reason this class exists. `items/` is another tool's format.
        Dir("atoms");
        File_(Dir("items", "base-types"), "plant-standard.json");
        File_(Path.Combine(_root, "atoms"), "vitality.json");

        var files = SeedScanner.Files(SeedScanner.Roots(_root, explicitRoot: false, Directory.Exists));

        Assert.Single(files);
        Assert.EndsWith("vitality.json", files[0]);
    }

    [Fact]
    public void An_owned_folder_that_does_not_exist_is_simply_absent()
    {
        // A tree holding only atoms is normal; demanding all four would refuse it.
        Dir("atoms");

        var roots = SeedScanner.Roots(_root, explicitRoot: false, Directory.Exists);

        Assert.Single(roots);
    }

    [Fact]
    public void A_seed_root_with_none_of_the_four_folders_yields_no_roots()
    {
        // Which is what makes the tool say "nothing to import" and exit non-zero, rather than
        // reporting a clean run over zero files.
        Dir("items");

        Assert.Empty(SeedScanner.Roots(_root, explicitRoot: false, Directory.Exists));
    }

    [Fact]
    public void An_explicitly_named_root_is_swept_whole()
    {
        // The escape hatch for a migration folder, which has no reason to use the four names.
        Dir("migration-2026-08");

        var roots = SeedScanner.Roots(_root, explicitRoot: true, Directory.Exists);

        Assert.Equal(new[] { _root }, roots);
    }

    // ---- order ------------------------------------------------------------------------------------

    [Fact]
    public void Files_come_back_in_ordinal_order_whatever_the_filesystem_says()
    {
        // A cross-file duplicate reports which file claimed the id first. If the order varied by
        // machine, so would that message — and so would which of two authors gets told to rename.
        var scrambled = new[] { "z.json", "a.json", "M.json", "b.json" };

        var ordered = SeedScanner.Order(scrambled);

        Assert.Equal(new[] { "M.json", "a.json", "b.json", "z.json" }, ordered);
    }

    [Fact]
    public void Underscore_files_are_notes_and_are_skipped()
    {
        var kept = SeedScanner.Order(new[] { "_exemplar.json", "real.json", "_registry.json" });

        Assert.Equal(new[] { "real.json" }, kept);
    }

    [Fact]
    public void An_underscore_inside_a_name_is_not_a_note()
    {
        // The rule is a leading underscore, not any underscore — `fire_rider.json` is content.
        Assert.Equal(new[] { "fire_rider.json" }, SeedScanner.Order(new[] { "fire_rider.json" }));
    }

    [Fact]
    public void Nested_folders_under_an_owned_folder_are_swept()
    {
        // Authors group by family, and a folder per family is the obvious way to do it.
        File_(Dir("atoms", "elemental"), "fire.json");
        File_(Dir("atoms"), "vitality.json");

        var files = SeedScanner.Files(SeedScanner.Roots(_root, explicitRoot: false, Directory.Exists));

        Assert.Equal(2, files.Count);
    }

    [Fact]
    public void Files_that_are_not_json_are_ignored()
    {
        var atoms = Dir("atoms");
        File.WriteAllText(Path.Combine(atoms, "notes.md"), "# notes");
        File_(atoms, "vitality.json");

        var files = SeedScanner.Files(SeedScanner.Roots(_root, explicitRoot: false, Directory.Exists));

        Assert.Single(files);
    }

    // ---- the real repo: curves/ and rarity/ (completeness-audit.md C3) -------------------------------

    [Fact]
    public void The_real_curves_and_rarity_folders_exist_and_document_why_they_are_empty_or_seeded()
    {
        // C3: two owned folders declared with no content looked identical to two forgotten ones.
        // The README in each is the distinction — a real, checked-in file, not a synthetic fixture.

        Assert.True(Directory.Exists(Path.Combine(KeepverseRoots.Content(), "data", "seed", "curves")), "data/seed/curves missing");
        Assert.True(Directory.Exists(Path.Combine(KeepverseRoots.Content(), "data", "seed", "rarity")), "data/seed/rarity missing");
        Assert.True(File.Exists(Path.Combine(KeepverseRoots.Content(), "data", "seed", "curves", "README.md")));
        Assert.True(File.Exists(Path.Combine(KeepverseRoots.Content(), "data", "seed", "rarity", "README.md")));
    }

    [Fact]
    public void The_real_sweep_finds_zero_json_in_curves_still_empty_on_purpose()
    {
        var roots = SeedScanner.Roots(Path.Combine(KeepverseRoots.Content(), "data", "seed"), explicitRoot: false, Directory.Exists);
        var files = SeedScanner.Files(roots);

        Assert.DoesNotContain(files, f => f.Replace('\\', '/').Contains("/curves/", StringComparison.Ordinal));
    }

    [Fact]
    public void The_real_sweep_finds_ratitys_seeded_ladder_item_ideal_rarity_bands_module_7()
    {
        // item-ideal.md, rarity-bands (module 7, 2026-09-04): rarity/ stopped being "empty on
        // purpose" once the ten-rung ladder was seeded -- gk-data/packs/fusion/data/seed/rarity/README.md says so, and
        // this is the sweep-level pin that a future regression can't silently re-empty the folder
        // and have this suite stay green either way.
        var roots = SeedScanner.Roots(Path.Combine(KeepverseRoots.Content(), "data", "seed"), explicitRoot: false, Directory.Exists);
        var files = SeedScanner.Files(roots);

        Assert.Contains(files, f => f.Replace('\\', '/').EndsWith("/rarity/ladder.v1.json", StringComparison.Ordinal));
    }

    // ---- E32 test 9: the two halves of the affix write path ------------------------------------

    /// <summary>The test 9 the spec's own §5 names as "the one that would have prevented this
    /// module" — seedsmith wrote to a folder nothing swept and nobody noticed, because no test
    /// compared the two. Reads seedsmith's own `OUTPUT_DIR` line directly (not the spec's prose
    /// claim), so a future path change on either side fails this test rather than silently
    /// reopening the gap.</summary>
    [Fact]
    public void AtomImporter_swept_folder_matches_seedsmiths_own_affix_write_path()
    {
        var generatorPath = Path.Combine(KeepverseRoots.Forge(), "tools", "seedsmith", "seedsmith", "adapters", "effects", "affix", "generate_affixes.py");
        Assert.True(File.Exists(generatorPath), $"seedsmith's affix generator moved or was renamed: {generatorPath}");

        var source = File.ReadAllText(generatorPath);
        // EITHER spelling, because the split changed which one is CORRECT and the coupling being pinned is
        // not the spelling. `REPO_ROOT / "data" / "seed" / "effects" / "affixes"` is what the line said when
        // `data/seed` lived in the same repository as the generator. After the split the corpus is the
        // gk-data pack's, so the line reads `_owned("data/seed/effects/affixes")` — asking for `REPO_ROOT`
        // again would pin a path that cannot exist, and that is exactly what this test did after the
        // rewrite. The resolved owner is asserted below, which the pre-split form could not express at
        // all, so this is a STRONGER coupling than the one it replaces rather than a looser one.
        var legacy = System.Text.RegularExpressions.Regex.IsMatch(
            source, @"OUTPUT_DIR\s*=\s*REPO_ROOT\s*/\s*""data""\s*/\s*""seed""\s*/\s*""effects""\s*/\s*""affixes""");
        var owned = System.Text.RegularExpressions.Regex.IsMatch(
            source, @"OUTPUT_DIR\s*=\s*_owned\(\s*""data/seed/effects/affixes""\s*\)");
        Assert.True(legacy ^ owned,
            "seedsmith's OUTPUT_DIR no longer reads data/seed/effects/affixes — neither the "
            + "`REPO_ROOT / \"data\" / \"seed\" / ...` form nor the `_owned(\"data/seed/effects/affixes\")` "
            + "form the post-split rewrite produces. If both are gone the folder is written somewhere "
            + "nothing sweeps; if both are present the resolution is ambiguous. Update this pin and "
            + "SeedScanner.OwnedFolders together — that is what it is for.");
        // The folder seedsmith writes is the CONTENT PACK's, so the importer's swept folder and
        // seedsmith's output dir agree about a path in a repository neither of them is. Asserted as the
        // directory's EXISTENCE rather than as a string join, because a join of two accessors is a
        // tautology: it would pass for any value of either.
        Assert.True(Directory.Exists(Path.Combine(KeepverseRoots.Content(), "data", "seed", "effects", "affixes")),
            $"the pack does not carry the folder seedsmith writes: " +
            $"{Path.Combine(KeepverseRoots.Content(), "data", "seed", "effects", "affixes")}");

        Assert.Contains("effects/affixes", SeedScanner.OwnedFolders);
    }

    // ---- T5.3 (species-effects, 2026-09-06): the same two-halves discipline, a second time -------

    /// <summary>The exact same class of gap `effects/affixes`' own test above exists to catch,
    /// applied to `species-effects`' own writer — found live, 2026-09-06, while verifying real
    /// generated content actually imports: `gk-data/packs/fusion/data/seed/creatures/species-effects/**` held real,
    /// importer-clean content that nothing swept, because `creatures/species-effects` was never added
    /// to <see cref="SeedScanner.OwnedFolders"/> when the writer was built.</summary>
    [Fact]
    public void AtomImporter_swept_folder_matches_seedsmiths_own_species_effects_write_path()
    {
        var generatorPath = Path.Combine(KeepverseRoots.Forge(), "tools", "seedsmith", "run_t53_claude_propose.py");
        Assert.True(File.Exists(generatorPath), $"seedsmith's species-effects generator moved or was renamed: {generatorPath}");

        var source = File.ReadAllText(generatorPath);
        // Same either-spelling pin as the affix case above, for the same reason: the corpus moved to the
        // gk-data pack, so `REPO_ROOT / "data" / "seed" / "creatures" / "species-effects"` became
        // `_owned("data/seed/creatures/species-effects")`. XOR rather than OR, so neither a vanished
        // write path nor an ambiguous double resolution can pass.
        var legacy = System.Text.RegularExpressions.Regex.IsMatch(
            source, @"OUTPUT_DIR\s*=\s*REPO_ROOT\s*/\s*""data""\s*/\s*""seed""\s*/\s*""creatures""\s*/\s*""species-effects""");
        var owned = System.Text.RegularExpressions.Regex.IsMatch(
            source, @"OUTPUT_DIR\s*=\s*_owned\(\s*""data/seed/creatures/species-effects""\s*\)");
        Assert.True(legacy ^ owned,
            "seedsmith's species-effects OUTPUT_DIR no longer reads data/seed/creatures/species-effects — "
            + "update SeedScanner.OwnedFolders's \"creatures/species-effects\" entry to match, in the same change");

        Assert.True(Directory.Exists(Path.Combine(KeepverseRoots.Content(), "data", "seed", "creatures", "species-effects")),
            "the pack does not carry the species-effects folder: "
            + Path.Combine(KeepverseRoots.Content(), "data", "seed", "creatures", "species-effects"));

        Assert.Contains("creatures/species-effects", SeedScanner.OwnedFolders);
    }

    [Fact]
    public void The_real_sweep_finds_the_committed_species_effects_pilot_batch()
    {
        // Pins that the folder is not just declared but actually reaches real committed content —
        // the same class of silent gap the folder's own addition just closed.
        var roots = SeedScanner.Roots(Path.Combine(KeepverseRoots.Content(), "data", "seed"), explicitRoot: false, Directory.Exists);
        var files = SeedScanner.Files(roots);

        Assert.Contains(files, f => f.Replace('\\', '/').EndsWith("creatures/species-effects/plant/pilot-batch.json", StringComparison.Ordinal));
        Assert.Contains(files, f => f.Replace('\\', '/').EndsWith("creatures/species-effects/zombie/pilot-batch.json", StringComparison.Ordinal));
    }

    // ---- D4.16 (spec-domain-catalog.md §1): the seven dungeon folders ----

    [Fact]
    public void OwnedFolders_carries_all_seven_dungeon_corpus_folders()
    {
        var expected = new[]
        {
            "dungeon/domains", "dungeon/rooms", "dungeon/layouts", "dungeon/events",
            "dungeon/quests", "dungeon/encounters", "dungeon/supplies",
        };
        foreach (var folder in expected)
            Assert.Contains(folder, SeedScanner.OwnedFolders);
    }

    [Fact]
    public void The_seven_dungeon_folders_are_scanned_when_present_never_when_absent()
    {
        // "the seven folders are scanned" (D4.16's own Verify line): none exist under the real repo
        // today (confirmed separately), so this proves the WIRING end to end against a fixture root
        // rather than the real, still-empty gk-data/packs/fusion/data/seed/dungeon/ tree -- absent, Roots skips them
        // (today's real behaviour); created, Roots includes them (the behaviour once content lands).
        var beforeRoots = SeedScanner.Roots(_root, explicitRoot: false, Directory.Exists);
        Assert.DoesNotContain(beforeRoots, r => r.Replace('\\', '/').EndsWith("dungeon/domains", StringComparison.Ordinal));

        Dir("dungeon", "domains");
        Dir("dungeon", "quests");

        var afterRoots = SeedScanner.Roots(_root, explicitRoot: false, Directory.Exists);
        Assert.Contains(afterRoots, r => r.Replace('\\', '/').EndsWith("dungeon/domains", StringComparison.Ordinal));
        Assert.Contains(afterRoots, r => r.Replace('\\', '/').EndsWith("dungeon/quests", StringComparison.Ordinal));
        // The five dungeon folders never created stay absent -- each folder is checked independently.
        Assert.DoesNotContain(afterRoots, r => r.Replace('\\', '/').EndsWith("dungeon/rooms", StringComparison.Ordinal));
    }

    [Fact]
    public void The_real_repo_dungeon_tree_has_all_seven_owned_corpus_folders()
    {
        // D4.16 content has landed since the original no-op pin. Keep this test tied to the real tree
        // so ownership drift is visible, while the atom import path uses AtomRoots and excludes these
        // dungeon-specific envelopes.
        var dungeonRoot = Path.Combine(KeepverseRoots.Content(), "data", "seed", "dungeon");
        Assert.True(Directory.Exists(dungeonRoot));
        var subfolders = Directory.GetDirectories(dungeonRoot).Select(Path.GetFileName).ToList();
        Assert.Contains("_containers", subfolders!);
        Assert.Contains("_plan", subfolders!);
        Assert.Contains("_registry", subfolders!);
        foreach (var folder in new[] { "domains", "rooms", "layouts", "events", "quests", "encounters", "supplies" })
            Assert.Contains(folder, subfolders!);
    }

}
