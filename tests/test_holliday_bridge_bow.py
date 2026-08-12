"""Regression coverage for the authorized scaffold Holliday-junction bow."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.core import atomistic
from backend.core.atomistic_validation import (
    BACKBONE_STRETCH_NM,
    CLASH_NM,
    COVALENT_MAX_NM,
    _bond_class,
    _find_clashes,
)
from backend.core.models import Design, StrandType


_FIXTURE = Path("workspace/24hb_1xT.nadoc")


def _positions(model) -> np.ndarray:
    return np.asarray([[atom.x, atom.y, atom.z] for atom in model.atoms])


def _clashes(model) -> list[dict]:
    positions = _positions(model)
    return _find_clashes(
        positions,
        np.isfinite(positions).all(axis=1),
        model.bonds,
        CLASH_NM,
        200,
    )


def _bond_summary(model) -> tuple[float, int]:
    positions = _positions(model)
    maximum = 0.0
    overstretched = 0
    for row_a, row_b in model.bonds:
        length = float(np.linalg.norm(positions[row_a] - positions[row_b]))
        maximum = max(maximum, length)
        bond_class = _bond_class(model.atoms[row_a], model.atoms[row_b])
        limit = (
            BACKBONE_STRETCH_NM
            if bond_class in {"backbone", "bridge"}
            else COVALENT_MAX_NM
        )
        overstretched += length > limit
    return maximum, overstretched


def test_exact_seed_bridge_path_does_not_consult_display_bow(monkeypatch):
    from tests.reciprocal_design import reciprocal_design

    def forbidden(*_args):
        raise AssertionError("display-only Holliday bow reached the exact seed path")

    monkeypatch.setattr(atomistic, "_scaffold_holliday_bridge_bows", forbidden)
    atomistic.build_atomistic_model(reciprocal_design(None), fast_bridges=False)


@pytest.mark.slow
def test_scaffold_holliday_bow_clears_24hb_contacts_and_moves_only_linkers(
    monkeypatch,
):
    design = Design.model_validate_json(_FIXTURE.read_text())
    bow_solver = atomistic._scaffold_holliday_bridge_bows

    monkeypatch.setattr(atomistic, "_scaffold_holliday_bridge_bows", lambda *_: {})
    straight = atomistic.build_atomistic_model(design, fast_bridges=True)
    monkeypatch.setattr(atomistic, "_scaffold_holliday_bridge_bows", bow_solver)
    bowed = atomistic.build_atomistic_model(design, fast_bridges=True)

    # This is the exact failure observed in the audit: eleven reciprocal scaffold
    # OP1 pairs collide when both bridges use their straight bead-to-bead chords.
    assert len(_clashes(straight)) == 11
    assert _clashes(bowed) == []
    straight_max_bond, straight_overstretched = _bond_summary(straight)
    bowed_max_bond, bowed_overstretched = _bond_summary(bowed)
    assert bowed_max_bond < straight_max_bond + 0.02
    assert bowed_overstretched <= straight_overstretched

    displacement = np.linalg.norm(_positions(bowed) - _positions(straight), axis=1)
    moved = np.where(displacement > 1e-10)[0]
    assert moved.size == 110  # 11 reciprocal pairs × 2 paths × 5 linker atoms
    assert float(displacement[moved].max()) < 0.061  # < 0.61 Å

    scaffold_ids = {
        strand.id
        for strand in design.strands
        if strand.strand_type == StrandType.SCAFFOLD
    }
    assert {bowed.atoms[row].name for row in moved} <= {
        "O3'",
        "P",
        "OP1",
        "OP2",
        "O5'",
    }
    assert all(bowed.atoms[row].strand_id in scaffold_ids for row in moved)

    # Every ring/base/anchor coordinate is byte-identical; only the five flexible
    # linker atoms named above receive the sub-angstrom bow.
    stationary = np.where(displacement <= 1e-10)[0]
    assert np.array_equal(
        _positions(bowed)[stationary], _positions(straight)[stationary]
    )
