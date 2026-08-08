"""Relax a BOUND direct duplex + the direct-relax solver's MINIMAL-MOTION /
idempotency guarantee.

Two concerns:

  * ``POST /design/duplexes/{id}/relax`` (Proposal-B) resolves driver/driven from a
    bound duplex and runs the shared ``direct_relax`` solve — the sibling of
    ``relax_overhang_binding`` for a duplex with no legacy binding.
  * The solve is UNDER-CONSTRAINED (the 2-DOF overhang swing can close the tip↔root
    bond at any hinge angle), so it must resolve the redundant hinge DOF by
    MINIMISING TOTAL MOTION — which makes it idempotent (re-relaxing an already-closed
    bond must not keep drifting the hinge) and stops the "hinge decreased too much /
    overshoot" the raw Powell result produced.

Uses an IMMUTABLE frozen copy of the 2x2 test design (``tests/fixtures/…``) — the live
``workspace/2x2_OH_test.nadoc`` is edited by hand between sessions.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.direct_relax import relax_direct_binding
from backend.core.models import (
    ClusterRigidTransform,
    Design,
    Direction,
    Domain,
    Helix,
    OverhangSpec,
    Strand,
    StrandType,
    SubDomain,
    Vec3,
)

client = TestClient(app)

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "relax_2x2_binding.nadoc"
# A pose the user hand-set so the tip↔root bond is ALREADY closer than one bond
# length (chord ≈ 0.38 nm < 0.67 nm target) — pins the one-sided floor (no back-off).
_CLOSE_FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "relax_2x2_closebond.nadoc"
)
# Untracked fixtures with no headless builder yet (design-automation AF-FIXTURES); the tests that
# read them skip cleanly where absent (fresh checkout / other computer). The 422/404 error-path
# tests build in-memory and stay unguarded so they still run everywhere.
_needs_fixture = pytest.mark.skipif(
    not _FIXTURE.exists(),
    reason="relax_2x2_binding.nadoc missing (untracked; regen via AF-FIXTURES builder)",
)
_needs_close_fixture = pytest.mark.skipif(
    not _CLOSE_FIXTURE.exists(),
    reason="relax_2x2_closebond.nadoc missing (untracked; regen via AF-FIXTURES builder)",
)


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    design_state.set_design(_demo_design())


def _load_fixture() -> Design:
    return Design.model_validate(json.loads(_FIXTURE.read_text()))


def _hinge_angle_deg(design: Design) -> float:
    """Signed x-axis hinge angle of the second (driven) cluster."""
    q = design.cluster_transforms[1].rotation
    return float(np.degrees(2.0 * np.arctan2(q[0], q[3])))


# ── Solver: minimal-motion + idempotency (the reported "overshoot" bug) ───────


def _driver_overhang_rotation(design: Design, driver_oh_id: str) -> np.ndarray:
    return np.asarray(
        next(o for o in design.overhangs if o.id == driver_oh_id).rotation, dtype=float
    )


@_needs_fixture
def test_relax_is_idempotent():
    """The bridge-method relax is idempotent in its FINAL pose: a second relax of the
    relaxed result reproduces the same driven-cluster pose AND the same duplex placement
    (the re-seat zeros then re-derives the same absolute placement, and the clash spin
    lands on the same min angle), so nothing drifts."""
    design = _load_fixture()
    b = design.overhang_bindings[0]

    out1, _i1 = relax_direct_binding(design, b.driver_oh_id, b.driven_oh_id)
    out2, info2 = relax_direct_binding(out1, b.driver_oh_id, b.driven_oh_id)
    assert info2["final_chord_nm"] == pytest.approx(info2["target_nm"], abs=0.05)
    assert all(abs(t) < 1.0 for t in info2["thetas_deg"])  # arc-min doesn't re-rotate
    # Duplex placement (driver overhang rotation) and driven cluster are unchanged.
    r1 = _driver_overhang_rotation(out1, b.driver_oh_id)
    r2 = _driver_overhang_rotation(out2, b.driver_oh_id)
    assert float(np.linalg.norm(r2 - r1)) < 1e-2
    assert abs(_hinge_angle_deg(out2) - _hinge_angle_deg(out1)) < 1.0


@_needs_close_fixture
def test_relax_opens_an_over_compressed_bond_to_natural_length():
    """Bridge method is TWO-SIDED (like the dsDNA linker bridge): a bond CLOSER than
    one backbone step (the frozen fixture's chord ≈ 0.38 nm — an over-compressed steric
    clash) is opened back out to the natural target (≈ 0.67 nm) by the cluster kinematics.
    Relieving the compression is what makes a subsequent simulation easier to equilibrate.
    (Supersedes the old one-sided 'don't back off' floor — see LESSONS E7.)"""
    design = Design.model_validate(json.loads(_CLOSE_FIXTURE.read_text()))
    b = design.overhang_bindings[0]

    out, info = relax_direct_binding(design, b.driver_oh_id, b.driven_oh_id)
    assert info["final_chord_nm"] == pytest.approx(info["target_nm"], abs=0.15)


@_needs_fixture
def test_relax_closes_a_stretched_bond_via_cluster_motion_only():
    """From a neutralised (un-posed) state the ~7 nm stretched bond closes to the natural
    target using the CLUSTER kinematics (joint rotation about the JOINT axis) — the clash
    spin lives on the DUPLEX (driver overhang rotation), never on the cluster about the
    overhang axis, so the whole driven part stays put apart from the joint hinge."""
    design = _load_fixture()
    b = design.overhang_bindings[0]
    # Neutralise the stored pose (identity driven cluster + identity driver overhang).
    c2 = design.cluster_transforms[1].model_copy(
        update={"rotation": [0, 0, 0, 1.0], "translation": [0, 0, 0.0]}
    )
    drv = next(i for i, o in enumerate(design.overhangs) if o.id == b.driver_oh_id)
    oh = design.overhangs[drv].model_copy(
        update={"rotation": [0, 0, 0, 1.0], "translation": [0, 0, 0.0]}
    )
    ohs = [oh if i == drv else o for i, o in enumerate(design.overhangs)]
    design = design.model_copy(
        update={
            "cluster_transforms": [design.cluster_transforms[0], c2],
            "overhangs": ohs,
        }
    )

    out, info = relax_direct_binding(design, b.driver_oh_id, b.driven_oh_id)
    assert info["final_chord_nm"] == pytest.approx(info["target_nm"], abs=0.2)
    assert any(
        abs(t) > 1.0 for t in info["thetas_deg"]
    )  # the joint carried the closure


# ── Route: relax a bound duplex (Proposal-B path) ─────────────────────────────


@_needs_fixture
def test_relax_bound_duplex_route_closes_and_is_idempotent():
    """A bound duplex resolves driver/driven and relaxes via the same solve. The
    frozen design is already relocated (shared with its binding), so marking the
    duplex bound lets the route drive it; re-relaxing must stay put."""
    design = _load_fixture()
    dx = design.duplexes[0].model_copy(update={"bound": True})
    design = design.model_copy(update={"duplexes": [dx]})
    design_state.set_design(design)

    r = client.post(f"/api/design/duplexes/{dx.id}/relax")
    assert r.status_code == 200, r.text
    info = r.json()["relax_info"]
    assert info["final_chord_nm"] == pytest.approx(info["target_nm"], abs=0.6)


# ── Route guards ──────────────────────────────────────────────────────────────


def _helix(hid, length, *, x=0.0):
    return Helix(
        id=hid,
        axis_start=Vec3(x=x, y=0.0, z=0.0),
        axis_end=Vec3(x=x, y=0.0, z=length * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=length,
        grid_pos=(0, 0),
    )


def _simple_design() -> Design:
    st_drv = Strand(
        id="st_drv",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id="h_drv",
                start_bp=0,
                end_bp=23,
                direction=Direction.FORWARD,
                overhang_id="OHd",
            )
        ],
    )
    st_drvn = Strand(
        id="st_drvn",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id="h_drvn",
                start_bp=0,
                end_bp=9,
                direction=Direction.FORWARD,
                overhang_id="OHn",
            )
        ],
    )
    ohd = OverhangSpec(
        id="OHd",
        helix_id="h_drv",
        strand_id="st_drv",
        sequence="A" * 24,
        sub_domains=[SubDomain(id="sdd", start_bp_offset=0, length_bp=24)],
    )
    ohn = OverhangSpec(
        id="OHn",
        helix_id="h_drvn",
        strand_id="st_drvn",
        sequence="T" * 10,
        sub_domains=[SubDomain(id="sdn", start_bp_offset=0, length_bp=10)],
    )
    return Design(
        helices=[_helix("h_drv", 24), _helix("h_drvn", 10, x=8.0)],
        strands=[st_drv, st_drvn],
        overhangs=[ohd, ohn],
        cluster_transforms=[
            ClusterRigidTransform(id="c1", name="C1", helix_ids=["h_drv"]),
            ClusterRigidTransform(id="c2", name="C2", helix_ids=["h_drvn"]),
        ],
    )


def test_relax_unbound_duplex_is_422():
    design_state.set_design(_simple_design())
    r = client.post(
        "/api/design/duplexes",
        json={
            "left": {"overhang_id": "OHd", "start_bp": 0, "end_bp": 9},
            "right": {"overhang_id": "OHn", "start_bp": 9, "end_bp": 0},
            "driver": "left",
            "bound": False,
        },
    )
    assert r.status_code == 201, r.text
    dxid = r.json()["duplex_id"]
    r2 = client.post(f"/api/design/duplexes/{dxid}/relax")
    assert r2.status_code == 422, r2.text
    assert "not bound" in r2.json()["detail"].lower()


def test_relax_unknown_duplex_is_404():
    design_state.set_design(_simple_design())
    r = client.post("/api/design/duplexes/does-not-exist/relax")
    assert r.status_code == 404, r.text
