"""seedsmith.adapters.items.naming_grammar — the shared prompt text for naming.v1.json's authored
`name` grammar (`NamingCheck.cs`'s `NameGrammarViolation` / `PossessiveForbidden` /
`InventedConnective` / `PluralForbidden` / `GeneratedOnlyNamePattern` checks,
`namingGrammar.patterns` + `namingGrammar.pluralsPossessivesConnectives` +
`namingGrammar.generatedOnlyPattern`).

Single source of truth so every brief that asks a model to author an item-family `name` (set, charm,
base-type, drop-table, combination, affix-family) states the SAME rule, rather than each generator
drifting into its own paraphrase of naming.v1.json's text. Found necessary 2026-09-20: nothing in the
generation pipeline stated this contract at all — every brief just said "a short display name" — so
the species-population set/charm names (and a smaller tail from every other item-family generator)
shipped grammar-illegal identity text: 1125 NameGrammarViolation/PossessiveForbidden/
InventedConnective/PluralForbidden/GeneratedOnlyNamePattern errors on a real ItemSeedValidator run,
almost all of them just these fixed authoring rules never having been said out loud to the model.
"""
from __future__ import annotations

#: Embed verbatim in any brief that asks a model for a `name` field on set/charm/base-type/
#: drop-table/combination/affix-family identity text. Kept short and imperative on purpose — a
#: model that reads a rule as narrative advice ("try to avoid...") treats it as optional; one that
#: reads it as a closed choice between three shapes treats it as the actual task.
#:
#: ⛔ Deliberately spells NO English number word (one/two/three/four/…) and no bare digit for a
#: word/part count — `combogen.brief`'s own `spells_the_count` guard refuses a brief that restates
#: its per-cell ingredient count in prose (its rule: the schema's fixed array length is the only
#: enforcement, so prose must never risk disagreeing with it), and this text is shared into that
#: brief too. "two words" / "a four-part name" collided with a real cell's count and raised
#: `BriefRefused` — found by running the combogen test suite, not by inspection.
NAMING_GRAMMAR_RULES = """`name` must use EXACTLY a single shape from the list below — pick whichever reads best, never combine them:
  A. Adjective Base — a short adjective-noun pair, e.g. "Ember Legion", "Hardened Seedcase".
  B. Base of [the] Concept — e.g. "Fang of Ash", "Signet of the Hollow Crown". `of` is the ONLY
     legal connective word, and only inside this shape.
  C. A single fused word made by concatenating a pair of real words with no space, e.g. "Ashfang"
     (Ash + Fang).

Hard rules, no exceptions:
  - No possessive ('s) anywhere in the name — write "Dragon Fang", never "Dragon's Fang".
  - No plural form of the head noun — the name identifies a single specific thing, not a category.
  - No connective word other than `of` (and an optional following `the`) — never "and", "from",
    "at", "&", or a hyphenated compound standing in for a connective.
  - Never combine shapes A and B into a single longer name ("Sturdy Bark Helm of Embers") — that
    shape is reserved for the engine's own rolled-instance naming and is refused from authored
    content."""
