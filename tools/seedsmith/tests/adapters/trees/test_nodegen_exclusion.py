"""Tests for seedsmith.adapters.trees.nodegen.exclusion (task H1) — the D14 form ladder;
`propertyKeys` checked against the plan's own `propertyVocabulary`, never a node id
(spec-tree-language.md §5, §7 gate 19).
"""
from __future__ import annotations

import unittest

from seedsmith.adapters.trees.nodegen import exclusion


VOCAB = {"posture": ("vanguard", "warden"), "conversionState": ("converted", "unconverted")}


class ExclusionClaimTests(unittest.TestCase):
    def test_from_response_reads_form_and_keys(self) -> None:
        claim = exclusion.ExclusionClaim.from_response(
            {"form": "reroute", "propertyKeys": ["posture"]})
        self.assertEqual(claim.form, "reroute")
        self.assertEqual(claim.property_keys, ("posture",))

    def test_from_response_defaults_to_none_form_with_no_keys(self) -> None:
        claim = exclusion.ExclusionClaim.from_response({})
        self.assertEqual(claim.form, exclusion.NONE_FORM)
        self.assertEqual(claim.property_keys, ())


class ValidateExclusionTests(unittest.TestCase):
    def test_none_form_with_no_keys_is_clean(self) -> None:
        claim = exclusion.ExclusionClaim(form=exclusion.NONE_FORM, property_keys=())
        self.assertEqual(exclusion.validate_exclusion(claim, VOCAB), [])

    def test_none_form_carrying_keys_is_a_defect(self) -> None:
        claim = exclusion.ExclusionClaim(form=exclusion.NONE_FORM, property_keys=("posture",))
        defects = exclusion.validate_exclusion(claim, VOCAB)
        self.assertTrue(defects)

    def test_reroute_with_a_legal_key_is_clean(self) -> None:
        claim = exclusion.ExclusionClaim(form=exclusion.REROUTE, property_keys=("posture",))
        self.assertEqual(exclusion.validate_exclusion(claim, VOCAB), [])

    def test_a_non_none_form_with_no_keys_is_a_defect(self) -> None:
        claim = exclusion.ExclusionClaim(form=exclusion.PRECEDENCE, property_keys=())
        defects = exclusion.validate_exclusion(claim, VOCAB)
        self.assertTrue(defects)

    def test_a_key_outside_the_vocabulary_is_a_defect(self) -> None:
        claim = exclusion.ExclusionClaim(form=exclusion.REROUTE, property_keys=("notAProperty",))
        defects = exclusion.validate_exclusion(claim, VOCAB)
        self.assertTrue(defects)

    def test_a_key_shaped_like_a_node_id_is_a_defect_even_if_never_seen_before(self) -> None:
        """D14/§5.2 item 3: a predicate must key on a PROPERTY, never on a node id — this is
        checked by SHAPE, so it fires even against a vocabulary that (incorrectly) contained one."""
        claim = exclusion.ExclusionClaim(
            form=exclusion.NULLIFICATION, property_keys=("skill.might-off-t3-n2",))
        defects = exclusion.validate_exclusion(claim, {"posture": ("skill.might-off-t3-n2",)})
        self.assertTrue(defects)
        self.assertTrue(any("node-id shape" in str(d) for d in defects))

    def test_an_illegal_form_is_a_defect(self) -> None:
        claim = exclusion.ExclusionClaim(form="always", property_keys=())
        defects = exclusion.validate_exclusion(claim, VOCAB)
        self.assertTrue(defects)

    def test_accepts_a_flattened_sequence_vocabulary_too(self) -> None:
        claim = exclusion.ExclusionClaim(form=exclusion.REROUTE, property_keys=("posture",))
        self.assertEqual(exclusion.validate_exclusion(claim, ["posture", "conversionState"]), [])

    def test_nullification_stays_a_legal_form_per_d40(self) -> None:
        self.assertIn(exclusion.NULLIFICATION, exclusion.EXCLUSION_FORMS)


# ---------------------------------------------------------------------------------------------
# task H3 — exclusion_winner / compose_printed_text: "both sides print the rule, both name the
# same winner" (§5.2 rule 1, D40), made a property of a PURE template rather than a cross-node
# runtime check (this module's own resolved ambiguity).
# ---------------------------------------------------------------------------------------------

class ExclusionWinnerTests(unittest.TestCase):
    def test_a_single_property_names_itself(self) -> None:
        self.assertEqual(exclusion.exclusion_winner(("posture",)), "posture")

    def test_multiple_properties_join_with_and(self) -> None:
        self.assertEqual(exclusion.exclusion_winner(("posture", "conversionState")),
                        "posture and conversionState")

    def test_no_properties_refuses(self) -> None:
        with self.assertRaises(ValueError):
            exclusion.exclusion_winner(())


class ComposePrintedTextTests(unittest.TestCase):
    def test_none_form_composes_to_the_empty_string(self) -> None:
        self.assertEqual(exclusion.compose_printed_text(exclusion.NONE_FORM, ()), "")
        # even if a (malformed) caller hands it keys, 'none' never prints anything
        self.assertEqual(exclusion.compose_printed_text(exclusion.NONE_FORM, ("posture",)), "")

    def test_every_non_none_form_produces_non_empty_text_naming_the_property(self) -> None:
        for form in (exclusion.REROUTE, exclusion.PRECEDENCE, exclusion.NULLIFICATION):
            text = exclusion.compose_printed_text(form, ("posture",))
            self.assertTrue(text)
            self.assertIn("posture", text)

    def test_a_non_none_form_with_no_properties_refuses(self) -> None:
        with self.assertRaises(ValueError):
            exclusion.compose_printed_text(exclusion.NULLIFICATION, ())

    def test_an_unknown_form_refuses(self) -> None:
        with self.assertRaises(ValueError):
            exclusion.compose_printed_text("always", ("posture",))

    def test_an_unknown_role_refuses(self) -> None:
        with self.assertRaises(ValueError):
            exclusion.compose_printed_text(exclusion.NULLIFICATION, ("posture",), role="tie")

    def test_loser_and_winner_roles_name_the_same_winner_by_construction(self) -> None:
        """§5.2 rule 1's own load-bearing property: BOTH roles must name the identical winner
        string, for every form -- proven here as a template identity rather than a cross-node
        comparison this module has no second response to run against (its own docstring)."""
        for form in (exclusion.REROUTE, exclusion.PRECEDENCE, exclusion.NULLIFICATION):
            winner = exclusion.exclusion_winner(("posture", "conversionState"))
            loser_text = exclusion.compose_printed_text(form, ("posture", "conversionState"), role="loser")
            winner_text = exclusion.compose_printed_text(form, ("posture", "conversionState"), role="winner")
            self.assertIn(winner, loser_text)
            self.assertIn(winner, winner_text)
            self.assertNotEqual(loser_text, winner_text)  # the two sides read differently, never identically

    def test_the_same_form_and_properties_always_compose_the_same_text(self) -> None:
        """Determinism: no node identity, no RNG, no call order enters the template."""
        a = exclusion.compose_printed_text(exclusion.NULLIFICATION, ("posture",))
        b = exclusion.compose_printed_text(exclusion.NULLIFICATION, ("posture",))
        self.assertEqual(a, b)

    def test_never_names_a_node_id(self) -> None:
        for form in (exclusion.REROUTE, exclusion.PRECEDENCE, exclusion.NULLIFICATION):
            text = exclusion.compose_printed_text(form, ("posture",))
            self.assertNotIn("skill.", text)


if __name__ == "__main__":
    unittest.main()
