using System.Globalization;

namespace FusionRpg.Tools.FamilyExpandGen;

/// <summary>
/// Numeric selection for the versioned registries read by <c>FamilyExpandGen</c>.
/// Filename ordering is not version ordering: <c>v10</c> sorts before <c>v2</c> as text.
/// </summary>
public static class VersionedInputFile
{
    public static string? FindLatestPath(string directory, string stem)
    {
        if (!Directory.Exists(directory)) return null;

        return Directory.EnumerateFiles(directory, $"{stem}.v*.json")
            .Select(path => (Path: path, Version: TryVersion(path, stem)))
            .Where(candidate => candidate.Version.HasValue)
            .OrderByDescending(candidate => candidate.Version!.Value)
            .Select(candidate => candidate.Path)
            .FirstOrDefault();
    }

    public static int VersionOf(string path, string stem)
    {
        return TryVersion(path, stem)
            ?? throw new FormatException($"{path}: expected {stem}.v<number>.json");
    }

    static int? TryVersion(string path, string stem)
    {
        var name = Path.GetFileName(path);
        var prefix = $"{stem}.v";
        const string suffix = ".json";
        if (!name.StartsWith(prefix, StringComparison.Ordinal) ||
            !name.EndsWith(suffix, StringComparison.Ordinal) ||
            name.Length <= prefix.Length + suffix.Length)
            return null;

        var versionText = name[prefix.Length..^suffix.Length];
        return int.TryParse(versionText, NumberStyles.None, CultureInfo.InvariantCulture, out var version)
            ? version
            : null;
    }
}
