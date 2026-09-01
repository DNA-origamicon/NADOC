"""Strand-name metadata must be durable without returning a full design payload."""

from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.models import Design, Domain, Direction, Helix, OverhangSpec, Strand, Vec3


def _design() -> Design:
    strand = Strand(
        id="oligo-1",
        domains=[Domain(
            helix_id="h1", start_bp=0, end_bp=3,
            direction=Direction.FORWARD, overhang_id="oh1",
        )],
    )
    return Design(
        name="name-persistence",
        helices=[Helix(id="h1", length_bp=4, axis_start=Vec3(x=0, y=0, z=0), axis_end=Vec3(x=0, y=0, z=1))],
        strands=[strand],
        overhangs=[OverhangSpec(id="oh1", helix_id="h1", strand_id="oligo-1", label="Old")],
    )


def test_name_patch_is_small_and_survives_serialized_reload():
    design_state.set_design(_design())
    response = TestClient(app).patch(
        "/api/design/strand/oligo-1", json={"name": "Custom oligo"}
    )

    assert response.status_code == 200
    assert len(response.content) < 1024
    assert response.json()["name"] == "Custom oligo"
    assert response.json()["overhang_labels"] == {"oh1": "Custom oligo"}

    saved = design_state.get_or_404().model_dump_json()
    reloaded = Design.model_validate_json(saved)
    assert reloaded.find_strand("oligo-1").name == "Custom oligo"
    assert reloaded.overhangs[0].label == "Custom oligo"
