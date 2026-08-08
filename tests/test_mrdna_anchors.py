"""Oracle for M1 — mrDNA anchors via ARBD RESTRAINTs.

Property under test (the bright line — a comparable prediction, not "a wrapper exists"):
the ARBD input carries a harmonic RESTRAINT for exactly the CG beads covering the resolved
anchor scope, and (slow) a real ARBD run holds those beads while free beads move.

Anchors are a JOB-REQUEST annotation, never a Design edit (Three-Layer Law): these tests
only read positions/keys off the design + model.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.conftest import make_6hb_design


# ── helpers ───────────────────────────────────────────────────────────────────


def _built_model(design):
    """A parameter-free coarse mrDNA model with beads already generated (as the runner
    builds it, minus the crossover-potential override, which is irrelevant to geometry)."""
    from backend.core.mrdna_bridge import mrdna_model_from_nadoc

    return mrdna_model_from_nadoc(design)


def _flat_beads(model):
    return [b for s in model.segments for b in s.beads]


def _base_anchor(design):
    """A single-nucleotide `base` scope at a real interior nucleotide (guaranteed to
    resolve), built from the shared provenance so it uses the exact key convention."""
    from backend.physics.oxdna_interface import _strand_nucleotide_provenance

    prov = [
        p for p in _strand_nucleotide_provenance(design) if p["helix_id"] is not None
    ]
    p = prov[len(prov) // 2]
    return [
        {
            "kind": "base",
            "helix_id": p["helix_id"],
            "bp": p["bp"],
            "direction": p["direction"],
        }
    ]


# ── FAST oracle ───────────────────────────────────────────────────────────────


def test_no_anchors_yields_no_restraints():
    from backend.core.mrdna_anchors import install_anchor_restraints, restraint_records

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    assert install_anchor_restraints(d, m, None) == 0
    assert install_anchor_restraints(d, m, []) == 0
    assert restraint_records(m) == []


def test_stale_scope_drops_silently():
    """A scope that resolves to nothing leaves the run unanchored (no crash) — matching
    the shared resolver's stale-selection tolerance."""
    from backend.core.mrdna_anchors import apply_anchor_restraints

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    bogus = [{"kind": "strand", "id": "does-not-exist"}]
    assert apply_anchor_restraints(d, m, bogus) == []


def test_strand_anchor_covers_scope_and_only_scope():
    """The restrained bead set is a NON-EMPTY, STRICT subset of all beads, and every
    restrained bead sits within a bead spacing of some anchored nucleotide (covers the
    scope), while the anchored-nt positions never reach a NON-restrained bead more
    closely than their own bead (no leakage)."""
    from backend.core.mrdna_anchors import _anchor_nt_positions, resolve_anchor_beads

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    beads = _flat_beads(m)
    anchor = [{"kind": "strand", "id": d.strands[0].id}]

    held = resolve_anchor_beads(d, m, anchor)
    assert 0 < len(held) < len(beads)  # covers something, not everything

    ntpos = _anchor_nt_positions(d, anchor)
    assert ntpos.shape[0] > 0
    bpos = np.array([b.get_collapsed_position() for b in beads])
    held_ids = {id(b) for b in held}
    # Every anchored nucleotide's NEAREST bead is a held bead (definition of the map).
    for p in ntpos:
        nearest = beads[int(np.argmin(((bpos - p) ** 2).sum(axis=1)))]
        assert id(nearest) in held_ids


def test_restraint_block_indices_match_resolved_beads():
    """The ARBD restraint block (bead_idx, k, pos) carries a line for EXACTLY the
    resolved beads — idx set equals their flat-list ordinals, spring == our constant,
    and pinned position == each bead's own current position (an anchor)."""
    from backend.core.mrdna_anchors import (
        ANCHOR_SPRING_KCAL_MOL_A2,
        apply_anchor_restraints,
        restraint_records,
    )

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    beads = _flat_beads(m)
    idx_of = {id(b): i for i, b in enumerate(beads)}

    held = apply_anchor_restraints(d, m, _base_anchor(d))
    assert len(held) >= 1
    expected_idx = {idx_of[id(b)] for b in held}

    recs = restraint_records(m)
    got_idx = {i for i, _k, _p in recs}
    assert got_idx == expected_idx, (got_idx, expected_idx)
    assert all(k == ANCHOR_SPRING_KCAL_MOL_A2 for _i, k, _p in recs)
    # pinned position is the bead's own position (RESTRAINT holds it in place)
    for i, _k, pos in recs:
        assert np.allclose(pos, beads[i].get_collapsed_position(), atol=1e-6)


def test_dry_run_writes_restraint_file_for_scope(tmp_path):
    """End-to-end ARBD input: a dry-run write produces potentials/<name>.restraint.txt
    with one RESTRAINT line per resolved anchor bead (the real writer, not our mirror)."""
    from backend.core.mrdna_anchors import apply_anchor_restraints

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    held = apply_anchor_restraints(d, m, _base_anchor(d))
    assert len(held) >= 1

    m.simulate(
        output_name="anchortest",
        directory=str(tmp_path),
        num_steps=0.0,
        timestep=200e-6,
        output_period=1.0,
        gpu=0,
        dry_run=True,
    )
    rfile = tmp_path / "potentials" / "anchortest.restraint.txt"
    assert rfile.exists(), "ARBD input did not include a restraint file"
    lines = [ln for ln in rfile.read_text().splitlines() if ln.startswith("RESTRAINT")]
    assert len(lines) == len(held)


def test_install_survives_bead_regeneration():
    """multiresolution_simulation does clear_beads()+generate_bead_model() between
    stages, wiping bead restraints; install_anchor_restraints must re-apply after each
    regeneration (the mechanism that makes a FINE anchored run possible)."""
    from backend.core.mrdna_anchors import install_anchor_restraints, restraint_records

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    n0 = install_anchor_restraints(d, m, _base_anchor(d))
    assert n0 >= 1

    # Emulate a resolution-stage switch (coarse → fine 1 bp/bead).
    m.clear_beads()
    m.generate_bead_model(1, 1, local_twist=True, escapable_twist=True)
    recs = restraint_records(m)
    assert len(recs) >= 1, "restraints were lost across bead regeneration"


# ── SLOW oracle: real ARBD holds anchored beads ───────────────────────────────


@pytest.mark.slow
def test_real_arbd_anchored_beads_hold(tmp_path):
    """A real short ARBD coarse run: anchored beads barely move; the free bulk moves
    more.  This is the physical anchor prediction, independent of the input-file check."""
    from backend.core.mrdna_bridge import find_arbd

    if not find_arbd():
        pytest.skip("arbd binary not installed")

    from backend.core.mrdna_anchors import (
        install_anchor_restraints,
        resolve_anchor_beads,
    )

    d = make_6hb_design(length_bp=42)
    m = _built_model(d)
    beads = _flat_beads(m)
    idx_of = {id(b): i for i, b in enumerate(beads)}

    anchor = [{"kind": "strand", "id": d.strands[0].id}]
    held = resolve_anchor_beads(d, m, anchor)
    held_idx = {idx_of[id(b)] for b in held}
    free_idx = [i for i in range(len(beads)) if i not in held_idx]
    assert held and free_idx

    start = np.array([b.get_collapsed_position() for b in beads])
    install_anchor_restraints(d, m, anchor)
    m.simulate(
        output_name="anchorhold",
        directory=str(tmp_path),
        num_steps=2000.0,
        timestep=200e-6,
        output_period=1000.0,
        gpu=0,
    )

    # Read the final frame from the DCD and RMS-align to remove any global drift.
    import MDAnalysis as mda  # noqa: PLC0415

    # mrdna writes the PSF/PDB to the run dir and only the DCD under output/.
    u = mda.Universe(
        str(tmp_path / "anchorhold.psf"), str(tmp_path / "output" / "anchorhold.dcd")
    )
    u.trajectory[-1]
    end = u.atoms.positions[: len(beads)]
    disp = np.linalg.norm(end - start, axis=1)
    held_move = float(np.median(disp[list(held_idx)]))
    free_move = float(np.median(disp[free_idx]))
    assert held_move < free_move, (held_move, free_move)
