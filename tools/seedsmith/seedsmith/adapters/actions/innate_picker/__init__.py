"""seedsmith.adapters.actions.innate_picker — A-S6 (spec-innate-picker.md), the last model-free
module in the action-corpus program: picks each species' single free sixth action slot (the
innate, outside `LoadoutSet.MaxSize = 5`) from that species' own eligible accepted candidates, and
writes the COMMITTED corpus — permanently model-free, never provisionally (spec's own opening
line: "the escape hatch that made this 'model-free for now' was struck").
"""
from __future__ import annotations
