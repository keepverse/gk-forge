"""EPL1.1 -- the `affix-power-class` closed enum, its checked-in registry, and the C# mirror.

`docs/architecture/effect-pipeline/spec-affix-power-class.md` (module 11) is the authority for
what this file pins. The row under test is a CLOSED, append-only, structurally-ordered vocabulary
of five classes, and the three contracts that make it worth having are:

1. **The vocabulary is closed and the ids are fixed** -- five ids, consecutive ordinals 0..4, no
   renumbering, no gaps. A sixth class is an owner-reviewed change (spec "Boundaries"), which is
   exactly why the roster is a closed vocabulary and a pinned literal is correct here
   (`docs/architecture/validation-ssot.md` §6) rather than a population reading.
2. **The registry is IDENTITY, never a magnitude** (spec P1 / "Boundaries": the model writes
   identity, deterministic code writes magnitude). This file therefore audits every number in the
   registry document mechanically -- only `ordinal` / `schemaVersion` / `registryVersion` may hold
   one, and those are structural metadata, not values a balance pass would move. There is NO
   weight, rate, probability, magnitude or target share anywhere in it.
3. **The C# mirror and the JSON registry cannot drift** -- same ids, same ordinals, and the mirror
   file declares exactly ONE enum (the one-mirror rule: no second enum, no classifier, no
   channel vocabulary, no allowlist).

Plus the two-axes guard the spec makes a named test: **no power-class id may equal a rarity rung
id** (`chaff .. almanac`) -- checked against the CURRENT rarity vocabulary read from the rarity
ladder seed, not from a copied list that could rot.

What this file deliberately does NOT assert: any family, affix or corpus count. The
classification run is EPL1.3, under its own owner charter; nothing here may pre-populate or
fake-populate its results, and a coverage number is a READING that moves when content ships
(`validation-ssot.md` §1, "derived population").
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
REGISTRY_PATH = REPO_ROOT / "data" / "seed" / "items" / "_registry" / "power-classes.v1.json"
MIRROR_PATH = REPO_ROOT / "src" / "FusionRpg.Core" / "Effects" / "Atoms" / "AffixPowerClass.cs"
RARITY_LADDER_PATH = REPO_ROOT / "data" / "seed" / "rarity" / "ladder.v1.json"

# The closed roster, written out. This is a CLOSED vocabulary (spec "Boundaries": adding a sixth is
# ask-first), so the literal is the contract and not a population reading.
EXPECTED_IDS = ("filler", "notable", "potent", "defining", "pinnacle")

#: Keys permitted to hold a number anywhere in the registry. Everything else is a magnitude, and a
#: magnitude in an identity file is the P1 violation the spec names (`the_schema_audit_rejects_a_
#: numeric_power_class`).
STRUCTURAL_NUMERIC_KEYS = frozenset({"ordinal", "schemaVersion", "registryVersion"})

#: The generator-provenance keys `gk-core/scripts/guard-generated-seed.py` keys on. A file carrying any
#: of them is generator OUTPUT, which is not what this file is: it is authored, like every other
#: `gk-data/packs/fusion/data/seed/items/_registry/**` entry.
PROVENANCE_KEYS = ("model", "promptVersion", "batch")


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def numeric_leaves(node, path: str = "$"):
    """Every (jsonPath, key, value) whose value is a JSON number, depth-first."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from numeric_leaves(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from numeric_leaves(value, f"{path}[{i}]")
    elif isinstance(node, bool):  # bool is an int subclass -- not a magnitude
        return
    elif isinstance(node, (int, float)):
        yield path, node


def leaf_key(json_path: str) -> str:
    return json_path.rsplit(".", 1)[-1]


def strip_csharp_comments(text: str) -> str:
    """Drop `/* */` and `//` comments. A member's own XML doc comment must never be read as a
    member — the same discipline `gk-core/scripts/guard-vocabulary-mirror.py`'s `strip_comments` applies
    to the C# enums it reads by text."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", text)


def extract_csharp_enum(path: Path, enum_name: str) -> list[tuple[str, int]]:
    """`(Member, ordinal)` pairs of a real C# enum declaration, in declaration order.

    Text-level on purpose: this is a MIRROR contract, so it reads the shipped file itself rather
    than importing anything, and it understands both an explicit `= N` and an implicit
    "previous + 1" so it is not a formatting pin. Comments are stripped first, so a member's own
    doc comment is never read as a member.
    """
    text = strip_csharp_comments(path.read_text(encoding="utf-8"))
    open_match = re.search(r"public\s+enum\s+" + re.escape(enum_name) + r"\s*\{", text)
    if open_match is None:
        raise AssertionError(f"{path.name}: no `public enum {enum_name}` declaration")
    body_start = open_match.end()
    depth = 1
    i = body_start
    while i < len(text) and depth:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    body = text[body_start : i - 1]

    members: list[tuple[str, int]] = []
    next_ordinal = 0
    for chunk in body.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "=" in chunk:
            name, _, raw = chunk.partition("=")
            name = name.strip()
            try:
                next_ordinal = int(raw.strip(), 0)
            except ValueError as exc:  # pragma: no cover - a malformed mirror is the finding
                raise AssertionError(f"{enum_name}.{name}: non-integer ordinal {raw.strip()!r}") from exc
        else:
            name = chunk.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            raise AssertionError(f"{enum_name}: {name!r} is not a plain identifier member")
        members.append((name, next_ordinal))
        next_ordinal += 1
    return members


class RegistryFileShapeTests(unittest.TestCase):
    """The registry's own schema -- closed roster, no magnitudes, authored not generated."""

    def test_the_registry_file_exists_and_declares_the_house_schema_keys(self):
        doc = load_registry()
        for key in ("schemaVersion", "registryVersion", "_meta", "classes"):
            self.assertIn(key, doc, f"power-classes.v1.json is missing '{key}'")

    def test_schema_and_append_only_flags_are_valid(self):
        doc = load_registry()
        self.assertEqual(doc["schemaVersion"], 1)
        self.assertIs(doc["appendOnly"], True)
        self.assertGreaterEqual(doc["registryVersion"], 1)

    def test_the_roster_is_the_five_ids_with_consecutive_ordinals_from_zero(self):
        classes = load_registry()["classes"]
        self.assertEqual([c["id"] for c in classes], list(EXPECTED_IDS))
        self.assertEqual([c["ordinal"] for c in classes], list(range(len(EXPECTED_IDS))))
        self.assertEqual(len(classes), len(EXPECTED_IDS))

    def test_ordinals_are_unique_and_declaration_order_is_ordinal_order(self):
        classes = load_registry()["classes"]
        ordinals = [c["ordinal"] for c in classes]
        self.assertEqual(len(set(ordinals)), len(ordinals), "two classes share one ordinal")
        self.assertEqual(ordinals, sorted(ordinals), "a row's ordinal is out of declaration order")

    def test_ids_are_unique_bare_lowercase_words(self):
        ids = [c["id"] for c in load_registry()["classes"]]
        self.assertEqual(len(set(ids)), len(ids), "two classes share one id")
        for power_class_id in ids:
            self.assertRegex(
                power_class_id,
                r"^[a-z]+$",
                f"power-class id {power_class_id!r} is not a bare lowercase word",
            )

    def test_the_registry_carries_no_magnitude_only_structural_numbers(self):
        """P1, mechanically: identity only. A number here would be a weight, rate, probability,
        magnitude or target share -- every one of which belongs to deterministic code or
        `gk-core/data/tuning/`, never to the registry this file pins."""
        offenders = [
            f"{path} = {value!r}"
            for path, value in numeric_leaves(load_registry())
            if leaf_key(path) not in STRUCTURAL_NUMERIC_KEYS
        ]
        self.assertEqual(offenders, [], f"numeric field(s) in an identity registry: {offenders}")

    def test_the_registry_is_authored_not_generator_output(self):
        """`gk-core/scripts/guard-generated-seed.py` classifies a file under a generated tree as output
        only when it carries provenance; this file is authored, so it must carry none."""
        meta = load_registry()["_meta"]
        for key in PROVENANCE_KEYS:
            self.assertNotIn(key, meta, f"_meta.{key} would mark this authored registry as generated")
        self.assertIn("authoredUtc", meta, "an authored registry records when it was authored")

    def test_the_registry_says_where_the_target_shares_live(self):
        """The spec's share column is a balance TARGET, so the registry points at its real home
        (EPL1.3's tuning file) instead of carrying the numbers."""
        meta = load_registry()["_meta"]
        self.assertIn("targetSharesHome", meta)
        self.assertIn("data/tuning/", meta["targetSharesHome"])


class RarityCollisionTests(unittest.TestCase):
    """Two axes must never be confusable: `spec-affix-power-class.md` "The names deliberately
    share no word with a rarity rung"."""

    def test_no_power_class_id_equals_a_rarity_rung_id(self):
        rarity = json.loads(RARITY_LADDER_PATH.read_text(encoding="utf-8"))
        rung_ids = {entry["id"] for entry in rarity["entries"]}
        self.assertTrue(rung_ids, "the rarity ladder resolved no rungs -- the check would be vacuous")
        power_ids = {c["id"] for c in load_registry()["classes"]}
        self.assertEqual(power_ids & rung_ids, set(), "a power-class id collides with a rarity rung id")


class CSharpMirrorTests(unittest.TestCase):
    """`gk-core/src/FusionRpg.Core/Effects/Atoms/AffixPowerClass.cs` mirrors the registry. Same ids, same
    ordinals, and it is the ONE mirror (one-mirror rule)."""

    def test_the_mirror_file_exists_and_declares_exactly_one_enum(self):
        text = MIRROR_PATH.read_text(encoding="utf-8")
        declared = re.findall(r"public\s+enum\s+([A-Za-z_][A-Za-z0-9_]*)", text)
        self.assertEqual(
            declared,
            ["AffixPowerClass"],
            "the power-class vocabulary has exactly one home; a second enum is a defect",
        )

    def test_the_mirror_declares_the_same_ids_and_ordinals_as_the_registry(self):
        mirror = extract_csharp_enum(MIRROR_PATH, "AffixPowerClass")
        registry = [(c["id"], c["ordinal"]) for c in load_registry()["classes"]]
        self.assertEqual(
            [name.lower() for name, _ in mirror],
            [power_class_id for power_class_id, _ in registry],
            "C# member order and ids do not match the registry",
        )
        self.assertEqual([o for _, o in mirror], [o for _, o in registry], "ordinals disagree")

    def test_the_mirror_declares_no_numeric_balance_field(self):
        """The mirror is identity too: a `double`/`decimal`/weight-shaped member would be P1 in
        C# instead of in JSON, and the same audit has to hold here."""
        text = MIRROR_PATH.read_text(encoding="utf-8")
        body = strip_csharp_comments(text)
        body = body[body.index("public enum AffixPowerClass") :]
        body = body[body.index("{") + 1 : body.index("}")]
        for member in body.split(","):
            if not member.strip():
                continue  # a trailing comma is formatting, not a member
            self.assertRegex(
                member.strip(),
                r"^[A-Za-z_][A-Za-z0-9_]*(\s*=\s*\d+)?$",
                f"enum member {member.strip()!r} is not a bare name/ordinal pair",
            )


if __name__ == "__main__":
    unittest.main()
