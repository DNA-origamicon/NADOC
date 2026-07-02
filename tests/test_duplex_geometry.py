"""Phase 4b — duplex driver toggle RE-PLACES geometry (#4 + #1: entire driven
domain relocates onto the new driver's helix, via the proven bind machinery).

Verified on the real `2x2_OH_test` fixture (two clusters, two 10-mer overhangs).
Bind them, then flip the duplex driver and assert the shared duplex helix moves
from the old driver's helix to the new driver's helix. See
`memory/project_overhang_duplex_foundation.md`.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import Design

client = TestClient(app)
FIXTURE = "/home/joshua/NADOC/workspace/playwright_tests/2x2_OH_test.nadoc"

OH1, OH2 = "ovhg_h_XY_1_0_40_5p", "ovhg_h_XY_4_0_40_3p"
SD1, SD2 = "2bc55cd5-f0eb-5c59-b01f-d7fe3f62d042", "c48033e6-031b-5e13-8495-6b56cb5d513b"
HELIX1, HELIX2 = "h_XY_2_0", "h_XY_3_0"   # OH1's / OH2's own overhang helices


@pytest.fixture(autouse=True)
def _reset_state():
    yield
    design_state.set_design(_demo_design())


def _helix_of(overhang_id: str) -> str:
    """Helix hosting the strand domain tagged with `overhang_id` (the domain
    relocates onto the DRIVER's helix when bound)."""
    d = design_state.get_design()
    for s in d.strands:
        for dom in s.domains:
            if dom.overhang_id == overhang_id:
                return dom.helix_id
    return ""


def test_driver_flip_replaces_geometry_on_2x2():
    design_state.set_design(Design.from_json(open(FIXTURE, encoding="utf-8").read()))

    # Complementary sequences so a binding can be created (RC(OH1) == OH2).
    assert client.patch(f"/api/design/overhang/{OH1}", json={"sequence": "AAAACCCCGG"}).status_code == 200
    assert client.patch(f"/api/design/overhang/{OH2}", json={"sequence": "CCGGGGTTTT"}).status_code == 200

    # Bind the two 10-mer sub-domains, then relocate (bound=True).
    r = client.post("/api/design/overhang-bindings",
                    json={"sub_domain_a_id": SD1, "sub_domain_b_id": SD2})
    assert r.status_code == 201, r.text
    bid = design_state.get_design().overhang_bindings[0].id
    assert client.patch(f"/api/design/overhang-bindings/{bid}", json={"bound": True}).status_code == 200

    # Driver heuristic picks side 'a' (OH1): OH2's domain relocated onto OH1's helix.
    assert _helix_of(OH2) == HELIX1, "driven OH2 should sit on driver OH1's helix after bind"
    assert _helix_of(OH1) == HELIX1

    # Derive the duplex (driver='left' == OH1, matching the heuristic).
    did = client.post("/api/design/duplexes/sync-from-bindings").json()["design"]["duplexes"][0]["id"]

    # Flip the driver → OH2 drives; the ENTIRE driven domain (now OH1) must
    # relocate onto OH2's helix, and the binding driver follows (#4).
    r = client.patch(f"/api/design/duplexes/{did}", json={"driver": "right"})
    assert r.status_code == 200, r.text
    assert design_state.get_design().overhang_bindings[0].driver_oh_id == OH2
    assert _helix_of(OH1) == HELIX2, "driven OH1 should now sit on driver OH2's helix after flip"
    assert _helix_of(OH2) == HELIX2
