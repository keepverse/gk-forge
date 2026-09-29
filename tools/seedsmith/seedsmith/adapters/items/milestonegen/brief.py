"""seedsmith.adapters.items.milestonegen.brief — the prompt text; carries the closed vocabularies
and nothing the model could echo back as a magnitude.

Mirrors `combogen.brief`'s own discipline (that module's docstring: "no number, no citation text")
applied to this corpus's own shape: no tier, no `+n` threshold, no op, no powerBand — those are
resolved after the answer, from `schema.CHANNEL_TUNING`, never authored.
"""
from __future__ import annotations

PROMPT_VERSION = "enhancement-milestones-gen/1"


def _channel_lines(channels: "tuple[str, ...]") -> str:
    return "\n".join(f"  - {c}" for c in channels)


def _tag_lines(tags: "tuple[str, ...]") -> str:
    return "\n".join(f"  - {t}" for t in tags)


def _existing_names_line(existing_names: "tuple[str, ...]", limit: int = 20) -> str:
    if not existing_names:
        return "  (none yet)"
    shown = existing_names[:limit]
    lines = [f"  - {n}" for n in shown]
    if len(existing_names) > limit:
        lines.append(f"  - ...and {len(existing_names) - limit} more")
    return "\n".join(lines)


def build_brief(channels: "tuple[str, ...]", tags: "tuple[str, ...]",
                 existing_names: "tuple[str, ...]" = (), *, theme_hint: str = "") -> str:
    """One enhancement-milestone family, one brief. `channels` and `tags` are the caller's own
    closed vocabularies (`schema.channel_vocab()` / `schema.TAG_VOCAB` by default) — passed in
    rather than imported directly so a test can exercise a narrowed vocabulary without touching the
    module's own defaults.
    """
    if not channels:
        raise ValueError("no channels offered — cannot build a brief with an empty vocabulary")
    if not tags:
        raise ValueError("no tags offered — cannot build a brief with an empty vocabulary")

    theme_line = f"\nTheme hint: {theme_hint}." if theme_hint else ""

    return f"""Author ONE enhancement-milestone family — a bonus a base type's own enhancement track \
grants at a milestone `+n` level (e.g. "+4 max HP", "+1 shield on spawn"). This is NOT a set, a \
charm, or a socket combination: it stands alone, and it grants nothing that references any other \
corpus.{theme_line}

Choose, and nothing else:
1. `name` — must read "Enhancement <Word>" (one capitalized word after "Enhancement "), matching \
every existing family's own naming convention.
2. `flavor` — one or two sentences of mechanical flavor for what this milestone represents. Never a \
number, a tier, or a threshold — those are resolved after you answer, from tuning data.
3. `channel` — the ONE real stat channel this milestone touches, from the closed list below. The \
op (Flat/Increased/More) and the power band are both resolved from this choice, not chosen by you.
4. `tags` — one or more from the closed list below.

Legal channels ({len(channels)}):
{_channel_lines(channels)}

Legal tags ({len(tags)}):
{_tag_lines(tags)}

Existing family names already in the corpus (pick something distinct):
{_existing_names_line(existing_names)}

If no legal channel fits a family you would be happy to ship, set `blocked` and say why."""
