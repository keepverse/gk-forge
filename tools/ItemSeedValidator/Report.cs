using System.Text;
using FusionRpg.Tools.ItemSeedValidator.Model;

namespace FusionRpg.Tools.ItemSeedValidator;

/// <summary>
/// One report, once. authoring-fleet-plan.md §8.2 makes this the reporting channel for the whole
/// build: the orchestrator learns whether the corpus is good from this table, not from 125 agent
/// accounts. So errors group by partition — a fix pass re-runs exactly the named agents.
/// </summary>
public static class Report
{
    public static string Render(ValidationResult result, string seedRoot)
    {
        var sb = new StringBuilder();
        var reg = result.Registries;

        sb.AppendLine("Item seed validator");
        sb.AppendLine($"  seed root   {seedRoot}");
        sb.AppendLine($"  registries  {reg.RegistryDir}");
        sb.AppendLine("              " + string.Join("  ", new[]
        {
            $"core v{reg.Versions.GetValueOrDefault("core")}",
            $"bands v{reg.Versions.GetValueOrDefault("bands")}",
            $"tags v{reg.Versions.GetValueOrDefault("tags")}",
            $"themes v{reg.Versions.GetValueOrDefault("themes")}",
            $"classes v{reg.Versions.GetValueOrDefault("classes")}",
            $"naming v{reg.Versions.GetValueOrDefault("naming")}",
        }));
        sb.AppendLine($"  partitions  {result.Allocation.All.Count} allocated prefixes");
        sb.AppendLine($"  word pool   {(reg.Words is null ? "ABSENT (words.v1.json not authored)" : $"{reg.CanonicalWords.Count} canonical words")}");
        sb.AppendLine($"  connectives {string.Join(", ", reg.Connectives)}  [{reg.ConnectiveSource}]");
        sb.AppendLine();

        sb.AppendLine("  ---------------------------------");
        sb.AppendLine($"  {"files scanned",-18}{result.FilesScanned,8}");
        sb.AppendLine($"  {"entries",-18}{result.EntriesScanned,8}");
        sb.AppendLine($"  {"errors",-18}{result.ErrorCount,8}");
        sb.AppendLine($"  {"warnings",-18}{result.WarningCount,8}");
        sb.AppendLine("  ---------------------------------");
        sb.AppendLine();

        if (result.ScannedNothing)
        {
            sb.AppendLine("!! NO SEED FILES WERE SCANNED.");
            sb.AppendLine("!! Nothing was validated, so nothing passed. A validator that reports success");
            sb.AppendLine("!! over an empty tree is worse than no validator at all.");
            sb.AppendLine($"!! Looked under: {seedRoot}");
            sb.AppendLine("!! Expected one directory per kind, e.g. base-types/, affix-families/, uniques/.");
            sb.AppendLine();
        }

        RenderGroup(sb, "ERRORS BY PARTITION", result.Findings.Where(f => f.Severity == Severity.Error).ToList());
        RenderGroup(sb, "WARNINGS", result.Findings.Where(f => f.Severity == Severity.Warning).ToList());

        if (result.ErrorCount == 0 && !result.ScannedNothing)
            sb.AppendLine($"PASS — {result.EntriesScanned} entries across {result.FilesScanned} files, "
                          + $"{result.WarningCount} warnings.");
        else if (result.ErrorCount > 0)
            sb.AppendLine($"FAIL — {result.ErrorCount} errors across "
                          + $"{result.Findings.Where(f => f.Severity == Severity.Error).Select(f => f.Partition).Distinct().Count()} "
                          + "partitions. Re-run the partitions named above; do not hand-fix.");

        return sb.ToString();
    }

    static void RenderGroup(StringBuilder sb, string title, IReadOnlyList<Finding> findings)
    {
        if (findings.Count == 0) return;

        sb.AppendLine(title);
        foreach (var partition in findings
                     .GroupBy(f => f.Partition, StringComparer.Ordinal)
                     .OrderBy(g => g.Key, StringComparer.Ordinal))
        {
            sb.AppendLine($"  {partition.Key}  ({partition.Count()})");
            foreach (var file in partition
                         .GroupBy(f => f.File, StringComparer.Ordinal)
                         .OrderBy(g => g.Key, StringComparer.Ordinal))
            {
                sb.AppendLine($"    {file.Key}");
                foreach (var finding in file.OrderBy(f => f.EntryId ?? "", StringComparer.Ordinal)
                             .ThenBy(f => f.Code, StringComparer.Ordinal))
                    sb.AppendLine($"      {finding.EntryId ?? "(file)",-34} {finding.Code,-28} "
                                  + $"[{finding.Rule}] {finding.Message}");
            }
        }
        sb.AppendLine();
    }
}
