"""Real history API responses may never temporarily substitute legacy positions."""
import pytest
from fastapi.testclient import TestClient

from backend.api import state
from backend.api.main import app
from backend.core.design_geometry import _positions_by_helix
from backend.core.models import BendParams, DeformationOp, DeformationRange, TwistParams
from tests.conftest import make_minimal_design

pytestmark = pytest.mark.native_placement


@pytest.mark.parametrize("kind", ["bend", "twist"])
@pytest.mark.parametrize("scoped", [False, True])
def test_metadata_undo_redo_positions_match_full_get_exactly(kind, scoped, native_placement_evidence):
    design = make_minimal_design()
    operation = DeformationOp(type=kind, plane_a_bp=5, plane_b_bp=35,
        params=BendParams(curvature_deg_per_bp=3.1, direction_deg=37) if kind == "bend" else TwistParams(total_degrees=127),
        target_ranges=[DeformationRange(helix_id="h0", start_bp=0, end_bp=41, direction="FORWARD")] if scoped else None)
    design = design.copy_with(deformations=[operation])
    state.load_design(design)
    state.mutate_and_validate(lambda d: setattr(d.metadata, "description", "placement history probe"))
    client = TestClient(app)
    for step in ("undo", "redo"):
        response = client.post(f"/api/design/{step}")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["diff_kind"] == "positions_only"
        fresh = client.get("/api/design/geometry")
        assert fresh.status_code == 200, fresh.text
        expected = _positions_by_helix(fresh.json()["nucleotides"])
        actual = payload["positions_by_helix"]
        native_placement_evidence(operation=kind, scoped=scoped, history_step=step,
                                 expected_positions=expected, actual_positions=actual)
        assert actual == expected
        assert {source for directions in actual.values() for bucket in directions.values()
                for source in bucket["pv"]} == {"native-full-o5-v1"}
