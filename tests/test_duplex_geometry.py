"""The frozen separate-arm 2x2 connection must refuse incompatible root lengths.

Driver-switch success is covered on explicit same-body inputs in
``test_part_duplex_commands``. Do not change this asset or its linker atoms to
make the former unconstrained relocation succeed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import Design

client = TestClient(app)
# Lives in the gitignored playwright-fixtures dir (per feedback_playwright_fixtures_location),
# so it is not present on every checkout — skip cleanly rather than hard-fail when absent.
FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "workspace"
    / "playwright_tests"
    / "2x2_OH_test.nadoc"
)
pytestmark = pytest.mark.skipif(
    not FIXTURE.exists(), reason=f"fixture {FIXTURE.name} not present on this checkout"
)

OH1, OH2 = "ovhg_h_XY_1_0_40_5p", "ovhg_h_XY_4_0_40_3p"
SD1, SD2 = (
    "2bc55cd5-f0eb-5c59-b01f-d7fe3f62d042",
    "c48033e6-031b-5e13-8495-6b56cb5d513b",
)
HELIX1, HELIX2 = "h_XY_2_0", "h_XY_3_0"  # OH1's / OH2's own overhang helices


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


def test_2x2_binding_refuses_linker_conflict_before_driver_switch():
    design_state.set_design(Design.from_json(open(FIXTURE, encoding="utf-8").read()))

    # Complementary sequences so a binding can be created (RC(OH1) == OH2).
    assert (
        client.patch(
            f"/api/design/overhang/{OH1}", json={"sequence": "AAAACCCCGG"}
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/design/overhang/{OH2}", json={"sequence": "CCGGGGTTTT"}
        ).status_code
        == 200
    )

    # Bind the two 10-mer sub-domains, then relocate (bound=True).
    r = client.post(
        "/api/design/overhang-bindings",
        json={"sub_domain_a_id": SD1, "sub_domain_b_id": SD2},
    )
    assert r.status_code == 201, r.text
    bid = design_state.get_design().overhang_bindings[0].id
    before, revision = design_state.get_design_with_revision()
    depth = design_state.undo_depth()
    original = before.model_dump_json()
    response = client.patch(f"/api/design/overhang-bindings/{bid}", json={"bound": True})
    assert response.status_code == 422
    assert "native viewer and export root linkers" in response.json()["detail"]
    assert design_state.get_design_with_revision() == (before, revision)
    assert design_state.undo_depth() == depth
    assert design_state.get_design().model_dump_json() == original
    assert _helix_of(OH1) == HELIX1
    assert _helix_of(OH2) == HELIX2
