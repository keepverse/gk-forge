"""Every production path that reaches a model goes through ONE seam and ONE config layer.

**This file is the merge of two guards that overlapped.** `test_seam_universality_guard.py`
(hereafter A) and `test_transport_seam_wiring.py` (hereafter B) both scanned the seedsmith package
for seam bypasses and disagreed about what a bypass even is. A was left unconsolidated pending an
owner decision; this is that decision, and the measurement behind it is in the commit body.

**WHAT THE TWO FILES ACTUALLY OVERLAPPED ON: one axis.** Both claimed ownership of "there is one
HTTP transport and `pipeline/llm_caller.py` is it" — A's rule `G1 TRANSPORT_OWNER` and B's shape
`W3`. Nothing else was duplicated. A alone held `G2` (seam entry), `G3` (mode literal), `G4`
(single home for the default) and `G5` (stray `delegated` literal); B alone held `W1` (a transport
config built outside the config layer) and `W2` (`DEFAULT_CONFIG` named outside it), and alone held
the widened scan root that covers the top-level driver scripts.

**THE DUPLICATION WAS NOT HARMLESS, AND MEASURED, IT WAS A LIVE DISAGREEMENT.** The two detectors
for the one shared axis fired on different spellings. Each therefore caught bypasses the other could
not see:

    spelling                          G1(A)   W3(B)
    import urllib.request              yes     yes
    import requests                    yes     yes
    import openai                      yes     NO     <- only A
    import urllib                      NO      yes    <- only B
    import urllib.parse                NO      yes    <- only B
    from urllib import parse           NO      yes    <- only B
    import http                        NO      yes    <- only B

Two guards, one property, two definitions, both green: an `import openai` bypass would have been
caught by one file and invisible to the other, and a bare `import urllib` the reverse. That is the
axis that is easiest to lose silently when two files are entangled, and it is why the rules are
merged rather than merely de-duplicated by deletion. `W3` is therefore FOLDED INTO `G1`: one rule,
one matcher, the union of both spellings, measured over the widened root. Nothing is dropped — the
shape code `W3` becomes the shape code `G1`, and every W3 fixture becomes a G1 fixture.

**THE OTHER HAZARD A MERGE CREATES, AND HOW IT IS STRUCTURALLY IMPOSSIBLE HERE.** A exempts the
seam (`plumbing/authorer.py`) and B does not; B exempts the reachability probe
(`action_run_preflight.py`) and A does not, because A never scanned the drivers where it lives. Merge
the two exemption sets naively and one of three things happens silently: the seam gains a
config-and-socket exemption it never had, the probe gains a mode-literal exemption it never needed, or
a single global exempt set is inherited from one file and the other's rules lose their legitimate
exemptions. So exemptions here are **per rule, not per file**: `EXEMPT[path]` maps a RULE CODE to the
reason that rule cannot apply to that file. Each entry below was measured — a rule is exempted from a
module only where that module measurably trips it:

    pipeline/llm_caller.py       G1 G2 G3 G5  +  W1 W2      (G4 does NOT trip it: no blanket)
    plumbing/authorer.py         G2 G3 G4 G5                 (no W exemption: it opens nothing)
    action_run_preflight.py      G1                          (no W1/W2: a probe may not freeze a config)

Removing three exemptions that were never used is a TIGHTENING, not a loosening: A exempted the
transport from `G4` and the seam from `G1` without either tripping, and B did not exempt the seam
from `W1`-`W3` because it needed none. `ExceptionIsNarrowTests` asserts that no file is exempt from
EVERY rule, so this table can never decay into a blanket that silences the guard.

**THE SCAN ROOT IS B's, because a package-rooted scan is how a committed hardcoded endpoint shipped.**
`tests/test_no_model_literal.py` reads `seedsmith/` only, so every driver in `tools/seedsmith/*.py`
was unchecked by any guard — which is how `_j9_poc_run.py` came to carry a committed endpoint and
model id. Every rule here therefore runs over the package AND the top-level drivers.

**ONE LIMIT IS DELIBERATELY RETAINED, and it is stated rather than inherited silently.** A relative
import cannot open a socket — it stays inside the package — so a relative import is skipped, and
B's detector firing on `from . import urllib` was a false positive (that is a local module of that
name, not an HTTP client). The consequence is honest and worth naming: a HTTP library VENDORED inside
the package under a relative import would not be caught by `G1`. Nothing does that today, and a
vendored transport is a different defect with a different guard.

**WHAT THIS FILE DOES NOT POLICE.** It does not police how many modules import `llm_caller`.
Importing the transport is the sanctioned shape — routing the call sites through the dispatch point
was deliberate, precisely so no adapter had to be edited.

**THIS FILE RUNS UNDER `python <this file>` WITH NO TEST FRAMEWORK**, deliberately. It is registered
in `gk-core/scripts/enforcement-registry.v1.json` as the guard `seedsmith-seam`, and that runner
dispatches a guard with `sys.executable <script>` on an interpreter it provisions itself. A guard that
imported `pytest` would go red on any machine without it — a red about a missing test dependency,
not about the seam — so everything below is `unittest`, which is also why pytest collects it.

    python tools/seedsmith/tests/test_transport_seam_wiring.py
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

# The tests directory is put on sys.path by sibling suites that import test helpers by name; this
# file imports nothing from the package, so the entry is inert here and kept because removing it
# would change collection for tests outside this file's scope.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TOOL_ROOT = Path(__file__).resolve().parent.parent
PKG = TOOL_ROOT / "seedsmith"
TRANSPORT_PATH = PKG / "pipeline" / "llm_caller.py"

#: Keys into `EXEMPT` and into the scan. A key CONTAINING a slash is package-relative
#: (`pipeline/llm_caller.py`); a key with no slash is a top-level driver in `tools/seedsmith/`. The
#: two namespaces cannot collide, because every package-relative path has at least one directory in
#: it, and one spelling for both is what lets the exemption table be checked against disk.
SEAM_REL = "plumbing/authorer.py"
TRANSPORT_REL = "pipeline/llm_caller.py"
PROBE_REL = "action_run_preflight.py"

#: Top-level driver scripts in `tools/seedsmith/`. They are committed, and at least one is driven by a
#: committed launcher, so they are production code — they just live beside the package rather than
#: inside it, which is exactly why a package-rooted scan misses them.
DRIVERS: "tuple[Path, ...]" = tuple(
    sorted(p for p in TOOL_ROOT.glob("*.py") if not p.name.startswith("conftest"))
)

#: Modules that mean "an HTTP transport able to reach a model endpoint". THIS IS THE UNION of the
#: two merged spellings, and it is the union that matters: `urllib`/`http` are counted as the bare
#: stdlib parents (B's breadth — `import urllib` is a transport reach) and `openai` is counted at
#: all (A's coverage, which B never had). Matching is on a WHOLE SEGMENT, never a `startswith`:
#: `re` is not `requests` and `myhttpx` is not `httpx`.
TRANSPORT_ROOTS = frozenset({"urllib", "http", "requests", "httpx", "aiohttp", "openai"})

#: The only two modes. Mode selection is the seam's decision and nothing else's.
MODE_LITERALS = frozenset({"api", "delegated"})

#: The seam's names. `resolve_authorer`/`DEFAULT_MODE`/`MODES` are importable only by the transport;
#: the two implementations are constructible only inside the seam.
SEAM_ENTRY_NAMES = frozenset({"resolve_authorer", "DEFAULT_MODE", "MODES"})
SEAM_CLASSES = frozenset({"ApiAuthorer", "DelegatedAuthorer"})

#: The config layer's names. `LlmCallerConfig` is the type a production site must NOT build, and
#: `DEFAULT_CONFIG` is the import-time freeze it must NOT name.
CONFIG_TYPE_NAME = "LlmCallerConfig"
CONFIG_BUILTIN_NAME = "DEFAULT_CONFIG"


# --- helpers -------------------------------------------------------------------------------------


def _tree(source: str) -> ast.Module:
    return ast.parse(source)


def _docstring_constants(tree: ast.Module) -> set[int]:
    """ids() of Constant nodes that are a bare expression, not a value in use.

    A SUPERSET of "the docstring at position 0 of a module/class/function": it marks every
    `Expr(Constant)`, which includes every genuine docstring and also a bare string statement.
    Narrowing this to only the conventional docstring positions would let G5 fire on prose a
    module states outside a docstring, which is the same false positive in a different position.
    """
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


def _callee_name(node: ast.Call) -> "str | None":
    """The name a call names, whether it is `f(...)` or `mod.f(...)`."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return getattr(func, "id", None)


def _arg_defaults(args: ast.arguments) -> "list[ast.expr | None]":
    """Every default argument of a signature, positional and keyword, aligned with its parameters."""
    positional = list(args.posonlyargs) + list(args.args)
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    defaults += list(args.kw_defaults)
    return defaults


def _named(node: ast.AST) -> "str | None":
    """The name an expression binds, whether `Name` or `Attribute`."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_transport_import(name: str) -> bool:
    """Whether `name` is an HTTP client able to reach a model endpoint. Whole-segment match."""
    seg = [s for s in name.split(".") if s]
    return bool(seg) and seg[0] in TRANSPORT_ROOTS


# --- the rules -----------------------------------------------------------------------------------
#
# Every rule has the shape `rule(source, key, *, exempt=False) -> list[str]` and returns findings
# formatted `f"{key}:{line}: {CODE}: {detail}"`. The CODE is the shape's own name, so a failure names
# the property that broke in the vocabulary its rule was declared in (`G1`-`G5` for the seam's
# universality, `W1`/`W2` for the config layer) and `exempt` is the single place a declared
# exemption is applied — never inside a rule.


def g1_transport_owner(source: str, key: str, *, exempt: bool = False) -> list[str]:
    """G1 (was also B's W3): only `pipeline/llm_caller.py` may open an HTTP transport.

    A relative import cannot open a socket — it stays inside the package — so it is skipped. See the
    module docstring for what that deliberately does not catch.
    """
    if exempt:
        return []
    out: list[str] = []
    for node in ast.walk(_tree(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_transport_import(alias.name):
                    out.append(f"{key}:{node.lineno}: G1: imports {alias.name}; only "
                               f"{TRANSPORT_REL} may open a transport, so a second one is outside "
                               f"the seam and outside its refusals")
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            base = node.module or ""
            if _is_transport_import(base):
                out.append(f"{key}:{node.lineno}: G1: from {base} import ...; only "
                           f"{TRANSPORT_REL} may open a transport, so a second one is outside "
                           f"the seam and outside its refusals")
            for alias in node.names:
                if _is_transport_import(f"{base}.{alias.name}"):
                    out.append(f"{key}:{node.lineno}: G1: from {base} import {alias.name}; only "
                               f"{TRANSPORT_REL} may open a transport, so a second one is outside "
                               f"the seam and outside its refusals")
    return out


def g2_seam_entry(source: str, key: str, *, exempt: bool = False) -> list[str]:
    """G2: the authorers are built only in the seam; its entry points are imported only by the transport."""
    if exempt:
        return []
    out: list[str] = []
    for node in ast.walk(_tree(source)):
        if isinstance(node, ast.ImportFrom):
            imported = {a.name for a in node.names}
            tail = (node.module or "").lstrip(".").split(".")[-1]
            hit = imported & SEAM_ENTRY_NAMES
            if hit or tail in SEAM_ENTRY_NAMES:
                out.append(f"{key}:{node.lineno}: G2: imports seam entry {sorted(hit) or [tail]}")
        elif isinstance(node, ast.Call):
            if _named(node.func) in SEAM_CLASSES:
                out.append(f"{key}:{node.lineno}: G2: constructs {_named(node.func)} directly")
    return out


def g3_mode_literal_branch(source: str, key: str, *, exempt: bool = False) -> list[str]:
    """G3: no branch outside the seam may decide on a mode literal."""
    if exempt:
        return []
    out: list[str] = []
    for node in ast.walk(_tree(source)):
        if isinstance(node, ast.Compare):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Constant) and sub.value in MODE_LITERALS:
                    out.append(f"{key}:{node.lineno}: G3: compares against mode literal "
                               f"{sub.value!r}")
        elif isinstance(node, ast.If):
            for sub in ast.walk(node.test):
                if isinstance(sub, ast.Constant) and sub.value in MODE_LITERALS:
                    out.append(f"{key}:{node.lineno}: G3: branches on mode literal {sub.value!r}")
    return out


def g4_single_home(source: str, key: str, *, exempt: bool = False) -> list[str]:
    """G4: DEFAULT_MODE / MODES are assigned in the seam and nowhere else."""
    if exempt:
        return []
    out: list[str] = []
    for node in ast.walk(_tree(source)):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Name) and target.id in SEAM_ENTRY_NAMES:
                out.append(f"{key}:{node.lineno}: G4: assigns {target.id}")
    return out


def g5_stray_delegated_literal(source: str, key: str, *, exempt: bool = False) -> list[str]:
    """G5: `"delegated"` outside the seam belongs in an argparse `choices=`, nowhere else."""
    if exempt:
        return []
    tree = _tree(source)
    skip = _docstring_constants(tree) | _argparse_choice_positions(tree)
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value == "delegated" and id(node) not in skip:
            out.append(f"{key}:{node.lineno}: G5: uses the literal 'delegated' outside an "
                       f"add_argument")
    return out


def w1_frozen_config(source: str, key: str, *, exempt: bool = False) -> list[str]:
    """W1: a transport config built outside the config layer, so its `mode` can never be chained."""
    if exempt:
        return []
    out: list[str] = []
    for node in ast.walk(_tree(source)):
        if isinstance(node, ast.Call) and _callee_name(node) == CONFIG_TYPE_NAME:
            out.append(f"{key}:{node.lineno}: W1: builds an {CONFIG_TYPE_NAME} outside "
                       f"{TRANSPORT_REL}; its `mode` can never come from the config chain, so this "
                       f"pipeline cannot be reached by SEEDSMITH_LLM_MODE=delegated. Pass None and "
                       f"let the chain resolve.")
    return out


def w2_import_time_config(source: str, key: str, *, exempt: bool = False) -> list[str]:
    """W2: the import-time built-in, named by its module-level name."""
    if exempt:
        return []
    out: list[str] = []
    for node in ast.walk(_tree(source)):
        if isinstance(node, ast.Name) and node.id == CONFIG_BUILTIN_NAME:
            out.append(f"{key}:{node.lineno}: W2: names {CONFIG_BUILTIN_NAME} outside "
                       f"{TRANSPORT_REL}; it is frozen at import, so the operator's "
                       f"endpoint/model/mode never reach this call.")
    return out


#: `(code, rule name, detector)`. The code is what a finding reports, so a failure names the shape
#: its rule was declared as.
RULES: "tuple[tuple[str, str, object], ...]" = (
    ("G1", "transport owner", g1_transport_owner),
    ("G2", "seam entry points", g2_seam_entry),
    ("G3", "no mode-literal branch", g3_mode_literal_branch),
    ("G4", "single home for the default", g4_single_home),
    ("G5", "no stray delegated literal", g5_stray_delegated_literal),
    ("W1", "no frozen transport config", w1_frozen_config),
    ("W2", "no import-time DEFAULT_CONFIG", w2_import_time_config),
)
CODES = tuple(code for code, _, _ in RULES)
G_CODES = CODES[:5]
W_CODES = CODES[5:]
RULE_BY_CODE = {code: (name, rule) for code, name, rule in RULES}

_REASON_TRANSPORT_SEAM = (
    "the transport the seam delegates INTO - ApiAuthorer.answer calls back into "
    "llm_caller.call_model, so this module must name both the dispatch and the HTTP client"
)
_REASON_TRANSPORT_CONFIG = (
    "the config layer itself - it owns LlmCallerConfig and DEFAULT_CONFIG, and it is the one "
    "module allowed to open a socket"
)
_REASON_SEAM = "the seam itself"
_REASON_PROBE = (
    "a reachability probe: it rewrites the caller's own /v1/chat/completions URL to /v1/models "
    "and asks whether the server is there. It sends no prompt, authors nothing, and has no seam "
    "to bypass"
)

#: PER-RULE EXEMPTIONS. `EXEMPT[path][CODE] = reason`, so a rule can be excused for one module and
#: still be enforced on every other. Every entry is measured: a module appears under a code only
#: where that module actually trips it, and the narrowness is asserted rather than hoped for.
EXEMPT: "dict[str, dict[str, str]]" = {
    TRANSPORT_REL: {
        "G1": _REASON_TRANSPORT_SEAM,
        "G2": _REASON_TRANSPORT_SEAM,
        "G3": _REASON_TRANSPORT_SEAM,
        "G5": _REASON_TRANSPORT_SEAM,
        "W1": _REASON_TRANSPORT_CONFIG,
        "W2": _REASON_TRANSPORT_CONFIG,
    },
    SEAM_REL: {"G2": _REASON_SEAM, "G3": _REASON_SEAM, "G4": _REASON_SEAM, "G5": _REASON_SEAM},
    PROBE_REL: {"G1": _REASON_PROBE},
}

#: Production sites that bind the seam's transport as an INJECTABLE CALLABLE rather than calling it
#: through (`caller=call_model`, `caller = call or call_model`, or passing a `CallFn` down).
#: Listed, not tolerated: each is reviewed as legitimate because the config it forwards still
#: resolves through the chain, and a stub callable is what lets a test prove a path makes zero
#: calls. A new one is added here deliberately, never by accident.
#:
#: The name says "defaults" because these are injectable parameters; MEASURED, three of the seven
#: bind the transport through `call or call_model` rather than in a default argument, so the list is
#: an inventory of injected callables rather than of default arguments specifically. What every
#: entry has in common — and what `InjectedCallableTests` enforces — is that it imports the seam's
#: own transport, so the entry is still the thing it was reviewed as.
ALLOWED_INJECTED_CALLABLES: "frozenset[str]" = frozenset({
    "seedsmith/adapters/dungeon/pipelines.py",
    "seedsmith/adapters/items/uniques/pipelines.py",
    "seedsmith/adapters/items/setgen/run.py",
    "seedsmith/adapters/narrative/gloss/fill.py",
    "seedsmith/adapters/narrative/preflight.py",
    "seedsmith/adapters/structures/generate_anchor.py",
    "seedsmith/workflow/nodes/generate.py",
})


def _path_for_key(key: str) -> Path:
    """The file a scan key names. A slash means package-relative; no slash means a top-level driver."""
    return PKG / key if "/" in key else TOOL_ROOT / key


def production_sources() -> "list[tuple[str, str]]":
    """`(key, source)` for every production module: the package AND the top-level drivers.

    The driver half is not optional. `tests/test_no_model_literal.py` scans `seedsmith/` only, so
    before this root was widened every driver in `tools/seedsmith/*.py` was unchecked by any guard,
    and a committed hardcoded endpoint in `_j9_poc_run.py` shipped through that hole.
    """
    out = [(p.relative_to(PKG).as_posix(), p.read_text(encoding="utf-8"))
           for p in sorted(PKG.rglob("*.py")) if "__pycache__" not in p.parts]
    out += [(p.name, p.read_text(encoding="utf-8")) for p in DRIVERS]
    return out


def findings(code: str, source: str, *, key: str = "<fixture>", exempt: bool = False) -> "list[str]":
    """Every finding of one rule over one source. `exempt=True` applies a declared exemption."""
    return list(RULE_BY_CODE[code][1](source, key, exempt=exempt))  # type: ignore[operator]


def repo_violations() -> "dict[str, list[str]]":
    """Every finding of every rule across the widened root, with the declared exemptions applied."""
    found: "dict[str, list[str]]" = {code: [] for code in CODES}
    for key, source in production_sources():
        allowed = EXEMPT.get(key, {})
        for code in CODES:
            found[code] += findings(code, source, key=key, exempt=code in allowed)
    return found


# --- the repository honours every rule --------------------------------------------------------------


class RepositoryHonoursEveryRuleTests(unittest.TestCase):
    """The production tree violates nothing, over the WIDENED root."""

    def test_no_rule_is_violated_anywhere(self):
        found = repo_violations()
        report = "\n".join(f"  {code}: {v}" for code, v in found.items() if v)
        self.assertEqual(
            {code: len(v) for code, v in found.items() if v}, {},
            f"the seam is bypassed; route these through {SEAM_REL} and {TRANSPORT_REL}:\n{report}",
        )

    def test_the_scan_covers_the_top_level_drivers_not_just_the_package(self):
        """The hole that let a committed hardcoded endpoint through: a package-rooted scan.

        If this ever finds zero drivers, the scan has silently narrowed and would report green over
        files it never read.
        """
        self.assertTrue(DRIVERS, "no driver scripts found - the scan root moved and this guard is "
                                 "now vacuous")
        names = {p.name for p in DRIVERS}
        self.assertIn("_j9_batch_run.py", names, f"expected driver missing from the scan: {sorted(names)}")
        scanned = {key for key, _ in production_sources()}
        for driver in DRIVERS:
            self.assertIn(driver.name, scanned, f"driver {driver.name} is on disk but unread")

    def test_the_config_layer_is_exempt_because_it_is_the_config_layer(self):
        """The transport may build a config, name the import-time one, and open a socket."""
        source = (f"cfg = {CONFIG_TYPE_NAME}()\n"
                  "import urllib.request\n"
                  f"C = {CONFIG_BUILTIN_NAME}\n")
        for code in ("W1", "W2", "G1"):
            self.assertEqual(findings(code, source, exempt=True), [],
                             f"{code} does not honour a declared exemption")


# --- NON-VACUITY: every rule fires on a synthetic offender -------------------------------------------


class DetectorFiresTests(unittest.TestCase):
    """Each rule must demonstrably fire on a synthetic offender.

    Without this half, a detector that matches nothing is indistinguishable from a clean tree, and
    the guard above would be reporting success it had not earned. This is the check that keeps the
    guard from being the very kind of vacuous test it exists to forbid.
    """

    OFFENDERS = {
        # --- G1 transport owner. The first three are the merged detector's OWN spellings; the next
        # five are the ones only one of the two merged detectors caught, kept here because each one
        # is a bypass that the other detector would have missed.
        "G1 transport owner (urllib.request)": (
            "import urllib.request\n"
            "def go(url):\n"
            "    return urllib.request.urlopen(url).read()\n",
            "G1",
        ),
        "G1 transport owner (requests)": ("import requests\n", "G1"),
        "G1 transport owner (from urllib import request)": ("from urllib import request\n", "G1"),
        "G1 transport owner (from urllib.request import urlopen)": (
            "from urllib.request import urlopen\n", "G1"),
        "G1 transport owner (http.client)": ("import http.client\n", "G1"),
        "G1 transport owner (bare urllib parent - only the merged spelling caught this)": (
            "import urllib\n", "G1"),
        "G1 transport owner (urllib.parse import)": ("import urllib.parse\n", "G1"),
        "G1 transport owner (from urllib import parse)": ("from urllib import parse\n", "G1"),
        "G1 transport owner (bare http parent)": ("import http\n", "G1"),
        "G1 transport owner (openai SDK - only the merged spelling caught this)": (
            "import openai\n", "G1"),
        "G2 seam entry points": ("from ..plumbing.authorer import resolve_authorer\n", "G2"),
        "G2 direct construction": (
            "from ..plumbing import authorer\n"
            "def go(config):\n"
            "    return authorer.ApiAuthorer(config)\n",
            "G2",
        ),
        "G3 mode-literal branch": (
            "def go(mode):\n"
            "    if mode == 'delegated':\n"
            "        return 'agent'\n"
            "    return 'endpoint'\n",
            "G3",
        ),
        "G4 single home for the default": ("DEFAULT_MODE = 'delegated'\n", "G4"),
        "G5 stray delegated literal": ("def go():\n    return 'delegated'\n", "G5"),
        "W1 frozen transport config": ("cfg = LlmCallerConfig()\n", "W1"),
        "W1 frozen config as a default argument": ("def f(config=LlmCallerConfig()):\n    pass\n", "W1"),
        "W2 import-time DEFAULT_CONFIG": ("cfg = DEFAULT_CONFIG\n", "W2"),
    }

    def test_every_offender_is_caught(self):
        for label, (source, code) in self.OFFENDERS.items():
            with self.subTest(offender=label):
                self.assertTrue(
                    findings(code, source, key="synthetic.py"),
                    f"{label} was NOT detected - the rule cannot be trusted",
                )

    def test_every_rule_has_an_offender(self):
        """No rule may ship without a demonstration that it fires."""
        covered = {code for _, code in self.OFFENDERS.values()}
        for code in CODES:
            with self.subTest(rule=code):
                self.assertIn(code, covered, f"{code} has no non-vacuity offender")

    def test_every_offender_fires_the_rule_it_is_attributed_to(self):
        """A fixture must not pass on the credit of a NEARBY rule.

        What it may legitimately do is violate TWO rules — a mode literal is both a decision (G3) and
        a stray `'delegated'` (G5) — so co-firing is not a defect. What would be a defect is a
        fixture attributed to `G3` that only trips `G5`: that is a fixture proving nothing about the
        shape it names. So the attributed code must fire, AND any code that also fires must already
        have an offender of its own rather than borrowing this fixture's proof.
        """
        proved = {code for _, code in self.OFFENDERS.values()}
        for label, (source, code) in self.OFFENDERS.items():
            fired = [c for c in CODES if findings(c, source, key="s.py")]
            with self.subTest(offender=label):
                self.assertIn(code, fired,
                              f"{label} is attributed to {code} but that rule does not fire on it")
                for other in fired:
                    self.assertIn(other, proved,
                                  f"{label} also trips {other}, which has no offender of its own")

    def test_clean_source_is_not_flagged_by_any_rule(self):
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
        for code in CODES:
            with self.subTest(rule=code):
                self.assertEqual(findings(code, clean, key="clean.py"), [],
                                 f"{code} flags a legitimate module")

    def test_a_docstring_naming_the_mode_is_not_a_decision(self):
        """G5 must not fire on prose. Comments never reach the AST; docstrings do."""
        source = (
            "'''Delegated mode is the owner's explicit request only.'''\n"
            "def go():\n"
            "    return None\n"
        )
        self.assertEqual(findings("G5", source, key="prose.py"), [])

    def test_an_argparse_choices_declaration_is_allowed(self):
        """`--mode` with choices=(..., 'delegated') is the CLI surface, not a transport decision."""
        source = (
            "def build(p):\n"
            "    p.add_argument('--mode', default='', choices=('api', 'delegated'))\n"
        )
        self.assertEqual(findings("G5", source, key="cli.py"), [])

    def test_prose_naming_a_transport_is_not_code_reaching_past_the_seam(self):
        """A module documenting the rule, or commenting on it, has not bypassed anything."""
        source = ('"""Prose: urllib.request lives only in llm_caller."""\n'
                  "# a comment naming requests is invisible to ast\n"
                  "X = 1\n")
        self.assertEqual(findings("G1", source, key="prose.py"), [])
        self.assertEqual(findings("G2", source, key="prose.py"), [])
        self.assertEqual(findings("W1", source, key="prose.py"), [])
        self.assertEqual(findings("W2", source, key="prose.py"), [])

    def test_a_same_named_local_import_is_not_a_transport(self):
        """`import re`, `import os`, `import requests_` — a whole-segment match, never `startswith`."""
        for source in ("import re\n", "import os\n", "import requests_\n",
                       "import http_helpers\n", "import myhttpx\n", "from os import path\n"):
            with self.subTest(source=source.strip()):
                self.assertEqual(findings("G1", source, key="local.py"), [])

    def test_an_ordinary_use_of_the_config_type_is_not_a_config_being_built(self):
        """A type annotation or an `isinstance` check does not freeze anything at import."""
        self.assertEqual(findings("W1", "def f(config: LlmCallerConfig | None = None):\n    pass\n",
                                  key="a.py"), [])
        self.assertEqual(findings("W1", "assert isinstance(cfg, LlmCallerConfig)\n", key="a.py"), [])
        # ...and the sanctioned resolutions produce nothing either.
        self.assertEqual(findings("W1", "cfg = load_config()\n", key="a.py"), [])
        self.assertEqual(findings("W1", "cfg = resolve_live_transport()\n", key="a.py"), [])

    def test_a_transport_bound_as_an_injectable_callable_is_not_a_frozen_config(self):
        """The documented W4 exception, asserted rather than left implied by an absence.

        `caller=call_model` and `caller = call or call_model` bind the seam's own transport so a test
        can stub it. W1 matches a CONSTRUCTION of the config type, and neither spelling constructs
        one, so both are clean - which is a claim worth testing rather than assuming.
        """
        for source in ("def f(caller=call_model):\n    return caller\n",
                       "def f(call=None):\n    caller = call or call_model\n    return caller\n",
                       "def f(caller=call_with_self_heal):\n    return caller\n"):
            with self.subTest(source=source.splitlines()[0]):
                self.assertEqual(findings("W1", source, key="inject.py"), [])
                self.assertEqual(findings("W2", source, key="inject.py"), [])
        # And the read side of the same helper must still work, or the exception above is untested.
        # `_arg_defaults` yields NODES, so a literal default is a Constant and `_named` reads None for
        # it; only the `c=call_model` default is a name.
        defaults = _arg_defaults(ast.parse("def f(a, b=1, *, c=call_model):\n    pass\n"
                                          ).body[0].args)
        self.assertEqual([_named(d) for d in defaults], [None, None, "call_model"])

    def test_the_injected_callable_allowlist_still_names_real_files(self):
        """An allowlist whose entries no longer exist is an allowlist that stopped reviewing anything."""
        for rel in sorted(ALLOWED_INJECTED_CALLABLES):
            with self.subTest(entry=rel):
                self.assertTrue((TOOL_ROOT / rel).is_file(), f"allowlisted seam site is gone: {rel}")

    def test_every_allowlisted_site_still_binds_the_seams_own_transport(self):
        """What makes an entry the thing it was reviewed as: it reaches the model THROUGH the seam.

        A listed site that stopped importing `call_model` has become a second transport by another
        name, and its entry is now describing nothing.
        """
        for rel in sorted(ALLOWED_INJECTED_CALLABLES):
            with self.subTest(entry=rel):
                tree = ast.parse((TOOL_ROOT / rel).read_text(encoding="utf-8"))
                imported = any(
                    isinstance(node, ast.ImportFrom)
                    and (node.module or "").endswith("llm_caller")
                    and "call_model" in {a.name for a in node.names}
                    for node in ast.walk(tree)
                )
                self.assertTrue(imported, f"{rel} is allowlisted as an injected seam callable but "
                                           f"no longer imports call_model")


# --- the exemption table must not become a loophole ---------------------------------------------------


class ExceptionIsNarrowTests(unittest.TestCase):
    """Every exemption is measured, per rule, and justified."""

    def test_only_the_three_measured_modules_are_exempt(self):
        """A new exemption needs a deliberate edit and a reason, not an accident.

        The three are the transport (which IS the transport and the config layer), the seam (which
        IS where the mode is decided), and the reachability probe (which authors nothing).
        """
        self.assertEqual(set(EXEMPT), {TRANSPORT_REL, SEAM_REL, PROBE_REL},
                         "a new exemption needs a deliberate edit and a reason, not an accident")

    def test_every_exempt_module_exists_and_is_scanned(self):
        """An exemption naming a file that is not there is a guard that guards nothing."""
        scanned = {key for key, _ in production_sources()}
        for key in EXEMPT:
            with self.subTest(module=key):
                self.assertTrue(_path_for_key(key).is_file(), f"{key} is exempt but does not exist")
                self.assertIn(key, scanned, f"{key} is exempt but is not in the scan root")

    def test_every_exemption_carries_a_reason(self):
        for key, per_rule in EXEMPT.items():
            for code, reason in per_rule.items():
                with self.subTest(module=key, rule=code):
                    self.assertTrue(reason.strip(), f"{key} is exempt from {code} with no reason")

    def test_the_seam_is_exempt_only_from_the_rules_it_must_be(self):
        """The seam may not gain a config or socket exemption it never had.

        It opens no socket and freezes no config, so W1/W2 apply to it in full - and G1 too, because
        the seam must never be the thing that reaches an endpoint directly.
        """
        self.assertEqual(set(EXEMPT[SEAM_REL]), {"G2", "G3", "G4", "G5"},
                         "the seam's exemption widened; it must be exactly the rules it measurably trips")

    def test_the_seam_reason_is_still_the_seam_itself(self):
        for code, reason in EXEMPT[SEAM_REL].items():
            self.assertEqual(reason, "the seam itself", f"G{code} lost the seam's own reason")

    def test_the_transport_is_exempt_from_the_config_layer_rules_and_no_others(self):
        """It builds the config, so W1/W2 cannot apply - but G4 does, and does apply.

        `llm_caller.py` assigns neither `DEFAULT_MODE` nor `MODES`, so exempting it from G4 would
        be an exemption nothing uses: a hole with no bypass behind it.
        """
        self.assertEqual(set(EXEMPT[TRANSPORT_REL]), {"G1", "G2", "G3", "G5", "W1", "W2"})
        self.assertIn("G4", CODES)
        self.assertNotIn("G4", EXEMPT[TRANSPORT_REL],
                         "the transport does not assign the default, so G4 must stay enforced on it")

    def test_the_probe_may_open_a_socket_but_never_freeze_a_config(self):
        """It exists to ask whether the endpoint is configured; it must never build one."""
        self.assertEqual(set(EXEMPT[PROBE_REL]), {"G1"})
        self.assertFalse(set(EXEMPT[PROBE_REL]) & set(W_CODES),
                         "the reachability probe may not gain a config-build exemption")

    def test_no_module_is_exempt_from_every_rule(self):
        """THE BLANKET CHECK. If one file were exempt from all of them, every rule would be
        unenforceable against it and a mistake in this table would be silent."""
        for key, per_rule in EXEMPT.items():
            with self.subTest(module=key):
                self.assertNotEqual(set(per_rule), set(CODES),
                                    f"{key} is exempt from EVERY rule; the table has become a blanket")

    def test_every_rule_can_still_be_violated_by_something(self):
        """A rule every exempt module is excused from would be a rule no file is subject to."""
        for code in CODES:
            with self.subTest(rule=code):
                self.assertTrue(
                    any(code not in EXEMPT.get(key, {}) for key, _ in production_sources()),
                    f"{code} is excused from every scanned module",
                )

    def test_the_seam_builds_both_authorers_in_exactly_one_function(self):
        """Both implementations are instantiated in `resolve_authorer` and nowhere else.

        Note what this does NOT claim. An earlier version asserted that `authorer.py` contains no
        mode literal at all, which is false by design: the seam is the place the mode is compared
        and where `ApiAuthorer.answer` pins its own config back to api. Asserting the seam contains
        no decision would assert that the seam is not a seam.

        So the invariant is on CONSTRUCTION, which is what G2 enforces everywhere else: a third
        construction site anywhere - a helper, an adapter, another branch inside the seam - fails
        here.
        """
        tree = _tree((PKG / SEAM_REL).read_text(encoding="utf-8"))
        builders: "set[str]" = set()
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call) and _named(inner.func) in SEAM_CLASSES:
                    builders.add(node.name)
        self.assertEqual(builders, {"resolve_authorer"},
                         f"an authorer is built outside resolve_authorer: {sorted(builders)}")

    def test_the_exemptions_are_the_ones_the_rules_actually_need(self):
        """MEASURED, not asserted by hand: every entry is a rule that module really trips.

        This is the anti-decay check on the whole table. A reason that no longer describes a real
        violation goes red here rather than silently widening the exemption.
        """
        for key, per_rule in EXEMPT.items():
            source = _path_for_key(key).read_text(encoding="utf-8")
            for code in CODES:
                trips = bool(findings(code, source, key=key))
                with self.subTest(module=key, rule=code):
                    self.assertEqual(
                        code in per_rule, trips,
                        f"{key}: exemption from {code} {'does not match' if trips else 'overstates'} "
                        f"what the rule finds there",
                    )


if __name__ == "__main__":  # pragma: no cover - dev entrypoint and the registry's dispatch path
    unittest.main()