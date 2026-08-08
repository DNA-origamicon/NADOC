"""oxDNA→NAMD seed reconstruction must be a pure function of the oxDNA positions.

A NADOC design built from copy-pasted, rotated clusters carries `cluster_transforms`
(and possibly deformations).  `build_atomistic_model` applies those as a final pass on
straight-geometry atoms.  But a seed's CG override already supplies each nucleotide's
FINAL world position (deformed + cluster-transformed, then oxDNA-relaxed) — so
re-applying the design transforms DOUBLES them and blows the model up ~N× (the
GT_corner_v2 "explosion": 102 nm CG → 367 nm all-atom).  The fix: the seed path passes
`apply_design_geometry=False`, so the reconstruction depends only on the oxDNA frames.

These pin that a cluster ROTATION and a cluster TRANSLATION both reconstruct at ~1×
(no double transform) with Watson-Crick pairs intact, while a plain design is unchanged.
Uses the ideal oxDNA conf written headlessly — no GROMACS / oxDNA binary needed.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np

from backend.core.cg_to_atomistic import build_atomistic_model_from_cg_spline
from backend.core.design_geometry import _geometry_for_design
from backend.core.lattice import LatticeType, make_bundle_design
from backend.core.models import ClusterRigidTransform
from backend.physics.oxdna_interface import (
    oxdna_backbone_site,
    read_configuration_full,
    write_configuration,
)


def _rot_z_quat(deg: float) -> list[float]:
    r = math.radians(deg) / 2
    return [0.0, 0.0, math.sin(r), math.cos(r)]


def _reconstruct_metrics(design) -> dict:
    """Write the design's IDEAL oxDNA conf, reconstruct the seed, and return
    {ratio, atom_to_cg_p50_nm, wc_c1_p50_nm}."""
    geom = _geometry_for_design(design)
    with tempfile.TemporaryDirectory() as td:
        conf = Path(td) / "conf.dat"
        write_configuration(design, geom, conf, oxdna_native_seed=True)
        model = build_atomistic_model_from_cg_spline(design, conf)
        full = read_configuration_full(conf, design)

    cg = {
        k: oxdna_backbone_site(r["backbone_position"], r["a1"], r["a3"])
        for k, r in full.items()
    }
    atoms = np.asarray([[a.x, a.y, a.z] for a in model.atoms])
    d = np.asarray(
        [
            np.linalg.norm(
                np.array([a.x, a.y, a.z]) - cg[(a.helix_id, a.bp_index, a.direction)]
            )
            for a in model.atoms
            if (a.helix_id, a.bp_index, a.direction) in cg
        ]
    )
    cg_span = float(np.ptp(np.asarray(list(cg.values())), axis=0).max())
    at_span = float(np.ptp(atoms, axis=0).max())

    c1: dict = {}
    for a in model.atoms:
        if a.name == "C1'":
            c1[(a.helix_id, a.bp_index, a.direction)] = np.array([a.x, a.y, a.z])
    wc = [
        np.linalg.norm(p - c1[(h, bp, "REVERSE")])
        for (h, bp, dr), p in c1.items()
        if dr == "FORWARD" and (h, bp, "REVERSE") in c1
    ]
    return {
        "ratio": at_span / max(cg_span, 1e-9),
        "atom_to_cg_p50_nm": float(np.percentile(d, 50)),
        "wc_c1_p50_nm": float(np.median(wc)) if wc else float("nan"),
    }


def _flat_bundle():
    return make_bundle_design(
        [(0, c) for c in range(8)], 64, name="flat8", lattice_type=LatticeType.SQUARE
    )


def _with_cluster(**ct_kwargs):
    base = _flat_bundle()
    hids = [h.id for h in base.helices]
    pivot = np.mean(
        [g["backbone_position"] for g in _geometry_for_design(base)], axis=0
    ).tolist()
    return base.copy_with(
        cluster_transforms=[
            ClusterRigidTransform(name="C", helix_ids=hids, pivot=pivot, **ct_kwargs)
        ]
    )


def test_plain_design_reconstructs_at_unity():
    m = _reconstruct_metrics(_flat_bundle())
    assert m["ratio"] < 1.3, m
    assert m["atom_to_cg_p50_nm"] < 2.0, m
    assert 0.7 < m["wc_c1_p50_nm"] < 1.3, m


def test_cluster_translation_no_double_transform():
    # Before the fix this reconstructed ~50 nm off (the translation applied twice).
    m = _reconstruct_metrics(_with_cluster(translation=[50.0, 0.0, 0.0]))
    assert m["atom_to_cg_p50_nm"] < 2.0, f"translated cluster double-applied: {m}"
    assert m["ratio"] < 1.3, m
    assert 0.7 < m["wc_c1_p50_nm"] < 1.3, m


def test_cluster_rotation_no_double_transform():
    m = _reconstruct_metrics(_with_cluster(rotation=_rot_z_quat(90.0)))
    assert m["atom_to_cg_p50_nm"] < 2.0, f"rotated cluster double-applied: {m}"
    assert m["ratio"] < 1.3, m
    assert 0.7 < m["wc_c1_p50_nm"] < 1.3, m


def test_two_clusters_rot_plus_trans():
    base = _flat_bundle()
    hids = [h.id for h in base.helices]
    pivot = np.mean(
        [g["backbone_position"] for g in _geometry_for_design(base)], axis=0
    ).tolist()
    design = base.copy_with(
        cluster_transforms=[
            ClusterRigidTransform(
                name="A", helix_ids=hids[:4], rotation=_rot_z_quat(90.0), pivot=pivot
            ),
            ClusterRigidTransform(
                name="B",
                helix_ids=hids[4:],
                rotation=_rot_z_quat(-90.0),
                translation=[80.0, 0.0, 0.0],
                pivot=pivot,
            ),
        ]
    )
    m = _reconstruct_metrics(design)
    assert m["atom_to_cg_p50_nm"] < 2.0, f"multi-cluster double-applied: {m}"
    assert m["ratio"] < 1.3, m
