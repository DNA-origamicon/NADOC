"""Display visibility persists in .nadoc JSON without entering the feature log."""

from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api import assembly
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import Design, VisibilityState


def test_visibility_defaults_empty_for_legacy_designs():
    restored = Design.from_json(_demo_design().to_json())
    assert restored.visibility_state == VisibilityState()


def test_visibility_round_trips_through_nadoc_json():
    design = _demo_design()
    design.visibility_state = VisibilityState(
        hidden_base_keys=["demo_helix:0:FORWARD"],
        shown_base_keys=["demo_helix:1:FORWARD"],
        hidden_cluster_ids=["cluster-a"],
    )
    restored = Design.from_json(design.to_json())
    assert restored.visibility_state == design.visibility_state


def test_visibility_endpoint_persists_without_feature_log_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    design = _demo_design()
    design_state.set_design(design)
    before_log = list(design.feature_log)
    body = {
        "hidden_base_keys": ["demo_helix:0:FORWARD"],
        "shown_base_keys": ["demo_helix:1:FORWARD"],
        "hidden_cluster_ids": ["cluster-a"],
    }
    with TestClient(app) as client:
        # Lifespan startup may restore the default document; establish this
        # test's design after startup so revision pointers match tmp_path.
        design_state.set_design_branch(design, push_history=False)
        response = client.put("/api/design/visibility", json=body)
        assert response.status_code == 200
        saved_path = tmp_path / "visibility.nadoc"
        save = client.post(
            "/api/design/save-workspace",
            json={"path": "visibility.nadoc", "overwrite": True},
        )
        assert save.status_code == 200, save.text

    restored = Design.from_json(saved_path.read_text())
    assert restored.visibility_state.model_dump() == body
    assert restored.feature_log == before_log
