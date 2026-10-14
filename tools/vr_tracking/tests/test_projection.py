"""Independent pinhole/depth oracles and coordinate-ownership rejection tests."""
import copy
import math

import numpy as np
import pytest

from tools.vr_tracking.projection import (
    APPLICATION_EYE, FINAL_SWAPCHAIN, ApplicationFrame,
    FrameIdentity, ImagePoints, project_source_points, projection_residuals,
    source_to_tracking_matrix, unproject_application_depth,
)


def presentation():
    return {
        "model_to_tracking_rows": np.eye(4).tolist(),
        "source_center_nm": [0, 0, 0],
        "normalization_model_per_nm": 1,
        "normalized_offset_model": [0, 0, 0],
    }


def journal(*, eye="left", position=(0, 0, 0), quaternion=(0, 0, 0, 1)):
    return {
        "source": "application_projection", "frame": 17,
        "predicted_display_time_ns": 123456,
        "submitted": True, "xr_end_frame_succeeded": True,
        "presentation": presentation(),
        "eyes": [{"eye": eye, "width": 100, "height": 80,
                  "position": list(position), "orientation_xyzw": list(quaternion),
                  "fov_left_right_up_down": [-math.pi/4, math.pi/4, math.pi/4, -math.pi/4],
                  "rendered": True}],
    }


def context(row=None):
    return ApplicationFrame.from_journal({"session": "fixture"}, row or journal(), "left")


def measured(xy, frame, *, space=APPLICATION_EYE):
    return ImagePoints(xy, space, frame.camera.eye, frame.camera.width,
                       frame.camera.height, frame.identity)


def test_symmetric_projection_analytic_and_behind_eye():
    result = project_source_points([[0, 0, -2], [1, 1, -2], [0, 0, 1]], context())
    # A 90-degree pinhole maps x/z=.5 to u=.75; integer coordinates are centers.
    np.testing.assert_allclose(result.image.xy[:2], [[49.5, 39.5], [74.5, 19.5]])
    np.testing.assert_array_equal(result.in_front, [True, True, False])
    np.testing.assert_array_equal(result.inside_image, [True, True, False])
    assert np.isnan(result.image.xy[2]).all()
    assert result.image.coordinate_space == APPLICATION_EYE


def test_asymmetric_fov_independent_ray_slope_oracle():
    row = journal()
    row["eyes"][0]["fov_left_right_up_down"] = list(map(math.atan, [-.8, 1.2, .7, -.3]))
    result = project_source_points([[0, 0, -3], [.6, -.3, -3]], context(row))
    np.testing.assert_allclose(result.image.xy, [[39.5, 55.5], [49.5, 63.5]], atol=1e-12)


def test_eye_pose_and_source_normalization_are_both_applied():
    row = journal(position=(1, 2, 3), quaternion=(0, math.sqrt(.5), 0, math.sqrt(.5)))
    # Eye faces -X in tracking coordinates. Source center maps two meters ahead.
    row["presentation"] = {
        "model_to_tracking_rows": [[2, 0, 0, -1], [0, 2, 0, 2], [0, 0, 2, 3], [0, 0, 0, 1]],
        "source_center_nm": [10, 20, 30], "normalization_model_per_nm": .01,
        "normalized_offset_model": [0, 0, 0],
    }
    result = project_source_points([[10, 20, 30], [10, 30, 30]], context(row))
    np.testing.assert_allclose(result.image.xy, [[49.5, 39.5], [49.5, 35.5]], atol=1e-12)
    np.testing.assert_allclose(result.forward_depth_m, [2, 2])


def test_normalized_offset_is_not_discarded_or_scaled_twice():
    p = presentation()
    p.update(source_center_nm=[10, 20, 30], normalization_model_per_nm=.02,
             normalized_offset_model=[0, 0, -1.3])
    matrix = source_to_tracking_matrix(p)
    np.testing.assert_allclose(matrix @ [10, 20, 30, 1], [0, 0, -1.3, 1])
    np.testing.assert_allclose(matrix @ [60, 20, 30, 1], [1, 0, -1.3, 1])


def test_journal_prefers_model_uniform_at_the_eye_draw_without_mutating_row():
    row = journal()
    model = np.eye(4); model[0, 3] = 1
    row["eyes"][0]["model_to_tracking_rows"] = model.tolist()
    saved = copy.deepcopy(row)
    result = project_source_points([[0, 0, -2]], context(row))
    np.testing.assert_allclose(result.image.xy, [[74.5, 39.5]])
    assert row == saved


def test_depth_unprojection_analytic_and_background_excluded():
    frame = context()
    xy = measured([[49.5, 39.5], [74.5, 19.5], [49.5, 39.5]], frame)
    near, far, z = .1, 10., 2.
    # Standard OpenGL depth: far/(far-near) - far*near/((far-near)*forward_z).
    depth = far/(far-near) - far*near/((far-near)*z)
    result = unproject_application_depth(xy, [depth, depth, 1.], frame, near_m=near, far_m=far)
    np.testing.assert_allclose(result.source_nm[:2], [[0, 0, -2], [1, 1, -2]], atol=1e-12)
    np.testing.assert_array_equal(result.valid, [True, True, False])
    assert np.isnan(result.source_nm[2]).all()


def test_depth_unprojection_preserves_nontrivial_source_to_tracking():
    row = journal(position=(.3, -.2, .1))
    row["presentation"]["source_center_nm"] = [10, 20, 30]
    row["presentation"]["normalization_model_per_nm"] = .01
    row["presentation"]["normalized_offset_model"] = [.3, -.2, -1.9]
    frame = context(row)
    near, far = .05, 20
    depth = far/(far-near) - far*near/((far-near)*2)
    result = unproject_application_depth(measured([[49.5, 39.5]], frame), [depth], frame,
                                         near_m=near, far_m=far)
    np.testing.assert_allclose(result.source_nm, [[10, 20, 30]], atol=1e-10)


@pytest.mark.parametrize("change", ["space", "eye", "size", "frame", "session", "time"])
def test_residuals_never_mix_coordinate_or_frame_ownership(change):
    frame = context()
    result = project_source_points([[0, 0, -2]], frame)
    args = dict(xy=[[49.5, 39.5]], coordinate_space=APPLICATION_EYE, eye="left",
                width=100, height=80, frame=frame.identity)
    if change == "space": args["coordinate_space"] = FINAL_SWAPCHAIN
    if change == "eye": args["eye"] = "right"
    if change == "size": args["width"] = 2160
    if change == "frame": args["frame"] = FrameIdentity("fixture", 18, 123456)
    if change == "session": args["frame"] = FrameIdentity("other", 17, 123456)
    if change == "time": args["frame"] = FrameIdentity("fixture", 17, 123457)
    with pytest.raises(ValueError, match="ownership"):
        projection_residuals(result, ImagePoints(**args))


def test_residuals_report_measured_minus_expected_without_snapping():
    frame = context()
    result = project_source_points([[0, 0, -2]], frame)
    np.testing.assert_allclose(projection_residuals(result, measured([[50, 39]], frame)), [[.5, -.5]])


def test_final_pixels_cannot_be_unprojected_with_application_camera():
    frame = context()
    with pytest.raises(ValueError, match="ownership"):
        unproject_application_depth(measured([[30, 20]], frame, space=FINAL_SWAPCHAIN),
                                    [.5], frame, near_m=.1, far_m=10)


@pytest.mark.parametrize("field,value", [("source", "final_swapchain"), ("submitted", False),
                                         ("xr_end_frame_succeeded", False)])
def test_journal_rejects_unsubmitted_or_wrong_source_rows(field, value):
    row = journal(); row[field] = value
    with pytest.raises(ValueError): context(row)


def test_journal_rejects_unrendered_or_duplicate_eye_and_does_not_mutate_input():
    row = journal(); saved = copy.deepcopy(row)
    context(row)
    assert row == saved
    row["eyes"][0]["rendered"] = False
    with pytest.raises(ValueError): context(row)
    row = journal(); row["eyes"].append(copy.deepcopy(row["eyes"][0]))
    with pytest.raises(ValueError): context(row)


def test_capture_evidence_uses_its_own_eye_and_state_not_observer_head():
    row = journal()
    evidence = {"source": "application_swapchain", "xr_end_frame_succeeded": True,
                "eyes": row["eyes"], "state": {"session": "capture", "frame": 9,
                "predicted_display_time": 456, "presentation": presentation(),
                "head_position": [99, 99, 99]}}
    frame = ApplicationFrame.from_capture_evidence(evidence, "left")
    assert frame.identity == FrameIdentity("capture", 9, 456)
    np.testing.assert_allclose(project_source_points([[0, 0, -2]], frame).image.xy, [[49.5, 39.5]])


@pytest.mark.parametrize("kind", ["quaternion", "nan", "fov", "matrix", "scale"])
def test_malformed_geometry_fails_closed(kind):
    row = journal()
    if kind == "quaternion": row["eyes"][0]["orientation_xyzw"] = [0, 0, 0, 0]
    if kind == "nan": row["eyes"][0]["position"][0] = float("nan")
    if kind == "fov": row["eyes"][0]["fov_left_right_up_down"][0] = math.pi/2
    if kind == "matrix": row["presentation"]["model_to_tracking_rows"][3][0] = 1
    if kind == "scale": row["presentation"]["normalization_model_per_nm"] = 0
    with pytest.raises(ValueError): context(row)


def test_readonly_result_and_input_array_do_not_alias():
    frame = context(); xy = np.array([[1., 2.]])
    points = measured(xy, frame); xy[0, 0] = 9
    assert points.xy[0, 0] == 1
    with pytest.raises(ValueError): points.xy[0, 0] = 8


def test_predicted_display_time_preserves_signed_openxr_epoch():
    row = journal(); row["predicted_display_time_ns"] = -123
    assert context(row).identity.predicted_display_time_ns == -123
    for invalid in (-(1 << 63)-1, 1 << 63, True, 1.5):
        with pytest.raises(ValueError): FrameIdentity("fixture", 1, invalid)
