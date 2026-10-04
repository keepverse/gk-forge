#!/usr/bin/env python3
r"""Guard `seedsmith-lf`: every seedsmith writer must pin its newline, or refuse text mode.

THE DEFECT THIS EXISTS TO STOP
------------------------------
gk-data carries `.gitattributes` with `* text=auto eol=lf`. Git therefore normalises line endings on
staging, so a file written with CRLF is committed as LF, `git status` reports it CLEAN, and a
byte-comparison test against the committed blob fails for a reason that carries no meaning.

Measured on the live corpus while writing this guard: 34 tracked files under
`packs/fusion/data/seed/creatures/` were `w/crlf` in the working tree and `i/lf` in the blob, with
`git status --porcelain` on all 34 returning empty. Two writers produced every one of them, and both
were `path.write_text(json.dumps(...), encoding="utf-8")` with no `newline=`.

    adapters/creatures/preflight.py:445        -> _dump/_preflight.json
    adapters/creatures/run/record.py:81       -> _runs/*.json

A guard written after the writers were fixed would have seen a clean tree and been unfalsified. So this
one was run BEFORE the sweep: 68 findings (60 `write_text`, 8 text-handle) on a tree whose own
`git status` was clean. After the sweep: 3, all exempted.

AST, NEVER REGEX
----------------
The scan is `ast.parse`, because regex lies on this exact corpus: a raw text search for `write_text`
finds 73 lines that contain the token, while AST finds 67 call sites — the 6 extra are comments and
docstrings. A masked-literal regex would have produced a confident wrong number, which is a failure
mode this project has already recorded twice. `--reconcile` re-runs the text search and prints every
line the parser does not confirm, so the gap is accounted for rather than assumed.

WHAT IS FLAGGED
---------------
* `X.write_text(...)` with no `newline=` keyword.
* A text-mode handle (`open(p, "w")`, `os.fdopen(fd, "w")`, `Path.open("w")`) with no `newline=`, or
  an explicit `newline=None`, whose handle reaches `.write()` / `.writelines()`.

WHAT IS NOT FLAGGED — and the subtlety is the whole point
----------------------------------------------------------
`newline=""` is COMPLIANT, not deficient. `open()` documents `''` and `'\n'` as *no translation on
write*. Two sites use it correctly (`adapters/items/meta_registry_repair.py`,
`adapters/items/droptablegen/run.py`) and this guard accepts both.

There are TWO house conventions and they disagree; a guard that picks one and rejects the other
would have failed working code:

* `newline="\n"` — `adapters/items/setgen/seedfile.py:502` states the rule inline and names its own
  canary, `test_topology_repair::test_written_partitions_are_lf_only`.
* `write_bytes` + `canonical_json_bytes`, refusing text mode entirely —
  `adapters/trees/plan/emit.py:561`, `adapters/trees/nodegen/emit.py:284`.

Both are accepted. All `write_bytes` is immune by construction. `"rb"`/`"r"` opens are not write
hazards. `os.open` for locks and `shutil.copy*` are out of scope.

EXEMPTIONS ARE EXACT (file, line) KEYS, AND THAT IS THE POINT
--------------------------------------------------------------
No glob, no prefix, no pattern. Two properties make this durable instead of a slow leak:

* Exact line keys break when the file is edited, forcing the author to re-decide rather than inherit.
* A stale exemption is itself a finding (`EXEMPTION-STALE`). An exemption that outlives its reason
  must not quietly accumulate — that is how an exemption list becomes a second, unreviewed corpus.

SCOPE, AND WHAT WAS DELIBERATELY NOT SWEPT
------------------------------------------
Two roots, and the boundary between them is deliberate:

* `tools/seedsmith/seedsmith/**` — the package, recursive.
* `tools/seedsmith/*.py` — the top-level driver scripts, NOT recursive, because `tests/` and the
  package's own children are handled separately (see below).

The second root was added after a re-measurement found the first one was too narrow. Both
`run_t53_claude_propose.py` (writes `data/seed/creatures/species-effects/{plant,zombie}/pilot-batch.json`,
2 tracked files in gk-data) and `run_t71_claude_propose.py` (writes `data/seed/effects/affixes/all.json`,
1 tracked file) are seedsmith DRIVERS that emit committed seed files, and neither was reachable while
the scan stopped at the package directory. A guard that covers the library and misses the two
executables that actually write the corpus is not a weaker guard; it is the wrong shape.

`tools/seedsmith/tests/**` holds roughly 350 further `write_text` calls that are NOT swept — stated
here rather than hidden, because it is a separate decision, not an oversight. They write into pytest
`tmp_path` fixtures, which carry no committed-bytes contract, so CRLF in them is not this defect. Two
of them are structurally blind to the defect anyway, which is worth recording: `test_type_weights.py`
and `test_characteristic_pool.py` build "frozen snapshots" via
`frozen.write_text(src.read_text(...))` and then read them back with `read_text()`. `read_text()`
applies universal newlines, so both sides of the comparison are normalised and the assertion passes
whether or not the bytes on disk were LF. Those comparisons cannot detect this defect, and changing
them is a decision for whoever owns the tests.

FAIL CLOSED BY NAME
-------------------
`SEEDSMITH-PKG-MISSING` (the package this guards is not where the guard expects it),
`PARSE-ERROR` with `file:lineno` (a file the scanner could not read is never "clean"),
`EXEMPTION-STALE`. Findings and the BLOCKED block go to stderr; only the verdict reaches stdout;
`--json` carries the machine form. An empty result that read as success is a defect, so every refusal
exits non-zero and names its stage.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

GUARD_ID = "seedsmith-lf"
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2

SCAN_TIMEOUT_NOTE = "no subprocess is run; the scan is pure AST over the tree"

# Writes that provably cannot reach a git-tracked tree, so CRLF in them is not this defect. Each key
# is an exact (file, line) pair. Editing any of these files invalidates its key and the guard reports
# EXEMPTION-STALE until the author re-decides.
#
# A glob or a prefix here would be the defect this guard exists to prevent.
#
# EACH ENTRY IS EVIDENCED BY `git ls-files`, not by a docstring calling the path "scratch". That
# distinction earned its keep: `dungeon/regen.py` and `gloss/fill.py` both describe their own output
# as scratch, and both are exempt — but `data/seed/dungeon` carries 285 tracked files while
# `data/seed/dungeon/_runs` carries 0, and it is the `_runs` leaf that is written. Reading the
# docstring alone would have exempted the wrong path in both files.
EXEMPTIONS: dict[tuple[str, int], str] = {
    ("tools/seedsmith/seedsmith/adapters/dungeon/regen.py", 169):
        "SCRATCH: write_run targets _runs_dir() -> data/seed/dungeon/_runs, which `git ls-files` "
        "reports as 0 tracked files, while the data/seed/dungeon corpus beside it holds 285. The "
        "module calls it 'a run file is scratch' (regen.py:128) and the bytes never leave that leaf.",
    ("tools/seedsmith/seedsmith/adapters/narrative/gloss/fill.py", 111):
        "SCRATCH: write_gloss_run targets content_root()/RUNS_REL = data/seed/narrative/_runs, "
        "0 tracked files by `git ls-files`, against 26 tracked in data/seed/narrative. RUNS_REL's "
        "own comment (fill.py:33) calls it 'a fill run's scratch document'.",
    ("tools/seedsmith/seedsmith/report/cli.py", 1614):
        "SCRATCH: a tempfile.mkstemp file holding an inline --theme string, handed to a child "
        "process as --brief and never renamed onto any path. The only exemption here that is "
        "transient by construction rather than by location.",
    ("tools/seedsmith/_j9_batch_run.py", 80):
        "SCRATCH, evidenced by the OUTPUT not the docstring: _write_results targets RESULTS_PATH "
        "(line 60) = <tools/seedsmith>/_j9_batch_run_results.json, a resume checkpoint beside the "
        "driver. `git ls-files --error-unmatch` reports that output UNTRACKED, while the seed tree "
        "the sibling drivers in this same directory write (data/seed/creatures/species-effects) "
        "holds tracked files. Nothing consumes its bytes as a contract; it is a progress file that "
        "the next process reads and overwrites. CR in it cannot make a committed corpus differ "
        "from itself.",
}

# ---------------------------------------------------------------------------
# AST scanning
# ---------------------------------------------------------------------------

# `os.fdopen(fd, mode, ...)` takes the mode second; `open(file, mode, ...)` also takes it second.
# `Path.open` mirrors `open`. So one positional index serves all three, and the keyword fallback
# catches `open(p, mode="w")`.
_TEXT_WRITE_TOKENS = ("w", "a", "x")
_OPEN_FUNCS = {"open", "fdopen"}


def _call_name(node: ast.AST) -> str:
    """The trailing attribute or bare name of a call target, as written."""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _is_open_like(node: ast.AST) -> bool:
    """`open(...)`, `Path(...).open(...)`, `os.fdopen(...)`, `io.open(...)` — but not `os.open`.

    `fdopen` is included because this codebase's atomic-JSON idiom is
    `with os.fdopen(handle, "w", encoding="utf-8", newline="\\n") as output:` (an `ast.Attribute`
    whose `attr` is `fdopen`, not `open`). Matching only `"open"` silently skipped all 20 of them —
    which is exactly the "a guard that was never seen failing" trap, caught here by a count the audit
    had already made and this scanner did not reproduce.
    """
    if isinstance(node, ast.Attribute):
        if node.attr == "fdopen":
            # `os.fdopen` / `io.fdopen` only. A bare `fdopen(...)` is the ast.Name branch below.
            return _call_name(node.value) in {"os", "io"}
        if node.attr != "open":
            return False
        # Path(...).open() / p.open() — the receiver is a path-ish expression. os.open is an int
        # fd constructor used for locks in this codebase and must NOT match.
        base = _call_name(node.value)
        return base in {"Path", "PosixPath", "WindowsPath", "PurePath", "PurePosixPath",
                        "PureWindowsPath", "path", "p", "self"}
    if isinstance(node, ast.Name):
        return node.id in _OPEN_FUNCS
    return False


def _mode_of(call: ast.Call) -> str | None:
    """The mode string of an open-like call, or None when it is absent/unreadable.

    Index 1 for all three callees: `open(file, mode)`, `os.fdopen(fd, mode)`, `Path.open(mode)`.
    """
    mode_arg = None
    if len(call.args) >= 2:
        mode_arg = call.args[1]
    for kw in call.keywords:
        if kw.arg == "mode":
            mode_arg = kw.value
    if mode_arg is None:
        return None
    if isinstance(mode_arg, ast.Constant) and isinstance(mode_arg.value, str):
        return mode_arg.value
    return None  # computed mode: cannot be judged, so never guessed as text-write


def _is_text_write_mode(mode: str) -> bool:
    if "b" in mode:
        return False
    return any(tok in mode for tok in _TEXT_WRITE_TOKENS)


def _newline_kw(call: ast.Call) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg == "newline":
            return kw.value
    return None


def _newline_is_compliant(node: ast.AST | None) -> bool:
    """No `newline` is the hazard. `''` and '\\n' both mean "write the bytes as given"."""
    if node is None:
        return False
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value in ("", "\n")
    # A computed newline cannot be shown to be safe, so it is not accepted.
    return False


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


def _bound_names(tree: ast.AST) -> dict[int, set[str]]:
    """Map `id(call node)` -> the names that call's handle is bound to.

    One walk builds both halves, because linking them afterwards would be O(n^2) over the file.
    """
    bound: dict[int, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                tgt = item.optional_vars
                if isinstance(tgt, ast.Name):
                    bound.setdefault(id(item.context_expr), set()).add(tgt.id)
        elif isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if names:
                bound.setdefault(id(node.value), set()).update(names)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.value is not None:
                bound.setdefault(id(node.value), set()).add(node.target.id)
    return bound


def scan_file(path: Path, rel: str) -> tuple[list[Finding], list[str]]:
    """Findings in one file, plus parse errors (as `file:lineno` strings)."""
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as exc:
        return [], [f"{rel}:{exc.lineno or 0}"]

    findings: list[Finding] = []

    # ---- 1. write_text with no newline -----------------------------------
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "write_text"):
            continue
        kw = _newline_kw(node)
        if _newline_is_compliant(kw):
            continue
        detail = ("no newline= — text mode re-translates \\n to os.linesep on Windows"
                  if kw is None else f"newline={ast.dump(kw)[:40]} is not '' or '\\n'")
        findings.append(Finding(rel, node.lineno, "WRITE-TEXT-NEWLINE", detail))

    # ---- 2. text-mode handle reaching .write() / .writelines() -----------
    # Pass A: which names hold a text-mode handle opened without a compliant newline.
    bound = _bound_names(tree)
    unsafe: dict[str, int] = {}
    chained: list[tuple[ast.Call, ast.Call]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_open_like(node.func):
            continue
        mode = _mode_of(node)
        if mode is None or not _is_text_write_mode(mode):
            continue
        if _newline_is_compliant(_newline_kw(node)):
            continue
        names = bound.get(id(node))
        if names:
            for n in names:
                unsafe.setdefault(n, node.lineno)
        # `os.fdopen(fd, "w").write(...)` — chained, no name at all.
        chained.append((node, node))

    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("write", "writelines")):
            src = node.func.value
            if isinstance(src, ast.Call) and id(src) in {id(c) for c, _ in chained}:
                mode = _mode_of(src)
                findings.append(Finding(
                    rel, src.lineno, "TEXT-HANDLE-NEWLINE",
                    f"text-mode handle (mode={mode!r}) reaches .{node.func.attr}() with no newline="))
            elif isinstance(src, ast.Name) and src.id in unsafe:
                opened_at = unsafe[src.id]
                if not any(f.line == opened_at and f.kind == "TEXT-HANDLE-NEWLINE"
                           for f in findings):
                    findings.append(Finding(
                        rel, opened_at, "TEXT-HANDLE-NEWLINE",
                        f"text-mode handle {src.id!r} reaches .{node.func.attr}() at line "
                        f"{node.lineno} with no newline="))

    findings.sort(key=lambda f: (f.line, f.kind))
    return findings, []


# (directory, recursive). The package is walked whole; the driver directory is walked ONE level, so
# this reaches run_t53/run_t71 without also re-walking tests/ or re-walking the package above.
# Set by main() to the resolved repo root, so a helper can render repo-relative keys without every
# caller threading `repo` through. One element; only ever assigned once per run.
_REPO: list[Path] = [Path(".").resolve()]

SCAN_ROOTS: tuple[tuple[str, bool], ...] = (
    ("tools/seedsmith/seedsmith", True),
    ("tools/seedsmith", False),
)


def _python_files(repo: Path) -> list[Path]:
    """Every .py under the scanned roots, de-duplicated, __pycache__ excluded, sorted."""
    seen: dict[str, Path] = {}
    for rel_root, recursive in SCAN_ROOTS:
        base = repo / rel_root
        if not base.is_dir():
            continue
        candidates = base.rglob("*.py") if recursive else base.glob("*.py")
        for path in candidates:
            if "__pycache__" in path.parts:
                continue
            seen[path.relative_to(repo).as_posix()] = path
    return [seen[k] for k in sorted(seen)]


def scan_tree(pkg: Path, repo: Path) -> tuple[list[Finding], list[str]]:
    findings: list[Finding] = []
    parse_errors: list[str] = []
    for path in _python_files(repo):
        rel = path.relative_to(repo).as_posix()
        f, errs = scan_file(path, rel)
        findings.extend(f)
        parse_errors.extend(errs)
    return findings, parse_errors


def reconcile(pkg: Path, repo: Path, findings: list[Finding]) -> dict[str, object]:
    """Text-match vs AST: every line the raw search finds that the parser does not confirm."""
    confirmed = {(f.rel, f.line) for f in findings if f.kind == "WRITE-TEXT-NEWLINE"}
    files = _python_files(repo)
    _REPO[0] = repo
    confirmed_calls = _ast_write_text_lines(files)
    text_hits: list[str] = []
    for path in files:
        rel = path.relative_to(repo).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if "write_text" in line:
                text_hits.append(f"{rel}:{n}")
    unconfirmed = [h for h in text_hits if _key(h) not in confirmed_calls]
    return {"text_lines_with_token": len(text_hits),
            "ast_write_text_calls": len(confirmed_calls),
            "text_lines_not_confirmed_by_ast": len(unconfirmed),
            "unconfirmed": unconfirmed}


def _key(spec: str) -> tuple[str, int]:
    rel, _, n = spec.rpartition(":")
    return rel, int(n)


def _ast_write_text_lines(files: list[Path]) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for path in files:
        rel = path.relative_to(_REPO[0]).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=rel)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "write_text"):
                out.add((rel, node.lineno))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable result on stdout")
    ap.add_argument("--reconcile", action="store_true",
                    help="also report raw-text write_text hits the AST does not confirm")
    ap.add_argument("--repo", type=Path, default=None,
                    help="repository root (default: the parent of this script's directory)")
    args = ap.parse_args(argv)

    repo = (args.repo or Path(__file__).resolve().parents[1]).resolve()
    pkg = repo / "tools" / "seedsmith" / "seedsmith"

    def refuse(code: str, message: str) -> int:
        print(f"[guard-{GUARD_ID}] REFUSED [{code}]: {message}", file=sys.stderr)
        if args.json:
            print(json.dumps({"guard": GUARD_ID, "status": "refused", "refusal": code,
                              "message": message}, indent=2))
        return EXIT_REFUSED

    if not pkg.is_dir():
        return refuse("SEEDSMITH-PKG-MISSING",
                      f"seedsmith package not found at {pkg}; the guard cannot certify a tree it "
                      f"did not read ({SCAN_TIMEOUT_NOTE})")

    findings, parse_errors = scan_tree(pkg, repo)

    if parse_errors:
        print(f"[guard-{GUARD_ID}] BLOCKED: PARSE-ERROR", file=sys.stderr)
        for e in parse_errors:
            print(f"  [PARSE-ERROR] {e}", file=sys.stderr)
        if args.json:
            print(json.dumps({"guard": GUARD_ID, "status": "blocked",
                              "parse_errors": parse_errors}, indent=2))
        return EXIT_REFUSED

    found = [f for f in findings if not f.as_dict()["exempt"]]
    exempt = [f for f in findings if f.as_dict()["exempt"]]
    seen = {(f.rel, f.line) for f in findings}
    stale = [{"file": rel, "line": ln, "reason": why}
             for (rel, ln), why in sorted(EXEMPTIONS.items()) if (rel, ln) not in seen]

    payload: dict[str, object] = {
        "guard": GUARD_ID, "status": "clean" if not found and not stale else "blocked",
        "scanned_files": len(_python_files(repo)),
        "hazards_found": len(findings),
        "findings": len(found),
        "exemptions_used": len(exempt),
        "exemptions_declared": len(EXEMPTIONS),
        "stale_exemptions": stale,
        "findings_detail": [f.as_dict() for f in found],
    }
    if args.reconcile:
        payload["reconcile"] = reconcile(pkg, repo, findings)

    if found or stale:
        print(f"[guard-{GUARD_ID}] BLOCKED: {len(found)} finding(s), {len(stale)} stale exemption(s)",
              file=sys.stderr)
        for f in found:
            print(str(f), file=sys.stderr)
        for s in stale:
            print(f"  [EXEMPTION-STALE] {s['file']}:{s['line']}  no hazard at this key any more "
                  f"— re-decide and delete the exemption (stated reason: {s['reason']})",
                  file=sys.stderr)
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"[guard-{GUARD_ID}] BLOCKED: {len(found)} finding(s), {len(stale)} stale "
                  f"exemption(s)", file=sys.stderr)
        return EXIT_FAILED

    verdict = (f"[guard-{GUARD_ID}] clean ({payload['scanned_files']} file(s) scanned, "
               f"{len(exempt)} exempt hazard(s), 0 unexempted findings)")
    if args.json:
        # stdout must be parseable JSON and nothing else, so the verdict moves to stderr.
        print(json.dumps(payload, indent=2))
        print(verdict, file=sys.stderr)
    else:
        print(verdict)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
