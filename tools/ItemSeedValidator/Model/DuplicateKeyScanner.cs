using System.Text;
using System.Text.Json;

namespace FusionRpg.Tools.ItemSeedValidator.Model;

/// <summary>
/// Finds duplicated object keys, which <c>System.Text.Json</c> resolves silently by keeping the
/// last one. In an authored corpus that is a value nobody validated, so it is worth a pass.
/// </summary>
public static class DuplicateKeyScanner
{
    public static IReadOnlyList<string> Scan(string json)
    {
        var duplicates = new List<string>();
        var seen = new Stack<HashSet<string>>();
        var path = new Stack<string>();
        string? pendingKey = null;

        var reader = new Utf8JsonReader(Encoding.UTF8.GetBytes(json), new JsonReaderOptions
        {
            CommentHandling = JsonCommentHandling.Disallow,
            AllowTrailingCommas = false,
        });

        try
        {
            while (reader.Read())
            {
                switch (reader.TokenType)
                {
                    case JsonTokenType.StartObject:
                        path.Push(pendingKey ?? "$");
                        pendingKey = null;
                        seen.Push(new HashSet<string>(StringComparer.Ordinal));
                        break;
                    case JsonTokenType.EndObject:
                        if (seen.Count > 0) seen.Pop();
                        if (path.Count > 0) path.Pop();
                        break;
                    case JsonTokenType.StartArray:
                        path.Push(pendingKey ?? "[]");
                        pendingKey = null;
                        break;
                    case JsonTokenType.EndArray:
                        if (path.Count > 0) path.Pop();
                        break;
                    case JsonTokenType.PropertyName:
                        var name = reader.GetString() ?? "";
                        if (seen.Count > 0 && !seen.Peek().Add(name))
                            duplicates.Add(string.Join('.', path.Reverse().Skip(1).Append(name)));
                        pendingKey = name;
                        break;
                }
            }
        }
        catch (JsonException)
        {
            // The parse error is reported by SeedFile.Load; nothing useful to add here.
        }

        return duplicates;
    }
}
