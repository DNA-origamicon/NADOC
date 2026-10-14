import hashlib
import json

import pytest

from tools.vr_tracking.gpu_timing import summarize_gpu_passes


def sample(frame=1, host=1000, **changes):
    row = dict(frame=frame, host_begin_monotonic_ns=host, host_collected_monotonic_ns=host+100,
               valid=1, reason="observed", view_tools_version=9, view_tools_flags=2304,
               menu_open=0, shadow_scope="canonical", shadow_calls=1, motion_detail_reduced=0,
               left_calls=1, right_calls=1, boundaries=4, first_eye=1, second_eye=0,
               timestamp0_ns=100, timestamp1_ns=2000100, timestamp2_ns=7000100, timestamp3_ns=13000100,
               shadow_ns=2000000, right_ns=5000000, left_ns=6000000, total_ns=13000000)
    row.update(changes)
    return "VR_GPU_PASS " + " ".join(f"{k}={v}" for k, v in row.items())


def status(completed, **changes):
    values = dict(completed_frames=completed, attempted_frames=completed, issued_frames=completed,
                  valid_frames=completed, invalid_frames=0, ring_full_frames=0, unsupported_frames=0,
                  sink_failures=0, shutdown_unobserved_frames=0,
                  record_delivery="existing bounded TraceSink; VR_TRACE_DROPPED invalidates coverage")
    values.update(changes)
    return "VR_GPU_PASS_STATUS phase=shutdown status=" + json.dumps(values)


def write(tmp_path, *lines):
    path = tmp_path / "viewer.log"
    path.write_text("\n".join(lines)+"\n")
    return path


def test_exact_passes_actual_eye_order_and_source_hash(tmp_path):
    path = write(tmp_path, sample(), sample(2, 2000), status(2))
    report = summarize_gpu_passes(path)
    assert report["source"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert report["coverage"]["full_log_complete"]
    assert report["passes_ms"]["left"]["median"] == 6
    assert report["passes_ms"]["right"]["median"] == 5
    assert report["passes_ms"]["shadow"]["median"] == 2
    assert report["passes_ms"]["total"]["median"] == 13
    assert report["records"]["genuine_trace_dropped_total"] == 0
    assert "not pure GPU busy time" in report["limits"][0]


def test_host_submission_membership_is_trimmed_half_open(tmp_path):
    path = write(tmp_path, *(sample(i+1, host) for i, host in enumerate((1099, 1100, 1899, 1900))), status(4))
    report = summarize_gpu_passes(path, start_ns=1000, end_ns=2000, boundary_exclusion_ns=100)
    assert report["coverage"]["selected_valid_unique_records"] == 2
    assert report["coverage"]["first_selected_frame"] == 2
    assert report["coverage"]["last_selected_frame"] == 3


@pytest.mark.parametrize("line", [
    "other stdout " + sample(), sample() + " VR_GPU_TRACE epoch_ms=12 gpu_ms=4",
    sample().replace("left_ns=6000000", "left_ns=5000000"),
    sample().replace("timestamp1_ns=2000100", "timestamp1_ns=10"),
    sample()+" frame=2", sample().replace("valid=1", "valid=3"),
])
def test_interleaving_and_invalid_receipts_are_explicitly_rejected(tmp_path, line):
    report = summarize_gpu_passes(write(tmp_path, line, status(1)))
    assert report["records"]["candidate_pass_records"] == 1
    assert len(report["records"]["rejected"]) == 1
    assert report["records"]["rejected"][0]["line"] == 1
    assert report["coverage"]["selected_valid_unique_records"] == 0
    assert not report["coverage"]["full_log_complete"]


def test_true_dropped_trace_differs_from_status_documentation(tmp_path):
    report = summarize_gpu_passes(write(tmp_path, sample(), "VR_TRACE_DROPPED epoch_ms=123.5 count=7", status(1)))
    assert report["records"]["genuine_trace_dropped_total"] == 7
    assert len(report["records"]["genuine_trace_drop_records"]) == 1
    assert not report["coverage"]["full_log_complete"]


def test_interleaved_drop_is_unreadable_not_invented_count(tmp_path):
    report = summarize_gpu_passes(write(tmp_path, sample(), "other VR_TRACE_DROPPED epoch_ms=123.5 count=7", status(1)))
    assert report["records"]["genuine_trace_dropped_total"] == 0
    assert report["records"]["rejected"][0]["kind"] == "drop_record"


def test_all_duplicates_excluded_and_frame_gaps_are_not_refresh_drops(tmp_path):
    report = summarize_gpu_passes(write(tmp_path, sample(1), sample(2, 2000), sample(2, 2000), sample(3, 3000), status(4)))
    assert report["records"]["duplicate_frame_ids"] == {"2": 2}
    assert report["coverage"]["selected_valid_unique_records"] == 2
    assert report["coverage"]["selected_frame_id_gaps"] == [{"previous_frame": 1, "next_frame": 3, "missing_pass_frame_ids": 1}]
    assert not report["coverage"]["full_log_complete"]


def test_native_invalid_partial_receipt_remains_invalid_not_malformed(tmp_path):
    line = ("VR_GPU_PASS frame=1 host_begin_monotonic_ns=1000 host_collected_monotonic_ns=2000 "
            "valid=0 reason=incomplete_boundaries view_tools_version=9 view_tools_flags=2304 menu_open=0 "
            "shadow_scope=unknown shadow_calls=unknown motion_detail_reduced=0 left_calls=0 right_calls=0 "
            "boundaries=1 first_eye=-1 second_eye=-1 timestamp0_ns=100")
    report = summarize_gpu_passes(write(tmp_path, line, status(1, invalid_frames=1, valid_frames=0)))
    assert report["records"]["native_invalid_pass_records"] == 1
    assert report["records"]["rejected"] == []
    assert report["coverage"]["selected_valid_unique_records"] == 0


def test_query_ring_shutdown_loss_remains_visible_with_valid_window(tmp_path):
    report = summarize_gpu_passes(write(tmp_path, sample(), status(1, attempted_frames=2, shutdown_unobserved_frames=1)), start_ns=900, end_ns=1200)
    assert report["coverage"]["selected_valid_unique_records"] == 1
    assert "nonzero or unavailable shutdown_unobserved_frames" in report["coverage"]["limitations"]
    assert not report["coverage"]["full_log_complete"]


@pytest.mark.parametrize("options", [dict(start_ns=1), dict(end_ns=1), dict(start_ns=1, end_ns=2, boundary_exclusion_ns=1), dict(boundary_exclusion_ns=1), dict(start_ns=True, end_ns=10)])
def test_invalid_windows_rejected(tmp_path, options):
    with pytest.raises(ValueError):
        summarize_gpu_passes(write(tmp_path, sample(), status(1)), **options)
