import copy
import json

import pytest

from tools.vr_tracking.temporal import compare_temporal_motion


def reports(tmp_path):
    tracked = {"schema": 1, "coordinate_space": "final_swapchain_distorted", "frames": []}
    identities = {"schema": 1, "coordinate_space": tracked["coordinate_space"],
                  "request": 17, "session": "42-1234", "frames": []}
    # Two held images followed by one new image displaced eight pixels.
    for i, (app, x) in enumerate(((10, 20), (10, 20), (11, 28), (11, 28))):
        source = {"coordinate_space": tracked["coordinate_space"], "width": 100, "height": 80,
                  "eye_rectangles": {"left": [0, 0, 100, 80]}, "rgb_sha256": str(i)*64,
                  "provenance": {"request": 17, "index": i, "present": 100+i}}
        tracked["frames"].append({"source": source, "groups": {"left": {"matches": [
            {"landmark_id": "molecule", "eye": "left", "status": "tracked", "position_xy": [x, 30]}]}}})
        identities["frames"].append({"source": copy.deepcopy(source), "host_present_enter_ns": 1000+11*i,
                                     "eyes": {"left": {"status": "joined", "identity": {
                                         "frame": app, "eye": "left", "session": identities["session"]}}}})
    a, b = tmp_path/"tracking.json", tmp_path/"identities.json"

    def save():
        a.write_text(json.dumps(tracked)); b.write_text(json.dumps(identities))

    save()
    return a, b, tracked, identities, save


def test_measured_hold_jump_is_conditioned_on_exact_image_identity(tmp_path):
    a, b, *_ = reports(tmp_path)
    result = compare_temporal_motion(a, b)
    assert [r["image_transition"] for r in result["transitions"]] == ["reused", "advanced", "reused"]
    summary = result["summary"]["left"]["molecule"]
    assert summary["reused"]["count"] == 2
    assert summary["reused"]["max_distance_px"] == 0
    assert summary["advanced"]["median_distance_px"] == 8


@pytest.mark.parametrize("change", ["unknown", "rejected", "missing", "nonadjacent"])
def test_incomplete_evidence_is_not_inferred(tmp_path, change):
    a, b, tracked, ids, save = reports(tmp_path)
    if change == "unknown": ids["frames"][1]["eyes"]["left"]["status"] = "unknown"
    if change == "rejected": tracked["frames"][1]["groups"]["left"]["matches"][0]["status"] = "ambiguous"
    if change == "missing": tracked["frames"].pop(1)
    if change == "nonadjacent":
        ids["frames"].pop(1); tracked["frames"].pop(1)
    save()
    result = compare_temporal_motion(a, b)
    assert all(not r["landmarks"] for r in result["transitions"] if r["capture_index"] <= 2)
    assert result["summary"]["left"]["molecule"]["reused"]["count"] == 1


@pytest.mark.parametrize("change", ["pixels", "eye_rectangles", "request", "duplicate", "reorder"])
def test_mixed_or_ambiguous_sources_fail_closed(tmp_path, change):
    a, b, tracked, ids, save = reports(tmp_path)
    if change == "pixels": tracked["frames"][1]["source"]["rgb_sha256"] = "f"*64
    if change == "eye_rectangles": tracked["frames"][1]["source"]["eye_rectangles"]["left"][2] = 99
    if change == "request": ids["frames"][1]["source"]["provenance"]["request"] = 18
    if change == "duplicate": tracked["frames"].append(copy.deepcopy(tracked["frames"][0]))
    if change == "reorder": ids["frames"].reverse()
    save()
    with pytest.raises(ValueError): compare_temporal_motion(a, b)


@pytest.mark.parametrize("field,value", [("session", "42-9999"), ("eye", "right"),
                                         ("frame", True), ("frame", -1),
                                         ("frame", 1 << 64), ("frame", 10.0)])
def test_inconsistent_joined_identity_rejected_even_in_first_frame(tmp_path, field, value):
    a, b, _, ids, save = reports(tmp_path)
    ids["frames"][0]["eyes"]["left"]["identity"][field] = value
    save()
    with pytest.raises(ValueError, match="Joined identity"):
        compare_temporal_motion(a, b)
