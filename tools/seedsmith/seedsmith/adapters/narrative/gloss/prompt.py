"""The gloss-fill prompt: the chunk schema and the chunk brief (spec-gloss-fill.md, NS14).

The schema is a CLOSED contract, not a hint: its root carries `blocked` (a chunk the model will not
answer is named, never silently skipped), every string field carries an `maxLength` where a bound is
structural, `additionalProperties` is `false` at both levels, and every field's description names what
it is NOT — the audit's own four shapes (`narrative-contract` §11) applied here at the source.

Nothing here calls a model: `fill.py` owns the call, this module owns the text.
"""
from __future__ import annotations

from typing import Mapping, Sequence

__all__ = ["SENSE_FIELD", "GLOSS_MAX_LENGTH", "GLOSS_PROMPT_VERSION", "chunk_schema",
           "build_chunk_brief", "render_exemplars"]

#: The gloss-fill prompt version stamped on every committed row's `promptVersion`. It lives here, with
#: the prompt text it versions, so a changed brief is a version bump rather than a silent rewrite of
#: rows that a bad batch can no longer be scoped by.
GLOSS_PROMPT_VERSION = "gloss/1"

#: The field the per-motif option permutation applies to (spec §3: the sense options are permuted per
#: motif so a vote over them measures the model's reading, never its position bias).
SENSE_FIELD = "sense"

#: A structural bound on a gloss string (a phrase, not a paragraph). The WORD bound is
#: `gloss.maxWords` in the budget file; this is the character backstop the transport needs, because a
#: JSON-Schema `maxLength` is not enforced at decode time by every server (see `llm_caller`'s own
#: degradation note) and a runaway string is what the 2026-09-08 incident burned an hour on.
GLOSS_MAX_LENGTH = 64


def chunk_schema(*, senses: Sequence[str]) -> dict:
    """The per-chunk answer schema. `blocked` is REQUIRED so a refusal is a named field rather than an
    empty chunk, and every key is required so a partial answer is a schema violation, not a silent
    gap."""
    gloss_item = {
        "type": "object",
        "properties": {
            "motif": {"type": "string",
                      "description": "The motif EXACTLY as given in the list. NOT translated, NOT "
                                     "normalised, NOT a display string."},
            "gloss": {"type": "string", "maxLength": GLOSS_MAX_LENGTH,
                      "description": "A short English phrase carrying the motif's meaning. NOT a "
                                     "name, NOT a sentence, NOT the motif itself, NOT a digit."},
            "sense": {"type": "string", "enum": list(senses),
                      "description": "Which kind of meaning the gloss carries. NOT a part-of-speech "
                                     "tag for grammar."},
        },
        "required": ["motif", "gloss", "sense"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "blocked": {"type": "string", "maxLength": 200,
                        "description": "The reason you cannot gloss this chunk, or the empty string. "
                                       "NOT a gloss, NOT a placeholder for one."},
            "glosses": {"type": "array", "minItems": 0, "items": gloss_item,
                        "description": "One entry per motif you can gloss. NOT a partial list padded "
                                       "with guesses."},
        },
        "required": ["blocked", "glosses"],
        "additionalProperties": False,
    }


def render_exemplars(exemplars: "Sequence[Mapping[str, str]]") -> str:
    """The authored few-shot pairs, as one line each. Authored content, never model output."""
    return "\n".join(f"- {p['motif']} -> {p['gloss']} ({p['sense']})" for p in exemplars)


def build_chunk_brief(motifs: "Sequence[str]", *, exemplars: "Sequence[Mapping[str, str]]",
                      senses: Sequence[str], sense_order: "Mapping[str, Sequence[str]]") -> str:
    """The user-role brief for one chunk: the motifs to gloss, the exemplar pairs, and the sense
    options IN THIS CHUNK'S OWN PER-MOTIF ORDER (`sense_order[motif]`, `order_for`'s permutation)."""
    lines = [f"Gloss each of these {len(motifs)} motifs into English.", "", "Motifs:"]
    lines += [f"- {motif}" for motif in motifs]
    lines += ["", "Examples (authored, for the register only — do not copy their words):",
              render_exemplars(exemplars), "", "Sense options, in the order to use for each motif:"]
    for motif in motifs:
        lines.append(f"- {motif}: {', '.join(sense_order[motif])}")
    lines += ["", "Return one entry per motif. Set `blocked` only if you cannot gloss the chunk at all.",
              "Every gloss is a short English phrase: no digits, no Chinese, not the motif itself."]
    return "\n".join(lines)
