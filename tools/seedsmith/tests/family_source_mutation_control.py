"""MUTATION CONTROL for the four new family-label refusals (2026-10-04).

One script, one process, `try/finally` restore, sha256-verified — because a control whose result is
unknown is not a control. A multi-step shell sequence in this programme was interrupted by a server
restart and left the control's outcome unrecorded, so every gate below is asserted in-process and
the restore is proven byte-identical rather than assumed.

FOUR GATES PER REFUSAL:

  1. BASELINE      the suite is GREEN before anything is touched.
  2. MUTANT RED    the refusal is disabled in place and the suite goes RED — a specific named test,
                    not "something failed".
  3. RESTORED      `try/finally` puts the original bytes back.
  4. SHA256 + GREEN  the file's sha256 equals the pre-mutation sha256, the bytes compare equal, and
                    the suite is GREEN again.

Exit code 0 only if all four gates passed for all three refusals AND the whole acceptance set is
green at the end. Any failure prints the offending gate and exits 1.

Run from tools/seedsmith:  python tasks/reports/family-source-mutation-control.py
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # tools/seedsmith
PKG = ROOT / "seedsmith"

#: The acceptance set from the brief, plus the family tests this change added or altered.
ACCEPTANCE = [
    "tests/test_seed_consumer_contract.py",
    "tests/test_run_element_guard.py",
    "tests/test_runner_guard_binding.py",
    "tests/test_characteristic_pool.py",
    "tests/test_family_consolidate.py",
    "tests/test_family_extract.py",
    "tests/test_family_propose.py",
    "tests/test_family_source_repairs.py",
    # The one-decider guard: `catalog`'s output must be exactly `consolidate` then
    # `resolve_unresolved_family`, and the family package must hold no second predicate module.
    # Added with the removal of the unwired `family/label_rules.py` (33 tests, zero call sites).
    "tests/test_family_label_refusal.py",
]

#: `refusal -> (file, the exact source text that disables it, the exact text that restores the
#: live refusal, the test that must go red)`.
#:
#: Each mutation is a ONE-LINE edit that turns the refusal's DECISION POINT into a constant, so the
#: mutant is "the guard does not fire", never "the guard is gone" — a deleted guard would fail to
#: import and prove nothing.
#:
#: R3's first attempt mutated `resolve_unresolved_family`'s early-return guard, and the control
#: caught its own mistake: removing that `if` makes the function FALL THROUGH to the selection loops
#: instead of blocking, so all 11 cases still passed and the named gate stayed green. The mutation
#: belongs on `family_label_is_artefact`'s corroboration clause — the decision the fallback actually
#: turns on. Recorded here because "the control found a bug in itself" is exactly the case a control
#: exists to catch, and the alternative was a control reporting PASS on a mutant that did nothing.
REFUSALS = {
    "R1 placeholder / no-identity family label": (
        PKG / "adapters/creatures/anchor/schema.py",
        "if carries_placeholder(label) or carries_no_identity(label)",
        "if False",
        "tests/test_seed_consumer_contract.py::"
        "test_a_family_label_asserting_no_identity_is_refused",
    ),
    "R2 corroboration-gated head-noun merge": (
        PKG / "adapters/creatures/family/consolidate.py",
        "if leading in corroborated and head not in corroborated:",
        "if False:",
        "tests/test_family_source_repairs.py::"
        "test_a_merge_that_would_discard_a_corroborated_family_term_is_refused",
    ),
    "R3 deterministic family fallback": (
        PKG / "adapters/creatures/family/fallback.py",
        "    return len(set(key_owners.get(text, ())) - {species_id}) < 1",
        "    return False",
        "tests/test_family_source_repairs.py::"
        "test_each_artefact_only_species_resolves_to_a_real_grouping",
    ),
    # The owner's 2026-10-04 clause. Disabled by making the predicate answer False, which is
    # exactly the pre-clause behaviour. The named test is the SYNTHETIC case, not the corpus-wide
    # invariant: the invariant is "no species keeps its own name as a label", which would go
    # vacuously green if the corpus ever held no such label, whereas the synthetic one fails for as
    # long as the predicate exists.
    "R4 a label may not be the whole of a species' name": (
        PKG / "adapters/creatures/family/fallback.py",
        '    return sorted(str(family_id).split("-")) == words',
        "    return False",
        "tests/test_family_label_refusal.py::"
        "test_the_clause_refuses_a_name_even_when_the_label_groups_other_species",
    ),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(targets: "list[str]") -> "tuple[int, str]":
    """Run pytest in a SUBPROCESS, so no mutated module stays in this process's `sys.modules` and
    poisons the next gate. A control that reuses one interpreter proves less than it looks like it
    does — a cached import would keep the un-mutated module alive and report green."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *targets, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, timeout=1800,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def gate(label: str, ok: bool, detail: str = "") -> bool:
    print(f"   {'PASS' if ok else 'FAIL'}  {label}{(' :: ' + detail) if detail and not ok else ''}")
    return ok


def control(name: str, path: Path, disable: str, enable: str, red_test: str) -> bool:
    print(f"\n=== {name} ===")
    print(f"   file: {path.relative_to(ROOT.parent.parent)}")
    original_bytes = path.read_bytes()
    original_sha = sha256(path)
    print(f"   gate 1 BASELINE  sha256 {original_sha}")

    ok = True
    # ---- gate 1: baseline green -------------------------------------------------------------
    code, out = run(ACCEPTANCE)
    ok &= gate("baseline suite is GREEN", code == 0, out[-800:])

    try:
        text = original_bytes.decode("utf-8")
        if text.count(disable) != 1:
            ok &= gate(f"mutation target is unique in the file", False,
                       f"found {text.count(disable)} occurrences of the disable text")
            return ok
        mutated = text.replace(disable, enable)
        # A structural edit validates in a step that can FAIL BEFORE it is written, never beside
        # the write: an unparsable mutant would fail to import and the red gate would read as
        # "the guard fired" when it is really "the module is broken".
        try:
            compile(mutated, str(path), "exec")
        except SyntaxError as exc:
            ok &= gate("mutant compiles before it is written", False, str(exc))
            return ok
        path.write_text(mutated, encoding="utf-8")
        mutant_sha = sha256(path)
        ok &= gate("mutant differs from the original", mutant_sha != original_sha,
                   "the mutation text matched but the file did not change")

        # ---- gate 2: the mutant is RED ------------------------------------------------------
        code, out = run([red_test])
        ok &= gate(f"mutant is RED on {red_test.rsplit('::', 1)[-1]}", code != 0, out[-800:])
        code, out = run(ACCEPTANCE)
        ok &= gate("mutant makes the acceptance suite RED", code != 0, out[-800:])
    finally:
        # ---- gate 3: restored ----------------------------------------------------------------
        path.write_bytes(original_bytes)
        restored_sha = sha256(path)
        ok &= gate("restored sha256 equals the pre-mutation sha256", restored_sha == original_sha,
                   f"{restored_sha} != {original_sha}")
        ok &= gate("restored bytes are byte-identical",
                   path.read_bytes() == original_bytes)

    # ---- gate 4: green again ------------------------------------------------------------------
    code, out = run(ACCEPTANCE)
    ok &= gate("restored suite is GREEN again", code == 0, out[-800:])
    return ok


def main() -> int:
    print("MUTATION CONTROL — four new family-label refusals")
    print(f"repo: {ROOT.parent}")
    print(f"acceptance set: {len(ACCEPTANCE)} files")

    results = {}
    for name, (path, disable, enable, red_test) in REFUSALS.items():
        results[name] = control(name, path, disable, enable, red_test)

    print("\n" + "=" * 78)
    for name, ok in results.items():
        print(f"   {'PASS' if ok else 'FAIL'}  {name}")
    all_ok = all(results.values())
    print("=" * 78)
    print("CONTROL RESULT:", "ALL GREEN" if all_ok else "FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
