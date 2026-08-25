from pathlib import Path
import struct
from types import SimpleNamespace

from scripts.vr_atomistic_diagnostics import (
    _benchmark_frame_indices,
    _assess_playback,
    _capture_evidence,
    _dna_prefix_atoms,
    _decode_md_atom_source_frame,
    _percentile,
    _psf_dna_prefix_indices,
    _steamvr_counter_deltas,
    _write_coordinate_frame,
)

from PIL import Image, ImageDraw
import numpy as np


def test_steamvr_counter_deltas_report_only_the_active_interval() -> None:
    before = {
        "frame_presents": 100,
        "frame_submits": 98,
        "dropped_frames": 12,
        "dropped_frames_timed_out": 10,
        "reprojected_frames": 4,
        "timed_out": 3,
    }
    after = {
        "frame_presents": 370,
        "frame_submits": 368,
        "dropped_frames": 13,
        "dropped_frames_timed_out": 10,
        "reprojected_frames": 4,
        "timed_out": 3,
    }

    interval = _steamvr_counter_deltas(before, after)

    assert interval["frame_presents"] == 270
    assert interval["frame_submits"] == 270
    assert interval["dropped_frames"] == 1
    assert interval["dropped_frames_timed_out"] == 0
    assert interval["reprojected_frames"] == 0
    assert interval["timed_out"] == 0


def test_steamvr_counter_deltas_tolerate_runtime_counter_reset() -> None:
    interval = _steamvr_counter_deltas(
        {"frame_presents": 500, "dropped_frames": 8},
        {"frame_presents": 20, "dropped_frames": 0},
    )

    assert interval["frame_presents"] == 0
    assert interval["dropped_frames"] == 0


def test_trajectory_probe_helpers_are_deterministic() -> None:
    assert _percentile([40.0, 10.0, 20.0, 30.0], 0.5) == 25.0
    indices = _benchmark_frame_indices(11_182, 9)
    assert len(indices) == 9
    assert set(indices) == {0, 1398, 2795, 4193, 5590, 6988, 8386, 9783, 11181}


def test_dna_prefix_uses_all_dna_topology_segments() -> None:
    manifest = {
        "charge_audit": {
            "topology_metadata": {
                "segments": [
                    {"segid": "D000", "n_atoms_input": 100},
                    {"segid": "D001", "n_atoms_input": 30},
                    {"segid": "W000", "n_atoms_input": 50_000},
                ]
            }
        }
    }
    assert _dna_prefix_atoms(manifest) == 130


def test_psf_heavy_prefix_excludes_hydrogen(tmp_path: Path) -> None:
    psf = tmp_path / "small.psf"
    psf.write_text(
        "PSF\n\n       4 !NATOM\n"
        "       1 D000 1 DA P  P    1.0 30.974 0\n"
        "       2 D000 1 DA H1 H    0.0  1.008 0\n"
        "       3 D000 1 DA C1 C    0.0 12.011 0\n"
        "       4 W000 1 TIP3 OH2 O 0.0 15.999 0\n"
    )
    assert _psf_dna_prefix_indices(psf, {"D000"}) == (3, [0, 2])


def test_binary_md_source_republishes_native_coordinate_frame(tmp_path: Path) -> None:
    columns = np.asarray([[1, 4], [2, 5], [3, 6]], dtype="<f4")
    raw = struct.pack("<8sIIIIId", b"NADOCMDA", 1, 36, 4, 8, 2, 80.0)
    raw += columns.tobytes()

    message, xyz = _decode_md_atom_source_frame(raw)
    assert message == {
        "type": "frame", "frame_idx": 4, "n_frames": 8, "time_ps": 80.0,
    }
    np.testing.assert_array_equal(xyz, [[1, 2, 3], [4, 5, 6]])

    output = tmp_path / "frame.coordinates.bin"
    assert _write_coordinate_frame(
        output, xyz, sequence=9, frame_idx=4, n_frames=8
    ) == 2
    written = output.read_bytes()
    assert struct.unpack_from("<8sIIQIII", written) == (
        b"NVRCOORD", 1, 36, 9, 4, 8, 2,
    )
    np.testing.assert_array_equal(
        np.frombuffer(written, dtype="<f4", offset=36).reshape(2, 3), xyz
    )


def test_capture_evidence_rejects_uniform_images_and_accepts_sparse_geometry(
    tmp_path: Path,
) -> None:
    names = (
        "trajectory_ballstick_unobstructed.png",
        "trajectory_stick_unobstructed.png",
        "trajectory_full_unobstructed.png",
        "trajectory_ballstick_return_unobstructed.png",
    )
    for name in names:
        Image.new("RGB", (320, 180), (4, 6, 11)).save(tmp_path / name)
    assert not _capture_evidence(tmp_path)["passed"]

    for name in names:
        image = Image.new("RGB", (320, 180), (4, 6, 11))
        ImageDraw.Draw(image).rectangle((130, 60, 190, 120), fill=(255, 100, 30))
        image.save(tmp_path / name)
    assert _capture_evidence(tmp_path)["passed"]


def test_playback_assessment_combines_all_evidence(tmp_path: Path) -> None:
    viewer = tmp_path / "viewer.log"
    viewer.write_text(
        "ScryWrite Witness PASSED at frame 900\n"
        + "\n".join(
            "VR_METRIC event=process_progress phase=visualization_update "
            f"sequence={index} sequence_gap=0 parse_ms=1 apply_upload_ms=2 total_ms=3"
            for index in range(1, 11)
        )
        + "\nVR_METRIC event=process_progress phase=frame_timing "
        "runtime_period_ms=11.111 scene_p95_ms=4\n"
    )
    producer = tmp_path / "producer.jsonl"
    producer.write_text(
        '{"event":"process_end","phase":"md_playback","status":"ok",'
        '"deadline_misses":0}\n'
    )
    steamvr = tmp_path / "steamvr.jsonl"
    steamvr.write_text(
        '{"event":"process_end","phase":"steamvr_stats","assessment":{'
        '"active_headset_sample":true,"no_interval_drops":true,'
        '"no_interval_reprojection":true,"app_cpu_within_90hz":true,'
        '"app_gpu_within_90hz":true}}\n'
    )

    class Metrics:
        def emit(self, *_args, **_kwargs):
            pass

    result = _assess_playback(
        SimpleNamespace(
            viewer_log=viewer, producer_metrics=producer,
            steamvr_metrics=steamvr, target_hmd_hz=90.0, min_updates=10,
        ),
        Metrics(),
    )
    assert result["status"] == "pass"
    assert all(result["checks"].values())
