"""Measurement: who reaches the LLM transport directly, and who imports the seam.

This is the BASELINE, written before any routing change, so it stands on its own.

Three methods are computed, because "excluding comment lines and def lines" admits
more than one reading. Only the primary is quoted as the headline number.

  primary (AST, authoritative)
      Every `ast.Name` / `ast.Attribute` reference to the target identifier in the
      module body or inside any function. A `def` of that name is a binding, not a
      reference, so it is naturally excluded -- as are comments, docstrings and
      string literals. This is the count of "places a file mentions the transport".

  lines   (text, comment+def-line excluded)
      Occurrences of the bare name on a code line, excluding comment lines and the
      one line that defines a function *of that name*. This is the permissive
      reading: references inside other functions' bodies all count.

  lines_strict
      As `lines`, but excluding the whole signature of ANY function, i.e. only
      statement lines count. Kept because it is the narrowest reading and produces
      the smallest numbers.

`--json` prints the full report for diffing against a later run.
"""

from __future__ import annotations

import ast
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PKG = ROOT / "seedsmith"

TARGETS = (
    "resolve_live_transport",
    "live_answer_caller",
    "call_model",
    "call_with_self_heal",
)

SEAM = "authorer"
SEAM_REL = "plumbing/authorer.py"
TRANSPORT_REL = "pipeline/llm_caller.py"


def iter_sources() -> list[Path]:
    out: list[Path] = []
    for base in (PKG, ROOT / "tests"):
        if not base.exists():
            continue
        for p in base.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            out.append(p)
    return sorted(out)


def is_test(path: Path) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    if rel.startswith("tests/") or "/tests/" in rel:
        return True
    name = path.name
    return name.startswith("test_") or name.endswith("_test.py")


def ast_refs(path: Path) -> dict[str, list[int]] | None:
    """Line numbers of each real reference to a target identifier."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        print(f"WARN unparsed: {path}: {exc}", file=sys.stderr)
        return None
    hits: dict[str, list[int]] = defaultdict(list)
    targets = set(TARGETS)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in targets:
            hits[node.id].append(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr in targets:
            hits[node.attr].append(node.lineno)
    return hits


def ast_calls(path: Path) -> dict[str, list[int]] | None:
    """Line numbers of each actual CALL to a target.

    The strictest and least ambiguous count: a `def` is a binding, a comment is not
    code, and `foo` passed as a value is a reference but not a call site. This counts
    only `Call` nodes whose callee names a target.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        print(f"WARN unparsed: {path}: {exc}", file=sys.stderr)
        return None
    hits: dict[str, list[int]] = defaultdict(list)
    targets = set(TARGETS)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = None
        if isinstance(fn, ast.Name):
            name = fn.id
        elif isinstance(fn, ast.Attribute):
            name = fn.attr
        if name in targets:
            hits[name].append(node.lineno)
    return hits


def def_name_lines(path: Path) -> dict[str, set[int]]:
    """target -> line numbers of the `def`/class header binding that name."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return {}
    out: dict[str, set[int]] = defaultdict(set)
    for node in ast.walk(tree):
        name = getattr(node, "name", None)
        if name in TARGETS and hasattr(node, "lineno"):
            for deco in getattr(node, "decorator_list", []) or []:
                out[name].add(deco.lineno)
            out[name].add(node.lineno)
    return out


def all_def_header_lines(path: Path) -> set[int]:
    """Every line belonging to a `def`/`class` header (not its body)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return set()
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for deco in getattr(node, "decorator_list", []) or []:
            out.add(deco.lineno)
        start = node.lineno
        first_body = node.body[0].lineno if node.body else start
        out.update(range(start, max(start, first_body)))
    return out


def text_line_count(path: Path, skip: set[int], names: tuple[str, ...]) -> dict[str, int]:
    src = path.read_text(encoding="utf-8")
    counts: dict[str, int] = defaultdict(int)
    for i, raw in enumerate(src.splitlines(), start=1):
        if i in skip:
            continue
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        for n in names:
            counts[n] += raw.count(n)
    return counts


def imports_of(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            out.append("." * node.level + mod)
            for a in node.names:
                out.append(f"{'.' * node.level}{mod}.{a.name}".replace("..", "."))
        elif isinstance(node, ast.Import):
            for a in node.names:
                out.append(a.name)
    return out


def measure() -> dict:
    primary_prod = defaultdict(int)
    primary_test = defaultdict(int)
    lines_prod = defaultdict(int)
    lines_test = defaultdict(int)
    strict_prod = defaultdict(int)
    strict_test = defaultdict(int)
    files_prod: dict[str, dict[str, int]] = defaultdict(dict)
    files_test: dict[str, dict[str, int]] = defaultdict(dict)
    seam_importers: list[str] = []
    transport_importers: list[str] = []
    missing: list[str] = []
    call_prod = defaultdict(int)
    call_test = defaultdict(int)
    call_files_prod: dict[str, dict[str, int]] = defaultdict(dict)
    call_files_test: dict[str, dict[str, int]] = defaultdict(dict)

    for path in iter_sources():
        rel = path.relative_to(ROOT).as_posix()
        if rel.endswith(SEAM_REL) or rel.endswith(TRANSPORT_REL):
            continue

        refs = ast_refs(path)
        if refs is None:
            continue
        test_file = is_test(path)

        cs = ast_calls(path) or {}
        for tgt, lines in cs.items():
            if test_file:
                call_test[tgt] += len(lines)
                call_files_test[rel][tgt] = len(lines)
            else:
                call_prod[tgt] += len(lines)
                call_files_prod[rel][tgt] = len(lines)

        pc = {k: len(v) for k, v in refs.items()}
        lc = text_line_count(path, set().union(*def_name_lines(path).values()) if def_name_lines(path) else set(), TARGETS)
        sc = text_line_count(path, all_def_header_lines(path), TARGETS)

        for tgt in TARGETS:
            if pc.get(tgt):
                if test_file:
                    primary_test[tgt] += pc[tgt]
                else:
                    primary_prod[tgt] += pc[tgt]
            if lc.get(tgt):
                if test_file:
                    lines_test[tgt] += lc[tgt]
                else:
                    lines_prod[tgt] += lc[tgt]
            if sc.get(tgt):
                if test_file:
                    strict_test[tgt] += sc[tgt]
                else:
                    strict_prod[tgt] += sc[tgt]
            if pc.get(tgt):
                bucket = files_test if test_file else files_prod
                bucket[rel][tgt] = pc[tgt]

        if any(SEAM in m for m in imports_of(path)):
            seam_importers.append(rel)
        if any("llm_caller" in m for m in imports_of(path)):
            transport_importers.append(rel)

    for rel in (SEAM_REL, TRANSPORT_REL):
        if not (PKG / rel).exists():
            missing.append(rel)

    return {
        "root": str(ROOT),
        "seam_files_missing": missing,
        "primary_ast": {
            "production": {"total": sum(primary_prod.values()), "files": len(files_prod),
                           "per_symbol": dict(sorted(primary_prod.items()))},
            "tests": {"total": sum(primary_test.values()), "files": len(files_test),
                      "per_symbol": dict(sorted(primary_test.items()))},
        },
        "lines_defline_excluded": {
            "production": {"total": sum(lines_prod.values()), "per_symbol": dict(sorted(lines_prod.items()))},
            "tests": {"total": sum(lines_test.values()), "per_symbol": dict(sorted(lines_test.items()))},
        },
        "lines_all_headers_excluded": {
            "production": {"total": sum(strict_prod.values()), "per_symbol": dict(sorted(strict_prod.items()))},
            "tests": {"total": sum(strict_test.values()), "per_symbol": dict(sorted(strict_test.items()))},
        },
        "call_sites_ast": {
            "production": {"total": sum(call_prod.values()), "files": len(call_files_prod),
                           "per_symbol": dict(sorted(call_prod.items()))},
            "tests": {"total": sum(call_test.values()), "files": len(call_files_test),
                      "per_symbol": dict(sorted(call_test.items()))},
        },
        "seam_importers": sorted(seam_importers),
        "transport_importers_count": len(transport_importers),
        "production_call_files": {k: dict(v) for k, v in sorted(call_files_prod.items())},
        "test_call_files": {k: dict(v) for k, v in sorted(call_files_test.items())},
        "production_files": {k: dict(v) for k, v in sorted(files_prod.items())},
        "test_files": {k: dict(v) for k, v in sorted(files_test.items())},
    }


def main() -> int:
    r = measure()
    if "--json" in sys.argv:
        print(json.dumps(r, indent=2))
        return 0
    print("MISSING SEAM FILES:", r["seam_files_missing"] or "none")
    for label, key in (
        ("CALL SITES (ast.Call only) <-- headline", "call_sites_ast"),
        ("PRIMARY (ast references)", "primary_ast"),
        ("lines  (def-line excluded)", "lines_defline_excluded"),
        ("lines' (all def headers excluded)", "lines_all_headers_excluded"),
    ):
        print(f"\n== {label}")
        for kind in ("production", "tests"):
            b = r[key][kind]
            print(f"  {kind:11s} total={b['total']:4d} files={b.get('files', '-'):>3}  {b['per_symbol']}")
    print(f"\nseam ({SEAM_REL}) importers: {len(r['seam_importers'])}")
    for p in r["seam_importers"]:
        print(f"    {p}")
    print(f"\ntransport (llm_caller) importers: {r['transport_importers_count']}")
    print("\n== production files (primary ast)")
    for rel, counts in r["production_files"].items():
        print(f"    {rel:66s} {counts}")
    print("\n== test files (primary ast)")
    for rel, counts in r["test_files"].items():
        print(f"    {rel:66s} {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())