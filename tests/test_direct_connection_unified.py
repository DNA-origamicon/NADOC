"""Unified direct overhang connection (root-to-root + end-to-root, 2026-06-30).

Both direct types now materialize as ONE non-consuming OverhangBinding, relocated
on apply (duplex forms; driven tip↔root bond left stretched). Relax closes that
bond to ~0.67 nm. See backend/core/direct_relax.py + crud._cv_create_bound_binding.
"""
from __future__ import annotations

import numpy as np

from backend.api.crud import _cv_create_bound_binding, _geometry_for_design
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.direct_relax import (
    _bead_pos, _find_driven_tip_and_root, relax_direct_binding,
)
from backend.core.models import (
    ClusterJoint, ClusterRigidTransform, Crossover, Direction, Domain, HalfCrossover,
    Helix, OverhangSpec, Strand, StrandType, Vec3,
)
from backend.core.validator import validate_design

_IDENTITY = [0.0, 0.0, 0.0, 1.0]
_TARGET = 0.67


def _seed(*, same_body=False, cluster_b_translation=(5.0, 2.0, 1.0), joint=None):
    """Two extruded-style overhangs, each a [root → overhang-tip] staple."""
    base = _demo_design()
    L = 16
    ha = Helix(id="d_ha", axis_start=Vec3(x=0.0, y=0.0, z=0.0),
               axis_end=Vec3(x=0.0, y=0.0, z=L * BDNA_RISE_PER_BP),
               phase_offset=0.0, length_bp=L, grid_pos=(0, 0))
    hb = Helix(id="d_hb", axis_start=Vec3(x=0.0, y=0.0, z=0.0),
               axis_end=Vec3(x=0.0, y=0.0, z=L * BDNA_RISE_PER_BP),
               phase_offset=0.0, length_bp=L, grid_pos=(0, 4))
    sa = Strand(id="d_sa", strand_type=StrandType.STAPLE, domains=[
        Domain(helix_id="d_ha", start_bp=0, end_bp=3, direction=Direction.FORWARD),
        Domain(helix_id="d_ha", start_bp=4, end_bp=11, direction=Direction.FORWARD,
               overhang_id="oh_a")])
    sb = Strand(id="d_sb", strand_type=StrandType.STAPLE, domains=[
        Domain(helix_id="d_hb", start_bp=0, end_bp=3, direction=Direction.FORWARD),
        Domain(helix_id="d_hb", start_bp=4, end_bp=11, direction=Direction.FORWARD,
               overhang_id="oh_b")])
    overhangs = [
        OverhangSpec(id="oh_a", helix_id="d_ha", strand_id="d_sa", label="OHA",
                     sequence="ACGTACGT"),
        OverhangSpec(id="oh_b", helix_id="d_hb", strand_id="d_sb", label="OHB",
                     sequence="ACGTACGT"),
    ]
    if same_body:
        clusters = [ClusterRigidTransform(
            id="cAB", name="AB", helix_ids=["d_ha", "d_hb"],
            translation=[0, 0, 0], rotation=_IDENTITY, pivot=[0, 0, 0])]
    else:
        clusters = [
            ClusterRigidTransform(id="cA", name="A", helix_ids=["d_ha"],
                                  translation=[0, 0, 0], rotation=_IDENTITY, pivot=[0, 0, 0]),
            ClusterRigidTransform(id="cB", name="B", helix_ids=["d_hb"],
                                  translation=list(cluster_b_translation),
                                  rotation=_IDENTITY, pivot=[0, 0, 0])]
    return base.model_copy(update={
        "helices": [*base.helices, ha, hb],
        "strands": [*base.strands, sa, sb],
        "overhangs": overhangs,
        "cluster_transforms": clusters,
        "cluster_joints": [joint] if joint else [],
    })


def _tip_root_chord(design) -> float:
    strand, _i, _td, _rd, cb_bp, cr_bp = _find_driven_tip_and_root(design, "oh_b")
    tip_dom = strand.domains[_i]
    root_dom = strand.domains[_i - 1 if _i == len(strand.domains) - 1 else _i + 1]
    nucs = _geometry_for_design(design)
    pb = _bead_pos(nucs, strand_id=strand.id, helix_id=tip_dom.helix_id, bp=cb_bp)
    pr = _bead_pos(nucs, strand_id=strand.id, helix_id=root_dom.helix_id, bp=cr_bp)
    return float(np.linalg.norm(pb - pr))


def test_apply_direct_does_not_consume_and_relocates_root_to_root():
    d = _seed()
    d = _cv_create_bound_binding(d, "oh_a", "oh_b", "root", "root", "root-to-root")
    # Neither overhang consumed.
    assert {o.id for o in d.overhangs} == {"oh_a", "oh_b"}
    # One bound binding with the driver/driven recorded.
    assert len(d.overhang_bindings) == 1
    bnd = d.overhang_bindings[0]
    assert bnd.bound and bnd.driver_oh_id == "oh_a" and bnd.driven_oh_id == "oh_b"
    assert bnd.connection_type == "root-to-root"
    assert bnd.prior_driven_topology is not None
    # B's tip domain relocated onto A's helix (the duplex).
    sb = next(s for s in d.strands if s.id == "d_sb")
    tip = next(dm for dm in sb.domains if dm.overhang_id == "oh_b")
    assert tip.helix_id == "d_ha"
    # B's OverhangSpec.helix_id moved too.
    assert next(o for o in d.overhangs if o.id == "oh_b").helix_id == "d_ha"


def test_apply_direct_end_to_root_also_relocates_not_consumes():
    d = _seed()
    d = _cv_create_bound_binding(d, "oh_a", "oh_b", "free_end", "root", "end-to-root")
    assert {o.id for o in d.overhangs} == {"oh_a", "oh_b"}          # B not consumed
    assert d.overhang_bindings[0].connection_type == "end-to-root"
    # No ForcedLigation created (splice path is gone).
    assert d.forced_ligations == []


def test_relax_direct_closes_tip_root_chord_with_joint():
    joint = ClusterJoint(id="jB", cluster_id="cB", name="Hinge",
                         local_axis_origin=[0.0, 0.0, 6 * BDNA_RISE_PER_BP],
                         local_axis_direction=[0.0, 1.0, 0.0],
                         min_angle_deg=-180.0, max_angle_deg=180.0)
    d = _seed(cluster_b_translation=(4.0, 0.0, 0.0), joint=joint)
    d = _cv_create_bound_binding(d, "oh_a", "oh_b", "root", "root", "root-to-root")
    before = _tip_root_chord(d)
    assert before > 2.0                                            # genuinely stretched
    updated, info = relax_direct_binding(d, "oh_a", "oh_b")
    assert info["mode"] == "swing+joints"
    after = _tip_root_chord(updated)
    assert after < before and after < 0.8, (before, after)
    # swing persisted on the DRIVER's rotation; driven stays identity.
    assert next(o for o in updated.overhangs if o.id == "oh_a").rotation != _IDENTITY
    assert next(o for o in updated.overhangs if o.id == "oh_b").rotation == _IDENTITY


def _improper_msgs(design):
    return [r.message for r in validate_design(design).results
            if not r.ok and "Improper crossover" in r.message]


def test_validator_flags_improper_crossover():
    """validate_design flags a crossover whose halves sit at MISMATCHED bp (an
    invalid lattice crossover — must be a forced ligation), and passes a valid one.
    This is the guard against the relocation drawing a line to the wrong overhang end."""
    d = _seed()
    good = Crossover(
        half_a=HalfCrossover(helix_id="d_ha", index=5, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id="d_hb", index=5, strand=Direction.REVERSE))
    assert not _improper_msgs(d.model_copy(update={"crossovers": [good]}))
    bad = Crossover(
        half_a=HalfCrossover(helix_id="d_ha", index=5, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id="d_hb", index=9, strand=Direction.REVERSE))
    assert _improper_msgs(d.model_copy(update={"crossovers": [bad]}))


def test_relax_direct_no_joint_translates_to_target():
    d = _seed(cluster_b_translation=(6.0, 3.0, 2.0))
    d = _cv_create_bound_binding(d, "oh_a", "oh_b", "root", "root", "root-to-root")
    before = _tip_root_chord(d)
    updated, info = relax_direct_binding(d, "oh_a", "oh_b")
    assert info["mode"] == "swing+translate"
    after = _tip_root_chord(updated)
    assert before > 2.0 and abs(after - _TARGET) < 0.05, (before, after)
