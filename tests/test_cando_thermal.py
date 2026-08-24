"""CanDo-parity 298 K normal-mode fluctuation ensemble."""

import json
import struct

import numpy as np
from scipy.sparse import diags


def test_thermal_nma_is_deterministic_and_matches_reported_rmsf():
    from backend.physics.fem_solver import compute_thermal_nma

    # One six-DOF node plus a second: six near-zero rigid modes followed by a
    # well-conditioned elastic spectrum.  A large ensemble makes the sampled
    # translational variance converge to the RMSF computed from the same modes.
    K = diags([1e-8] * 6 + [2.0, 3.0, 4.0, 5.0, 6.0, 7.0], format="csr")
    rmsf, frames = compute_thermal_nma(
        K, 2, n_modes=4, n_rigid=6, n_frames=12000, seed=7
    )
    rmsf2, frames2 = compute_thermal_nma(
        K, 2, n_modes=4, n_rigid=6, n_frames=12000, seed=7
    )

    assert frames.shape == (12000, 12)
    assert np.array_equal(frames, frames2)
    assert np.array_equal(rmsf, rmsf2)
    sampled = np.sqrt(
        np.sum(np.var(frames.reshape(-1, 2, 6)[:, :, :3], axis=0), axis=1)
    )
    assert np.allclose(sampled, rmsf, rtol=0.04, atol=0.01)


def test_runner_caches_compact_thermal_payload(tmp_path):
    from backend.core.cando_job import new_cando_job
    from backend.core.cando_runner import (
        _cache_fem_analysis,
        load_thermal_representative,
        load_thermal_trajectory,
    )

    job = new_cando_job("thermal")
    job_dir = job.job_dir(tmp_path)
    job_dir.mkdir(parents=True)
    payload = {
        "solver": "linear",
        "positions": [],
        "thermal_trajectory": {
            "kind": "normal-mode-ensemble",
            "temperature_k": 298.0,
            "keys": [["h0", 0, "FORWARD", 0]],
            "frames": [[1.0, 2.0, 3.0]],
            "n_frames": 1,
            "representative_frame": 0,
            "representative_positions": [
                {
                    "helix_id": "h0",
                    "bp_index": 0,
                    "direction": "FORWARD",
                    "copy": 0,
                    "backbone_position": [1.0, 2.0, 3.0],
                    "nx": 1.0,
                    "ny": 0.0,
                    "nz": 0.0,
                    "tx": 0.0,
                    "ty": 0.0,
                    "tz": 1.0,
                }
            ],
            "representative_axis": [
                {
                    "helix_id": "h0",
                    "bp_index": 0,
                    "position": [0.0, 0.0, 0.0],
                }
            ],
        },
    }
    _cache_fem_analysis(job, job_dir, payload)

    cached = load_thermal_trajectory(job_dir)
    assert cached == payload["thermal_trajectory"]
    assert json.loads((job_dir / "thermal_trajectory.json").read_text()) == cached
    representative = load_thermal_representative(job_dir)
    assert representative == {
        key: payload["thermal_trajectory"][key]
        for key in (
            "kind",
            "temperature_k",
            "n_frames",
            "representative_frame",
            "representative_positions",
            "representative_axis",
        )
    }
    assert "frames" not in representative and "keys" not in representative
    assert (
        json.loads((job_dir / "thermal_representative.json").read_text())
        == representative
    )
    assert (job_dir / "thermal_representative.bin").read_bytes()


def test_representative_binary_is_columnar_float32_with_exact_identity_metadata():
    from backend.core.cando_runner import pack_thermal_representative_bin

    payload = {
        "kind": "normal-mode-ensemble",
        "temperature_k": 298.0,
        "n_frames": 48,
        "representative_frame": 14,
        "representative_positions": [
            {
                "helix_id": "h0",
                "bp_index": -2,
                "direction": "REVERSE",
                "copy": 3,
                "backbone_position": [1.25, -2.5, 3.75],
                "nx": 0.0,
                "ny": 1.0,
                "nz": 0.0,
                "tx": 0.0,
                "ty": 0.0,
                "tz": 1.0,
            }
        ],
        "representative_axis": [
            {"helix_id": "h0", "bp_index": -2, "position": [4.0, 5.0, 6.0]}
        ],
    }
    buf = pack_thermal_representative_bin(payload)
    magic, version, n_pos, n_axis, n_helix, header_len = struct.unpack_from(
        "<IIIIII", buf
    )
    assert magic == 0x4D524643  # little-endian bytes spell "CFRM"
    assert (version, n_pos, n_axis, n_helix) == (1, 1, 1, 1)
    header = json.loads(buf[24 : 24 + header_len])
    assert header == {
        "kind": "normal-mode-ensemble",
        "temperature_k": 298.0,
        "n_frames": 48,
        "representative_frame": 14,
        "helix_ids": ["h0"],
    }
    offset = 24 + header_len
    offset += (-offset) % 4
    identity = struct.unpack_from("<IiiI", buf, offset)
    coords = struct.unpack_from("<9f", buf, offset + 16)
    assert identity == (0, -2, 3, 1)
    assert np.allclose(coords, [1.25, -2.5, 3.75, 0, 1, 0, 0, 0, 1])
    axis_offset = offset + 52
    assert struct.unpack_from("<Ii", buf, axis_offset) == (0, -2)
    assert np.allclose(struct.unpack_from("<3f", buf, axis_offset + 8), [4, 5, 6])
    assert len(buf) == axis_offset + 20
