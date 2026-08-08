from __future__ import annotations

import numpy as np
import pytest

from backend.core.atomistic import build_atomistic_model
from backend.core.lattice import make_bundle_design
from backend.core.md_precondition import (
    WORKFLOW_FLAG_NO_CROSSOVER_EXTRABASES_ONLY,
    assert_no_crossover_extrabases,
    build_precondition_report,
    crossover_extrabase_records,
)
from backend.core.models import Crossover, Direction, HalfCrossover


def _design_with_crossover_extra_bases():
    design = make_bundle_design([(0, 0), (0, 1)], length_bp=21, plane="XY")
    xo = Crossover(
        id="xo_extra",
        half_a=HalfCrossover(
            helix_id=design.helices[0].id,
            index=6,
            strand=Direction.FORWARD,
        ),
        half_b=HalfCrossover(
            helix_id=design.helices[1].id,
            index=6,
            strand=Direction.REVERSE,
        ),
        extra_bases="TT",
    )
    return design.model_copy(update={"crossovers": [xo]})


def test_crossover_extrabase_records_empty_for_direct_crossover_design():
    design = make_bundle_design([(0, 0), (0, 1)], length_bp=21, plane="XY")
    assert crossover_extrabase_records(design) == []
    assert_no_crossover_extrabases(design)


def test_no_crossover_extrabase_guard_rejects_explicit_linkers():
    design = _design_with_crossover_extra_bases()
    records = crossover_extrabase_records(design)

    assert len(records) == 1
    assert records[0]["crossover_id"] == "xo_extra"
    assert records[0]["extra_bases"] == "TT"
    assert records[0]["extra_base_count"] == 2

    with pytest.raises(ValueError, match="no crossover extra bases only"):
        assert_no_crossover_extrabases(design)


def test_precondition_report_carries_no_extrabase_workflow_flag():
    design = make_bundle_design([(0, 0)], length_bp=12, plane="XY")
    model = build_atomistic_model(design)
    override = {
        (atom.helix_id, atom.bp_index, atom.direction): np.array(
            [atom.x, atom.y, atom.z]
        )
        for atom in model.atoms
        if atom.name == "P"
    }

    report = build_precondition_report(
        design,
        source="unit-test",
        override=override,
        model=model,
        notes="synthetic override",
    )

    assert report["schema"] == "nadoc.md_precondition_report.v1"
    assert report["workflow_flag"] == WORKFLOW_FLAG_NO_CROSSOVER_EXTRABASES_ONLY
    assert report["workflow_scope"]["requires_no_crossover_extrabases"] is True
    assert report["workflow_scope"]["crossover_extrabase_count"] == 0
    assert report["override"]["entries"] == len(override)
    assert report["atomistic_model"]["atoms"] == len(model.atoms)


def test_precondition_report_rejects_extra_base_design_by_default():
    design = _design_with_crossover_extra_bases()
    model = build_atomistic_model(design)

    with pytest.raises(ValueError, match="no crossover extra bases only"):
        build_precondition_report(
            design,
            source="unit-test",
            override={},
            model=model,
        )


def test_precondition_report_can_be_overridden_for_debugging():
    design = _design_with_crossover_extra_bases()
    model = build_atomistic_model(design)
    report = build_precondition_report(
        design,
        source="unit-test",
        override={},
        model=model,
        allow_crossover_extrabases=True,
    )

    assert report["workflow_scope"]["allow_crossover_extrabases"] is True
    assert report["workflow_scope"]["requires_no_crossover_extrabases"] is False
    assert report["workflow_scope"]["crossover_extrabase_count"] == 1
