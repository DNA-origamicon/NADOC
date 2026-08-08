"""Phase 4b: a DIFFERENT-length duplex relocates the driven overhang's domain onto
the driver's helix at the paired-window range (so the duplex forms in 3D/cadnano),
WITHOUT stretching the short driven to the long driver's length. Verifies the fix
for "the driven overhang is not relocated after connecting different-length overhangs".
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
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


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    design_state.set_design(_demo_design())


def _helix(hid, length):
    return Helix(
        id=hid,
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=length * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=length,
        grid_pos=(0, 0),
    )


def _design_diff_length_overhangs() -> Design:
    """Driver overhang = 24 bp on h_drv; driven overhang = 10 bp on h_drvn."""
    hdrv, hdrvn = _helix("h_drv", 24), _helix("h_drvn", 10)
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
        helices=[hdrv, hdrvn], strands=[st_drv, st_drvn], overhangs=[ohd, ohn]
    )


def _dom_of(design, overhang_id):
    for s in design["strands"]:
        for d in s["domains"]:
            if d["overhang_id"] == overhang_id:
                return d
    return None


def test_connect_relocates_short_driven_onto_long_driver_helix():
    design_state.set_design(_design_diff_length_overhangs())
    # Longest (OHd, 24) drives; OHn (10) is driven.
    r = client.post(
        "/api/design/duplexes/connect",
        json={
            "overhang_a_id": "OHd",
            "overhang_a_attach": "root",
            "overhang_b_id": "OHn",
            "overhang_b_attach": "root",
        },
    )
    assert r.status_code == 201, r.text
    design = r.json()["design"]

    # Driven OHn relocated onto the driver's helix h_drv, keeping its OWN 10 bp
    # length (NOT stretched to the driver's 24).
    dn = _dom_of(design, "OHn")
    assert dn["helix_id"] == "h_drv"
    assert abs(dn["end_bp"] - dn["start_bp"]) + 1 == 10
    # Driver OHd untouched: still 24 bp on its own helix.
    dd = _dom_of(design, "OHd")
    assert dd["helix_id"] == "h_drv" and abs(dd["end_bp"] - dd["start_bp"]) + 1 == 24
    # The duplex recorded the relocation so it can be reverted.
    assert design["duplexes"][0]["bound"] is True
    assert design["duplexes"][0]["prior_driven_topology"] is not None
