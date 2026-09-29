using System.Runtime.CompilerServices;
using FusionRpg.Core.Stats.Derived;

namespace FusionRpg.TreeBinder.Tests;

/// <summary>tunables-ssot.md §7.2's own "construct one inline; a module initializer configures it once"
/// pattern (`FusionRpg.Core.Tests/ContractTuningTestBootstrap.cs`'s own convention), scoped down to
/// the ONE Policy class this assembly's tests actually reach: `PassiveTreeCatalogLoader`'s own static
/// constructor builds a `DerivedStatRegistry.CreateDefault()`, which reads `DerivedStatPolicy.Tuning` —
/// found 2026-09-07 the moment a real round-trip test in `ReportWriterTests` first exercised the
/// loader from this project (nothing here had ever needed it before). Values match the shipped
/// `gk-core/data/tuning/derived-stats.v2.json`, the same working set `ContractTuningTestBootstrap`'s own
/// `DefaultDerivedStats` already uses.</summary>
internal static class DerivedStatTestBootstrap
{
    [ModuleInitializer]
    public static void Init()
    {
        DerivedStatPolicy.Configure(new DerivedStatTuning(
            SchemaVersion: 2, Version: 2, CategoryResistCap: 0.95, TurnDefaultSpeed: 100));
    }
}
