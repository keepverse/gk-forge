"""Tests for `usage-direction`'s wiring into `general_propose` (FC3, spec-usage-direction.md,
roster-balance program).

    python -m pytest gk-forge/tools/seedsmith/tests/test_usage_direction.py -v

Model-free: `build_context`/`build_brief` make zero calls by construction, so no transport stub is
needed anywhere here — the same guarantee `test_general_propose.py` already relies on.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # noqa: E402

from seedsmith.adapters.actions.general_propose.prompts import build_brief, build_context  # noqa: E402
from seedsmith.adapters.actions.usage_direction.weights import (  # noqa: E402
    CEILING_WEIGHT_MILLI, CUE_LABEL, weights_for,
)

from test_general_propose import make_brief  # noqa: E402
import test_family_propose
import test_signature_propose
from seedsmith.adapters.actions.family_propose.prompts import (  # noqa: E402
    build_brief as family_build_brief, build_context as family_build_context,
)
from seedsmith.adapters.actions.signature_propose.prompts import (  # noqa: E402
    build_brief as signature_build_brief, build_context as signature_build_context,
)


class TestOmittingUsageWeightsIsInert:
    def test_context_is_byte_identical_when_usage_weights_is_omitted(self):
        brief = make_brief()
        with_none = build_context(brief, sample_index=0)
        without_param = build_context(brief, sample_index=0, usage_weights=None)
        assert with_none == without_param

    def test_context_is_byte_identical_when_usage_weights_is_empty(self):
        brief = make_brief()
        empty = build_context(brief, sample_index=0, usage_weights={})
        omitted = build_context(brief, sample_index=0)
        assert empty == omitted

    def test_rendered_brief_is_byte_identical_when_usage_weights_is_omitted(self):
        brief = make_brief()
        ctx_omitted = build_context(brief, sample_index=0)
        ctx_empty = build_context(brief, sample_index=0, usage_weights={})
        assert build_brief(ctx_omitted) == build_brief(ctx_empty)


class TestAllowedAtomFamiliesIsNeverTouched:
    def test_allowed_atom_families_is_identical_with_and_without_weighting(self):
        """⛔ THE load-bearing property. Weighting must only change how a family is DESCRIBED,
        never the pool a brief allows — this is what keeps spec-distribution-planner.md constraint
        4 (the C1 tier-widening gate) structurally unreachable rather than merely undiscussed."""
        brief = make_brief()
        weights = {"atom.a": CEILING_WEIGHT_MILLI}
        ctx_unweighted = build_context(brief, sample_index=0)
        ctx_weighted = build_context(brief, sample_index=0, usage_weights=weights)
        assert ctx_unweighted["allowedAtomFamilies"] == ctx_weighted["allowedAtomFamilies"]
        assert ctx_unweighted["forbiddenAtomFamilies"] == ctx_weighted["forbiddenAtomFamilies"]

    def test_weighting_never_narrows_the_pool_to_fewer_options(self):
        brief = make_brief()
        weights = weights_for(["atom.a"], {}, population_size=3)  # weight only ONE of the three
        ctx = build_context(brief, sample_index=0, usage_weights=weights)
        assert len(ctx["allowedAtomFamilies"]) == 3


class TestRenderingCarriesTheCue:
    def test_an_underused_family_is_rendered_with_the_legible_cue(self):
        brief = make_brief()
        weights = {"atom.a": CEILING_WEIGHT_MILLI, "atom.b": 1000, "atom.c": 1000}
        ctx = build_context(brief, sample_index=0, usage_weights=weights,
                            family_glossary={"atom.a": "Might", "atom.b": "Warding", "atom.c": "Vigor"})
        brief_text = build_brief(ctx)
        assert f"atom.a: Might ({CUE_LABEL})" in brief_text
        assert f"atom.b: Warding ({CUE_LABEL})" not in brief_text

    def test_no_cue_appears_anywhere_when_usage_weights_is_omitted(self):
        brief = make_brief()
        ctx = build_context(brief, sample_index=0,
                            family_glossary={"atom.a": "Might", "atom.b": "Warding", "atom.c": "Vigor"})
        brief_text = build_brief(ctx)
        assert CUE_LABEL not in brief_text

    def test_the_cue_never_leaks_a_numeric_weight_into_the_prompt_text(self):
        brief = make_brief()
        weights = {"atom.a": CEILING_WEIGHT_MILLI}
        ctx = build_context(brief, sample_index=0, usage_weights=weights)
        brief_text = build_brief(ctx)
        assert str(CEILING_WEIGHT_MILLI) not in brief_text

    def test_weighting_alone_without_a_glossary_still_renders_the_cue(self):
        brief = make_brief()
        weights = {"atom.a": CEILING_WEIGHT_MILLI}
        ctx = build_context(brief, sample_index=0, usage_weights=weights)
        brief_text = build_brief(ctx)
        assert f"atom.a ({CUE_LABEL})" in brief_text


# ---------------------------------------------------------------------------------------------
# The identical contract, proven on the other two propose pipelines -- not assumed to transfer.
# ---------------------------------------------------------------------------------------------

class TestFamilyProposeWiring:
    def test_context_is_byte_identical_when_usage_weights_is_omitted(self):
        brief = test_family_propose.make_brief()
        assert (family_build_context(brief, sample_index=0)
                == family_build_context(brief, sample_index=0, usage_weights=None))

    def test_allowed_atom_families_is_never_touched_by_weighting(self):
        brief = test_family_propose.make_brief()
        weights = {"atom.a": CEILING_WEIGHT_MILLI}
        unweighted = family_build_context(brief, sample_index=0)
        weighted = family_build_context(brief, sample_index=0, usage_weights=weights)
        assert unweighted["allowedAtomFamilies"] == weighted["allowedAtomFamilies"]

    def test_an_underused_family_is_rendered_with_the_legible_cue(self):
        brief = test_family_propose.make_brief()
        weights = {"atom.a": CEILING_WEIGHT_MILLI}
        ctx = family_build_context(brief, sample_index=0, usage_weights=weights)
        assert f"atom.a ({CUE_LABEL})" in family_build_brief(ctx)


class TestSignatureProposeWiring:
    def test_context_is_byte_identical_when_usage_weights_is_omitted(self):
        brief = test_signature_propose.make_brief()
        assert (signature_build_context(brief, sample_index=0)
                == signature_build_context(brief, sample_index=0, usage_weights=None))

    def test_allowed_atom_families_is_never_touched_by_weighting(self):
        brief = test_signature_propose.make_brief()
        weights = {"atom.a": CEILING_WEIGHT_MILLI}
        unweighted = signature_build_context(brief, sample_index=0)
        weighted = signature_build_context(brief, sample_index=0, usage_weights=weights)
        assert unweighted["allowedAtomFamilies"] == weighted["allowedAtomFamilies"]

    def test_an_underused_family_is_rendered_with_the_legible_cue(self):
        brief = test_signature_propose.make_brief()
        weights = {"atom.a": CEILING_WEIGHT_MILLI}
        ctx = signature_build_context(brief, sample_index=0, usage_weights=weights)
        assert f"atom.a ({CUE_LABEL})" in signature_build_brief(ctx)
