"""The ONE seam is universal BY CONSTRUCTION, and this file is what makes that mechanical.

**Why this file exists.** `plumbing/authorer.py` is the seam: two modes (`api`, `delegated`),
two implementations (`ApiAuthorer`, `DelegatedAuthorer`), one entry point (`resolve_authorer`),
`DEFAULT_MODE = "api"`, and no fallback — if API mode is selected and no endpoint is configured
it raises `AUTHORING-NO-ENDPOINT` rather than quietly reaching for a sub-agent whose agent is
permitted to hand-edit the corpus (owner rulings C4 and C6).

Every production path that talks to a model already terminated in `pipeline/llm_caller.py`:
either `call_model`, which dispatches on `config.mode` and hands delegated mode to
`resolve_authorer`, or `live_answer_caller`, which resolves an authorer through `resolve_authorer`
directly. That is the correct shape and it was measured, not assumed — `_seam_wiring_measure.py`
in the parent directory reports it.

What was NOT true is that anything stopped the next adapter from routing around all of it. A new
module that called `urllib.request.urlopen` itself, or imported `ApiAuthorer` and constructed one,
or branched on the literal `"delegated"`, would reach a model with no seam, no default, and no
refusal — and every existing test would still pass, because they all exercise paths that go
through `llm_caller`. That is the shape of defect this guard closes: not "the seam is bypassed
today" but "the seam could be bypassed without anything noticing".

**What it does NOT do.** It does not police how many modules import `llm_caller`. Importing the
transport is the sanctioned shape — `plumbing/authorer.py`'s own docstring records that routing the
call sites through the dispatch point was deliberate, precisely so no adapter had to be edited.
A guard that demanded every adapter import `plumbing.authorer` would invert that decision and push
the seam's API back into 30 files.

**The rules**, each enforced in both directions — the repository must have zero violations AND each
detector must demonstrably fire on a synthetic offender. The second half is the part that stops a
broken scanner from reading as a passing guard; a detector that silently matches nothing would
otherwise be indistinguishable from a clean tree.

    G1 TRANSPORT_OWNER     Only `pipeline/llm_caller.py` may import an HTTP client able to reach
                           a model endpoint (`urllib.request`, `http.client`, `requests`, `httpx`,
                           `aiohttp`, `openai`). Relative imports cannot reach the network.
    G2 SEAM_ENTRY_ONLY     `ApiAuthorer`/`DelegatedAuthorer` are constructed only inside
                           `plumbing/authorer.py`. `resolve_authorer`/`DEFAULT_MODE`/`MODES` are
                           importable only by `pipeline/llm_caller.py`.
    G3 NO_MODE_LITERAL     No `if`/comparison outside the seam branches on the literal
                           `"delegated"` or `"api"`. Mode selection is the seam's decision.
    G4 SINGLE_HOME         `DEFAULT_MODE` and `MODES` are assigned in `plumbing/authorer.py` and
                           nowhere else. Two homes for the default is how they drift.
    G5 NO_STRAY_DELEGATED   The literal `"delegated"` outside the seam may appear only as an
                           argparse `choices=` declaration — the CLI surface declaring what the
                           operator may type. It is not a decision, and the decision still happens
                           in the seam.

**Documented exceptions.** `pipeline/llm_caller.py` is exempt from G1-G5 because it is not a
caller of the seam, it is the transport the seam delegates INTO: `ApiAuthorer.answer` calls back
into `llm_caller.call_model`, so that module must be able to name both the dispatch and the HTTP
client. `report/cli.py`'s `--mode` argparse declaration is the one allowed occurrence of the
`"delegated"` literal, and is what G5's rule permits. There are no other exceptions, and an
exception that is added to this list must carry its reason in a comment on the line — a seam with
silent exceptions is the defect this guard exists to prevent, reproduced one level up.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "seedsmith"
AUTHORER_REL = "plumbing/authorer.py"
TRANSPORT_REL = "pipeline/llm_caller.py"

#: Modules exempt from G1-G5, with the reason each one is exempt. Adding an entry here is a
#: design decision, not a convenience: the reason is part of the guard.
EXEMPT: dict[str, str] = {
    TRANSPORT_REL: (
        "the transport the seam delegates INTO - ApiAuthorer.answer calls back into "
        "llm_caller.call_model, so this module must name both the dispatch and the HTTP client"
    ),
    AUTHORER_REL: "the seam itself",
}

HTTP_ROOTS = {"requests", "httpx", "aiohttp", "openai"}
HTTP_SUBMODULES = {("urllib", "request"), ("http", "client")}

SEAM_ENTRY_NAMES = {"resolve_authorer", "DEFAULT_MODE", "MODES"}
SEAM_CLASSES = {"ApiAuthorer", "DelegatedAuthorer"}
MODE_LITERALS = {"api", "delegated"}


def _is_http_import(name: str) -> bool:
    """Whole-segment match. Never a bare ``startswith``: ``re`` is not ``requests``."""
    seg = [s for s in name.split(".") if s]
    if not seg:
        return False
    root = seg[0]
    if root in HTTP_ROOTS:
        return True
    if root in {"urllib", "http"}:
        # The stdlib parents alone cannot speak to a model; their client submodules can.
        return len(seg) >= 2 and (seg[0], seg[1]) in HTTP_SUBMODULES
    return False


def _tree(source: str) -> ast.Module:
    return ast.parse(source)


def _docstring_constants(tree: ast.Module) -> set[int]:
    """ids() of Constant nodes that are a bare docstring expression, not a value in use."""
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            out.add(id(node.value))
    return out


def _argparse_choice_positions(tree: ast.Module) -> set[int]:
    """ids() of Constant nodes belonging to an `add_argument(...)` call.

    Positional AND keyword arguments: `choices=` is a keyword, and reading only `node.args`
    missed all six `--mode` declarations in `report/cli.py`, which then showed up as six
    violations of a rule that explicitly permits them.
    """
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else "")
            if name.endswith("add_argument"):
                for arg in [*node.args, *(kw.value for kw in node.keywords)]:
                    for sub in ast.walk(arg):
                        if isinstance(sub, ast.Constant):
                            out.add(id(sub))
    return out


# --- the rules: each takes source text, so each can be self-tested on a synthetic offender ---


def g1_http_bypass(source: str, relpath: str) -> list[str]:
    """Only the transport module may import an HTTP client able to reach an endpoint."""
    out: list[str] = []
    for node in ast.walk(_tree(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_http_import(alias.name):
                    out.append(f"{relpath}:{node.lineno} imports {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue  # a relative import stays inside the package; it cannot open a socket
            base = node.module or ""
            if _is_http_import(base):
                out.append(f"{relpath}:{node.lineno} from {base} import ...")
            for alias in node.names:
                if _is_http_import(f"{base}.{alias.name}"):
                    out.append(f"{relpath}:{node.lineno} from {base} import {alias.name}")
    return out


def g2_seam_entry(source: str, relpath: str) -> list[str]:
    """Authorers are constructed only in the seam; its entry points are imported only by the transport."""
    out: list[str] = []
    for node in ast.walk(_tree(source)):
        if isinstance(node, ast.ImportFrom):
            imported = {a.name for a in node.names}
            tail = (node.module or "").lstrip(".").split(".")[-1]
            hit = imported & SEAM_ENTRY_NAMES
            if hit or tail in SEAM_ENTRY_NAMES:
                out.append(f"{relpath}:{node.lineno} imports seam entry {sorted(hit) or [tail]}")
        elif isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
            if name in SEAM_CLASSES:
                out.append(f"{relpath}:{node.lineno} constructs {name} directly")
    return out


def g3_mode_literal_branch(source: str, relpath: str) -> list[str]:
    """No branch outside the seam may decide on a mode literal."""
    out: list[str] = []
    for node in ast.walk(_tree(source)):
        if isinstance(node, ast.Compare):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and sub.value in MODE_LITERALS:
                    out.append(f"{relpath}:{node.lineno} compares against mode literal {sub.value!r}")
        elif isinstance(node, ast.If):
            for sub in ast.walk(node.test):
                if isinstance(sub, ast.Constant) and sub.value in MODE_LITERALS:
                    out.append(f"{relpath}:{node.lineno} branches on mode literal {sub.value!r}")
    return out


def g4_single_home(source: str, relpath: str) -> list[str]:
    """DEFAULT_MODE / MODES are assigned in one module only."""
    out: list[str] = []
    for node in ast.walk(_tree(source)):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id in {"DEFAULT_MODE", "MODES"}:
                out.append(f"{relpath}:{node.lineno} assigns {target.id}")
    return out


def g5_stray_delegated_literal(source: str, relpath: str) -> list[str]:
    """"delegated" outside the seam belongs in an argparse `choices=`, nowhere else."""
    tree = _tree(source)
    exempt = _docstring_constants(tree) | _argparse_choice_positions(tree)
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "delegated" and id(node) not in exempt:
            out.append(f"{relpath}:{node.lineno} uses the literal 'delegated' outside an add_argument")
    return out


RULES = (
    ("G1 transport owner", g1_http_bypass),
    ("G2 seam entry points", g2_seam_entry),
    ("G3 no mode-literal branch", g3_mode_literal_branch),
    ("G4 single home for the default", g4_single_home),
    ("G5 no stray delegated literal", g5_stray_delegated_literal),
)


def production_sources() -> list[tuple[str, str]]:
    """(relpath, source) for every module in the package, excluding __pycache__."""
    return [
        (p.relative_to(PKG).as_posix(), p.read_text(encoding="utf-8"))
        for p in sorted(PKG.rglob("*.py"))
        if "__pycache__" not in p.parts
    ]


def repo_violations() -> dict[str, list[str]]:
    """Every violation of every rule across the package, with the exempted modules skipped."""
    found: dict[str, list[str]] = {name: [] for name, _ in RULES}
    for relpath, source in production_sources():
        if relpath in EXEMPT:
            continue
        for name, rule in RULES:
            found[name].extend(rule(source, relpath))
    return found


class SeamUniversalityTests(unittest.TestCase):
    """The repository honours every rule."""

    def test_no_rule_is_violated_anywhere_in_the_package(self):
        found = repo_violations()
        report = "\n".join(f"  {name}: {v}" for name, v in found.items() if v)
        self.assertEqual(
            {k: len(v) for k, v in found.items() if v}, {},
            f"the seam is bypassed; route these through plumbing/authorer.py:\n{report}",
        )

    def test_the_exempt_modules_exist_and_are_the_ones_claimed(self):
        """An exemption list naming a file that is not there is a guard that guards nothing."""
        on_disk = {rel for rel, _ in production_sources()}
        for rel in EXEMPT:
            self.assertIn(rel, on_disk, f"{rel} is exempt but does not exist")
        self.assertEqual(EXEMPT[AUTHORER_REL], "the seam itself")

    def test_every_exemption_carries_a_reason(self):
        for rel, reason in EXEMPT.items():
            self.assertTrue(reason.strip(), f"{rel} is exempt with no stated reason")


class DetectorFiresTests(unittest.TestCase):
    """NON-VACUITY. Each rule must fire on a synthetic offender.

    Without this half, a detector that matches nothing is indistinguishable from a clean tree,
    and the guard above would be reporting success it had not earned. This is the check that
    keeps the guard from being the very kind of vacuous test it exists to forbid.
    """

    OFFENDERS = {
        "G1 transport owner": (
            "import urllib.request\n"
            "def go(url):\n"
            "    return urllib.request.urlopen(url).read()\n",
            g1_http_bypass,
        ),
        "G1 transport owner (requests)": (
            "import requests\n",
            g1_http_bypass,
        ),
        "G1 transport owner (from urllib import request)": (
            "from urllib import request\n",
            g1_http_bypass,
        ),
        "G2 seam entry points": (
            "from ..plumbing.authorer import resolve_authorer\n",
            g2_seam_entry,
        ),
        "G2 direct construction": (
            "from ..plumbing import authorer\n"
            "def go(config):\n"
            "    return authorer.ApiAuthorer(config)\n",
            g2_seam_entry,
        ),
        "G3 mode-literal branch": (
            "def go(mode):\n"
            "    if mode == 'delegated':\n"
            "        return 'agent'\n"
            "    return 'endpoint'\n",
            g3_mode_literal_branch,
        ),
        "G4 single home for the default": (
            "DEFAULT_MODE = 'delegated'\n",
            g4_single_home,
        ),
        "G5 stray delegated literal": (
            "def go():\n"
            "    return 'delegated'\n",
            g5_stray_delegated_literal,
        ),
    }

    def test_every_offender_is_caught(self):
        for label, (source, rule) in self.OFFENDERS.items():
            with self.subTest(offender=label):
                self.assertTrue(
                    rule(source, "synthetic.py"),
                    f"{label} was NOT detected - the rule cannot be trusted",
                )

    def test_every_rule_has_an_offender(self):
        """No rule may ship without a demonstration that it fires."""
        covered = {rule for _, rule in self.OFFENDERS.values()}
        for name, rule in RULES:
            with self.subTest(rule=name):
                self.assertIn(rule, covered, f"{name} has no non-vacuity offender")

    def test_clean_source_is_not_flagged_by_the_same_rules(self):
        """The mirror: a legitimate module must produce nothing, or every rule is noise."""
        clean = (
            '"""A module that does the sanctioned thing."""\n'
            "import json\n"
            "from ..pipeline.llm_caller import call_model, resolve_live_transport\n"
            "\n"
            "def run(brief):\n"
            '    config = resolve_live_transport("", "")\n'
            "    return call_model('sys', brief, config=config)\n"
        )
        for name, rule in RULES:
            with self.subTest(rule=name):
                self.assertEqual(rule(clean, "clean.py"), [], f"{name} flags a legitimate module")

    def test_a_docstring_naming_the_mode_is_not_a_decision(self):
        """G5 must not fire on prose. Comments never reach the AST; docstrings do."""
        source = (
            '"""Delegated mode is the owner\'s explicit request only."""\n'
            "def go():\n"
            "    return None\n"
        )
        self.assertEqual(g5_stray_delegated_literal(source, "prose.py"), [])

    def test_an_argparse_choices_declaration_is_allowed(self):
        """`--mode` with choices=(..., 'delegated') is the CLI surface, not a transport decision."""
        source = (
            "def build(p):\n"
            "    p.add_argument('--mode', default='', choices=('api', 'delegated'))\n"
        )
        self.assertEqual(g5_stray_delegated_literal(source, "cli.py"), [])


class ExceptionIsNarrowTests(unittest.TestCase):
    """The exemption list must not become a loophole."""

    def test_only_the_seam_and_the_transport_are_exempt(self):
        self.assertEqual(set(EXEMPT), {AUTHORER_REL, TRANSPORT_REL},
                         "a new exemption needs a deliberate edit and a reason, not an accident")

    def test_the_seam_itself_still_obeys_the_rules_that_apply_to_it(self):
        """Both authorers are built in exactly one function, and it is the seam's entry point.

        Note what this does NOT claim. An earlier version of this test asserted that
        `authorer.py` contains no mode literal at all, which is false by design: the seam is
        the place the mode is compared (`resolve_authorer`'s `chosen == "delegated"`) and where
        `ApiAuthorer.answer` pins its own config back to api before handing it down. Asserting
        the seam contains no decision would assert that the seam is not a seam.

        So the invariant is on CONSTRUCTION, which is the thing G2 can enforce everywhere else:
        the two `Authorer` implementations are instantiated in one function, and that function is
        `resolve_authorer`. A third construction site anywhere - a helper, an adapter, another
        branch inside the seam - fails here.
        """
        tree = ast.parse((PKG / AUTHORER_REL).read_text(encoding="utf-8"))
        builders: set[str] = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    fn = inner.func
                    name = (fn.id if isinstance(fn, ast.Name)
                            else fn.attr if isinstance(fn, ast.Attribute) else None)
                    if name in SEAM_CLASSES:
                        builders.add(node.name)
        self.assertEqual(builders, {"resolve_authorer"},
                         f"an authorer is built outside resolve_authorer: {sorted(builders)}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()