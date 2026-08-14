"""Regression: applying a DIRECT connection between two DIFFERENT-length overhangs
must NOT resize either one (the shorter must not grow to the longer's length), and
must NOT create an unequal-length OverhangBinding. The pairing is a Duplex instead.

Root cause fixed: (frontend) the complementary-sequence write is capped to the
target's length; (backend) `_cv_create_bound_binding` skips different-length pairs.
See `memory/project_overhang_duplex_foundation.md`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import (
    ConnectionVersion,
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
from backend.core.constants import BDNA_RISE_PER_BP

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    design_state.set_design(_demo_design())


def _design_diff_lengths() -> Design:
    """Overhang A = 24 bp, overhang B = 10 bp, plus a root-to-root version to apply."""
    sa = Strand(
        id="sa",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id="hA",
                start_bp=0,
                end_bp=23,
                direction=Direction.FORWARD,
                overhang_id="ohA",
            )
        ],
    )
    sb = Strand(
        id="sb",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id="hB",
                start_bp=0,
                end_bp=9,
                direction=Direction.FORWARD,
                overhang_id="ohB",
            )
        ],
    )
    ohA = OverhangSpec(
        id="ohA",
        helix_id="hA",
        strand_id="sa",
        sequence="A" * 24,
        sub_domains=[SubDomain(id="sdA", start_bp_offset=0, length_bp=24)],
    )
    ohB = OverhangSpec(
        id="ohB",
        helix_id="hB",
        strand_id="sb",
        sequence="T" * 10,
        sub_domains=[SubDomain(id="sdB", start_bp_offset=0, length_bp=10)],
    )
    ver = ConnectionVersion(
        id="v1",
        name="V1",
        overhang_a_id="ohA",
        overhang_b_id="ohB",
        connection_type="root-to-root",
        overhang_a_seq="A" * 24,
        overhang_b_seq="T" * 10,
        applied=False,
    )
    def _helix(hid, length):
        return Helix(
            id=hid,
            axis_start=Vec3(x=0.0, y=0.0, z=0.0),
            axis_end=Vec3(x=0.0, y=0.0, z=length * BDNA_RISE_PER_BP),
            length_bp=length,
        )

    return Design(
        helices=[_helix("hA", 24), _helix("hB", 10)],
        strands=[sa, sb],
        overhangs=[ohA, ohB],
        connection_versions=[ver],
    )


def _dom_len(design_dict, overhang_id):
    for s in design_dict["strands"]:
        for d in s["domains"]:
            if d["overhang_id"] == overhang_id:
                return abs(d["end_bp"] - d["start_bp"]) + 1
    return None


def test_apply_direct_different_lengths_preserves_both_and_skips_binding():
    design_state.set_design(_design_diff_lengths())
    r = client.post("/api/design/connection-versions/v1/apply")
    assert r.status_code == 200, r.text
    design = r.json()["design"]
    # Neither overhang was resized (24 stays 24, 10 stays 10).
    assert _dom_len(design, "ohA") == 24
    assert _dom_len(design, "ohB") == 10
    # No unequal-length binding was created.
    assert design["overhang_bindings"] == []
    # The length-preserving Duplex is the pairing record for this case.
    assert len(design["duplexes"]) == 1
    left = design["duplexes"][0]["left"]
    right = design["duplexes"][0]["right"]
    assert abs(left["end_bp"] - left["start_bp"]) + 1 == 10
    assert abs(right["end_bp"] - right["start_bp"]) + 1 == 10
