"""Basic duplex propagator — pure-logic tests (no MD, no torch).

Pins the parts that must be correct independent of any trajectory: pair formation
respects segment boundaries, minimum-image kills box-wrap jumps, the velocity-Verlet
fit recovers known coefficients, and evaluate() scores a synthetic dataset sanely.
"""
import json

import numpy as np

from backend.ml.propagator import baseline as B


def test_pair_indices_never_cross_a_segment_boundary():
    # 8 frames, two segments starting at 0 and 5 → within-segment pairs only.
    idx = B._pair_indices(8, np.array([0, 5]))
    assert list(idx) == [0, 1, 2, 3, 5, 6]   # 4→5 (boundary) excluded


def test_pair_indices_stride_stays_within_segments():
    # stride 2 over the same layout: pairs (t, t+2) must not cross the 5-boundary.
    idx = B._pair_indices(8, np.array([0, 5]), stride=2)
    assert list(idx) == [0, 1, 2, 5]   # seg0: 0,1,2 (3→5 excluded); seg1: 5 (6→8 excluded)


def test_min_image_removes_full_box_jump():
    box = np.array([50.0, 50.0, 50.0])
    disp = np.array([[0.3, -0.2, 0.1], [49.6, 0.0, 0.0]])  # 2nd atom wrapped a full box
    out = B._min_image(disp, box)
    assert np.allclose(out[0], [0.3, -0.2, 0.1])
    assert np.allclose(out[1], [-0.4, 0.0, 0.0], atol=1e-5)


def test_min_image_noop_without_box():
    disp = np.array([[1.0, 2.0, 3.0]])
    assert np.allclose(B._min_image(disp, np.zeros(3)), disp)


def test_fit_recovers_known_coefficients():
    rng = np.random.default_rng(0)
    vel = rng.normal(size=(500, 3))
    acc = rng.normal(size=(500, 3))
    disp = 0.31 * vel + 0.047 * acc
    a, b = B.fit_verlet(disp, vel, acc)
    assert abs(a - 0.31) < 1e-6
    assert abs(b - 0.047) < 1e-6


def test_per_element_fit_specializes_by_element():
    rng = np.random.default_rng(1)
    z = np.array([1, 1, 8, 8])                    # two H, two O
    velP = rng.normal(size=(200, 4, 3))
    accP = np.zeros_like(velP)
    # H moves at 0.01·v (fast vibration), O at 0.2·v — the exact real-data pattern.
    dispP = np.where((z == 1)[None, :, None], 0.01 * velP, 0.2 * velP)
    coeffs = B.fit_verlet_per_element(dispP, velP, accP, z)
    assert abs(coeffs[1][0] - 0.01) < 1e-6
    assert abs(coeffs[8][0] - 0.20) < 1e-6


def _write_synthetic_dataset(tmp_path, a=0.3, b=0.05, n_frames=60, n_atoms=8):
    rng = np.random.default_rng(2)
    vel = rng.normal(size=(n_frames, n_atoms, 3)).astype(np.float32)
    frc = rng.normal(size=(n_frames, n_atoms, 3)).astype(np.float32)
    mass = np.ones(n_atoms, np.float32)
    # disp = a·v + b·(f/m); positions are the running sum so within-segment pairs
    # reproduce disp exactly.
    disp = a * vel + b * frc
    pos = np.cumsum(np.concatenate([np.zeros((1, n_atoms, 3), np.float32), disp[:-1]]), axis=0)
    npz = tmp_path / "syn.npz"
    np.savez_compressed(
        npz, positions=pos.astype(np.float32), velocities=vel, forces=frc,
        z=np.ones(n_atoms, np.int16), mass=mass, charge=np.zeros(n_atoms, np.float32),
        resid=np.ones(n_atoms, np.int32), bonds=np.zeros((0, 2), np.int32),
        segment_starts=np.array([0], np.int32), box_ang=np.zeros(3, np.float32))
    (tmp_path / "dataset_manifest.json").write_text(json.dumps({"dt_fs": 20.0}))
    return npz


def test_evaluate_scores_a_learnable_synthetic_dataset(tmp_path):
    npz = _write_synthetic_dataset(tmp_path)
    m = B.evaluate(npz)
    # The fitted model reproduces disp exactly → near-zero RMSE, ~perfect skill.
    assert m["one_step_rmse_A"]["fitted_verlet_global"] < 1e-4
    assert m["skill_vs_zero_motion"]["global"] > 0.99
    assert abs(m["fit_coeffs"]["a_vel"] - 0.3) < 1e-3
