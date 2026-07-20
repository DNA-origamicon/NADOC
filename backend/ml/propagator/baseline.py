"""Basic duplex propagator + evaluation (numpy, no torch).

Answers the reframed MVP question — *how well can we predict short-time duplex
fluctuations one step ahead?* — with real numbers, and establishes the reference
the eventual equivariant GNN must beat.

Model. The simplest rotation-equivariant per-atom step is velocity-Verlet-shaped:

    Δx_i  ≈  a · v_i  +  b · (f_i / m_i)

with SCALAR coefficients (any rotation-equivariant linear vector→vector map is a
scalar), optionally per chemical element. Fitting `a, b` by least squares recovers an
integrator from the data; `a` also empirically confirms the NAMD velocity unit scale
(`a ≈ (20.45482706/1000)·dt_fs` if velocities are in NAMD velDCD units and Δx in Å).

Benchmarks reported against two dumb references:
  * zero-motion  (Δx = 0)          — the "nothing moves" floor
  * inertial     (Δx = v·dt)        — pure ballistic, physical units

Evaluation is a TEMPORAL split: coefficients fit on early frames, error measured on
held-out later frames (same duplex, unseen fluctuations). Pairs are formed only WITHIN
a captured segment (clean dt). A short teacher-forced rollout (true v,f fed each step)
bounds the position-integration drift; a free-running rollout needs learned velocity +
force prediction — that's the GNN phase, deferred.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

NAMD_VEL_TO_A_PER_PS = 20.45482706


def load_dataset(npz_path: str | Path) -> dict:
    npz_path = Path(npz_path)
    d = dict(np.load(npz_path))
    manifest = json.loads((npz_path.parent / "dataset_manifest.json").read_text())
    d["dt_fs"] = manifest["dt_fs"]
    d["manifest"] = manifest
    return d


def _pair_indices(n_frames: int, segment_starts: np.ndarray, stride: int = 1) -> np.ndarray:
    """All (t, t+stride) frame indices within a single captured segment.

    ``stride`` coarsens the macrostep: the captured cadence is dt_fs, so stride k
    predicts displacement over k·dt_fs — lets us sweep macrostep on existing data by
    subsampling (never interpolating), never crossing a segment boundary."""
    starts = list(segment_starts) + [n_frames]
    idx = []
    for a, b in zip(starts[:-1], starts[1:]):
        idx.extend(range(a, b - stride))
    return np.array(idx, dtype=np.int64)


def _min_image(disp: np.ndarray, box: np.ndarray) -> np.ndarray:
    """Wrap displacements into [-L/2, L/2] per axis so a boundary atom that NAMD
    wrapAll flipped by a full box length doesn't register a spurious jump."""
    b = np.asarray(box, dtype=np.float64)
    if b.shape != (3,) or not np.all(b > 0):
        return disp
    return (disp - b * np.round(disp / b)).astype(disp.dtype)


def build_pairs(data: dict, stride: int = 1) -> dict:
    pos, vel, frc = data["positions"], data["velocities"], data["forces"]
    box = data.get("box_ang", np.zeros(3, np.float32))
    t = _pair_indices(pos.shape[0], data["segment_starts"], stride)
    return {
        "disp": _min_image(pos[t + stride] - pos[t], box).reshape(-1, 3),   # Å
        "vel":  vel[t].reshape(-1, 3),                          # NAMD velDCD units
        "acc":  (frc[t] / data["mass"][None, :, None]).reshape(-1, 3),  # f/m
        "pair_frames": t,
        "n_atoms": pos.shape[1],
    }


def _rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.sum((a - b) ** 2, axis=-1))))


def fit_verlet(disp: np.ndarray, vel: np.ndarray, acc: np.ndarray) -> tuple[float, float]:
    """Least-squares scalars for Δx ≈ a·v + b·(f/m), stacking the 3 components."""
    X = np.stack([vel.reshape(-1), acc.reshape(-1)], axis=1)   # [3M, 2]
    y = disp.reshape(-1)                                        # [3M]
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return float(coef[0]), float(coef[1])


def fit_verlet_per_element(dispP, velP, accP, z) -> dict:
    """Per-element (a_z, b_z): H vs heavy atoms decorrelate very differently over a
    macrostep (fast C–H stretch vs slow backbone), so a per-element coefficient is a
    cheap, still-equivariant win over one global scalar pair. Inputs are [P, N, 3]."""
    coeffs = {}
    for zz in np.unique(z):
        m = z == zz
        coeffs[int(zz)] = fit_verlet(
            dispP[:, m].reshape(-1, 3), velP[:, m].reshape(-1, 3), accP[:, m].reshape(-1, 3))
    return coeffs


def predict_per_element(velP, accP, z, coeffs) -> np.ndarray:
    pred = np.zeros_like(velP)
    for zz, (a, b) in coeffs.items():
        m = z == zz
        pred[:, m] = a * velP[:, m] + b * accP[:, m]
    return pred


def evaluate(npz_path: str | Path, *, train_frac: float = 0.7, stride: int = 1) -> dict:
    """Fit on the early fraction of pairs, report errors on the held-out tail.

    ``stride`` coarsens the macrostep to ``stride × dt_fs`` (subsampling the captured
    frames) — used by :func:`macrostep_sweep` to quantify skill vs step size."""
    data = load_dataset(npz_path)
    pairs = build_pairs(data, stride)
    disp, vel, acc = pairs["disp"], pairs["vel"], pairs["acc"]
    dt_fs = data["dt_fs"] * stride

    # Reshape to [n_pairs, n_atoms, 3] so the split is temporal (by pair), not by atom.
    n_atoms = pairs["n_atoms"]
    P = disp.shape[0] // n_atoms
    dispP = disp.reshape(P, n_atoms, 3)
    velP = vel.reshape(P, n_atoms, 3)
    accP = acc.reshape(P, n_atoms, 3)
    k = max(1, int(P * train_frac))
    tr = slice(0, k); te = slice(k, P)

    z = data["z"]
    a, b = fit_verlet(dispP[tr].reshape(-1, 3), velP[tr].reshape(-1, 3), accP[tr].reshape(-1, 3))
    a_vonly, _ = fit_verlet(dispP[tr].reshape(-1, 3), velP[tr].reshape(-1, 3),
                            np.zeros_like(accP[tr].reshape(-1, 3)))
    elem_coeffs = fit_verlet_per_element(dispP[tr], velP[tr], accP[tr], z)

    d_te = dispP[te]
    zero = np.zeros_like(d_te)
    inertial_a = (NAMD_VEL_TO_A_PER_PS / 1000.0) * dt_fs        # v(Å/fs)·dt(fs), correct units
    pred_inertial = inertial_a * velP[te]
    pred_fit = a * velP[te] + b * accP[te]
    pred_elem = predict_per_element(velP[te], accP[te], z, elem_coeffs)

    rms_disp = float(np.sqrt(np.mean(np.sum(d_te ** 2, axis=-1))))
    out = {
        "npz": str(npz_path),
        "n_pairs_total": P, "n_train_pairs": k, "n_test_pairs": P - k,
        "n_atoms": n_atoms, "dt_fs": dt_fs,
        "mean_true_step_displacement_A": rms_disp,
        "fit_coeffs": {"a_vel": a, "b_acc": b, "a_vel_only": a_vonly},
        "elem_coeffs": {str(zz): {"a": ab[0], "b": ab[1]} for zz, ab in elem_coeffs.items()},
        # Ballistic v·dt (correct NAMD units) OVERSHOOTS: a_vel_only ≪ ballistic a
        # because stiff-bond vibration (C–H stretch ~10 fs) reverses motion within the
        # 20 fs step, so instantaneous velocity poorly predicts net displacement.
        "velocity_regime": {
            "fitted_a_vel_only": a_vonly,
            "ballistic_a": inertial_a,
            "fitted_over_ballistic": (a_vonly / inertial_a) if inertial_a else None,
        },
        "one_step_rmse_A": {
            "zero_motion": _rmse(zero, d_te),
            "inertial_vdt": _rmse(pred_inertial, d_te),
            "fitted_verlet_global": _rmse(pred_fit, d_te),
            "fitted_verlet_per_element": _rmse(pred_elem, d_te),
        },
    }
    # Skill of each learned model vs the zero-motion floor (variance-reduction style).
    e0 = out["one_step_rmse_A"]["zero_motion"]
    out["skill_vs_zero_motion"] = {
        "global": (1.0 - out["one_step_rmse_A"]["fitted_verlet_global"] / e0) if e0 else None,
        "per_element": (1.0 - out["one_step_rmse_A"]["fitted_verlet_per_element"] / e0) if e0 else None,
    }
    out["rollout"] = _teacher_forced_rollout(data, a, b)
    return out


def _teacher_forced_rollout(data: dict, a: float, b: float, *, max_steps: int = 50) -> dict:
    """Integrate Δx = a·v + b·(f/m) forward using TRUE v,f each step, within the last
    captured segment; report position RMSD vs the true trajectory over the horizon.
    Bounds the position-update error (a free-running rollout needs learned v,f)."""
    pos, vel, frc, mass = (data["positions"], data["velocities"],
                           data["forces"], data["mass"])
    box = data.get("box_ang", np.zeros(3, np.float32))
    starts = list(data["segment_starts"]) + [pos.shape[0]]
    s0, s1 = starts[-2], starts[-1]
    horizon = min(max_steps, s1 - s0 - 1)
    if horizon < 1:
        return {"horizon": 0, "rmsd_A": []}
    x = pos[s0].copy()
    rmsd = []
    for j in range(horizon):
        acc = frc[s0 + j] / mass[:, None]
        x = x + a * vel[s0 + j] + b * acc
        err = _min_image(x - pos[s0 + j + 1], box)
        rmsd.append(float(np.sqrt(np.mean(np.sum(err ** 2, axis=-1)))))
    return {"horizon": horizon, "rmsd_A": rmsd, "final_rmsd_A": rmsd[-1]}


def report(npz_path: str | Path) -> dict:
    """Evaluate + pretty-print a one-screen summary; returns the metrics dict."""
    m = evaluate(npz_path)
    rl = m["rollout"]
    print(f"=== basic duplex propagator — {Path(npz_path).name} ===")
    print(f"atoms={m['n_atoms']}  pairs={m['n_pairs_total']} "
          f"(train {m['n_train_pairs']}/test {m['n_test_pairs']})  dt={m['dt_fs']:.1f} fs")
    print(f"mean true one-step displacement: {m['mean_true_step_displacement_A']:.4f} Å")
    vr = m["velocity_regime"]
    print(f"velocity regime: fitted a={vr['fitted_a_vel_only']:.4g} vs ballistic "
          f"a={vr['ballistic_a']:.4g}  (fitted/ballistic={vr['fitted_over_ballistic']:.3f} "
          f"→ sub-ballistic: stiff-bond vibration within the step)")
    print("one-step RMSE (Å):")
    for k, v in m["one_step_rmse_A"].items():
        print(f"    {k:28s} {v:.4f}")
    sk = m["skill_vs_zero_motion"]
    print(f"skill vs zero-motion: global {sk['global']:.3f}  per-element {sk['per_element']:.3f}")
    print("per-element vel coeff a (Z→a): "
          + "  ".join(f"{z}:{c['a']:.3g}" for z, c in m["elem_coeffs"].items()))
    if rl["horizon"]:
        print(f"teacher-forced rollout: {rl['horizon']} steps, "
              f"final position RMSD {rl['final_rmsd_A']:.4f} Å")
    return m


def macrostep_sweep(npz_path: str | Path, strides=(1, 2, 3, 5, 10)) -> list[dict]:
    """Skill vs macrostep, coarsening the existing trajectory by subsampling (no new
    MD). Answers 'how much does the 20 fs step itself cost us?' — as the step grows,
    velocity decorrelates further and the linear propagator's skill should collapse."""
    rows = []
    print(f"=== macrostep sweep — {Path(npz_path).name} ===")
    print(f"{'dt(fs)':>7} {'disp(Å)':>9} {'zero':>8} {'inertial':>9} "
          f"{'fit_glob':>9} {'fit_elem':>9} {'skill_elem':>10}")
    for s in strides:
        m = evaluate(npz_path, stride=s)
        r = m["one_step_rmse_A"]
        row = {
            "dt_fs": m["dt_fs"], "stride": s,
            "mean_disp_A": m["mean_true_step_displacement_A"],
            "zero": r["zero_motion"], "inertial": r["inertial_vdt"],
            "fit_global": r["fitted_verlet_global"], "fit_elem": r["fitted_verlet_per_element"],
            "skill_elem": m["skill_vs_zero_motion"]["per_element"],
        }
        rows.append(row)
        print(f"{m['dt_fs']:7.0f} {row['mean_disp_A']:9.4f} {row['zero']:8.4f} "
              f"{row['inertial']:9.4f} {row['fit_global']:9.4f} {row['fit_elem']:9.4f} "
              f"{row['skill_elem']:10.3f}")
    return rows
