from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import Design, ViewVolume


def setup_function():
    design_state.set_design(_demo_design())


def test_view_volume_round_trip_and_old_default():
    design = _demo_design()
    design.view_volumes = [ViewVolume(name="Focus", min_corner=(0, 1, 2), max_corner=(3, 4, 5), rotation=(0, 0, 0.70710678, 0.70710678), representation="surface", opacity=.35)]
    restored = Design.from_json(design.to_json())
    assert restored.view_volumes == design.view_volumes
    assert Design.from_json(_demo_design().to_json()).view_volumes == []


def test_put_view_volumes_persists_and_validates():
    client = TestClient(app)
    revision_before = design_state.revision()
    body = {"volumes": [{"name": "Atomistic window", "min_corner": [-2, -2, -2], "max_corner": [2, 2, 2], "representation": "stick", "opacity": .7}]}
    response = client.put("/api/design/view-volumes", json=body)
    assert response.status_code == 200
    saved = response.json()["view_volumes"][0]
    assert response.json()["revision"] > revision_before
    assert saved["name"] == "Atomistic window"
    assert saved["opacity"] == .7
    lightweight = client.get("/api/design/view-volumes")
    assert lightweight.status_code == 200
    assert lightweight.json()["view_volumes"] == response.json()["view_volumes"]
    assert lightweight.json()["revision"] == response.json()["revision"]
    assert client.put("/api/design/view-volumes", json={"volumes": [{**body["volumes"][0], "opacity": 1.2}]}).status_code == 422
    assert client.put("/api/design/view-volumes", json={"volumes": [{**body["volumes"][0], "min_corner": [3, 0, 0]}]}).status_code == 422
    assert client.put("/api/design/view-volumes", json={"volumes": [{**body["volumes"][0], "rotation": [0, 0, 1, 1]}]}).status_code == 422
