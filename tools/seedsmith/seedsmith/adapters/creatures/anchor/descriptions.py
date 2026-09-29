"""Prose for every anchor attribute (spec-anchor-contract.md §5) — the reliability mechanism, not
documentation. Each description states what the field means, what distinguishes it from its
nearest neighbour, and an explicit **negative clause**: what the field is *not*. §4.7's finding is
that enum selection is the most bias-prone task shape there is, and the sentence that prevents the
most common error — picking a plausible neighbouring value — is the one saying what the field
excludes.

Edited far more often than schema.py's shape, which is why it lives in its own module (a diff that
mixes prose and structure is unreviewable).
"""
from __future__ import annotations

DESCRIPTIONS: dict = {
    "side": (
        "Which roster this species belongs to: 'plant' or 'zombie'. Captured directly from the "
        "game's own almanac record, never chosen or inferred — this is NOT a classification, and "
        "a model never fills it."
    ),
    "speciesId": (
        "The species' stable identifier, derived from its captured type name. This is an "
        "identifier for lookups, NOT a display name and NOT a description of the species."
    ),
    "gameTypeId": (
        "The integer type id the game engine uses internally to spawn this species. This is an "
        "opaque identifier for a table lookup, NOT a magnitude, NOT a power level, and NOT a "
        "count of anything — it must never be used in arithmetic."
    ),
    "elementPrimary": (
        "The species' dominant combat element: fire, ice, air, earth, light, or dark. This is the "
        "element its own attacks and identity lean on. It is NOT the element that is strong "
        "against it, and NOT a resistance — a species can be primarily 'fire' while still taking "
        "extra damage from ice."
    ),
    "elementSecondary": (
        "A second element this species draws on, alongside elementPrimary, or 'none' if it has "
        "only one. This is NOT a resistance and NOT a weakness — it is a second offensive/"
        "identity element, at half strength of the primary. Most species legitimately have none; "
        "do not invent a secondary element just because the field exists."
    ),
    "aptitudePrimary": (
        "The one of the twelve aptitudes (Might, Fortitude, Vigor, Onslaught, Agility, Composure, "
        "Pierce, Focus, Bulwark, Retribution, Precision, Ferocity) this species' combat style "
        "leans on hardest. This is a COMBAT ROLE, NOT an element and NOT a rarity — a fragile, "
        "fast species is Agility even if it hits hard, because Agility is about evasion, not "
        "power."
    ),
    "aptitudeSecondary": (
        "A second aptitude this species draws on, or 'none' if its style is singular. NOT a "
        "ranking of importance versus aptitudePrimary — it is a genuinely secondary lean, at "
        "lower weight. Most species legitimately have none."
    ),
    "posture": (
        "DERIVED. One of Force, Finesse, or Bastion — the posture group aptitudePrimary belongs "
        "to. This field is computed by code from aptitudePrimary and is NEVER authored directly; "
        "a model must never emit this key with a value that does not match its own "
        "aptitudePrimary answer."
    ),
    "pure": (
        "DERIVED. True when aptitudePrimary and aptitudeSecondary share one posture (or "
        "aptitudeSecondary is 'none'). Computed by code, NEVER authored — it is NOT a judgement "
        "about how good the species is, only a structural fact about the two aptitude picks "
        "above."
    ),
    "threatBand": (
        "One of ten threat-noun rungs (nuisance, pest, marauder, raider, warden, scourge, tyrant, "
        "harbinger, cataclysm, calamity) describing how DANGEROUS this species is in a fight. "
        "This is NOT the same ladder as rarity below, and the two vocabularies deliberately share "
        "no word — threatBand answers 'how dangerous', never 'how special' or 'how rare to "
        "obtain'."
    ),
    "rarity": (
        "One of ten botanical rungs (chaff, sprout, grafted, cultivated, fused, chimeric, "
        "heirloom, firstseed, sunwoven, almanac) describing how SPECIAL or hard-to-obtain this "
        "species is. This is NOT a measure of combat danger — a rare species can be weak, and a "
        "common species can be dangerous. Never conflate this with threatBand."
    ),
    "rank": (
        "DERIVED. One of ten hunting-fantasy ranks (chaff, sprout, grafted, cultivated, fused, "
        "chimeric, heirloom, firstseed, sunwoven, almanac) computed by code from this species' "
        "already-resolved threatBand and rarity through the creature-rank grid. It mirrors the "
        "rarity ladder's own ids, but it is NOT a second spelling of rarity: rank is what the "
        "creature IS to a hunter, rarity is how special it is to obtain, and threatBand answers "
        "how dangerous it is. It is NOT a magnitude and never prices or scales anything, and a "
        "model NEVER authors it."
    ),
    "deployMode": (
        "How this species physically joins a fight: 'PlantAvatar' (fights as a plant-side "
        "combatant) or 'HypnoAlly' (a hypnotised zombie fighting for the plant side). This "
        "describes DEPLOYMENT MECHANICS, NOT the species' original side (a hypnotised zombie is "
        "still recorded as side='zombie' above; deployMode is how it can be fielded, not what it "
        "originally was)."
    ),
    "acquisition": (
        "One or more of Summonable, CaptureOnly, EventOnly — the ways a player can add this "
        "species to their roster. This is NOT a rarity signal and NOT a power signal; a "
        "CaptureOnly species is not automatically weaker or stronger than a Summonable one, only "
        "obtained differently. At least one flag is required."
    ),
    "variants": (
        "Which of the seven known variant forms (normal, ancient, mutated, corrupted, blessed, "
        "cursed, shiny) this species could plausibly have, named from its lore and nature. This "
        "names WHICH variants exist for the species, NOT how many will actually be offered — the "
        "count a given rarity permits is derived separately from rarity, never from this list's "
        "length."
    ),
    "resourceProfile": (
        "Which of the six actor resources (hp, stamina, hunger, spirit, qi, poise) this species "
        "meaningfully uses. This is NOT a list of stats it is good at — it is which pools its "
        "abilities draw from or protect. Most species use hp at minimum; do not select a resource "
        "just because the species is powerful in a way unrelated to that resource."
    ),
    "basis": (
        "DERIVED. One of observed, stated, inferred, or blocked — where the species' numeric "
        "seed came from (power-parse module). Computed by code from the capture, NEVER authored "
        "or guessed by a model — a model has no access to the underlying numeric data this field "
        "summarises."
    ),
    "speciesKind": (
        "DERIVED. One of creature, mimic, or excluded — what this ROW is, not what the creature "
        "is like (creature-seed R-CS3/R-CS4). `creature`: its gameTypeId resolves to a real "
        "PlantType/ZombieType member. `mimic`: a real creature that deliberately borrows a lawn "
        "type id it does not natively own. `excluded`: not a creature at all — never spawn, never "
        "draw, never count as roster. Computed by code from the game's own captured type table, "
        "NEVER authored or guessed by a model; this is a fact about the corpus, not a judgement "
        "about a creature. It is NOT `basis` (which says where the numbers came from) and NOT a "
        "quality or power statement — a real creature can legitimately be `blocked` basis."
    ),
    "family": (
        "One or more short thematic tags describing what kind of creature this is (e.g. "
        "'undead', 'mechanical', 'aquatic'). This is an OPEN, growing vocabulary — invent a "
        "reasonable tag if none of the existing ones fit, rather than forcing a poor match. This "
        "is NOT the element and NOT the aptitude; it is a lore/flavor grouping."
    ),
    "traits": (
        "One or more short tags naming distinguishing characteristics from this species' lore or "
        "behaviour (e.g. 'burrowing', 'regenerating', 'swift'). This is an OPEN, growing "
        "vocabulary, distinct from `family` above — family answers 'what kind of thing is this', "
        "traits answers 'what does it specifically do'. NOT a list of game mechanics or numeric "
        "effects; those are generated later from this description, never written here."
    ),
    "attackTempo": (
        "How fast this species acts relative to others: ponderous, slow, steady, quick, or "
        "flurry. This describes ATTACK RHYTHM, NOT raw power and NOT movement speed on the "
        "lawn — a species that hits hard but rarely is 'slow' or 'ponderous', not 'flurry', even "
        "if each individual hit is dangerous."
    ),
    "reach": (
        "How far this species can affect a target: melee, short, long, or siege. 'melee' touches "
        "the adjacent cell only. 'short' covers a few cells ahead. 'long' covers most of a lane. "
        "'siege' outranges the lane and is usually paired with a slow tempo. This describes "
        "REACH, NOT movement speed and NOT area of effect — a creature that walks fast but hits "
        "only what it touches is 'melee'."
    ),
    "targetPreference": (
        "What this species is built to threaten most: frontline, backline, swarm, elite, "
        "structure, or indiscriminate. This describes TACTICAL FOCUS, NOT which side it fights "
        "for and NOT its own defensive posture — a species that is itself fragile can still "
        "prefer 'backline' targets if that is where its attacks are aimed."
    ),
}
