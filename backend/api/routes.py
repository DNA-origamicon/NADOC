"""
API layer — REST route definitions.

Phase 1 routes:
  GET  /api/health                    — liveness probe
  GET  /api/design/demo               — hardcoded seed Design (single 42 bp helix)
  GET  /api/design/demo/geometry      — NucleotidePosition array for the demo design

Geometry response fields per nucleotide:
  helix_id, bp_index, direction
  backbone_position, base_position, base_normal, axis_tangent  (all nm)
  strand_id, strand_type, is_five_prime, is_three_prime        (topology)
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.core.geometry import nucleotide_positions
from backend.core.models import (
    Design,
    DesignMetadata,
    Direction,
    Domain,
    Helix,
    LatticeType,
    Strand,
    StrandType,
    Vec3,
)

router = APIRouter()


# ── Seed design ───────────────────────────────────────────────────────────────

def _demo_design() -> Design:
    """
    Single 42 bp helix along +Z, phase_offset=0.
    Scaffold strand: FORWARD (5′ at bp 0, 3′ at bp 41).
    Staple strand:   REVERSE (5′ at bp 41, 3′ at bp 0).
    """
    from backend.core.constants import BDNA_RISE_PER_BP
    helix = Helix(
        id="demo_helix",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=42 * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=42,
    )
    scaffold = Strand(
        id="scaffold",
        domains=[Domain(helix_id="demo_helix", start_bp=0, end_bp=41, direction=Direction.FORWARD)],
        strand_type=StrandType.SCAFFOLD,
    )
    staple = Strand(
        id="staple_0",
        domains=[Domain(helix_id="demo_helix", start_bp=0, end_bp=41, direction=Direction.REVERSE)],
        strand_type=StrandType.STAPLE,
    )
    return Design(
        id="demo",
        helices=[helix],
        strands=[scaffold, staple],
        lattice_type=LatticeType.HONEYCOMB,
        metadata=DesignMetadata(name="Demo — single 42 bp helix"),
    )


def _strand_nucleotide_info(design: Design) -> dict:
    """
    Build a mapping (helix_id, bp_index, Direction) → strand metadata dict.

    For each strand, computes which nucleotides are the 5′ and 3′ endpoints
    based on domain order and direction.

    Convention: start_bp is always the 5′ end of a domain; end_bp is always
    the 3′ end.  make_bundle_design follows this convention:
      FORWARD domain: start_bp=0,   end_bp=N-1
      REVERSE domain: start_bp=N-1, end_bp=0
    """
    info: dict = {}
    for strand in design.strands:
        if not strand.domains:
            continue
        first = strand.domains[0]
        last  = strand.domains[-1]

        five_prime_key  = (first.helix_id, first.start_bp, first.direction)
        three_prime_key = (last.helix_id,  last.end_bp,   last.direction)

        for di, domain in enumerate(strand.domains):
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            for bp in range(lo, hi + 1):
                key = (domain.helix_id, bp, domain.direction)
                info[key] = {
                    "strand_id":    strand.id,
                    "strand_type":  strand.strand_type.value,
                    "is_five_prime":  key == five_prime_key,
                    "is_three_prime": key == three_prime_key,
                    "domain_index":   di,
                }
    return info


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/design/demo")
def get_demo_design() -> dict:
    """Return the demo Design as a JSON-serialisable dict."""
    return _demo_design().to_dict()


@router.get("/test/atomic_reference")
def get_atomic_reference() -> dict:
    """
    Diagnostic endpoint for atomistic calibration.

    Returns two models of a GC base pair at the world origin:
      • nadoc  — NADOC-rendered 1bp GC pair via build_atomistic_model (phase_offset=0)
      • pdb_ref — Averaged heavy atoms from inner GC pairs in 1zew.pdb, aligned by:
                   1. Helix axis → world Z  (SVD fit through inner C1' midpoints)
                   2. C1'–C1' midpoint projected to axis → z=0
                   3. Minor groove (N3-G, N2-G, O2-C centroid) rotated to match
                      NADOC's minor-groove direction at phase_offset=0, i.e., 345°
                      (≈ (0.966, −0.259) in XY).

    The two representations can be overlaid in the 3D view to diagnose frame
    errors in the atomistic template machinery.
    """
    import math as _m
    import numpy as _np
    from pathlib import Path as _Path

    from backend.core.atomistic import build_atomistic_model
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.models import DesignMetadata, LatticeType
    from backend.core.pdb_import import fit_helix_axis, group_residues, parse_pdb

    # ── Part 1: NADOC 1bp GC via build_atomistic_model (phase_offset = 0) ────────

    _helix = Helix(
        id="test_h0",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=BDNA_RISE_PER_BP),
        length_bp=1,
        bp_start=0,
        phase_offset=0.0,
    )
    _fwd = Strand(
        id="test_fwd",
        domains=[Domain(helix_id="test_h0", start_bp=0, end_bp=0,
                        direction=Direction.FORWARD)],
        sequence="G",
        strand_type=StrandType.SCAFFOLD,
    )
    _rev = Strand(
        id="test_rev",
        domains=[Domain(helix_id="test_h0", start_bp=0, end_bp=0,
                        direction=Direction.REVERSE)],
        sequence="C",
        strand_type=StrandType.STAPLE,
    )
    _design = Design(
        id="test_gc",
        helices=[_helix],
        strands=[_fwd, _rev],
        lattice_type=LatticeType.HONEYCOMB,
        metadata=DesignMetadata(name="test"),
    )
    _model = build_atomistic_model(_design)

    nadoc_atoms = [
        {"x": a.x, "y": a.y, "z": a.z,
         "element": a.element, "name": a.name,
         "residue": a.residue, "direction": a.direction,
         "strand_id": a.strand_id}
        for a in _model.atoms
    ]
    nadoc_bonds = [list(b) for b in _model.bonds]

    # ── Part 2: PDB-averaged GC pair (1zew inner residues) ───────────────────────

    pdb_path = _Path(__file__).resolve().parent.parent.parent / "Examples" / "1zew.pdb"
    _atoms = parse_pdb(str(pdb_path))
    _res   = group_residues(_atoms)

    # 1zew: chain A = CCTCTAGAGG (res 1–10), chain B (res 11–20, antiparallel complement)
    # Pairing: A:n ↔ B:(21−n)
    # Inner GC pairs (DG on A, DC on B):
    #   A:7 (DG) ↔ B:14 (DC),   A:9 (DG) ↔ B:12 (DC)
    _gc_pairs = [
        (_res[('A', 7)], _res[('B', 14)]),
        (_res[('A', 9)], _res[('B', 12)]),
    ]

    # Fit helix axis through all inner C1' midpoints (A:2–9 ↔ B:12–19)
    _mids = []
    for _aseq in range(2, 10):
        _bseq = 21 - _aseq
        _ra, _rb = _res.get(('A', _aseq)), _res.get(('B', _bseq))
        if _ra and _rb and _ra.has("C1'") and _rb.has("C1'"):
            _mids.append((_ra.pos("C1'") + _rb.pos("C1'")) / 2.0)
    _axis_cen, _axis_hat = fit_helix_axis(_np.array(_mids))

    # Build rotation R_to_z: _axis_hat → +Z
    _z = _np.array([0., 0., 1.])
    _cross = _np.cross(_axis_hat, _z)
    _s = _np.linalg.norm(_cross)
    _c = float(_np.dot(_axis_hat, _z))
    if _s < 1e-9:
        R_to_z = _np.eye(3) if _c > 0 else _np.diag([-1., 1., -1.])
    else:
        _K = _np.array([[0, -_cross[2], _cross[1]],
                        [_cross[2], 0, -_cross[0]],
                        [-_cross[1], _cross[0], 0]])
        R_to_z = _np.eye(3) + _K + _K @ _K * (1.0 - _c) / (_s * _s)

    # Accumulate atom positions for each pair, centered on axis and de-twisted.
    # Problem: A:7 and A:9 differ by ~68.6° of twist; naive averaging blurs the
    # geometry.  Fix: after axis-alignment (R_to_z), rotate each pair around Z
    # so that the G C1' atom sits at +X (angle=0), then accumulate, then rotate
    # back to the NADOC reference direction at the end.
    _gpos: dict[str, list] = {}
    _cpos: dict[str, list] = {}
    for (_rg, _rc) in _gc_pairs:
        # axis point = projection of C1'–C1' midpoint onto fitted axis
        _mid_c1 = (_rg.pos("C1'") + _rc.pos("C1'")) / 2.0
        _t = float(_np.dot(_mid_c1 - _axis_cen, _axis_hat))
        _apt = _axis_cen + _t * _axis_hat

        # Axis-align (R_to_z already rotates the helix direction to +Z)
        _g_c1_aligned = R_to_z @ (_rg.pos("C1'") - _apt)
        _theta = _m.atan2(_g_c1_aligned[1], _g_c1_aligned[0])
        _cth, _sth = _m.cos(-_theta), _m.sin(-_theta)
        _Rdetwist = _np.array([[_cth, -_sth, 0.], [_sth, _cth, 0.], [0., 0., 1.]])
        _R = _Rdetwist @ R_to_z

        for _nm, _at in _rg.atoms.items():
            _gpos.setdefault(_nm, []).append(_R @ (_at.pos - _apt))
        for _nm, _at in _rc.atoms.items():
            _cpos.setdefault(_nm, []).append(_R @ (_at.pos - _apt))

    _g_avg = {nm: _np.mean(ps, axis=0) for nm, ps in _gpos.items()}
    _c_avg = {nm: _np.mean(ps, axis=0) for nm, ps in _cpos.items()}

    # Translate z so average C1' of G and C lands at z = 0
    _z_c1 = [p[2] for p in [_g_avg.get("C1'"), _c_avg.get("C1'")] if p is not None]
    if _z_c1:
        _dz = float(_np.mean(_z_c1))
        _g_avg = {nm: p - _np.array([0., 0., _dz]) for nm, p in _g_avg.items()}
        _c_avg = {nm: p - _np.array([0., 0., _dz]) for nm, p in _c_avg.items()}

    # Rotate around Z to match NADOC's minor-groove direction at phase_offset=0.
    # NADOC _frame_from_helix_axis((0,0,1)) gives x_hat=(0,-1,0), y_hat=(1,0,0).
    # FWD backbone at angle 0°: direction = (0,-1,0).
    # Minor-groove centre at FWD+75°:
    #   cos(75°)*(0,-1,0) + sin(75°)*(1,0,0) = (sin75, -cos75, 0) ≈ (0.9659, -0.2588, 0).
    # Angle in XY = atan2(-0.2588, 0.9659) ≈ -15° = -π/12.
    _nadoc_mg_angle = _m.atan2(-0.2588, 0.9659)   # ≈ -15° (−π/12)

    # PDB minor-groove atoms for GC: N3(G), N2(G), O2(C) → centroid → angle
    _mg_pts = [_g_avg[k] for k in ("N3", "N2") if k in _g_avg]
    if "O2" in _c_avg:
        _mg_pts.append(_c_avg["O2"])

    if _mg_pts:
        _mg_cen = _np.mean(_mg_pts, axis=0)
        _mg_xy  = _mg_cen[:2]
        _mg_r   = _np.linalg.norm(_mg_xy)
        if _mg_r > 1e-9:
            _pdb_mg_angle = _m.atan2(_mg_xy[1], _mg_xy[0])
            _da = _nadoc_mg_angle - _pdb_mg_angle
            _cr, _sr = _m.cos(_da), _m.sin(_da)
            _Rz = _np.array([[_cr, -_sr, 0.], [_sr, _cr, 0.], [0., 0., 1.]])
            _g_avg = {nm: _Rz @ p for nm, p in _g_avg.items()}
            _c_avg = {nm: _Rz @ p for nm, p in _c_avg.items()}

    # Element from atom name
    _ELEM = {
        "P":"P","OP1":"O","OP2":"O","O5'":"O","C5'":"C","C4'":"C","O4'":"O",
        "C3'":"C","O3'":"O","C2'":"C","C1'":"C",
        "N9":"N","C8":"C","N7":"N","C5":"C","C4":"C","N3":"N","C2":"C",
        "N1":"N","C6":"C","N2":"N","N6":"N","N4":"N",
        "O2":"O","O4":"O","O6":"O","C7":"C",
    }

    def _fmt(avg_d: dict, resname: str) -> list[dict]:
        return [
            {"name": nm, "element": _ELEM.get(nm, "C"), "residue": resname,
             "x": float(p[0]), "y": float(p[1]), "z": float(p[2])}
            for nm, p in avg_d.items()
        ]

    _g_out = _fmt(_g_avg, "DG")
    _c_out = _fmt(_c_avg, "DC")

    # Build bond index lists from atom name pairs
    _g_idx = {a["name"]: i for i, a in enumerate(_g_out)}
    _c_idx = {a["name"]: i for i, a in enumerate(_c_out)}

    _SUGAR_BP = [
        ("P","OP1"),("P","OP2"),("P","O5'"),("O5'","C5'"),
        ("C5'","C4'"),("C4'","O4'"),("C4'","C3'"),
        ("O4'","C1'"),("C3'","O3'"),("C3'","C2'"),("C2'","C1'"),
    ]
    _DG_BP = [
        ("C1'","N9"),
        ("N9","C8"),("C8","N7"),("N7","C5"),("C5","C4"),("C4","N9"),
        ("C4","N3"),("N3","C2"),("C2","N1"),("N1","C6"),("C6","C5"),
        ("C6","O6"),("C2","N2"),
    ]
    _DC_BP = [
        ("C1'","N1"),("N1","C2"),("C2","N3"),("N3","C4"),
        ("C4","C5"),("C5","C6"),("C6","N1"),
        ("C2","O2"),("C4","N4"),
    ]

    def _bonds(pairs, idx):
        return [[idx[a], idx[b]] for a, b in pairs
                if a in idx and b in idx]

    return {
        "nadoc": {
            "atoms": nadoc_atoms,
            "bonds": nadoc_bonds,
        },
        "pdb_ref": {
            "g_atoms": _g_out,
            "g_bonds": _bonds(_SUGAR_BP + _DG_BP, _g_idx),
            "c_atoms": _c_out,
            "c_bonds": _bonds(_SUGAR_BP + _DC_BP, _c_idx),
        },
    }


@router.get("/design/demo/geometry")
def get_demo_geometry() -> list[dict]:
    """
    Return a flat array of nucleotide positions enriched with strand topology.

    backbone_position and base_position are in nanometres (world frame).
    base_normal and axis_tangent are unit vectors.

    strand_id / strand_type / is_five_prime / is_three_prime are derived from
    the Design's strand+domain structure so the frontend can draw correct
    strand direction arrows and mark 5′ end cubes without hard-coding anything.
    """
    design = _demo_design()
    nuc_info = _strand_nucleotide_info(design)
    _missing = {"strand_id": None, "strand_type": StrandType.STAPLE.value,
                "is_five_prime": False, "is_three_prime": False, "domain_index": 0}

    result: list[dict] = []
    for helix in design.helices:
        for nuc in nucleotide_positions(helix):
            key = (nuc.helix_id, nuc.bp_index, nuc.direction)
            sinfo = nuc_info.get(key, _missing)
            result.append({
                "helix_id":          nuc.helix_id,
                "bp_index":          nuc.bp_index,
                "direction":         nuc.direction.value,
                "backbone_position": nuc.position.tolist(),
                "base_position":     nuc.base_position.tolist(),
                "base_normal":       nuc.base_normal.tolist(),
                "axis_tangent":      nuc.axis_tangent.tolist(),
                **sinfo,
            })
    return result
