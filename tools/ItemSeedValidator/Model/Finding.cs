namespace FusionRpg.Tools.ItemSeedValidator.Model;

public enum Severity
{
    /// <summary>Fails the build. The corpus does not ship with one of these outstanding.</summary>
    Error,

    /// <summary>A lint. Reported, never fatal — see seed-contract.md's content lints.</summary>
    Warning,
}

/// <summary>
/// One validator result. Every finding names the file, the entry, and the rule it broke — a
/// finding a fix pass cannot act on is noise, and this corpus is fixed by re-running agents.
/// </summary>
/// <param name="Severity">Error fails the run; Warning never does.</param>
/// <param name="Code">Stable machine code, e.g. <c>MagnitudeAuthored</c>.</param>
/// <param name="Partition">The allocated partition the finding belongs to, so a fix pass can
/// re-run exactly the failing agents. <c>(unassigned)</c> when the id resolves to no namespace.</param>
/// <param name="File">Repo-relative path of the offending file.</param>
/// <param name="EntryId">The offending entry id, or null for a file-level finding.</param>
/// <param name="Rule">The contract or registry clause, e.g. <c>seed-contract.md §3</c>.</param>
/// <param name="Message">What is wrong, in one sentence.</param>
public sealed record Finding(
    Severity Severity,
    string Code,
    string Partition,
    string File,
    string? EntryId,
    string Rule,
    string Message)
{
    public const string NoPartition = "(unassigned)";

    public static Finding Error(string code, string file, string? entryId, string rule, string message,
        string partition = NoPartition) =>
        new(Model.Severity.Error, code, partition, file, entryId, rule, message);

    public static Finding Warn(string code, string file, string? entryId, string rule, string message,
        string partition = NoPartition) =>
        new(Model.Severity.Warning, code, partition, file, entryId, rule, message);
}
