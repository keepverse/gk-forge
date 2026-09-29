"""`anchor-emit`'s provenance record (creature-seed module 8, spec-anchor-emit.md §3) — the upgrade
path, not bookkeeping. `inferred` is upgradeable *because* this record says why a value is what it
is: a later `spawn_stats` observation promotes `basis`, and re-derivation corrects one entry
visibly, in a diff, with the reason attached.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: Bumped by hand when a pipeline's prompt text changes materially (spec §3: "a description change
#: invalidates exactly the fields that pipeline owns, not the whole entry"). Starts at 1 for every
#: pipeline — a real per-pipeline history is maintained by editing this dict as prompts evolve.
PROMPT_VERSIONS: "dict[str, int]" = {
    "element-primary": 1, "element-secondary": 1, "aptitude-primary": 1, "aptitude-secondary": 1,
    "threat-audit": 1, "deployment": 1, "kit-shape": 1, "identity": 1,
}


@dataclass(frozen=True)
class ReleadProvenance:
    """`provenance.relead` — the pass-2 re-label record (`empire-progression`'s `lead-relabel-pass`,
    spec-lead-relabel-pass.md "Where the answer lives").

    Labels only: `from_primary`, every entry of `votes`, `confidence` and `outcome` are CLOSED sets
    (`APTITUDES`, `vote.CONFIDENCES`, stage A's `OUTCOMES`), `prompt_version` is a pipeline-version
    INDEX, and the two hashes are identifiers. **No model-chosen number can appear here** — a
    re-label without provenance is the one thing the spec forbids outright.

    `dump_hash` is recorded because the staleness rule names it: a re-label computed against an older
    capture must be dropped when pass 1 re-runs on a new one, and nothing else in the entry can say
    which capture it was computed against (`_provenance.dumpHash` is the entry's CURRENT capture, not
    the one the re-label read — those are the same only until the dump moves).
    """

    from_primary: str
    prompt_version: int
    dump_hash: str
    votes: "tuple[str, ...]"
    confidence: str
    measure_hash: str
    outcome: str

    def __post_init__(self) -> None:
        from .schema import APTITUDES
        from ..build_favour.accept import OUTCOMES
        from ..build_favour.relead import CONFIDENCES

        if self.from_primary not in APTITUDES:
            raise ValueError(f"relead fromPrimary {self.from_primary!r} is not an aptitude id")
        for vote in self.votes:
            if vote not in APTITUDES:
                raise ValueError(f"relead vote {vote!r} is not an aptitude id")
        if self.confidence not in CONFIDENCES:
            raise ValueError(f"relead confidence {self.confidence!r} is not in {CONFIDENCES}")
        if self.outcome not in OUTCOMES:
            raise ValueError(f"relead outcome {self.outcome!r} is not in {OUTCOMES}")
        if isinstance(self.prompt_version, bool) or not isinstance(self.prompt_version, int) \
                or self.prompt_version < 1:
            raise ValueError(
                f"relead promptVersion {self.prompt_version!r} is a pipeline-version index (int >= 1), "
                "never a model-chosen number")
        for name, value in (("measureHash", self.measure_hash), ("dumpHash", self.dump_hash)):
            if not _is_hash(value):
                raise ValueError(f"relead {name} {value!r} is not a content hash (an identifier)")

    def to_dict(self) -> "dict[str, Any]":
        return {
            "fromPrimary": self.from_primary,
            "promptVersion": self.prompt_version,
            "dumpHash": self.dump_hash,
            "votes": list(self.votes),
            "confidence": self.confidence,
            "measureHash": self.measure_hash,
            "outcome": self.outcome,
        }

    @classmethod
    def from_dict(cls, d: "dict[str, Any]") -> "ReleadProvenance":
        return cls(
            from_primary=d["fromPrimary"], prompt_version=d["promptVersion"],
            dump_hash=d["dumpHash"], votes=tuple(d.get("votes") or ()),
            confidence=d["confidence"], measure_hash=d["measureHash"], outcome=d["outcome"])


def _is_hash(value: Any) -> bool:
    """A content hash: lowercase hex, at least 8 characters. An identifier by shape — never a
    magnitude — which is what lets it live in a provenance block at all."""
    return isinstance(value, str) and len(value) >= 8 and all(c in "0123456789abcdef" for c in value)


@dataclass(frozen=True)
class AnchorProvenance:
    dump_hash: str
    prompt_versions: "dict[str, int]"
    basis: str                                   # observed | stated | inferred | blocked
    confidence: "dict[str, str]" = field(default_factory=dict)     # voted field -> high|split|unresolved
    minority_values: "dict[str, str]" = field(default_factory=dict)  # voted field -> the losing value, split only
    audit_verdict: "str | None" = None            # agree | too-low | too-high; None for inferred/blocked
    attempts: "dict[str, int]" = field(default_factory=dict)   # pipeline id -> attempts used (1 = no repair)
    emitted_utc: str = ""
    #: Set only by `lead-relabel-pass`'s pass 2; None on every anchor pass 1 wrote, and written as an
    #: ABSENT key rather than a null so a re-emit does not add a claim about a pass that never ran.
    relead: "ReleadProvenance | None" = None

    def to_dict(self) -> "dict[str, Any]":
        d = asdict(self)
        # camelCase to match the rest of this program's committed JSON (corpus-dump, threat-band).
        out: "dict[str, Any]" = {
            "dumpHash": d["dump_hash"],
            "promptVersions": d["prompt_versions"],
            "basis": d["basis"],
            "confidence": d["confidence"],
            "minorityValues": d["minority_values"],
            "auditVerdict": d["audit_verdict"],
            "attempts": d["attempts"],
            "emittedUtc": d["emitted_utc"],
        }
        if self.relead is not None:
            out["relead"] = self.relead.to_dict()
        return out

    @classmethod
    def from_dict(cls, d: "dict[str, Any]") -> "AnchorProvenance":
        relead = d.get("relead")
        return cls(
            dump_hash=d["dumpHash"], prompt_versions=dict(d["promptVersions"]), basis=d["basis"],
            confidence=dict(d.get("confidence") or {}), minority_values=dict(d.get("minorityValues") or {}),
            audit_verdict=d.get("auditVerdict"), attempts=dict(d.get("attempts") or {}),
            emitted_utc=d.get("emittedUtc", ""),
            relead=ReleadProvenance.from_dict(relead) if relead else None)
