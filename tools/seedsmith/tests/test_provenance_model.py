"""NS5 — the provenance `model` stamp and its closed non-id vocabulary.

`spec-model-config-resolve.md` §3.4: a stamp is either a *resolved* model id (whatever the call
actually used), or exactly `unrecorded` (a replayed answer whose model was not recorded) or `none`
(a deterministic generator made the row with no model call). Every emitter's `model` parameter is a
REQUIRED keyword — there is no built-in fallback to stamp.

    python -m pytest gk-forge/tools/seedsmith/tests/test_provenance_model.py -q
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items.affixfamgen import emit as affixfamgen_emit  # noqa: E402
from seedsmith.adapters.items.basetypegen import emit as basetypegen_emit  # noqa: E402
from seedsmith.adapters.items.basetypegen import run as basetypegen_run  # noqa: E402
from seedsmith.adapters.items.droptablegen import run as droptablegen_run  # noqa: E402
from seedsmith.adapters.items.gemgen import run as gemgen_run  # noqa: E402
from seedsmith.adapters.items.recipegen import emit as recipegen_emit  # noqa: E402
from seedsmith.adapters.items.recipegen import run as recipegen_run  # noqa: E402
from seedsmith.pipeline.provenance import (  # noqa: E402
    PROVENANCE_MODEL_SENTINELS,
    provenance_model,
)

#: Every function that stamps a provenance `model` field. A new one belongs here the moment it is
#: written — this list is the emitters' own closed set, and `model` being required is the contract.
MODEL_STAMPING_EMITTERS = (
    affixfamgen_emit.emit_document,
    basetypegen_emit.emit_document,
    basetypegen_run.write_corpus,
    droptablegen_run.write_corpus,
    gemgen_run.write_partition_file,
    recipegen_emit.emit_document,
    recipegen_run.write_corpus,
)


def test_provenance_sentinels_are_closed():
    assert PROVENANCE_MODEL_SENTINELS == ("unrecorded", "none")


@pytest.mark.parametrize("sentinel", PROVENANCE_MODEL_SENTINELS)
def test_each_sentinel_is_accepted_verbatim(sentinel):
    assert provenance_model(sentinel) == sentinel


def test_a_resolved_model_id_passes_through_unchanged():
    assert provenance_model("google/gemma-4-26b-a4b-qat") == "google/gemma-4-26b-a4b-qat"


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_a_blank_stamp_is_refused(blank):
    with pytest.raises(ValueError, match="resolved model id"):
        provenance_model(blank)


def test_a_non_string_stamp_is_refused():
    with pytest.raises(ValueError):
        provenance_model(None)  # type: ignore[arg-type]


def test_every_emitters_model_parameter_is_required():
    for emitter in MODEL_STAMPING_EMITTERS:
        parameter = inspect.signature(emitter).parameters.get("model")
        assert parameter is not None, emitter.__qualname__
        assert parameter.default is inspect.Parameter.empty, (
            f"{emitter.__qualname__}.model still has a default {parameter.default!r} — a stamp the "
            f"caller never resolved")


if __name__ == "__main__":  # pragma: no cover - dev entrypoint
    raise SystemExit(pytest.main([__file__, "-q"]))
