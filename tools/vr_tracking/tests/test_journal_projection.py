import copy
import json
import math

import pytest

from tools.vr_tracking import journal_projection as jp


def fixtures(tmp_path):
    shape = {"session": "fixture", "scene_revision": 1, "visualization_sequence": 2,
             "coordinate_sequence": 3, "representation": "stick", "motion_detail_reduced": False,
             "view_tools": {"version": 7, "flags": 2304, "sequence": 0}}
    header = {"event": "pose_journal_start", "schema": 1, "source": "application_projection",
              "session": "fixture", "request": 1, "space": "OpenXR_LOCAL", "units": "meters",
              "clock": "CLOCK_MONOTONIC", "capture_start_monotonic_ns": 100,
              "capture_end_monotonic_ns": 200, "capacity_frames": 8192,
              "clock_mapping": "XR_KHR_convert_timespec_time"}
    row = {**shape, "event": "application_frame", "source": "application_projection", "frame": 1,
           "predicted_display_time_ns": -1, "predicted_display_monotonic_ns": 150,
           "clock_mapping": "XR_KHR_convert_timespec_time", "host_frame_start_ns": 120,
           "host_frame_end_ns": 140, "submitted": True, "xr_end_frame_succeeded": True,
           "eyes": [{"eye": "left", "width": 100, "height": 80, "position": [0, 0, 0],
                     "orientation_xyzw": [0, 0, 0, 1], "rendered": True,
                     "fov_left_right_up_down": [-math.pi/4, math.pi/4, math.pi/4, -math.pi/4]}],
           "presentation": {"model_to_tracking_rows": [[1,0,0,0],[0,1,0,0],[0,0,1,0],[0,0,0,1]],
                            "source_center_nm": [0,0,0], "normalization_model_per_nm": 1,
                            "normalized_offset_model": [0,0,0]}}
    trailer = {"event": "pose_journal_complete", "frames": 1, "overflow_frames": 0,
               "mapping_failures": 0, "complete": True}
    anchors = {"schema": 1, "coordinate_space": "application_eye_undistorted",
               "templates": [{"landmark_id": "actual_mesh", "eye": "left"}],
               "anchors": {"actual_mesh": {"source_nm": [1,1,-2], "shape_identity": shape,
                 "reference_frame": {"session": "fixture", "frame": 0, "predicted_display_time_ns": -10}}}}
    journal, anchor_path = tmp_path / "journal.jsonl", tmp_path / "anchors.json"
    def save():
        journal.write_text("".join(json.dumps(r)+"\n" for r in (header,row,trailer)))
        anchor_path.write_text(json.dumps(anchors))
    save()
    return journal, anchor_path, header, row, trailer, anchors, save


def test_native_application_projection_analytic_and_provenance(tmp_path):
    p,a,*_ = fixtures(tmp_path)
    result = jp.project_journal(p,a,"left")
    projected = result["frames"][0]["expected"]["actual_mesh"]
    assert projected["position_xy"] == pytest.approx([74.5,19.5])
    assert projected["forward_depth_m"] == 2
    assert result["frames"][0]["predicted_display_time_ns"] == -1
    assert len(result["journal_sha256"]) == 64
    assert result["final_present_association_verified"] is False
    assert result["optical_output_verified"] is False


@pytest.mark.parametrize("change", ["count", "overflow", "partial", "no_trailer", "truncated", "duplicate", "wrong_source"])
def test_incomplete_or_inconsistent_journal_rejected(tmp_path,change):
    p,a,h,r,t,anchors,save=fixtures(tmp_path)
    if change=="count":t["frames"]=2
    if change=="overflow":t["overflow_frames"]=1
    if change=="partial":t["complete"]=False
    if change=="wrong_source":r["source"]="final_swapchain"
    save()
    if change=="no_trailer":p.write_text(json.dumps(h)+"\n"+json.dumps(r)+"\n")
    if change=="truncated":p.write_text(p.read_text().rstrip())
    if change=="duplicate":
        t["frames"]=2;p.write_text("".join(json.dumps(v)+"\n" for v in [h,r,r,t]))
    with pytest.raises(ValueError):jp.project_journal(p,a,"left")


@pytest.mark.parametrize("change", ["session", "representation", "coordinate_sequence", "flags"])
def test_changed_shape_keeps_explicit_unavailable_result(tmp_path,change):
    p,a,h,r,t,anchors,save=fixtures(tmp_path)
    if change=="session":h["session"]="another"
    elif change=="flags":r["view_tools"]=dict(r["view_tools"],flags=0)
    elif change=="representation":r[change]="full"
    else:r[change]=4
    save();result=jp.project_journal(p,a,"left")["frames"][0]
    assert result["status"]=="unavailable"
    assert result["expected"]["actual_mesh"]["reason"]=="geometry_representation_or_session_changed_reanchor_required"


@pytest.mark.parametrize("change", ["submitted", "xr_end_frame_succeeded", "rendered"])
def test_invalid_application_rows_are_explicitly_retained(tmp_path,change):
    p,a,h,r,t,anchors,save=fixtures(tmp_path)
    if change=="rendered":r["eyes"][0][change]=False
    else:r[change]=False
    save();frames=jp.project_journal(p,a,"left")["frames"]
    assert len(frames)==1 and frames[0]["status"]=="unavailable"
    assert not frames[0]["expected"]


def test_unavailable_clock_remains_null_not_a_guessed_mapping(tmp_path):
    p,a,h,r,t,anchors,save=fixtures(tmp_path)
    r.update(clock_mapping="unavailable",predicted_display_monotonic_ns=None)
    t["mapping_failures"]=1
    save();assert jp.project_journal(p,a,"left")["frames"][0]["predicted_display_monotonic_ns"] is None
    r["predicted_display_monotonic_ns"]=150;save()
    with pytest.raises(ValueError,match="fabricated"):jp.project_journal(p,a,"left")


@pytest.mark.parametrize("change", ["space", "eye", "nan", "missing_owner", "duplicate_owner", "reference_session"])
def test_invalid_anchor_ownership_rejected(tmp_path,change):
    p,a,h,r,t,anchors,save=fixtures(tmp_path)
    if change=="space":anchors["coordinate_space"]="final_swapchain_distorted"
    if change=="eye":anchors["templates"][0]["eye"]="right"
    if change=="nan":anchors["anchors"]["actual_mesh"]["source_nm"][0]=float("nan")
    if change=="missing_owner":anchors["templates"]=[]
    if change=="duplicate_owner":anchors["templates"]*=2
    if change=="reference_session":anchors["anchors"]["actual_mesh"]["reference_frame"]["session"]="another"
    save()
    with pytest.raises(ValueError):jp.project_journal(p,a,"left")


def test_bounded_input_enforced_before_projection(tmp_path,monkeypatch):
    p,a,*_=fixtures(tmp_path)
    monkeypatch.setattr(jp,"MAX_BYTES",100)
    with pytest.raises(ValueError,match="bounded"):jp.project_journal(p,a,"left")


def test_missing_identity_fields_fail_closed(tmp_path):
    p,a,h,r,t,anchors,save=fixtures(tmp_path)
    del h["session"];save()
    with pytest.raises(ValueError,match="Malformed"):jp.project_journal(p,a,"left")


def test_actual_eye_model_precedence_and_behind_eye_null(tmp_path):
    p,a,h,r,t,anchors,save=fixtures(tmp_path)
    model=copy.deepcopy(r["presentation"]["model_to_tracking_rows"]);model[0][3]=1
    r["eyes"][0]["model_to_tracking_rows"]=model;save()
    assert jp.project_journal(p,a,"left")["frames"][0]["expected"]["actual_mesh"]["position_xy"]==pytest.approx([99.5,19.5])
    model[2][3]=3;save();result=jp.project_journal(p,a,"left")["frames"][0]
    assert result["expected"]["actual_mesh"]["position_xy"] is None
    json.dumps(result,allow_nan=False)
