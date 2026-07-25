"""oxDNA→NAMD seed must not collapse floppy ssDNA into coincident atoms.

Regression pin for the VoltronCore seeded-NAMD failure: the run died at NAMD
startup with ``FATAL ERROR: Bad global angle count!`` — NAMD's signature for
COINCIDENT atoms in the input coordinates (it can't distribute the bonded terms
through degenerate atoms).

Root cause: the seed backmap (``build_atomistic_model_from_cg_spline``) placed
every nucleotide by a fitted helix AXIS.  Unpaired single-stranded DNA — overhangs,
tails, unpaired scaffold loops — has no helix to fit, so a *folded* ssDNA run whose
nucleotides are 0.5–1 nm apart in the relaxed conf gets projected onto near-coincident
atoms (VoltronCore: 962 ssDNA nt → 55 coincident atom pairs → NAMD abort).

Fix: unpaired ssDNA is stamped from its oxDNA a1/a3 RIGID frame
(``oxdna_health._ssdna_frame_override``); the formed duplex stays on the axis path
(the rigid stamp collapses WC pairs, which ssDNA has none of).

Physical-layer only — the seed is a NAMD INPUT artifact, never Design topology.

The fixture folds a plain (NOT flexible-marked) ssDNA overhang into a hairpin so
two distant-index nucleotides come into spatial contact — exactly what a relaxed
floppy loop does — and asserts the axis path piles their atoms together while the
rigid-frame fix keeps them apart.  No oxDNA/NAMD binary, no GPU: fast + deterministic.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from backend.api.routes import _demo_design
from backend.core.atomistic import build_atomistic_model
from backend.core.cg_to_atomistic import (
    build_atomistic_model_from_cg_spline,
    deformed_helix_axes,
    read_configuration_full_unwrapped,
)
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Direction, Domain, Helix, Strand, StrandType, Vec3
from backend.core.oxdna_health import _ssdna_frame_override
from backend.physics.oxdna_interface import oxdna_backbone_site, write_configuration

# nm thresholds; the model is in nm.  0.03 nm = 0.3 Å = "near-coincident".
_NEAR_NM = 0.03


def _overhang_design():
    """One helix: a 12-bp duplex (bp 0-11, scaffold FWD + staple REV) plus a plain
    20-nt ssDNA overhang (bp 12-31, FORWARD, no complementary staple).  The overhang
    is UNMARKED ssDNA — not a flexible segment — so it flows through the axis path the
    fix targets, unlike marked-flexible runs (their own display override)."""
    n = 32
    helix = Helix(
        id="h0", axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=n * BDNA_RISE_PER_BP),
        phase_offset=0.0, length_bp=n, grid_pos=(0, 0),
    )
    scaffold = Strand(
        id="scaf", strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0", start_bp=0, end_bp=11, direction=Direction.FORWARD),
            Domain(helix_id="h0", start_bp=12, end_bp=31,
                   direction=Direction.FORWARD, overhang_id="oh"),
        ],
    )
    staple = Strand(
        id="stap", strand_type=StrandType.STAPLE,
        domains=[Domain(helix_id="h0", start_bp=0, end_bp=11, direction=Direction.REVERSE)],
    )
    return _demo_design().model_copy(update={
        "helices": [helix], "strands": [scaffold, staple],
        "crossovers": [], "forced_ligations": [], "cluster_transforms": [],
    })


def _unpaired_keys(full_map) -> set[tuple]:
    present = {k[:3] for k in full_map}

    def unpaired(k):
        h, bp, d = k[:3]
        return (h, bp, "REVERSE" if d == "FORWARD" else "FORWARD") not in present

    return {k[:3] for k in full_map if unpaired(k)}


def _write_folded_conf(path: Path):
    """Write a relaxed-style conf whose ssDNA overhang is hairpin-folded (distant
    indices meet in space), and return (design, unpaired-key set)."""
    design = _overhang_design()
    geometry = _geometry_for_design(design)
    # identify the unpaired overhang nucleotides from a straight write
    write_configuration(design, geometry, path, oxdna_native_seed=True)
    ss = _unpaired_keys(read_configuration_full_unwrapped(path, design))
    # fold the overhang into a hairpin in the geometry list, then rewrite the conf
    ordered_ss = sorted(k for k in ss)
    anchor = None
    m = len(ordered_ss)
    ss_index = {k: i for i, k in enumerate(ordered_ss)}
    for nuc in geometry:
        key = (nuc["helix_id"], nuc["bp_index"], nuc["direction"])
        if key not in ss_index:
            continue
        if anchor is None:
            anchor = np.asarray(nuc["backbone_position"], float)
        i = ss_index[key]
        t = i / (m - 1)
        nuc["backbone_position"] = (
            anchor + np.array([0.8 * np.sin(np.pi * t), 0.15 * i - 0.15 * (m - 1) / 2, 0.0])
        ).tolist()
    write_configuration(design, geometry, path, oxdna_native_seed=True)
    return design, ss


def _near_coincident(model, r_nm=_NEAR_NM) -> int:
    from scipy.spatial import cKDTree
    xyz = np.asarray([[a.x, a.y, a.z] for a in model.atoms])
    return len(cKDTree(xyz).query_pairs(r=r_nm, output_type="ndarray"))


def _build_no_fix(design, conf):
    """Replicate the PRE-FIX seed build (axis path, no ssDNA rigid override)."""
    full = read_configuration_full_unwrapped(conf, design)
    pos = {k: oxdna_backbone_site(r["backbone_position"], r["a1"], r["a3"])
           for k, r in full.items()}
    axis = deformed_helix_axes(design, full, sigma=2.0)
    return build_atomistic_model(design, nuc_pos_override=pos, axis_override=axis,
                                 apply_design_geometry=False)


def test_ssdna_fold_does_not_collapse_seed_atoms():
    """The production seed backmap keeps a folded ssDNA loop's atoms apart, while
    the pre-fix axis path piled them into near-coincidence (the NAMD abort)."""
    with tempfile.TemporaryDirectory() as td:
        conf = Path(td) / "folded.dat"
        design, _ = _write_folded_conf(conf)

        prod = build_atomistic_model_from_cg_spline(design, conf)   # WITH fix
        nofix = _build_no_fix(design, conf)                          # pre-fix path

        near_prod = _near_coincident(prod)
        near_nofix = _near_coincident(nofix)

    # can-go-red: without the ssDNA rigid frame the axis path collapses the folded
    # loop (measured ~115 near-coincident pairs); the fix cuts it to ~18.
    assert near_nofix > 60, f"fixture no longer reproduces the collapse (nofix={near_nofix})"
    assert near_prod < 40, f"production seed still collapses folded ssDNA (near={near_prod})"
    assert near_prod < near_nofix / 2


def test_fix_is_scoped_to_ssdna_duplex_atoms_unchanged():
    """The rigid-frame override moves ONLY unpaired ssDNA — every duplex atom is
    byte-identical between the pre-fix and fixed builds."""
    with tempfile.TemporaryDirectory() as td:
        conf = Path(td) / "folded.dat"
        design, ss = _write_folded_conf(conf)
        prod = build_atomistic_model_from_cg_spline(design, conf)
        nofix = _build_no_fix(design, conf)

    def amap(m):
        return {(a.helix_id, a.bp_index, a.direction, a.name): np.array([a.x, a.y, a.z])
                for a in m.atoms}

    a_fix, a_no = amap(prod), amap(nofix)
    common = a_fix.keys() & a_no.keys()
    dup_disp = [np.linalg.norm(a_fix[k] - a_no[k]) for k in common if k[:3] not in ss]
    ss_disp = [np.linalg.norm(a_fix[k] - a_no[k]) for k in common if k[:3] in ss]

    assert dup_disp and max(dup_disp) < 1e-6      # duplex untouched
    assert ss_disp and np.median(ss_disp) > 0.3   # ssDNA re-placed onto its rigid frame
