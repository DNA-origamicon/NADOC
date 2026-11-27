import pytest
from backend.rendering.optix_frame_state import resolve_frame


def test_camera_frames_keep_background_without_retaining_large_geometry_payloads():
    scene = dict(meshes=[{"position": "large"}], background="#abcdef", transparent=True)
    frame, state, changed = resolve_frame(scene, None)
    assert changed and frame is scene
    assert state == {"background": "#abcdef", "transparent": True}
    update, same, changed = resolve_frame(dict(reuse_scene=True, samples=4, camera={"matrix": [1]}), state)
    assert not changed and same is state
    assert update["samples"] == 4 and update["background"] == "#abcdef"
    _, state, changed = resolve_frame({**scene, "background": "#000000"}, state)
    assert changed and state["background"] == "#000000"


def test_reuse_cannot_omit_initial_scene_or_silently_ignore_lighting():
    with pytest.raises(ValueError, match="complete scene"):
        resolve_frame(dict(reuse_scene=True), None)
    with pytest.raises(ValueError, match="together"):
        resolve_frame(dict(reuse_scene=True, lights=[]), {})


def test_camera_and_lights_update_without_geometry_or_environment_upload():
    prior = {"background": "#abcdef", "transparent": False}
    lights = [{"type": "DirectionalLight", "position": [2, 3, 4]}]
    frame, state, changed = resolve_frame(dict(reuse_scene=True, lights=lights, rotation=[0, 1, 0]), prior)
    assert not changed and state is prior
    assert frame["lights"] == lights and frame["rotation"] == [0, 1, 0]
    assert "meshes" not in frame and "environment" not in frame
    next_frame, _, _ = resolve_frame(dict(reuse_scene=True), state)
    assert "lights" not in next_frame  # updates are applied once, not every refinement
    with pytest.raises(ValueError, match="environment"):
        resolve_frame(dict(reuse_scene=True, environment={}), prior)


def test_smooth_glow_transparency_budget_survives_camera_only_frames():
    _, state, _ = resolve_frame(dict(meshes=[], background="#000000", transparent=False, smoothEM=True), None)
    frame, _, changed = resolve_frame(dict(reuse_scene=True), state)
    assert not changed and frame["smoothEM"] is True
    _, state, _ = resolve_frame(dict(meshes=[], background="#000000", transparent=False, smoothEM=False), state)
    assert state["smoothEM"] is False
