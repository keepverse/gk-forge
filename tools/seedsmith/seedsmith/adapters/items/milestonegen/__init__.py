"""seedsmith.adapters.items.milestonegen — the enhancement-milestone generator
(`enhancement-milestones-gen`, item-seedgen module 11, `docs/architecture/item-seedgen/
spec-enhancement-milestones-gen.md`).

**Self-contained family authoring, mirroring `affix-families-gen`'s own shape — not `setgen`'s
brief-over-existing-vocabulary shape.** Every entry this module mints defines its OWN
`runtimeFamily` (`atom.enhance-<name>`) with real `kindId`/`params`/`powerBand`. It references
nothing else in this program: no set/charm membership, no combination ingredient list, no external
atom-family lookup. `base-types-gen`'s `enhanceTrack[].family` field is a HARD reference INTO this
module's output (the reverse direction) — this module has no outward reference to resolve at all.

⛔ **P1, same split every item-seedgen module sits on: the model writes identity, deterministic code
writes magnitude — and here, the op/vocabulary too.** The model (via `brief.build_brief` and the
schema in `schema.py`) picks the milestone's `name`, `flavor`, which real stat `channel` it touches,
and its `tags`. It never picks `op`, `powerBand`, `id`, `nameKey` or `runtimeFamily` — `emit.py`
derives all of those deterministically from the channel via `schema.CHANNEL_TUNING` and from the
name via `emit.slug_from_name`, so two runs over an unchanged answer are byte-identical.

⛔ **The real op vocabulary, verified against the actual C# consumer, not assumed to match
`affix-families-gen`'s.** `gk-core/src/FusionRpg.Core/Effects/Atoms/AtomKindRegistry.cs`'s `stat.modify`
kind (registered ~line 494-521, doc comment at line 517: "Ops are Flat|Increased|More — effects
cannot emit Override") explicitly REJECTS `op == "Override"` at bind time (`Validate()`,
line 349-357), case-insensitively. Three legal ops: `Flat`, `Increased`, `More` — PascalCase, the
same casing the real, shipped `gk-data/packs/fusion/data/seed/items/enhancement-milestones/milestones.json` already uses
(`enh.001`: `"op": "Flat"`; `enh.004`: `"op": "Increased"`). `schema.STAT_MODIFY_OPS` transcribes
this with the same citation discipline `affixfamgen.opvocab` uses for its own (different, sibling)
corpus — copied independently here rather than imported, because the two modules are separate,
parallel-built, and each owns its own corpus's op table per its own spec.

⚠ **A real finding from reading the shipped corpus, reported but NOT fixed by this module (out of
scope — this module authors NEW entries, it does not repair existing hand-authored ones):** four of
the ten hand-authored entries (`enh.004` `channel: "actionSpeed"`, `enh.005` `channel: "crit-rate"`,
`enh.008` `channel: "armor"`, `enh.010` `channel: "dodge"`) use channel names that are NOT members of
`stat.modify`'s own real channel vocabulary (`AtomKindRegistry.PrimaryChannels`, which is exactly
`FusionRpg.Core.Stats.StatChannels.All` — see `AtomKindRegistry.cs:83`, `ModifierOp.cs:69-75`).
`attackSpeedAdder`/`attackInterval` are the real speed-facing primary channels (`actionSpeed` is not
one of them); `armorFlat` is the real primary channel (plain `armor` is not); neither `crit-rate` nor
`dodge` appears in the 23-entry primary list at all. This generator's own `schema.CHANNEL_TUNING`
offers only strings drawn from the real `PrimaryChannels` vocabulary, so it cannot reproduce that
mismatch going forward — it is a pre-existing content gap in the hand-authored wave, not something
new content should repeat.
"""
from __future__ import annotations
