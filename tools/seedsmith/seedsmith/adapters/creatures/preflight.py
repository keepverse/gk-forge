"""`dump-preflight` (creature-seed module 5, spec-dump-preflight.md) — refuse to start a generation
run unless every prerequisite is present, and ask the human for whatever is missing rather than
guessing or degrading silently.

**No check may exist only in the gitignored skill.** Every one of the nine checks below is
reachable from this committed module, in CI and on every clone — the skill
(`.claude/skills/seedsmith-preflight/SKILL.md`) is a thin conversational wrapper that asks the
human what a failure means; it never detects anything this module does not already detect.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .anchor.audit import numeric_audit
from .anchor.schema import build_anchor_schema
from .power.bands import ThreatTuning

REPO_ROOT = Path(__file__).resolve().parents[5]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from ...workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

DEFAULT_DUMP_DIR = _owned("data/seed/creatures/_dump")
DEFAULT_LOCK_PATH = _owned("tools/seedsmith/requirements.lock")
PREFLIGHT_RECORD_NAME = "_preflight.json"

#: Starting value, tuned from play (this repo's own §5.3 precedent) — a generation run's output
#: is small JSON per species, so 200MB of headroom is conservatively generous, not a measured
#: worst case. A balance pass moving this is a one-line edit here, not a schema change.
MIN_DISK_HEADROOM_BYTES = 200 * 1024 * 1024

CallModelFn = Callable[[str, str, "dict | None"], str]


@dataclass(frozen=True)
class CheckResult:
    """`(id, ok, observed, expected, fix_command)` — never a bare bool, per spec's own code style.
    `action` is what a failure means: `refuse` (never proceed) or `ask` (a human may choose to
    proceed anyway) — `pass` when `ok` is True. A refusal without a `fix_command` is itself a
    defect in this module (see `every_failure_names_a_fix_command`)."""

    id: int
    name: str
    ok: bool
    observed: str
    expected: str
    action: str            # "pass" | "refuse" | "ask"
    fix_command: "str | None"

    def __post_init__(self) -> None:
        if not self.ok and self.fix_command is None:
            raise AssertionError(f"check {self.id} ({self.name}) failed with no fix_command")
        if self.ok and self.action != "pass":
            raise AssertionError(f"check {self.id} ({self.name}) passed but action != 'pass'")


def _read_manifest(dump_dir: Path) -> "dict | None":
    path = dump_dir / "_manifest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def check_1_dump_exists(dump_dir: Path = DEFAULT_DUMP_DIR) -> CheckResult:
    manifest = _read_manifest(dump_dir)
    if manifest is not None:
        return CheckResult(1, "dump-exists", True, "present", "present", "pass", None)
    return CheckResult(
        1, "dump-exists", False, f"no readable _manifest.json under {dump_dir}", "a parsed manifest",
        "ask", f"dotnet run --project tools/CreatureCorpusDump -- <server data dir> {dump_dir}")


def _payload_paths(dump_dir: Path) -> "list[Path]":
    """The four hashed payloads, in the fixed order both implementations concatenate them."""
    return [
        dump_dir / "almanac" / "plant.json",
        dump_dir / "almanac" / "zombie.json",
        dump_dir / "spawn-baseline.json",
        dump_dir / "recipes.json",
    ]


def _compute_content_hash(dump_dir: Path) -> "str | None":
    """Mirrors `DumpWriter.ComputeContentHash` byte-for-byte: SHA-256 over the four payload
    files' raw bytes, concatenated in the fixed order plant, zombie, baseline, recipes. Must
    agree with the C# implementation, or a dump this module calls "current" would disagree with
    the tool that produced it — proven by `test_hash_matches_the_real_committed_dump`.
    """
    paths = _payload_paths(dump_dir)
    if not all(p.exists() for p in paths):
        return None
    sha = hashlib.sha256()
    for p in paths:
        sha.update(p.read_bytes())
    return sha.hexdigest()


#: The stamp keys whose VALUES are capture metadata, not game data. Must equal
#: `DumpWriter.VolatileStampKeys` — a closed, named list on both sides so a new timestamp-shaped
#: field cannot be silently swallowed by one implementation and not the other.
VOLATILE_STAMP_KEYS = ("rebuiltUtc", "capturedUtc")

#: The constant both sides substitute. Must equal `DumpWriter.DataHashStampSentinel`.
DATA_HASH_STAMP_SENTINEL = "0001-01-01T00:00:00.0000000Z"

_STAMP_RE = re.compile(
    r'("(?:%s)"\s*:\s*)"[^"]*"' % "|".join(VOLATILE_STAMP_KEYS))


def _compute_data_hash(dump_dir: Path) -> "str | None":
    """Mirrors `DumpWriter.ComputeDataHash`: the same four payloads in the same order, with every
    volatile stamp VALUE replaced by a fixed sentinel first.

    Why this exists rather than reusing `_compute_content_hash`: the payloads carry 986 stamp fields
    (677 plant + 227 zombie `rebuiltUtc`, 82 spawn-baseline `capturedUtc`), so the content hash moves
    every time the dump is re-captured even when no game data changed. A staleness key built on it
    would report the whole corpus stale on every capture — which is precisely what
    spec-anchor-emit.md forbids: "an entry is stale when what it was derived from has changed,
    compared by recorded value, not by timestamp".

    The value is SUBSTITUTED, not the key removed: removal can leave a dangling comma and changes the
    byte length, which is exactly how two implementations drift apart. Substituting leaves the
    surrounding JSON byte-identical and is trivially mirrored in C#.
    """
    paths = _payload_paths(dump_dir)
    if not all(p.exists() for p in paths):
        return None
    sha = hashlib.sha256()
    for p in paths:
        text = p.read_text(encoding="utf-8")
        sha.update(_STAMP_RE.sub(r'\1"' + DATA_HASH_STAMP_SENTINEL + '"', text).encode("utf-8"))
    return sha.hexdigest()


class MissingDataHash(RuntimeError):
    """The envelope declares no usable `dataHash`, so there is no clock-free snapshot key.

    Named rather than returned as `None`, because every caller of this key either writes it into a
    committed file or compares it against one; a `None` there would be written or compared as if it
    were a value."""


def manifest_data_hash(dump_dir: Path) -> str:
    """The envelope's own `dataHash`, RE-VERIFIED against the payloads before it is returned.

    Recomputing rather than trusting the declared string is the point: this value decides what a
    corpus-wide pass rewrites, so reading it unchecked would let a stale envelope drive a 549-file
    write. Refuses by name when the field is missing or disagrees with the bytes on disk."""
    manifest = _read_manifest(dump_dir)
    if manifest is None:
        raise MissingDataHash(f"no _manifest.json under {dump_dir}")
    declared = manifest.get("dataHash")
    if not declared:
        raise MissingDataHash(f"_manifest.json under {dump_dir} declares no dataHash")
    recomputed = _compute_data_hash(dump_dir)
    if recomputed is None:
        raise MissingDataHash(f"one or more payload files are missing under {dump_dir}")
    if recomputed != declared:
        raise MissingDataHash(
            f"_manifest.json declares dataHash {declared} but the payloads hash to {recomputed}")
    return recomputed


def check_2_dump_is_current(dump_dir: Path = DEFAULT_DUMP_DIR) -> CheckResult:
    manifest = _read_manifest(dump_dir)
    if manifest is None:
        return CheckResult(2, "dump-is-current", False, "no manifest", "a manifest to compare against",
                           "ask", "run check 1 first")
    declared = manifest.get("contentHash")
    recomputed = _compute_content_hash(dump_dir)
    if recomputed is None:
        return CheckResult(2, "dump-is-current", False, "one or more payload files missing",
                           "all four payload files present", "ask",
                           f"dotnet run --project tools/CreatureCorpusDump -- <server data dir> {dump_dir}")
    if recomputed == declared:
        return CheckResult(2, "dump-is-current", True, recomputed, declared, "pass", None)
    return CheckResult(
        2, "dump-is-current", False, recomputed, declared, "ask",
        f"dotnet run --project tools/CreatureCorpusDump -- <server data dir> {dump_dir}   "
        f"(or proceed deliberately against the recorded hash {declared} if this is a pinned rerun)")


def check_3_dump_is_complete(dump_dir: Path = DEFAULT_DUMP_DIR) -> CheckResult:
    manifest = _read_manifest(dump_dir)
    if manifest is None:
        return CheckResult(3, "dump-is-complete", False, "no manifest", "a manifest to compare against",
                           "refuse", "run check 1 first")
    counts = {
        "plantCount": ("almanac", "plant.json"),
        "zombieCount": ("almanac", "zombie.json"),
        "baselineCount": ("spawn-baseline.json",),
        "recipeCount": ("recipes.json",),
    }
    mismatches = []
    for key, rel in counts.items():
        path = dump_dir.joinpath(*rel)
        if not path.exists():
            mismatches.append(f"{key}: file missing")
            continue
        try:
            actual = len(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            mismatches.append(f"{key}: file did not parse as JSON")
            continue
        declared = manifest.get(key)
        if actual != declared:
            mismatches.append(f"{key}: manifest declares {declared}, file has {actual}")
    if not mismatches:
        return CheckResult(3, "dump-is-complete", True, "counts match", "counts match", "pass", None)
    return CheckResult(
        3, "dump-is-complete", False, "; ".join(mismatches), "every declared count matches its file",
        "refuse", f"dotnet run --project tools/CreatureCorpusDump -- <server data dir> {dump_dir}")


def check_4_contract_audits_clean() -> CheckResult:
    defects = numeric_audit(build_anchor_schema())
    if not defects:
        return CheckResult(4, "contract-audits-clean", True, "0 findings", "0 findings", "pass", None)
    return CheckResult(
        4, "contract-audits-clean", False, f"{len(defects)} finding(s): {defects[0]}", "0 findings",
        "refuse", "python -m seedsmith creatures contract --audit   # then fix the named field")


_PREFLIGHT_PROBE_SCHEMA = {
    "type": "object",
    "properties": {
        "acknowledged": {"type": "boolean"},
        "note": {"type": "string", "enum": ["preflight-probe"]},
    },
    "required": ["acknowledged", "note"],
    "additionalProperties": False,
}


def _default_call_model(system: str, user: str, schema: "dict | None") -> str:
    from ...pipeline.llm_caller import call_model, load_config
    return call_model(system, user, config=load_config(), schema=schema)


def check_5_and_6_model(
    *, call_model_fn: CallModelFn = _default_call_model,
) -> "tuple[CheckResult, CheckResult, str | None]":
    """One real call proves both checks — Check 6 is the one that would be skipped and must not
    be: constrained decoding not working turns every downstream guardrail off (spec §2). Returns
    (check5, check6, model_id_used_or_None).
    """
    system = "You are a preflight probe. Reply only via the given schema."
    user = "Acknowledge that you are online by setting acknowledged=true and note='preflight-probe'."
    try:
        raw = call_model_fn(system, user, _PREFLIGHT_PROBE_SCHEMA)
    except Exception as e:
        c5 = CheckResult(5, "model-answers", False, f"call failed: {e}", "a response", "ask",
                         "start LM Studio, or point the config at a running endpoint")
        c6 = CheckResult(6, "model-honours-schema", False, "no response to check (check 5 failed)",
                         "a schema-conforming reply", "refuse", "resolve check 5 first")
        return c5, c6, None

    c5 = CheckResult(5, "model-answers", True, "responded", "responded", "pass", None)

    from ...pipeline.llm_caller import extract_json
    try:
        parsed = extract_json(raw)
    except Exception:
        c6 = CheckResult(
            6, "model-honours-schema", False, raw[:200], "a JSON object matching the probe schema",
            "refuse", "the server or model is not honouring response_format=json_schema — "
                      "check the LM Studio server logs and the model's GGUF/constrained-decoding support")
        return c5, c6, None

    ok = (
        isinstance(parsed, dict)
        and parsed.get("acknowledged") is True
        and parsed.get("note") == "preflight-probe"
        and set(parsed.keys()) == {"acknowledged", "note"}
    )
    if ok:
        c6 = CheckResult(6, "model-honours-schema", True, "schema honoured", "schema honoured", "pass", None)
    else:
        c6 = CheckResult(
            6, "model-honours-schema", False, json.dumps(parsed) if isinstance(parsed, dict) else raw[:200],
            "exactly {'acknowledged': true, 'note': 'preflight-probe'}", "refuse",
            "the server or model is not honouring response_format=json_schema — "
            "check the LM Studio server logs and the model's GGUF/constrained-decoding support")
    return c5, c6, None


def check_7_venv_and_lock_current(lock_path: Path = DEFAULT_LOCK_PATH) -> CheckResult:
    if not lock_path.exists():
        return CheckResult(7, "venv-lock-current", False, f"no lockfile at {lock_path}",
                           "a committed requirements.lock", "ask",
                           f"pip freeze > {lock_path}")
    mismatches = []
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        name, _, version = line.partition("==")
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            mismatches.append(f"{name}: not installed (lock wants {version})")
            continue
        if installed != version:
            mismatches.append(f"{name}: installed {installed}, lock wants {version}")
    if not mismatches:
        return CheckResult(7, "venv-lock-current", True, "matches lock", "matches lock", "pass", None)
    return CheckResult(
        7, "venv-lock-current", False, "; ".join(mismatches[:5]) + (" ..." if len(mismatches) > 5 else ""),
        "installed packages match requirements.lock exactly", "ask",
        f"python -m pip install -r {lock_path}")


def check_8_tuning_present() -> CheckResult:
    try:
        tuning = ThreatTuning.load(2)
    except (FileNotFoundError, KeyError, json.JSONDecodeError) as e:
        return CheckResult(8, "tuning-present", False, f"load failed: {e}",
                           "data/tuning/creature-threat.v2.json loads and validates", "refuse",
                           "restore data/tuning/creature-threat.v1.json from version control")
    if len(tuning.thresholds) != 10:
        return CheckResult(8, "tuning-present", False, f"{len(tuning.thresholds)} rungs, expected 10",
                           "10 rungs", "refuse", "restore data/tuning/creature-threat.v1.json from version control")
    return CheckResult(8, "tuning-present", True, "10 rungs loaded", "10 rungs loaded", "pass", None)


def check_9_disk_headroom(dump_dir: Path = DEFAULT_DUMP_DIR, *, min_bytes: int = MIN_DISK_HEADROOM_BYTES) -> CheckResult:
    target = dump_dir if dump_dir.exists() else dump_dir.parent
    if not target.exists():
        target = REPO_ROOT
    free = shutil.disk_usage(target).free
    if free >= min_bytes:
        return CheckResult(9, "disk-headroom", True, f"{free // (1024*1024)}MB free",
                           f">= {min_bytes // (1024*1024)}MB", "pass", None)
    return CheckResult(
        9, "disk-headroom", False, f"{free // (1024*1024)}MB free", f">= {min_bytes // (1024*1024)}MB",
        "ask", "free up disk space, or lower --min-disk-mb if this run's output is known to be small")


@dataclass(frozen=True)
class PreflightReport:
    checks: "tuple[CheckResult, ...]"
    dump_hash: "str | None"
    model_id: "str | None"

    @property
    def full_pass(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def refusals(self) -> "list[CheckResult]":
        return [c for c in self.checks if not c.ok and c.action == "refuse"]

    @property
    def asks(self) -> "list[CheckResult]":
        return [c for c in self.checks if not c.ok and c.action == "ask"]


def run_preflight(
    *, dump_dir: Path = DEFAULT_DUMP_DIR, lock_path: Path = DEFAULT_LOCK_PATH,
    skip_model: bool = False, call_model_fn: CallModelFn = _default_call_model,
    model_id: "str | None" = None,
) -> PreflightReport:
    """Runs all nine checks (or checks 1-4/7-9 when `skip_model=True` — CI's escape hatch, never
    legal before a real run per `run_control`'s own refusal, spec §2/Commands).
    """
    c1 = check_1_dump_exists(dump_dir)
    c2 = check_2_dump_is_current(dump_dir)
    c3 = check_3_dump_is_complete(dump_dir)
    c4 = check_4_contract_audits_clean()
    c7 = check_7_venv_and_lock_current(lock_path)
    c8 = check_8_tuning_present()
    c9 = check_9_disk_headroom(dump_dir)

    if skip_model:
        checks: "tuple[CheckResult, ...]" = (c1, c2, c3, c4, c7, c8, c9)
    else:
        c5, c6, _ = check_5_and_6_model(call_model_fn=call_model_fn)
        checks = (c1, c2, c3, c4, c5, c6, c7, c8, c9)

    # The snapshot key recorded here MUST be the same key `run-control` compares, or the gate it
    # writes is a gate nothing can ever pass.
    #
    # It used to be `_compute_content_hash`. That is the CONTENT hash, which covers the payloads'
    # 986 volatile stamp fields (677 plant + 227 zombie `rebuiltUtc`, 82 spawn-baseline
    # `capturedUtc`) and therefore moves on every re-capture. `run/record.py` compares this value
    # against `runner._compute_dump_hash`, which returns the manifest's `dataHash`. The two are
    # equal only when the payloads happen to carry no stamps at all - true of every test fixture
    # (`species_row()` emits no `rebuiltUtc`/`capturedUtc`) and false of the real tree. So
    # `can_start` returned False on the committed corpus forever, and `start` / `rerun` /
    # `overwrite-all` could not run at all, with the suite green throughout.
    #
    # Reading the manifest through `manifest_data_hash` rather than recomputing keeps ONE source of
    # truth: it is the value every `_provenance.dumpHash` records, and it re-verifies the envelope
    # against the payload bytes on the way, so a preflight cannot bless a stale manifest.
    # A preflight REPORTS; it does not raise. `check_1_dump_exists` and `check_2_dump_is_current`
    # exist precisely to report a missing dump or a stale envelope as failed checks, so a
    # MissingDataHash here is a finding to surface through those checks, not an exception that
    # replaces them. `None` is safe to carry: `write_preflight_record` writes only on a full pass,
    # and an absent or split-less manifest cannot produce one, so a None dump_hash can never reach
    # a written record and can never satisfy - or silently break - run-control's comparison.
    try:
        dump_hash = manifest_data_hash(dump_dir)
    except MissingDataHash:
        dump_hash = None
    return PreflightReport(checks=checks, dump_hash=dump_hash, model_id=model_id)


def write_preflight_record(report: PreflightReport, *, dump_dir: Path = DEFAULT_DUMP_DIR,
                           lock_path: Path = DEFAULT_LOCK_PATH, skip_model: bool) -> "Path | None":
    """Writes `_preflight.json` **only on a full pass** (spec §4) — a partial record would let
    `run-control` mistake a refused preflight for a passed one. `skip_model=True` records are
    tagged so `run-control` can reject them before a real run (spec's own escape-hatch rule)."""
    if not report.full_pass:
        return None
    lock_hash = hashlib.sha256(lock_path.read_bytes()).hexdigest() if lock_path.exists() else None
    record = {
        "dumpHash": report.dump_hash,
        "modelId": report.model_id,
        "lockHash": lock_hash,
        "skipModel": skip_model,
        "writtenUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    path = dump_dir / PREFLIGHT_RECORD_NAME
    path.write_text(json.dumps(record, indent=2), encoding="utf-8", newline="\n")
    return path
