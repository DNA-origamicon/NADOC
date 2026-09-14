"""Paired runtime controls, upstream examples, and uncapped contact NVE."""

import sys, json, random
import numpy as np
from ab_common import ROOT, run, settings_for, frames

sys.path.insert(0, str(ROOT.parents[2] / "scripts/validation/oxdna_physics_audit"))
from pair_audit import oracle

results = []


def add(r):
    results.append(r)
    (ROOT / "extended.json").write_text(json.dumps(results, indent=2))


rng = random.Random(61093)
# One factor per comparison, paired order randomized; sparse output.
contrasts = [
    ("biotin10", "bussi", "current_k"),
    ("biotin10", "john", "rigid_mask"),
    ("biotin10", "john", "gpu_epsilon1"),
    ("biotin10", "john", "cpu_epsilon2"),
    ("biotin10", "john", "combined_epsilon1"),
    ("biotin10", "john", "combined_epsilon2"),
    ("dna", "bussi", "current_k"),
    ("dna", "john", "rigid_mask"),
    ("protein", "langevin", "rigid_mask"),
    ("cage", "john", "rigid_mask"),
]
for geometry, thermostat, candidate in contrasts:
    for backend in ["CPU", "CUDA"]:
        repeats = 5 if geometry == "biotin10" else 3
        steps = 2000 if backend == "CPU" else 10000
        for rep in range(repeats):
            order = ["baseline", candidate]
            rng.shuffle(order)
            for v in order:
                s = settings_for(
                    geometry, backend, steps, 4001 + rep, thermostat, cadence=steps
                )
                if geometry == "protein":
                    s.update(
                        T="300K", diff_coeff=1, newtonian_steps=51, salt_concentration=1
                    )
                if geometry == "cage":
                    s.update(T="300K", diff_coeff=2.5, newtonian_steps=103)
                r = run(
                    f"perf_{geometry}_{thermostat}_{candidate}_{backend}_{rep}_{v}",
                    v,
                    s,
                    True,
                )
                r.update(
                    test="performance",
                    geometry=geometry,
                    candidate=candidate,
                    replicate=rep,
                )
                add(r)
for variant in ["baseline", "combined_epsilon1", "combined_epsilon2"]:
    for backend in ["CPU", "CUDA"]:
        for dt in [1e-4, 5e-5, 2.5e-5]:
            base = (
                ROOT
                / "functional"
                / variant
                / "pairs/back_core_rotated"
                / f"{backend}_1e-06"
            )
            # Independent pair oracle and unchanged input configuration.
            s = {
                k.strip(): v.strip()
                for k, v in [
                    line.split("=", 1)
                    for line in (base / "input").read_text().splitlines()
                    if "=" in line
                ]
            }
            for key in ["conf_file", "topology", "parfile"]:
                s[key] = base / s[key]
            s.update(
                steps=round(0.5 / dt),
                dt=dt,
                print_conf_interval=round(0.005 / dt),
                print_energy_every=round(0.005 / dt),
            )
            label = f"nve_{variant}_{backend}_{dt}"
            r = run(label, variant, s, True)
            if not r.get("error"):
                _, a = frames(ROOT / "runs" / label / "trajectory.dat", 2)
                a = np.concatenate([np.loadtxt(base / "conf.dat", skiprows=3)[None], a])
                u = np.array([oracle(x)[0] for x in a])
                k = 0.5 * (
                    (a[:, :, 9:12] ** 2).sum(axis=(1, 2))
                    + (a[:, 1, 12:] ** 2).sum(axis=1)
                )
                eps = (
                    2
                    if variant == "combined_epsilon2"
                    or (variant == "baseline" and backend == "CUDA")
                    else 1
                )
                e = k + eps * u
                r.update(
                    epsilon=eps,
                    relative_energy_range=float(np.ptp(e) / abs(e[0])),
                    energy_range=float(np.ptp(e)),
                )
            r.update(test="uncapped_pair_nve", dt=dt)
            add(r)
print("Extended tests complete", flush=True)
