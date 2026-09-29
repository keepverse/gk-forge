"""seedsmith.briefkit — one brief per job, inlining everything and citing nothing (plan P6).

**The incident this exists for: "tags come from `tags.v1.json`" cost 51 invented tags.** A citation
is an instruction to go and look, and a generating agent cannot go and look — so it invents. Every
closed vocabulary a brief depends on is therefore written into the brief *literally*, read from the
registry at generation time.

That rule is enforced, not merely intended: `CITATION_PATTERNS` is grepped over the rendered text
and a match refuses the brief. A rule this cheap to break needs a check, not a convention.

**Content-addressed.** A brief's hash is a pure function of its inputs — no wall clock, no random,
no dict iteration order — so a bad brief version is identifiable and exactly its output re-runnable.
Without that, "which brief produced this?" has no answer and a bad batch cannot be scoped.
"""
from __future__ import annotations

from .gloss import GlossMissing, GlossTable, load_glosses
from .render import (
    CITATION_PATTERNS,
    Brief,
    BriefRefusal,
    render_brief,
    render_briefs,
)

__all__ = [
    "Brief",
    "BriefRefusal",
    "CITATION_PATTERNS",
    "GlossMissing",
    "GlossTable",
    "load_glosses",
    "render_brief",
    "render_briefs",
]
