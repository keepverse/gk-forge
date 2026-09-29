"""The motif gloss pipeline: prompt, chunked fill, verify, bounded heal (spec-gloss-fill.md)."""
from .fill import MAX_HEAL, SENSES, chunk_motifs, fill_glosses, sense_order_for, verify_chunk
from .prompt import GLOSS_MAX_LENGTH, build_chunk_brief, chunk_schema, render_exemplars

__all__ = ["MAX_HEAL", "SENSES", "chunk_motifs", "sense_order_for", "verify_chunk", "fill_glosses",
           "GLOSS_MAX_LENGTH", "build_chunk_brief", "chunk_schema", "render_exemplars"]
