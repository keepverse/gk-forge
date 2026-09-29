"""Prose for every dungeon anchor field (D1.6, spec-dungeon-seed-contract.md §1) — the reliability
mechanism, not documentation (creatures/anchor/descriptions.py's own rationale, restated here because
enum selection is the most bias-prone task shape there is regardless of which corpus it is in).
Every entry states what the field means and an explicit negative clause — most lifted near-verbatim
from the spec's own "Is not" column, which the spec's own §1 preamble says the schema must "carry
... in full."
"""
from __future__ import annotations

DESCRIPTIONS: dict = {
    # ---- domain (§1.1) ----------------------------------------------------------------------
    "domainId": ("The domain's stable identifier, minted by the planner as `domain.<climate>-<band>-<nnn>`. "
                 "This is NOT a name — it is never shown to a player."),
    "name": ("The domain or room's display name, free text. NOT a description of mechanics — it "
             "names the place, not what happens in it."),
    "flavor": ("Short evocative prose for the place. NOT a hint about the outcome, and NOT mechanics."),
    "theme": ("The domain's loot-binding theme from the 84-row theme registry. This is NOT the climate "
              "and NOT the boss's element — a fire domain may carry a charnel theme. Every domain has "
              "one; 'none' is refused because a domain without a theme has no loot binding."),
    "climate": ("The domain's element, one of six ElementTypeId values, planner-supplied. NOT the theme "
                "and NOT the boss's element."),
    "dangerBand": ("The domain's entrance band ordinal — shallow, mid, deep, or abyssal — planner-supplied "
                   "from the budget. This is NOT difficulty: the rung a player picks at the descent door "
                   "is a separate axis layered on top of this entrance band."),
    "permadeathFromRung": ("An optional rung id that RAISES the domain's permadeath gate above the tuning "
                           "default. This is NOT a permadeath flag, NOT a number, and it may never sit "
                           "lower than `difficulty.permadeathFromRung` — a domain only makes itself harder."),
    "entry": ("Whether the domain may be entered many times (a standing sub-world) or only once (`once`, "
              "archived at extraction). Planner-supplied from the budget. This is NOT how long a delve "
              "runs — that is the layout's `sizeBand`, a separate field entirely."),
    "layoutTemplateId": ("Which room-graph layout this domain rolls from, rotated per cell by the planner. "
                         "NOT chosen for theme fit — layouts are structural, not flavour-matched."),
    "bossSpeciesRef": ("The species id seated as this domain's boss, drawn from species carrying a threat "
                       "band of tyrant or above. NOT the retinue (a separate field) and NOT a HypnoAlly "
                       "flag — this names the boss's identity only."),
    "firstClearRef": ("An optional rung-80-or-above deterministic unique container id granted, by id, on "
                      "this domain's first clear — or 'none'. NOT a table and NOT a role or frame: it "
                      "names one exact item, never a category, and it is never a weight."),
    "retinueFamily": ("The creature family the boss's retinue draws from, or 'none' if the boss stands alone. "
                      "NOT the boss's own family by default — a boss may command a retinue from a "
                      "different lineage entirely."),
    "roomPalette": ("At least one room-archetype id per room kind this domain's layout can place. NOT an "
                   "ordering — which room fills which graph slot is decided by the roll, not by this list."),
    "questPool": ("At least two quest ids this domain offers at entry. NOT the rewards themselves — a "
                  "quest names its own reward band independently."),
    "lootBinding": ("A map from room kind to the planner-emitted drop-table id that kind draws from. NOT "
                   "weights — the table itself carries the drop-band frequencies, this field only names "
                   "which table."),
    "entranceHint": ("Which of the four existing map slot kinds (Lair, Tear, Vault, Anomaly) this domain's "
                     "theme maps to. NOT a map position — the world-map generator decides where, this "
                     "only decides which icon and theme family."),
    "variants": ("Which of the seven content variants this anchor participates in, or 'none'. Legal to be "
                "empty — most anchors carry no variant. NOT a difficulty modifier and NOT a rarity tier."),
    "tags": ("Free-form dungeon tags for cross-cutting queries, or 'none'. Tags are NOT room kinds and "
            "carry no mechanical weight on their own."),
    "reason": ("The model's own free-text account of why it picked what it picked. This is provenance for "
              "a human reviewer, NOT a field any other system reads or validates against."),

    # ---- room (§1.2) -------------------------------------------------------------------------
    "roomId": ("The room archetype's stable identifier, minted as `room.<kind>-<climate>-<nnn>`. NOT a "
              "display name — it is never shown to a player."),
    "kind": ("Which of the eleven room kinds this archetype belongs to (room anchor) or which of the six "
            "event kinds this event belongs to (event anchor), planner-supplied. On a room, this is NOT "
            "the event kind a room's own event pool draws from — a `curio` room draws `curio` events but "
            "is not itself one."),
    "dispositionBase": ("The wild room's starting disposition toward the party — eager, open, wary, or "
                        "hostile — voted, required only on the `wild` kind and 'none' on every other kind. "
                        "NOT the delta-band shift a runtime encounter applies on top; this is the base row "
                        "only."),
    "hazardBand": ("How much hunger this room costs to cross — none, light, or heavy — voted, legal as "
                  "'none'. This is NOT danger: a heavy-hazard room can be an easy fight, and an easy room "
                  "can cost real hunger to reach."),
    "sightBand": ("How much of the graph this room reveals when scouted — dim, lit, or scouting. Required "
                 "on every room with no default: an omitted value is a defect, never silently 'lit'. NOT "
                 "room size."),
    "encounterRef": ("Which encounter filter this room draws its fight from, or 'none' on a non-fight "
                     "kind. The referenced encounter's formation must fit the room's own kind (fight/wild "
                     "-> pack, elite -> party, boss -> boss). NOT a species — an encounter never lists one."),
    "eventPool": ("At least one event id whose kind fits this room, or 'none' on fight/elite/boss/cache "
                 "kinds. NOT the whole deck — the runtime's four-filter selector narrows this pool "
                 "further at roll time."),
    "secretEligible": ("Whether this room may be placed as a secret dead end — a two-value 'yes'/'no' "
                       "enum, deliberately not a bool, so the field is always a stated decision rather "
                       "than an ambiguous default. NOT 'hidden from the map' — a secret room is still "
                       "drawn on the graph once discovered."),

    # ---- layout (§1.3) -----------------------------------------------------------------------
    "layoutId": ("The layout template's stable identifier. NOT a display name and NOT a reference any "
                "room or event ever carries — only a domain names its layoutTemplateId."),
    "sizeBand": ("How many rows the room graph has — short, medium, or long — planner-emitted from "
                "`dungeon.v1.json` bands. NOT the domain's dangerBand and NOT a difficulty signal — it "
                "is a pure graph-shape count."),
    "widthBand": ("How many columns the room graph has per row — narrow, regular, or broad. NOT the row "
                 "count (sizeBand) and NOT branchiness — a wide graph can still be a single linear walk."),
    "branchiness": ("How many parallel path walks the graph carries — linear, forked, or webbed. NOT the "
                    "row count; a linear graph can still be long."),
    "gateDensity": ("How often a locked door with a key elsewhere on the graph appears — none, sparse, or "
                    "dense. 'none' is legal: 'no gates' is itself a valid layout. NOT secretDensity and "
                    "NOT oneWayDensity — each door feature is an independent dial."),
    "secretDensity": ("How often a secret dead-end room may attach to the graph — none, sparse, or dense. "
                      "NOT gateDensity and NOT a room's own secretEligible flag — a dense layout still "
                      "only places a secret at a room that itself allows one."),
    "oneWayDensity": ("How often a one-way (deeper-only) lane appears — none, sparse, or dense. NOT a "
                      "locked gate — a one-way lane needs no key, it simply cannot be walked back through."),
    "raidModes": ("Which of solo, pair, or quad raid modes this layout supports — never empty. NOT the "
                 "domain's own raid-mode offer — a domain may restrict further, but never widen beyond "
                 "what its layout supports."),

    # ---- event (§1.4) ------------------------------------------------------------------------
    "eventId": ("The event's stable identifier. NOT a display name — the event's own `name` field is "
               "what a player sees."),
    "climateAffinity": ("Which element this event's flavour leans toward, or 'none' for a climate-blind "
                        "event. This is NOT an eligibility rule — affinity only weights the draw; it never "
                        "gates whether the event can appear."),
    "repeatScope": ("How often this event or quest may recur for the same player — per-delve, per-domain, "
                    "or once-per-player, on an event; delve, domain, or roster scope on a quest. Every "
                    "event repeats somehow, so 'none' is refused on the event anchor. NOT chainRef — a "
                    "scope names a recurrence rule, never a specific next entry."),
    "eligibility": ("An authored predicate tree over the closed leaf vocabulary (twelve PredicateNode "
                    "leaves plus event-deck's four additions) deciding whether this event may be drawn "
                    "here. Leaf arguments are bands (e.g. hpBand: low/half/high), never raw per-mille "
                    "values. 'none' means always-eligible and is legal. This is NOT the outcome filter — "
                    "a separate mechanism selects among a *drawable* event's own outcomes."),
    "outcomes": ("Two to four outcome rows, each an ordinal (good/mixed/bad/nothing), a drop-band "
                "frequency, and its granted effects. This is NOT a menu of equal options — the ordinals "
                "and bands make some outcomes deliberately more likely and more or less desirable than "
                "others."),
    "supplyOverride": ("A registry override tag (herbs, key, holy, bait, or watch) a held supply can spend "
                       "to force this event's best outcome, or 'none'. NOT a supply id — the tag lives on "
                       "the event; supplies separately declare which tags they satisfy."),
    "chainRef": ("The next chapter's event id for a `story`-kind event, or 'none' (required unless "
                "kind is 'story'). On a quest, an optional follow-up quest id, or 'none'. NOT a "
                "prerequisite — chaining is sequence, not gating."),

    # ---- quest (§1.5) ------------------------------------------------------------------------
    "questId": ("The quest's stable identifier. NOT a display name — the quest's own `name` field is "
               "what a player sees."),
    "objectiveTemplate": ("Which of the nine closed objective templates this quest instantiates, planner-"
                         "supplied. NOT the reward — a template only names the shape of the goal."),
    "scope": ("Which fact source this quest's predicate evaluates against — delve, domain, or roster. "
             "NOT the objective template and NOT the reward tier — scope only says which report the "
             "predicate reads."),
    "targetRef": ("A kind reference (a room kind, an event kind, or a species family) this quest's "
                 "objective counts against, or 'none' for count-only templates. NOT a specific id and "
                 "never a number."),
    "countBand": ("How much of the target this quest asks for — few, some, most, or all — voted. 'none' "
                 "is legal and REQUIRED on the six count-less templates (kill-boss, extract-with-item-"
                 "kind, bring-creature-home-alive, finish-under-hunger, survive-no-downed, spend-no-"
                 "provision). NOT a difficulty rating — 'all' on a short layout is easy, not hard."),
    "rewardBand": ("Which tier-window reward ordinal (modest, fair, or rich) this quest pays out on "
                  "completion — voted. NOT souls and NOT an item; it names a window the loot pipeline "
                  "resolves at completion time."),
    "prereqRefs": ("Quest ids that must already be complete before this one may be offered, or 'none'. "
                  "NOT an unlock mechanism — quests reward, they never unlock content."),

    # ---- encounter (§1.6) --------------------------------------------------------------------
    "encounterId": ("The encounter filter's stable identifier. NOT a display name and NOT a list of "
                   "species — an encounter never names one."),
    "formation": ("Which of pack, party, or boss shape this encounter fills. NOT a count — the actual "
                 "number of enemies comes from each slot's own countBand."),
    "elementSpread": ("How many distinct elements this encounter's species may carry — mono, dual, or "
                     "rainbow. NOT which elements — only how many; the actual elements come from "
                     "whichever species the slot filter draws."),
    "slots": ("The filter tuples (posture, reach, targetPreference, countBand) this encounter fills from "
             "the species corpus. NOT a list of species and NOT a role noun standing in for a real filter "
             "— 'front-line' must be written as an actual posture-and-reach combination, never as a "
             "descriptive label."),
    "threatWindow": ("The floor and ceiling threat-band rungs this encounter's species must fall within — "
                     "voted. NOT a Θ value — the actual offset from a threat rung to a power delta is a "
                     "tuning table this field never touches."),
    "rankOrder": ("The slot ids in front-to-back emission order. NOT a targeting priority — where an "
                 "enemy stands is not the same fact as who gets attacked first."),
    "tempo": ("Which of five attack-tempo values this encounter's species should carry, or 'none' for no "
             "preference. NOT initiative — tempo is a species-selection filter, not a turn-order value."),
    "synergyHint": ("An optional pair of trait-battle-catalog ids this encounter's roll should favour "
                   "pairing, or 'none'. NOT a guarantee — the weighted roll may still miss the pairing."),
    "affixRoll": ("A rarity rung id this encounter's elite affix should roll at, or 'none' on a non-elite "
                 "encounter. A rung sets breadth and a ceiling on what may roll — it is NOT a multiplier "
                 "on anything, and NOT the affix itself — the actual affix is rolled at runtime, this "
                 "only bounds the roll."),
    "boss": ("The boss-only kit: its pattern id, phasing shape, phase trigger, and signature action. NOT "
            "a species — the domain anchor pins the actual boss species at runtime; this only shapes "
            "how that species' fight plays out."),

    # ---- supply extension (§1.7) ---------------------------------------------------------------
    "consumableRef": ("The base consumable id (from the existing item consumable corpus) this dungeon-"
                      "specific extension record attaches additional context to. NOT a new consumable — "
                      "the extension adds context to an existing item record, it never mints a second one."),
    "overrideTags": ("Which override tags (herbs, key, holy, bait, watch) this supply satisfies, or "
                     "'none' — but a record with 'none' here and no restoring effect is refused; a "
                     "supply must do at least one of the two. NOT a supply id and NOT an event id — the "
                     "tag is a shared vocabulary both sides check against, never a direct reference."),
    "useContextAdds": ("Which of the two dungeon-only use contexts (rest, curio) this supply is additionally "
                      "usable in, beyond whatever contexts its base consumable record already carries. "
                      "NOT a replacement for the base record's own useContext — it only adds, never removes."),
}
