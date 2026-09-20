"""
Round-trip test: NADOC design → GROMACS PDB → NADOC bead positions.

Three comparisons:
  1. PDB round-trip  — input_nadoc.pdb P atoms vs AtomisticModel (expect ~0 Å)
  2. EM frame 0      — em.gro P atoms vs AtomisticModel (expect small RMSD from EM)
  3. Geometry offset — input_nadoc.pdb P atoms vs geometry-layer backbone
                       (expect ~1.1 Å systematic radial offset; P at 0.886 nm, backbone at 1.0 nm)

Run:
    pytest tests/test_atomistic_round_trip.py -v
  or:
    python tests/test_atomistic_round_trip.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from backend.core.models import Design
from backend.core.atomistic import build_atomistic_model
from backend.core.atomistic_to_nadoc import (
    build_chain_map,
    build_p_gro_order,
    compare_to_design,
    extract_from_gro,
    extract_from_pdb,
)

pytest_plugins = ["tests.md_trajectory_fixture"]


@pytest.fixture(scope="module")
def design(generated_gromacs) -> Design:
    return generated_gromacs.design


@pytest.fixture(scope="module")
def chain_map(design):
    model = build_atomistic_model(design)
    return build_chain_map(model)


@pytest.fixture(scope="module")
def p_order(chain_map, generated_gromacs):
    pdb_text = generated_gromacs.pdb.read_text()
    return build_p_gro_order(pdb_text, chain_map)


# ── Test 1: chain map completeness ───────────────────────────────────────────


def test_chain_map_size(chain_map, design, generated_gromacs):
    """Chain map should have one entry per nucleotide (all strands have P atoms)."""
    total_nt = sum(
        abs(d.end_bp - d.start_bp) + 1 for s in design.strands for d in s.domains
    )
    assert len(chain_map) == total_nt, (
        f"Expected {total_nt} P atoms in chain_map, got {len(chain_map)}"
    )


# ── Test 2: PDB round-trip (near-exact match) ─────────────────────────────────


def test_pdb_roundtrip_count(chain_map, generated_gromacs):
    """extract_from_pdb should recover all P atoms in the input PDB."""
    pdb_text = generated_gromacs.pdb.read_text()
    beads = extract_from_pdb(pdb_text, chain_map)
    assert len(beads) == len(chain_map), (
        f"PDB extraction: {len(beads)} beads, expected {len(chain_map)}"
    )


def test_pdb_roundtrip_rmsd(chain_map, design, generated_gromacs):
    """
    P atoms from input_nadoc.pdb should match AtomisticModel P positions
    to within PDB coordinate precision (0.001 Å = 0.0001 nm, stored as %8.3f).
    """
    pdb_text = generated_gromacs.pdb.read_text()
    beads = extract_from_pdb(pdb_text, chain_map)
    result = compare_to_design(beads, design, use_geometry_layer=False)

    assert result.n_missing == 0, f"{result.n_missing} P atoms not in reference"
    assert result.global_rmsd_nm < 5e-4, (
        f"PDB round-trip RMSD {result.global_rmsd_nm * 10:.4f} Å > 0.005 Å "
        "(PDB stores 3 decimal places in Å → 0.001 Å precision)"
    )
    assert result.max_deviation_nm < 1e-3, (
        f"PDB round-trip max deviation {result.max_deviation_nm * 10:.4f} Å > 0.01 Å"
    )


# ── Test 3: GRO p_order matches PDB count minus stripped 5'-terminals ─────────


def test_p_gro_order_count(p_order, design, generated_gromacs):
    """
    GRO P-atom order should have (total_nt - n_strands) entries:
    pdb2gmx strips the 5'-terminal P from each chain.
    """
    total_nt = sum(
        abs(d.end_bp - d.start_bp) + 1 for s in design.strands for d in s.domains
    )
    n_strands = len(design.strands)
    expected = total_nt - n_strands
    assert len(p_order) == expected, (
        f"p_gro_order: {len(p_order)} entries, expected {expected} "
        f"({total_nt} nt − {n_strands} stripped)"
    )


def test_p_gro_order_matches_gro(p_order, generated_gromacs):
    """p_order length must match actual DNA P atom count in em.gro."""
    import MDAnalysis as mda

    u = mda.Universe(str(generated_gromacs.gro))
    dna_p = u.select_atoms(
        "name P and resname DA DT DC DG DA3 DA5 DT3 DT5 DC3 DC5 DG3 DG5"
    )
    assert len(dna_p) == len(p_order), (
        f"em.gro has {len(dna_p)} DNA P atoms but p_order has {len(p_order)} entries"
    )


# ── Test 4: EM frame 0 extraction ────────────────────────────────────────────


def test_em_extraction_count(p_order, generated_gromacs):
    """extract_from_gro should return one BeadPosition per p_order entry."""
    beads = extract_from_gro(generated_gromacs.gro, p_order, frame=0)
    assert len(beads) == len(p_order)


def test_em_bead_positions_finite(p_order, generated_gromacs):
    """All extracted positions should be finite (no NaN/Inf)."""
    beads = extract_from_gro(generated_gromacs.gro, p_order, frame=0)
    for b in beads:
        assert np.all(np.isfinite(b.pos)), (
            f"Non-finite position for {b.helix_id} bp{b.bp_index}"
        )


def test_em_rmsd_vs_ideal(p_order, design, generated_gromacs):
    """
    EM should keep P atoms close to ideal B-DNA.  After centroid alignment
    (GROMACS translates the structure into the periodic box — ~6 nm offset),
    RMSD vs AtomisticModel should be < 3 Å.  Larger values indicate crossover
    geometry relief, which is the expected first-frame deformation.
    """
    beads = extract_from_gro(generated_gromacs.gro, p_order, frame=0)
    result = compare_to_design(
        beads, design, use_geometry_layer=False, align_translation=True
    )

    assert result.n_missing == 0
    assert result.global_rmsd_nm < 0.3, (
        f"EM aligned RMSD {result.global_rmsd_nm * 10:.2f} Å vs ideal; expected < 3 Å"
    )


# ── Test 5: geometry-layer offset is consistent ───────────────────────────────


def test_geometry_layer_radial_offset(chain_map, design, generated_gromacs):
    """
    Quantify the P-atom vs geometry-layer backbone offset.

    The geometry-layer bead sits at HELIX_RADIUS = 1.0 nm from the helix axis.
    The actual P atom sits at _ATOMISTIC_P_RADIUS ≈ 0.886 nm AND is rotated ~37°
    around the axis (the atomistic template bakes in a phase correction).  The
    combined chord distance is ~5–8 Å depending on direction (FORWARD vs REVERSE
    sit on opposite sides of the minor groove).

    This test documents the constant offset — it is NOT a mapping error.
    Use the AtomisticModel (use_geometry_layer=False) for accurate round-trip
    comparisons; the geometry layer is the abstract CG bead, not the P atom.
    """
    pdb_text = generated_gromacs.pdb.read_text()
    beads = extract_from_pdb(pdb_text, chain_map)
    result = compare_to_design(beads, design, use_geometry_layer=True)

    # ~5 Å radial+azimuthal offset; two values per helix (FWD/REV sit differently)
    assert 0.30 < result.global_rmsd_nm < 0.70, (
        f"Geometry-layer RMSD {result.global_rmsd_nm * 10:.2f} Å outside expected 3–7 Å range"
    )
    # Skip sites produce n_missing > 0; just verify it's not catastrophic (< 20%)
    total = result.n_matched + result.n_missing
    assert result.n_missing / total < 0.20, (
        f"Too many missing keys: {result.n_missing}/{total}"
    )


def test_binary_xtc_roundtrip(p_order, generated_gromacs):
    from backend.core.atomistic_to_nadoc import extract_from_xtc
    beads = extract_from_xtc(generated_gromacs.gro,
                             generated_gromacs.folder / "view_whole.xtc", p_order, frame=100)
    initial = extract_from_gro(generated_gromacs.gro, p_order, frame=0)
    assert len(beads) == len(initial) == len(p_order)
    # Writer adds 1 Å uniformly by frame 100; XTC precision is 0.001 nm.
    np.testing.assert_allclose(np.array([b.pos for b in beads]) -
                               np.array([b.pos for b in initial]), .1, atol=.0011)
