"""Compare collected fixed-gold trajectories using independent-seed confidence intervals.

Collect CPU and GPU metrics with collect_fixed_gold_metrics.py on their hosts,
then pass the two derived JSON reports and the stressed-kick audit to this CLI.
Saved frames within a trajectory are correlated and are never counted as replicas.
These engineering margins do not establish experimental accuracy or equilibration.
"""

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.stats import t

MARGINS = {
    "anchor_rms_nm": 0.2,
    "tether_distance_nm": 0.25,
    "anm_rms_extension_nm": 0.05,
    "protein_rg_nm": 0.1,
    "dna_tip_radius_nm": 0.5,
    "potential_per_particle": 0.05,
    "kinetic_per_particle": 0.03,
    "dna_rotational_per_particle": 0.03,
    "dna_translational_per_particle": 0.03,
}
FORCE_RTOL = 0.001
KICK_CHECKS = {
    "CPU_GPU_1e-05_linear",
    "CPU_GPU_1e-05_angular",
    "CPU_GPU_1e-06_linear",
    "CPU_GPU_1e-06_angular",
    "DNA_linear_1e-05",
    "DNA_linear_1e-06",
    "CPU_timestep_convergence",
    "CPU_translation_invariance",
    "CUDA_timestep_convergence",
    "CUDA_translation_invariance",
}


def compare(cpu, gpu, stressed_kicks):
    if set(cpu) != set(gpu) or not cpu:
        raise ValueError("CPU/GPU case sets must match and be nonempty")
    groups = {}
    cases = {}
    for name, a in cpu.items():
        b = gpu[name]
        if a["inputs_sha256"] != b["inputs_sha256"]:
            raise ValueError("CPU/GPU physical inputs differ: " + name)
        if a["particles"] != b["particles"]:
            raise ValueError("CPU/GPU particle counts differ: " + name)
        kick_a = np.asarray(a["kick"], dtype=float)
        kick_b = np.asarray(b["kick"], dtype=float)
        if kick_a.shape != (a["particles"], 6) or kick_b.shape != kick_a.shape:
            raise ValueError("Malformed kick response: " + name)
        if not np.isfinite(kick_a).all() or not np.isfinite(kick_b).all():
            raise ValueError("Nonfinite kick response: " + name)
        errors = {}
        for label, columns in [("linear", slice(0, 3)), ("angular", slice(3, 6))]:
            scale = np.linalg.norm(kick_a[:, columns])
            errors[label] = (
                float(np.linalg.norm(kick_b[:, columns] - kick_a[:, columns]) / scale)
                if scale
                else None
            )
        # Near-cancelling straight-handle torque is recorded, but the rotational
        # gate uses the explicitly rotated/displaced DNA probe below.
        cases[name] = {
            "force_relative_l2": errors,
            "force_pass": errors["linear"] is not None
            and errors["linear"] <= FORCE_RTOL,
        }
        group, seed = name.rsplit("_s", 1)
        groups.setdefault(group, []).append((int(seed), a, b))
    comparisons = {}
    for group, replicas in groups.items():
        if len(replicas) < 3 or len({r[0] for r in replicas}) != len(replicas):
            raise ValueError("At least three distinct seeds are required per geometry")
        metrics = {}
        for metric, margin in MARGINS.items():
            a = np.array([r[1]["stages"]["3_equil"]["means"][metric] for r in replicas])
            b = np.array([r[2]["stages"]["3_equil"]["means"][metric] for r in replicas])
            if not np.isfinite(a).all() or not np.isfinite(b).all():
                raise ValueError("Nonfinite metric: " + metric)
            delta = b - a
            mean = float(delta.mean())
            half = float(
                t.ppf(0.975, len(delta) - 1) * delta.std(ddof=1) / np.sqrt(len(delta))
            )
            metrics[metric] = {
                "CPU_mean": float(a.mean()),
                "CUDA_mean": float(b.mean()),
                "difference": mean,
                "paired_95ci": [mean - half, mean + half],
                "margin": margin,
                "equivalence_pass": abs(mean) + half <= margin,
            }
        thermometry = {}
        for backend, index in [("CPU", 1), ("CUDA", 2)]:
            rotational = np.array(
                [
                    r[index]["stages"]["3_equil"]["means"][
                        "dna_rotational_per_particle"
                    ]
                    for r in replicas
                ]
            )
            protein = np.array(
                [
                    r[index]["stages"]["3_equil"]["means"][
                        "protein_rotational_per_particle"
                    ]
                    for r in replicas
                ]
            )
            expected = 1.5 * 296 / 3000
            half = float(
                t.ppf(0.975, len(rotational) - 1)
                * rotational.std(ddof=1)
                / np.sqrt(len(rotational))
            )
            thermometry[backend] = {
                "DNA_rotational_expected": expected,
                "DNA_rotational_mean": float(rotational.mean()),
                "DNA_rotational_95ci": [
                    float(rotational.mean() - half),
                    float(rotational.mean() + half),
                ],
                "protein_rotational_max": float(protein.max()),
                "pass": bool(
                    np.isfinite(protein).all()
                    and np.max(np.abs(protein)) == 0
                    and abs(rotational.mean() - expected) + half <= 0.03
                ),
            }
        comparisons[group] = {
            "replicas": len(replicas),
            "metrics": metrics,
            "thermometry": thermometry,
        }
    for group in groups:
        if group not in stressed_kicks or not KICK_CHECKS <= set(stressed_kicks[group]):
            raise ValueError("Incomplete stressed-kick audit: " + group)
    kick_values = [
        stressed_kicks[group][check] for group in groups for check in KICK_CHECKS
    ]
    stressed_pass = bool(kick_values) and all(
        np.isfinite(v) and 0 <= v <= FORCE_RTOL for v in kick_values
    )
    deterministic_pass = all(c["force_pass"] for c in cases.values()) and stressed_pass
    stochastic_pass = all(
        m["equivalence_pass"]
        for g in comparisons.values()
        for m in g["metrics"].values()
    )
    thermometry_pass = all(
        v["pass"] for g in comparisons.values() for v in g["thermometry"].values()
    )
    return {
        "thermometry_pass": thermometry_pass,
        "cases": cases,
        "groups": comparisons,
        "force_rtol": FORCE_RTOL,
        "stressed_kicks": stressed_kicks,
        "deterministic_pass": deterministic_pass,
        "stochastic_equivalence_pass": stochastic_pass,
        "pass": deterministic_pass and stochastic_pass and thermometry_pass,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu", type=Path, required=True)
    parser.add_argument("--gpu", type=Path, required=True)
    parser.add_argument("--stressed-kicks", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = compare(
        json.loads(args.cpu.read_text()),
        json.loads(args.gpu.read_text()),
        json.loads(args.stressed_kicks.read_text()),
    )
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print("PASS" if report["pass"] else "NOT YET EQUIVALENT")
    raise SystemExit(0 if report["pass"] else 1)
