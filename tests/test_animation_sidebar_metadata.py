"""Animation sidebar display metadata persists through the public editor routes."""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.api.main import app
from backend.core.models import Annotation, CameraPose

THUMBNAIL = "data:image/jpeg;base64,YQ=="


@pytest.mark.parametrize("host", ["design", "assembly"])
def test_pose_thumbnail_and_keyframe_annotation_choices_round_trip(host):
    client = TestClient(app)
    response = client.post(f"/api/{host}", json={"name": "__e2e__animation-sidebar"})
    assert response.status_code in (200, 201)
    pose = {"name": "Side", "position": [6, 3, 7], "target": [0, 0, 7],
            "up": [0, 1, 0], "thumbnail": THUMBNAIL}
    response = client.post(f"/api/{host}/camera-poses", json=pose)
    assert response.status_code == 200, response.text
    document = response.json()[host]
    saved_pose = document["camera_poses"][-1]
    assert saved_pose["thumbnail"] == THUMBNAIL
    response = client.patch(f"/api/{host}/camera-poses/{saved_pose['id']}", json={"name": "Renamed"})
    assert response.json()[host]["camera_poses"][-1]["thumbnail"] == THUMBNAIL
    response = client.post(f"/api/{host}/animations", json={"name": "Slides"})
    animation_id = response.json()[host]["animations"][-1]["id"]
    response = client.post(f"/api/{host}/animations/{animation_id}/keyframes",
                           json={"camera_pose_id": saved_pose["id"], "annotation_ids": ["a", "b"]})
    keyframe = response.json()[host]["animations"][-1]["keyframes"][-1]
    assert keyframe["annotation_ids"] == ["a", "b"]
    for selection in [[], ["b"], None]:
        response = client.patch(f"/api/{host}/animations/{animation_id}/keyframes/{keyframe['id']}",
                                json={"annotation_ids": selection})
        assert response.status_code == 200, response.text
        assert response.json()[host]["animations"][-1]["keyframes"][-1]["annotation_ids"] == selection


def test_annotation_name_survives_wire_round_trip():
    entry = Annotation(name="Opening", text="First state", font_family="Georgia")
    assert Annotation.model_validate_json(entry.model_dump_json()).name == "Opening"
    assert Annotation.model_validate_json(entry.model_dump_json()).font_family == "Georgia"
    assert Annotation.model_validate({"text": "Legacy"}).name == ""


def test_thumbnail_rejects_remote_or_script_urls():
    for value in ["https://example.com/image.png", "data:image/svg+xml;base64,YQ==", "javascript:alert(1)"]:
        with pytest.raises(ValidationError):
            CameraPose(thumbnail=value)


def test_annotation_sizes_accept_arbitrary_positive_finite_values():
    for size in [0.001, 100, 1e200]:
        assert Annotation.model_validate_json(Annotation(size=size).model_dump_json()).size == size
    for size in [0, -1, float('inf'), float('nan')]:
        with pytest.raises(ValidationError):
            Annotation(size=size)


def test_annotation_box_geometry_round_trip():
    entry = Annotation(box_size=(320, 120), rotation_deg=37.5)
    loaded = Annotation.model_validate_json(entry.model_dump_json())
    assert loaded.box_size == (320, 120)
    assert loaded.rotation_deg == 37.5
    assert Annotation().box_size is None
    for size in [(0, 120), (320, float('inf')), (320, -1)]:
        with pytest.raises(ValidationError):
            Annotation(box_size=size)
