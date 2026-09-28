from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import Design, ViewVolume


def setup_function():
    design_state.set_design(_demo_design())


def test_view_volume_round_trip_and_old_default():
    design = _demo_design()
    design.view_volumes = [ViewVolume(name="Focus", shape="hexagonal", min_corner=(0, 1, 2), max_corner=(3, 4, 5), rotation=(0, 0, 0.70710678, 0.70710678), representation="surface", coloring="cluster", opacity=.35, outline_visible=False, enabled=False)]
    restored = Design.from_json(design.to_json())
    assert restored.view_volumes == design.view_volumes
    assert Design.from_json(_demo_design().to_json()).view_volumes == []


def test_put_view_volumes_persists_and_validates():
    client = TestClient(app)
    revision_before = design_state.revision()
    body = {"volumes": [{"name": "Atomistic window", "min_corner": [-2, -2, -2], "max_corner": [2, 2, 2], "representation": "stick", "coloring": "base", "opacity": .7}]}
    response = client.put("/api/design/view-volumes", json=body)
    assert response.status_code == 200
    saved = response.json()["view_volumes"][0]
    assert saved["outline_visible"] is True
    assert saved["enabled"] is True
    assert response.json()["revision"] > revision_before
    assert saved["name"] == "Atomistic window"
    assert saved["opacity"] == .7
    assert saved["coloring"] == "base"
    assert ViewVolume(min_corner=(0, 0, 0), max_corner=(1, 1, 1)).coloring == "strand"
    assert client.put("/api/design/view-volumes", json={"volumes": [{**body["volumes"][0], "coloring": "bad"}]}).status_code == 422
    lightweight = client.get("/api/design/view-volumes")
    assert lightweight.status_code == 200
    assert lightweight.json()["view_volumes"] == response.json()["view_volumes"]
    assert lightweight.json()["revision"] == response.json()["revision"]
    assert client.put("/api/design/view-volumes", json={"volumes": [{**body["volumes"][0], "opacity": 1.2}]}).status_code == 422
    assert client.put("/api/design/view-volumes", json={"volumes": [{**body["volumes"][0], "min_corner": [3, 0, 0]}]}).status_code == 422
    assert client.put("/api/design/view-volumes", json={"volumes": [{**body["volumes"][0], "rotation": [0, 0, 1, 1]}]}).status_code == 422
    assert client.put("/api/design/view-volumes", json={"volumes": [{**body["volumes"][0], "shape": "cylinder"}]}).status_code == 422
    assert client.put("/api/design/view-volumes", json={"volumes": [{**body["volumes"][0], "representation": "wireframe"}]}).status_code == 422
    assert client.put("/api/design/view-volumes", json={"volumes": [{**body["volumes"][0], "max_corner": [-2, 2, 2]}]}).status_code == 422


def test_assembly_volume_parity_and_isolated_persistence():
    from backend.api import assembly_state
    from backend.core.models import Assembly

    assembly_state.set_assembly(Assembly())
    client = TestClient(app)
    part_before = design_state.get_or_404().to_json()
    volume = ViewVolume(name="Assembly window", min_corner=(-3, -2, -1), max_corner=(4, 5, 6), representation="ballstick", coloring="base", opacity=.4)
    body = {"volumes": [volume.model_dump(mode="json")]}
    saved = client.put("/api/assembly/view-volumes", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["view_volumes"] == body["volumes"]
    assert client.get("/api/assembly/view-volumes").json()["view_volumes"] == body["volumes"]
    restored = Assembly.from_json(assembly_state.get_or_404().to_json())
    assert restored.view_volumes == [volume]
    assert design_state.get_or_404().to_json() == part_before
    for invalid in ({"opacity": 1.1}, {"coloring": "invalid"}, {"max_corner": [-5, -5, -5]}):
        bad = {"volumes": [{**body["volumes"][0], **invalid}]}
        assert client.put("/api/assembly/view-volumes", json=bad).status_code == client.put("/api/design/view-volumes", json=bad).status_code == 422
    assert client.put("/api/assembly/view-volumes", json={"volumes": []}).json()["view_volumes"] == []


def test_assembly_region_surface_uses_instance_source_and_part_pipeline(monkeypatch):
    from backend.api import assembly_state, routes_assembly_geometry as routes
    from backend.core.models import Assembly, PartInstance, PartSourceInline

    design = _demo_design()
    instance = PartInstance(source=PartSourceInline(design=design))
    assembly_state.set_assembly(Assembly(instances=[instance]))
    seen = []
    def capture(source, body):
        seen.append((source, body))
        return {"vertices": [], "faces": [], "vertex_colors": None, "stats": {}}
    monkeypatch.setattr(routes, "build_region_surface", capture)
    response = TestClient(app).post(f"/api/assembly/instances/{instance.id}/surface/region", json={"segments": [], "color_mode": "strand"})
    assert response.status_code == 200, response.text
    assert seen[0][0].id == design.id
    assert seen[0][1].color_mode == "strand"
    assert TestClient(app).post("/api/assembly/instances/missing/surface/region", json={"segments": []}).status_code == 404
