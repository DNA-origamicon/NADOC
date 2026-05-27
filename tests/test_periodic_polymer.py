"""
Tests for periodic polymerization — growing a chain from a SINGLE periodic part
with no hand-defined mate.

Covers:
  - pure-math ``backend.core.periodic_polymer.derive_periodic_delta``: the repeat
    transform of a straight bundle is a clean screw (|t| = L·rise, det(R)=+1), a
    single seam matches the two-seam fit, and the per-seam registration invariant
    holds; non-periodic designs raise PeriodicSeamError.
  - POST /assembly/polymerize-periodic: forward/backward/both, 422 on
    non-periodic, 400 on count<2, rigid joints with a replicated
    mate_relative_transform, connector coincidence across junctions, feature-log
    entry, and undo removing the whole chain.
"""

from __future__ import annotations
from tests._assembly_compat import v1_instances

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import assembly_state
from backend.api.main import app
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.lattice import make_bundle_design
from backend.core.models import (
    Assembly,
    Direction,
    ForcedLigation,
    LatticeType,
    Mat4x4,
    PartInstance,
    PartSourceInline,
)
from backend.core.periodic_polymer import (
    PeriodicSeamError,
    derive_periodic_delta,
    _iter_seam_frames,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    assembly_state.close_session()
    yield
    assembly_state.close_session()


# ── Fixtures ────────────────────────────────────────────────────────────────


def _seam_for(h, L: int) -> ForcedLigation:
    """A periodic seam wrapping helix *h*'s far end onto its near end.

    A forward strand presents its 3' at high bp and 5' at low bp; a reverse
    strand is antiparallel (3' at low bp, 5' at high bp).
    """
    if h.direction == Direction.FORWARD:
        return ForcedLigation(
            three_prime_helix_id=h.id, three_prime_bp=L - 1, three_prime_direction=Direction.FORWARD,
            five_prime_helix_id=h.id, five_prime_bp=0, five_prime_direction=Direction.FORWARD,
            is_periodic_seam=True,
        )
    return ForcedLigation(
        three_prime_helix_id=h.id, three_prime_bp=0, three_prime_direction=Direction.REVERSE,
        five_prime_helix_id=h.id, five_prime_bp=L - 1, five_prime_direction=Direction.REVERSE,
        is_periodic_seam=True,
    )


def _periodic_bundle_design(L: int = 42, *, periodic: bool = True):
    d = make_bundle_design([(0, 0), (0, 1)], L,
                           lattice_type=LatticeType.HONEYCOMB, strand_filter="both")
    if periodic:
        d.forced_ligations = [_seam_for(d.helices[0], L), _seam_for(d.helices[1], L)]
    return d


def _seed_periodic_assembly(L: int = 42, *, periodic: bool = True) -> Assembly:
    d = _periodic_bundle_design(L, periodic=periodic)
    inst = PartInstance(id="seed", name="Ring",
                        source=PartSourceInline(design=d), transform=Mat4x4())
    asm = Assembly(instances=[inst], joints=[])
    assembly_state.set_assembly(asm)
    return asm


# ── Pure-math: repeat transform ───────────────────────────────────────────────


# Lengths span both near-commensurate (21/42/84 ≈ whole turns) AND incommensurate
# (30/55: per-period twist ~51°/~28° from a whole turn) cases. The incommensurate
# ones are the spiral-bug regression guard: a straight bundle must yield a PURE
# axial translation regardless of where the helical twist lands — the radial
# (twist) phase must never leak into a perpendicular bend. (The original tests
# only used commensurate lengths, which masked the bug.)
@pytest.mark.parametrize("L", [21, 30, 42, 55, 84])
def test_delta_is_pure_axial_translation_no_bend(L):
    """Straight bundle → |t| ≈ L·rise along +Z and ~zero rotation (no spiral)."""
    d = _periodic_bundle_design(L)
    delta = derive_periodic_delta(d)
    R, t = delta[:3, :3], delta[:3, 3]
    assert np.isclose(np.linalg.norm(t), L * BDNA_RISE_PER_BP, atol=1e-2)
    assert np.isclose(t[2], L * BDNA_RISE_PER_BP, atol=1e-2)   # bundle axis = +Z (XY plane)
    assert np.isclose(np.linalg.det(R), 1.0, atol=1e-6)
    # A straight part must NOT bend, even at incommensurate periods.
    ang = np.degrees(np.arccos(np.clip((np.trace(R) - 1) / 2, -1.0, 1.0)))
    assert ang < 0.5, f"straight bundle L={L} bent by {ang:.2f}° (spiral bug)"


def test_single_seam_matches_two_seam_fit():
    """A 1-seam fallback recovers the same delta as the full 2-seam fit."""
    L = 42
    d_two = _periodic_bundle_design(L)
    d_one = d_two.model_copy(deep=True)
    d_one.forced_ligations = [d_two.forced_ligations[0]]
    np.testing.assert_allclose(derive_periodic_delta(d_one),
                               derive_periodic_delta(d_two), atol=1e-2)


def test_registration_invariant_per_seam():
    """delta maps every near frame onto its one-bp-past-far frame (residual ~0)."""
    d = _periodic_bundle_design(42)
    delta = derive_periodic_delta(d)
    for f_near, f_far_next in _iter_seam_frames(d):
        pred = delta @ f_near
        np.testing.assert_allclose(pred[:3, 3], f_far_next[:3, 3], atol=0.05)


def test_non_periodic_design_raises():
    d = _periodic_bundle_design(42, periodic=False)
    with pytest.raises(PeriodicSeamError):
        derive_periodic_delta(d)


# ── Route ──────────────────────────────────────────────────────────────────


def test_periodic_forward_extends_chain():
    _seed_periodic_assembly()
    r = client.post("/api/assembly/polymerize-periodic", json={
        "instance_id": "seed", "count": 4, "direction": "forward",
    })
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    assert len(v1_instances(r)) == 4          # seed + 3
    assert len([j for j in asm["joints"] if j["joint_type"] == "rigid"]) == 3


def test_periodic_backward_prepends_chain():
    _seed_periodic_assembly()
    r = client.post("/api/assembly/polymerize-periodic", json={
        "instance_id": "seed", "count": 3, "direction": "backward",
    })
    assert r.status_code == 200, r.text
    assert len(v1_instances(r)) == 3


def test_periodic_both_splits():
    _seed_periodic_assembly()
    r = client.post("/api/assembly/polymerize-periodic", json={
        "instance_id": "seed", "count": 5, "direction": "both",
    })
    assert r.status_code == 200, r.text
    assert len(v1_instances(r)) == 5


def test_periodic_rejects_non_periodic_422():
    _seed_periodic_assembly(periodic=False)
    r = client.post("/api/assembly/polymerize-periodic", json={
        "instance_id": "seed", "count": 4, "direction": "forward",
    })
    assert r.status_code == 422


def test_periodic_count_below_2_is_400():
    _seed_periodic_assembly()
    r = client.post("/api/assembly/polymerize-periodic", json={
        "instance_id": "seed", "count": 1, "direction": "forward",
    })
    assert r.status_code == 400


def test_periodic_missing_instance_404():
    _seed_periodic_assembly()
    r = client.post("/api/assembly/polymerize-periodic", json={
        "instance_id": "nope", "count": 4, "direction": "forward",
    })
    assert r.status_code == 404


def test_periodic_joints_carry_mate_relative_transform():
    _seed_periodic_assembly()
    r = client.post("/api/assembly/polymerize-periodic", json={
        "instance_id": "seed", "count": 4, "direction": "forward",
    })
    asm = r.json()["assembly"]
    new_joints = [j for j in asm["joints"] if j["joint_type"] == "rigid"]
    assert new_joints
    for j in new_joints:
        assert j["mate_relative_transform"] is not None
        assert len(j["mate_relative_transform"]) == 16
        assert j["connector_a_label"] == "seam0:3p"
        assert j["connector_b_label"] == "seam0:5p"


def test_periodic_connectors_coincide_across_junction():
    """Copy k's 3' seam connector world position ≈ copy k+1's 5' connector."""
    _seed_periodic_assembly()
    r = client.post("/api/assembly/polymerize-periodic", json={
        "instance_id": "seed", "count": 4, "direction": "forward",
    })
    asm = r.json()["assembly"]
    insts = {i["id"]: i for i in v1_instances(r)}

    def conn_world(inst, label):
        ip = next(p for p in inst["interface_points"] if p["label"] == label)
        T = np.array(inst["transform"]["values"], dtype=float).reshape(4, 4)
        p = np.array([ip["position"]["x"], ip["position"]["y"], ip["position"]["z"], 1.0])
        return (T @ p)[:3]

    # Build chain order from the rigid joints (instance_a 3p → instance_b 5p).
    for j in asm["joints"]:
        if j["joint_type"] != "rigid":
            continue
        a3 = conn_world(insts[j["instance_a_id"]], "seam0:3p")
        b5 = conn_world(insts[j["instance_b_id"]], "seam0:5p")
        np.testing.assert_allclose(a3, b5, atol=0.05)


def test_periodic_feature_log_and_undo():
    asm0 = _seed_periodic_assembly()
    n_before = len(asm0.feature_log)
    r = client.post("/api/assembly/polymerize-periodic", json={
        "instance_id": "seed", "count": 4, "direction": "forward",
    })
    asm = r.json()["assembly"]
    assert any(e["op_kind"] == "assembly-polymerize-periodic" for e in asm["feature_log"])
    assert len(asm["feature_log"]) == n_before + 1

    u = client.post("/api/assembly/undo")
    assert u.status_code == 200, u.text
    assert len(v1_instances(u)) == 1   # chain removed


def test_patch_instance_design_auto_resolves_periodic_chain():
    """The part-editor save path (PATCH /assembly/instances/{id}/design) must
    auto-resolve so a polymerized chain re-docks to the edited part — without the
    user clicking Resolve. Regression for `workspace/Spiral.nass`: editing teeth
    via the part editor left the 4 copies frozen at the pre-edit pose.
    """
    from backend.api.assembly import _WORKSPACE_DIR
    from backend.core.models import (
        Assembly, BendParams, DeformationOp, Mat4x4, PartInstance, PartSourceFile,
    )

    _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    part_path = _WORKSPACE_DIR / "_test_periodic_patch.nadoc"
    try:
        d = _periodic_bundle_design(42)
        part_path.write_text(d.to_json(), encoding="utf-8")
        client.post("/api/assembly")
        seed = PartInstance(id="seed", name="Ring",
                            source=PartSourceFile(path=part_path.name), transform=Mat4x4())
        assembly_state.set_assembly(Assembly(instances=[seed], joints=[]))
        client.post("/api/assembly/polymerize-periodic", json={
            "instance_id": "seed", "count": 4, "direction": "forward"})
        asm0 = assembly_state.get_or_404()
        base_T = {i.id: np.array(i.transform.to_array()) for i in asm0.instances}

        # Edit the part (add a bend) and save via the part-editor path. The bend
        # moves the seam cross-sections, so the chain must re-dock.
        bent = d.model_copy(update={"deformations": [
            DeformationOp(type="bend", plane_a_bp=0, plane_b_bp=41,
                          affected_helix_ids=[],
                          params=BendParams(angle_deg=45.0, direction_deg=0.0))]}, deep=True)
        r = client.patch("/api/assembly/instances/seed/design", json={"content": bent.to_json()})
        assert r.status_code == 200, r.text

        done = assembly_state.get_or_404()
        new_T = {i.id: np.array(i.transform.to_array()) for i in done.instances}
        moved = max(float(np.linalg.norm(new_T[k] - base_T[k])) for k in new_T)
        assert moved > 1.0, f"chain did not re-dock after part-design patch (max move {moved:.3f} nm)"
    finally:
        if part_path.exists():
            part_path.unlink()


def test_periodic_resolve_is_stable_noop():
    """resolve after polymerize keeps the chain (snap is a no-op by construction)."""
    _seed_periodic_assembly()
    client.post("/api/assembly/polymerize-periodic", json={
        "instance_id": "seed", "count": 4, "direction": "forward",
    })
    r = client.post("/api/assembly/resolve")
    assert r.status_code == 200, r.text
    assert len(v1_instances(r)) == 4


def test_periodic_chain_re_docks_after_part_geometry_change():
    """A feature change to the periodic part (here: a bend) moves its seam
    cross-sections, and resolve must RE-DOCK the whole chain to the new geometry.

    Regression for the frozen-chain bug: the synthesized ``seam0:*`` connectors
    used to resolve from a STATIC position baked at polymerize time, so geometry
    edits never reached the chain. They now resolve live (like ``blunt:`` ends).
    """
    from backend.core.models import BendParams, DeformationOp, PartSourceInline

    _seed_periodic_assembly(L=42)
    client.post("/api/assembly/polymerize-periodic", json={
        "instance_id": "seed", "count": 4, "direction": "forward",
    })
    client.post("/api/assembly/resolve")
    asm0 = assembly_state.get_or_404()
    base_T = {i.id: np.array(i.transform.to_array()) for i in asm0.instances}

    # Add a bend to the shared part design on every instance (mimics editing the
    # part's feature log), then re-resolve.
    base_design = next(i.source.design for i in asm0.instances)
    max_bp = max(h.bp_start + h.length_bp for h in base_design.helices) - 1
    bent = base_design.model_copy(update={
        "deformations": list(base_design.deformations) + [
            DeformationOp(type="bend", plane_a_bp=0, plane_b_bp=max_bp,
                          affected_helix_ids=[],
                          params=BendParams(angle_deg=45.0, direction_deg=0.0))],
    }, deep=True)
    new_src = PartSourceInline(design=bent)
    asm1 = asm0.model_copy(update={
        "instances": [i.model_copy(update={"source": new_src}) for i in asm0.instances]})
    assembly_state.set_assembly(asm1)

    r = client.post("/api/assembly/resolve")
    assert r.status_code == 200, r.text
    asm_done = assembly_state.get_or_404()
    new_T = {i.id: np.array(i.transform.to_array()) for i in asm_done.instances}

    # 1) The chain re-docked — clones moved to follow the new seam geometry.
    moved = max(float(np.linalg.norm(new_T[k] - base_T[k])) for k in new_T)
    assert moved > 1.0, f"chain did not re-dock after geometry change (max move {moved:.3f} nm)"

    # 2) Consecutive seam connectors still coincide — under the NEW live geometry.
    from backend.api.assembly import _get_connector_world
    insts = {i.id: i for i in asm_done.instances}
    rigid = [j for j in asm_done.joints if j.joint_type == "rigid"]
    assert rigid
    for j in rigid:
        a3 = _get_connector_world(insts[j.instance_a_id], "seam0:3p", bent)
        b5 = _get_connector_world(insts[j.instance_b_id], "seam0:5p", bent)
        np.testing.assert_allclose(a3, b5, atol=0.1)
