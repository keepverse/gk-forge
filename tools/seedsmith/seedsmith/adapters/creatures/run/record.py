"""The `run-control` run record (creature-seed module 9, spec-run-control.md §3, §6). **Lists, not
counts** — "412 completed" cannot answer "was `normalzombie` done?", which is the question a
resume actually asks.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


def new_run_id() -> str:
    """Sortable by construction — a UTC timestamp prefix (microsecond resolution) plus a short
    random suffix for uniqueness within the same microsecond. String-sorts the same as
    time-sorts, so "the latest run is the last line" (spec §3) needs no parsing."""
    ts = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + f"{time.time() % 1:.6f}"[1:]
    suffix = "".join(random.choices("0123456789ABCDEFGHJKMNPQRSTVWXYZ", k=6))
    return f"{ts}-{suffix}"


@dataclass
class RunRecord:
    run_id: str
    state: str
    preflight: "dict"                          # copied in whole, not referenced (spec §3)
    dump_hash: str
    selector: "dict"
    prompt_versions: "dict"
    pid: int
    completed: "list[str]" = field(default_factory=list)
    failed: "list[str]" = field(default_factory=list)
    skipped: "list[str]" = field(default_factory=list)
    calls_made: int = 0
    started_utc: str = ""
    updated_utc: str = ""

    def to_dict(self) -> "dict":
        d = asdict(self)
        return {
            "runId": d["run_id"], "state": d["state"], "preflight": d["preflight"],
            "dumpHash": d["dump_hash"], "selector": d["selector"],
            "promptVersions": d["prompt_versions"], "pid": d["pid"],
            "completed": d["completed"], "failed": d["failed"], "skipped": d["skipped"],
            "callsMade": d["calls_made"], "startedUtc": d["started_utc"], "updatedUtc": d["updated_utc"],
        }

    @classmethod
    def from_dict(cls, d: "dict") -> "RunRecord":
        return cls(
            run_id=d["runId"], state=d["state"], preflight=dict(d.get("preflight") or {}),
            dump_hash=d["dumpHash"], selector=dict(d.get("selector") or {}),
            prompt_versions=dict(d.get("promptVersions") or {}), pid=d.get("pid", 0),
            completed=list(d.get("completed") or []), failed=list(d.get("failed") or []),
            skipped=list(d.get("skipped") or []), calls_made=d.get("callsMade", 0),
            started_utc=d.get("startedUtc", ""), updated_utc=d.get("updatedUtc", ""))


def write_record(record: RunRecord, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def read_record(path: Path) -> "RunRecord | None":
    if not path.exists():
        return None
    return RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))


def is_process_alive(pid: int) -> bool:
    """Best-effort, cross-platform. A false negative (reports dead when actually alive) is the
    SAFE direction here — it only leads to offering `resume`, never to silently taking over a
    live run (spec §6: "it does not silently take over, and it does not refuse forever")."""
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just not ours to signal
    except OSError:
        return False
    except AttributeError:
        return False  # platform has no kill(pid, 0) at all
    return True


#: Confirmation required for `overwrite-all` (spec §5: "an irreversible action... gets a typed
#: token, in the same spirit as any other irreversible action"). Derived from the dump hash so a
#: token from one dump snapshot cannot accidentally authorize an overwrite against a different
#: one — copy-pasting an old token is a mismatch, not a silent bypass.
def overwrite_all_token(dump_hash: str) -> str:
    return hashlib.sha256(f"overwrite-all:{dump_hash}".encode("utf-8")).hexdigest()[:16]


# --- refusals (spec §5, §6) --------------------------------------------------------------------

def can_start(
    preflight: "dict | None", *, dump_hash: str, existing_record: "RunRecord | None",
) -> "tuple[bool, str]":
    """Every refusal names the reason, never a bare "no" (matching every other module in this
    program's own discipline — dump-preflight's `fix_command`, corpus-dump's `--check` message)."""
    if preflight is None:
        return False, "no preflight record — run `creatures preflight` first"
    if preflight.get("skipModel"):
        return False, "preflight was run with --skip-model — CI's escape hatch never reaches a real run"
    if preflight.get("dumpHash") != dump_hash:
        return False, (f"preflight's dumpHash ({preflight.get('dumpHash')}) does not match the "
                       f"current dump ({dump_hash}) — re-run preflight")
    if existing_record is not None and existing_record.state == "running":
        if is_process_alive(existing_record.pid):
            return False, f"another run is already running: {existing_record.run_id}"
        return False, (f"run {existing_record.run_id} is recorded as running but its process "
                       f"(pid {existing_record.pid}) is gone — use `resume`, not `start`, to "
                       f"recover it (spec §6: a crash must be recoverable without hand-editing JSON)")
    return True, ""


def can_resume(record: "RunRecord", *, current_dump_hash: str) -> "tuple[bool, str]":
    if record.dump_hash != current_dump_hash:
        return False, ("the dump has changed since this run started — resuming against a "
                       "different dump is refused; use `rerun --stale` instead")
    return True, ""


def can_overwrite_all(token: str, *, dump_hash: str) -> "tuple[bool, str]":
    expected = overwrite_all_token(dump_hash)
    if token != expected:
        return False, f"wrong confirmation token for overwrite-all — the correct token for this dump is {expected}"
    return True, ""
