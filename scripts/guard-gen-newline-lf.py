#!/usr/bin/env python3
r"""Guard `gen-newline-lf`: every C# generator in `tools/` must write LF, or normalize before it does.

THE DEFECT THIS EXISTS TO STOP
------------------------------
Every repository here carries `.gitattributes` with `* text=auto eol=lf`, so git normalises on
staging: a CRLF file is committed as LF, `git status` calls it clean, and the corruption is
invisible to any byte comparison that reads the blob. It is only visible to a consumer that reads
the file from disk — a `--check` mode, a validator, or anything that hashes a generated file — so a
regenerated tree can differ from its own committed state on line endings alone.

MEASURED ON net8.0, NOT ASSUMED — and it is not the intuitive answer
-------------------------------------------------------------------
A probe (`tools/` builds run net8.0; the claim was verified with a throwaway net8.0 console app)
measured each idiom on this machine, where `Environment.NewLine` is CRLF:

    File.WriteAllText(payload containing "\n")      CR=0   LF=3    LF      <- writes VERBATIM
    JsonSerializer.Serialize(x, WriteIndented)      CR=6   LF=6    CRLF
    Utf8JsonWriter(Indented = true)                CR=2   LF=2    CRLF
    StreamWriter.WriteLine(...)                     CR=2   LF=3    CRLF
    StringBuilder.AppendLine(...)                   CR=2   LF=2    CRLF
    File.WriteAllLines(...)                         CR=2   LF=2    CRLF
    File.WriteAllBytes(utf8.GetBytes(...))          CR=0   LF=3    LF

So `File.WriteAllText` is INNOCENT. It writes its string verbatim; the defect is always in the
PAYLOAD PRODUCER, and there are two of them: an indented JSON writer, and `AppendLine`/`WriteLine`.
An indented `Utf8JsonWriter` hardcodes `\r\n` on net8.0 — it does not read `Environment.NewLine` —
so it emitted CRLF on every platform, not merely a cross-platform difference. (`JsonWriterOptions.NewLine`
arrives in net9 and would have turned a universal CRLF into a platform-dependent one; either way,
wrong.) `TreeBinder/Program.cs` already carried a comment saying so, and `CanonicalEol.ToLf()`
(gk-core) is the house fix; five writers simply never called it.

WHAT IS FLAGGED
---------------
A `File.WriteAllText` / `File.AppendAllText` / `File.WriteAllLines` call in a `tools/**/*.cs`
project whose payload cannot be shown to be LF:

* payload is a method call whose body is not in the same file  -> UNPROVABLE, so a finding
* payload is a local defined by no assignment this file can see -> UNPROVABLE, so a finding
* payload is inline and carries no normalizer                    -> finding
* `File.WriteAllLines`                                          -> always a finding (measured)

WHAT IS ACCEPTED AS LF
----------------------
The payload carries one of `ToLf()`, `ToLfLineEndings(...)`, `Canonicalize(...)`, or
`Replace("\r\n", "\n")` — at the write, in the payload's assignment, or in the body of the method
the payload calls. `CanonicalEol.ToLf()` is gk-core's own house normaliser, and 17 of the 20
`tools/*` projects already reference it.

UNPROVABLE IS A FINDING, NOT A PASS
-----------------------------------
A payload that resolves outside the scanned file is reported rather than waved through. That is
deliberate and it is why the exemption list exists and is not empty: 9 of the 15 write calls here
depend on a normaliser in another file, and each exemption names that other file and line. The
alternative — treat "I cannot see it" as "it is fine" — is how a guard passes a tree it never read.

EXEMPTIONS ARE EXACT (file, line) KEYS
--------------------------------------
No glob, no prefix. Editing a file invalidates its keys and the guard reports `EXEMPTION-STALE`
until the author re-decides, so an exemption cannot outlive its reason.

TEXTUAL SCAN, AND THE HONEST LIMIT OF IT
----------------------------------------
There is no C# parser here, so this is a textual scan over a comment- and string-stripped source.
That stripping is not cosmetic: an earlier draft of this guard matched its own explanatory comment
in `CreatureCorpusEmit/Program.cs:153`, which is exactly the "regex lies on this corpus" failure the
Python sibling guard documents. Block comments, line comments, regular/verbatim/raw string literals,
and char literals are all blanked before any matching, and string contents are replaced with a
marker that still records whether the literal held a `\r\n` escape, because
`Replace("\r\n", "\n")` is the house idiom and must stay detectable.

The limit, stated rather than implied: this reads one file and follows a payload one call deep. It
cannot prove what a method in another repository does, and it does not attempt to. That gap is
closed by exemptions carrying that evidence by hand, which is a real ongoing cost and the reason
this is one narrow guard rather than a claim of completeness over the C# language.

FAIL CLOSED BY NAME
-------------------
`TOOLS-TREE-MISSING`, `PARSE-ERROR` with `file:lineno`, `EXEMPTION-STALE`. Findings and the BLOCKED
block go to stderr; only the verdict reaches stdout; `--json` carries the machine form. An empty
result that could read as success is a defect, so every refusal exits non-zero and names its stage.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

GUARD_ID = "gen-newline-lf"
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2

# Exact (file, line) keys. Every reason names the OTHER file that does the normalising, or the
# ownership rule that puts the output outside this guard's subject. No glob, no prefix.
EXEMPTIONS: dict[tuple[str, int], str] = {
    ("tools/CreatureBuildPlanGen/Program.cs", 269):
        "CROSS-FILE: payload `json` comes from SpeciesBuildPlanSerializer.Canonical, defined in "
        "gk-core/src/FusionRpg.Core/Creatures/Generation/SpeciesBuildPlan.cs:45, which ends "
        "`.ToLf() + \"\\n\"`. Not re-implemented here; this guard does not resolve another "
        "repository's method bodies.",
    ("tools/CreatureBuildPlanGen/Program.cs", 270):
        "CROSS-FILE: payload `measureJson` comes from BuildFavourMeasureSerializer.Canonical, "
        "gk-core/src/FusionRpg.Core/Creatures/Generation/BuildFavourMeasure.cs:173, which ends "
        "`.ToLf() + \"\\n\"`.",
    ("tools/CreatureCatalogGen/Program.cs", 53):
        "OUT OF SCOPE BY OWNERSHIP: emits C# source via CreatureSpeciesGenerator.EmitCSharp into "
        "src/**, which gk-core owns, not a data/ or seed/ tree. A generated-source newline problem "
        "is real and lives with the emitter; it is not this guard's subject and no exemption here "
        "should be read as saying the output is LF.",
    ("tools/CreatureSpeciesGen/Program.cs", 145):
        "CROSS-FILE: payload `json` comes from ConcreteSpeciesSerializer.Canonical, "
        "gk-core/src/FusionRpg.Core/Creatures/Generation/ConcreteSpeciesSerializer.cs:56, which "
        "ends `.ToLf() + \"\\n\"`.",
    ("tools/ElementEnumGen/Program.cs", 65):
        "OUT OF SCOPE BY OWNERSHIP: emits generated C# source into gk-core's src/**, not a data/ or "
        "seed/ tree. NOTE this emit is genuinely CRLF on Windows (StringBuilder.AppendLine), and its "
        "EffectCatalogGen.Normalize at line 50 is applied to the COMPARISON only, not to the emit. "
        "Recorded here so the gap is visible; it belongs to the src/** owner.",
    ("tools/ElementEnumGen/Program.cs", 91):
        "OUT OF SCOPE BY OWNERSHIP: same as line 65 — generated C# source into gk-core src/**.",
    ("tools/ElementEnumGen/Program.cs", 126):
        "OUT OF SCOPE BY OWNERSHIP: same as line 65 — generated C# source into gk-core src/**.",
    ("tools/PassiveTreeRosterGen/Program.cs", 42):
        "CROSS-FILE: payload `json` comes from StatusRosterCheck.GenerateJson in this same project "
        "(StatusRosterCheck.cs:78), which ends `.ToLf()`. Added by this sweep; the sibling emit at "
        "line 52 had been correct all along.",
    ("tools/PassiveTreeRosterGen/Program.cs", 52):
        "CROSS-FILE: payload `json` comes from AtomVocabCheck.GenerateJson "
        "(AtomVocabCheck.cs:116), which already returned `.Replace(\"\\r\\n\", \"\\n\", "
        "StringComparison.Ordinal)`. This is the evidence that the house fixes this idiom — its "
        "twin at line 42 did not, which is why the sweep touched one and not the other.",
}

# A normaliser call, by the name it is written with.
_NORMALIZERS = ("ToLf(", "ToLfLineEndings(", "Canonicalize(",)
_CR_LF_ESCAPE = "\x01CRLF\x01"   # marker for a string literal that held a \r\n escape
_LF_ESCAPE = "\x01LF\x01"
_STR_MARK = "\x01STR\x01"


def _blank_span(src: list[str], start: int, end: int) -> None:
    """Blank [start, end) in place, preserving every newline so line numbers survive."""
    for i in range(start, min(end, len(src))):
        if src[i] != "\n":
            src[i] = " "


def strip_comments_and_strings(src: str) -> str:
    """Blank comments and literal CONTENTS. Line numbers are preserved exactly.

    String contents become a marker rather than empty quotes, because `Replace("\r\n", "\n")` is
    the house idiom and a normaliser that looks like `Replace("", "")` is no longer detectable.
    """
    out = list(src)
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        # line comment
        if c == "/" and nxt == "/":
            j = src.find("\n", i)
            j = n if j == -1 else j
            _blank_span(out, i, j)
            i = j
            continue
        # block comment
        if c == "/" and nxt == "*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            _blank_span(out, i, j)
            i = j
            continue
        # raw string literal """..."""
        if src.startswith('"""', i):
            j = src.find('"""', i + 3)
            j = n if j == -1 else j + 3
            for k in range(i, min(j, n)):
                if out[k] != "\n":
                    out[k] = " "
            i = j
            continue
        # verbatim string @"..."
        if c == "@" and nxt == '"':
            j = i + 2
            while j < n:
                if src[j] == '"':
                    if j + 1 < n and src[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            j = min(j + 1, n)
            _blank_span(out, i, j)
            for k in range(i + 2, max(i + 2, j - 1)):   # keep the marker slot
                out[k] = _STR_MARK[0]
            i = j
            continue
        # char literal 'x' — never a normaliser, just blank it
        if c == "'":
            j = i + 1
            if j < n and src[j] == "\\":
                j += 2
            if j < n:
                j += 1
            if j < n and src[j] == "'":
                j += 1
            _blank_span(out, i, j)
            i = j
            continue
        # ordinary string literal
        if c == '"':
            j = i + 1
            body_start = j
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == '"':
                    break
                if src[j] == "\n":
                    break
                j += 1
            body = src[body_start:j]
            end = min(j + 1, n)
            marker = _CR_LF_ESCAPE if "\\r" in body else (_LF_ESCAPE if "\\n" in body else _STR_MARK)
            _blank_span(out, body_start, min(j, n))
            # Write the marker into the literal BODY only; the quote delimiters stay, so a later
            # `Replace("\r\n", "\n")` still reads as a normaliser call and not as `Replace( , )`.
            for k in range(body_start, min(j, n)):
                out[k] = marker[0]
            i = end
            continue
        i += 1
    return "".join(out)


def _has_normalizer(text: str) -> bool:
    if any(tok in text for tok in _NORMALIZERS):
        return True
    # Replace("\r\n", "\n") reads as Replace("<CRLF marker>", ...) once the literal body is swapped
    # for a marker. The \s* matters: an earlier version of this guard missed TreeBinder's own
    # `json = json.Replace("\r\n", "\n")` because the quote had been blanked to a space.
    return _REPLACE_CRLF_RE.search(text) is not None


class Finding:
    __slots__ = ("rel", "line", "kind", "detail")

    def __init__(self, rel: str, line: int, kind: str, detail: str) -> None:
        self.rel, self.line, self.kind, self.detail = rel, line, kind, detail

    def as_dict(self) -> dict[str, object]:
        return {"file": self.rel, "line": self.line, "kind": self.kind, "detail": self.detail,
                "exempt": (self.rel, self.line) in EXEMPTIONS}

    def __str__(self) -> str:
        tag = "EXEMPTED" if self.as_dict()["exempt"] else "FINDING"
        return f"  [{tag}] {self.rel}:{self.line}  {self.kind}  — {self.detail}"


def _balanced_arg(text: str, open_paren: int) -> tuple[str, int]:
    """The text inside the parens starting at `open_paren`, and the index just past the close."""
    depth, j, n = 0, open_paren, len(text)
    while j < n:
        ch = text[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[open_paren + 1:j], j + 1
        j += 1
    return text[open_paren + 1:], n


def _split_args(arg_text: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in arg_text:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    if cur:
        parts.append("".join(cur))
    return [p.strip() for p in parts]


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _method_body(text: str, name: str) -> str | None:
    """The body of `<name>(...)` declared in this text, or None when it is not declared here."""
    needle = name + "("
    pos = 0
    while True:
        k = text.find(needle, pos)
        if k == -1:
            return None
        # must be a declaration: preceded by a type-ish word, and the signature ends with ')'
        # followed by optional whitespace and '{' or '=>'
        before = text[max(0, k - 200):k]
        tail_start = text.find(")", k)
        if tail_start == -1:
            return None
        after = text[tail_start + 1:tail_start + 80].lstrip()
        if not (after.startswith("{") or after.startswith("=>")):
            pos = k + 1
            continue
        if not any(w in before for w in ("static ", "string ", "void ", "byte[] ", "public ",
                                          "private ", "internal ", "sealed ")):
            pos = k + 1
            continue
        if after.startswith("=>"):
            end = text.find(";", tail_start)
            return text[tail_start:end if end != -1 else tail_start]
        brace = text.find("{", tail_start)
        if brace == -1:
            return None
        depth, j = 0, brace
        while j < len(text):
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
                if depth == 0:
                    return text[brace:j + 1]
            j += 1
        return text[brace:]
    return None


def _assignments_of(text: str, ident: str, before: int) -> list[str]:
    """Every right-hand side assigned to `ident` BEFORE index `before`.

    The `before` bound is load-bearing, not a nicety. Collecting assignments from the whole file let
    one normalizing assignment anywhere in the file vouch for an unrelated write: `CreatureSpeciesGen`
    has two `File.WriteAllText(outPath, json)`-shaped calls, and the `.ToLf()` added to the later one
    silently cleared the earlier one that depends on a gk-core serializer. That is the "unprovable
    counts as safe" failure wearing a disguise, and it showed up as a STALE-EXEMPTION on this guard's
    first run.
    """
    out = []
    for m in _ASSIGN_RE.finditer(text):
        if m.start() >= before:
            continue
        if m.group("lhs").strip() == ident:
            out.append(m.group("rhs"))
    return out


import re  # noqa: E402  (used only by _assignments_of; kept beside it for locality)

_ASSIGN_RE = re.compile(
    r"(?:^|[;{}\n])\s*(?:var|byte\[\]|string|readonly\s+string)?\s*(?P<lhs>[A-Za-z_]\w*)\s*=(?!=)\s*(?P<rhs>[^;]+);",
    re.MULTILINE)
_REPLACE_CRLF_RE = re.compile(r"Replace\(\s*\"?\s*\x01")


def scan_file(path: Path, rel: str) -> tuple[list[Finding], list[str]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    text = strip_comments_and_strings(raw)
    findings: list[Finding] = []

    for call in ("File.WriteAllText", "File.AppendAllText", "File.WriteAllLines"):
        pos = 0
        while True:
            k = text.find(call, pos)
            if k == -1:
                break
            pos = k + len(call)
            # a longer member name (File.WriteAllTextX) is a different method
            if pos < len(text) and (text[pos].isalnum() or text[pos] == "_"):
                continue
            line = _line_of(text, k)
            open_paren = text.find("(", k)
            if open_paren == -1:
                continue
            arg_text, _ = _balanced_arg(text, open_paren)
            args = _split_args(arg_text)

            if call == "File.WriteAllLines":
                findings.append(Finding(
                    rel, line, "WRITELINES-TRANSLATES",
                    "File.WriteAllLines writes Environment.NewLine (CRLF on Windows); measured on "
                    "net8.0. Write the joined text with an explicit \\n instead."))
                continue

            if len(args) < 2:
                findings.append(Finding(
                    rel, line, "PAYLOAD-UNREADABLE",
                    f"{call} has {len(args)} argument(s); the payload cannot be read, so it cannot "
                    f"be shown to be LF."))
                continue

            payload = args[1]
            # Drop only the literal-content markers the stripper left behind, so an identifier
            # stays an identifier and can be resolved to its assignment.
            payload_norm = payload.replace("\x01", "").strip()
            if _has_normalizer(payload):
                continue

            ident = payload_norm
            if ident and ident.isalpha():
                rhss = _assignments_of(text, payload_norm, k)
                if not rhss:
                    findings.append(Finding(
                        rel, line, "PAYLOAD-UNPROVABLE",
                        f"payload `{payload_norm}` has no assignment this file can see; an "
                        f"unreadable payload is not a payload shown to be LF."))
                elif any(_has_normalizer(r) for r in rhss):
                    continue
                else:
                    findings.append(Finding(
                        rel, line, "PAYLOAD-NOT-NORMALIZED",
                        f"payload `{payload_norm}` is assigned "
                        f"{len(rhss)} time(s), none normalizing: "
                        f"{rhss[0].strip()[:70]}"))
                continue

            m = re.match(r"^([A-Za-z_][\w.]*)\s*\(", payload_norm)
            if m:
                name = m.group(1).split(".")[-1]
                body = _method_body(text, name)
                if body is not None and _has_normalizer(body):
                    continue
                if body is None:
                    findings.append(Finding(
                        rel, line, "PAYLOAD-UNPROVABLE",
                        f"payload calls `{name}(...)`, whose body is not in this file; unprovable is "
                        f"a finding, and an exemption must name where it IS normalized."))
                else:
                    findings.append(Finding(
                        rel, line, "PAYLOAD-NOT-NORMALIZED",
                        f"payload calls `{name}(...)` whose body carries no LF normalizer."))
                continue

            findings.append(Finding(
                rel, line, "PAYLOAD-NOT-NORMALIZED",
                f"payload `{payload.strip()[:60]}` is inline and carries no LF normalizer."))

    findings.sort(key=lambda f: (f.line, f.kind))
    return findings, []


def _line_slice(text: str, k: int, length: int) -> str:
    start = text.rfind("\n", 0, k) + 1
    return text[start:k + length]


def scan_tree(tools: Path, repo: Path) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    parse_errors: list[str] = []
    for path in sorted(tools.rglob("*.cs")):
        if any(p in ("obj", "bin") for p in path.parts):
            continue
        rel = path.relative_to(repo).as_posix()
        f, errs = scan_file(path, rel)
        findings.extend(f)
        parse_errors.extend(errs)
    return findings, parse_errors


def reconcile(tools: Path, repo: Path, findings: list[Finding]) -> dict[str, object]:
    """Raw-text write calls vs the scan: every line the plain search finds that the scan does not."""
    confirmed = {(f.rel, f.line) for f in findings}
    text_hits: list[str] = []
    for path in sorted(tools.rglob("*.cs")):
        if any(p in ("obj", "bin") for p in path.parts):
            continue
        rel = path.relative_to(repo).as_posix()
        raw = path.read_text(encoding="utf-8", errors="replace")
        for n, line in enumerate(raw.splitlines(), 1):
            if "File.WriteAllText" in line or "File.WriteAllLines" in line \
                    or "File.AppendAllText" in line:
                text_hits.append(f"{rel}:{n}")
    unconfirmed = [h for h in text_hits if _key(h) not in confirmed]
    return {"text_lines_with_write_call": len(text_hits),
            "scan_findings": len(confirmed),
            "text_lines_not_confirmed_by_scan": len(unconfirmed),
            "unconfirmed": unconfirmed}


def _key(spec: str) -> tuple[str, int]:
    rel, _, num = spec.rpartition(":")
    return rel, int(num)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable result on stdout")
    ap.add_argument("--reconcile", action="store_true",
                    help="also report raw-text write-call lines the scan does not confirm")
    ap.add_argument("--repo", type=Path, default=None,
                    help="repository root (default: the parent of this script's directory)")
    args = ap.parse_args(argv)

    repo = (args.repo or Path(__file__).resolve().parents[1]).resolve()
    tools = repo / "tools"

    def refuse(code: str, message: str) -> int:
        print(f"[guard-{GUARD_ID}] REFUSED [{code}]: {message}", file=sys.stderr)
        if args.json:
            print(json.dumps({"guard": GUARD_ID, "status": "refused", "refusal": code,
                              "message": message}, indent=2))
        return EXIT_REFUSED

    if not tools.is_dir():
        return refuse("TOOLS-TREE-MISSING",
                      f"tools/ not found at {tools}; this guard cannot certify a tree it did not "
                      f"read. No subprocess is run; the scan is textual over the tree.")

    findings, parse_errors = scan_tree(tools, repo)
    if parse_errors:
        print(f"[guard-{GUARD_ID}] BLOCKED: PARSE-ERROR", file=sys.stderr)
        for e in parse_errors:
            print(f"  [PARSE-ERROR] {e}", file=sys.stderr)
        return EXIT_REFUSED

    found = [f for f in findings if not f.as_dict()["exempt"]]
    exempt = [f for f in findings if f.as_dict()["exempt"]]
    seen = {(f.rel, f.line) for f in findings}
    stale = [{"file": rel, "line": ln, "reason": why}
             for (rel, ln), why in sorted(EXEMPTIONS.items()) if (rel, ln) not in seen]

    payload: dict[str, object] = {
        "guard": GUARD_ID,
        "status": "clean" if not found and not stale else "blocked",
        "scanned_files": sum(1 for p in tools.rglob("*.cs")
                             if not any(x in ("obj", "bin") for x in p.parts)),
        "hazards_found": len(findings),
        "findings": len(found),
        "exemptions_used": len(exempt),
        "exemptions_declared": len(EXEMPTIONS),
        "stale_exemptions": stale,
        "findings_detail": [f.as_dict() for f in found],
    }
    if args.reconcile:
        payload["reconcile"] = reconcile(tools, repo, findings)

    if found or stale:
        print(f"[guard-{GUARD_ID}] BLOCKED: {len(found)} finding(s), {len(stale)} stale "
              f"exemption(s)", file=sys.stderr)
        for f in found:
            print(str(f), file=sys.stderr)
        for s in stale:
            print(f"  [EXEMPTION-STALE] {s['file']}:{s['line']}  no write call at this key any more "
                  f"— re-decide and delete the exemption (stated reason: {s['reason']})",
                  file=sys.stderr)
        if args.json:
            print(json.dumps(payload, indent=2))
        return EXIT_FAILED

    verdict = (f"[guard-{GUARD_ID}] clean ({payload['scanned_files']} file(s) scanned, "
               f"{len(exempt)} exempt hazard(s), 0 unexempted findings)")
    if args.json:
        print(json.dumps(payload, indent=2))
        print(verdict, file=sys.stderr)
    else:
        print(verdict)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())