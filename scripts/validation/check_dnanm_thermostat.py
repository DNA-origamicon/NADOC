"""Ideal-gas DNANM test: no forces can conceal thermostat bookkeeping errors."""

import argparse
import json
import os
import subprocess
from pathlib import Path
import numpy as np

p = argparse.ArgumentParser()
p.add_argument("--binary", required=True)
p.add_argument("--out", type=Path, required=True)
p.add_argument("--backends", nargs="+", default=["CPU", "CUDA"])
p.add_argument("--precision", choices=["mixed", "float"], default="mixed")
p.add_argument("--seeds", nargs="+", type=int, default=[101, 202, 303])
a = p.parse_args()
a.out.mkdir(parents=True, exist_ok=True)
results = []
histories = {}
for protein, dna in [(0, 16), (484, 16), (64, 0)]:
    n = protein + dna
    common = a.out / ("gas_" + str(protein))
    common.mkdir(exist_ok=True)
    (common / "topology.top").write_text(
        f"{n} {dna + int(protein > 0)} {dna} {protein} {dna}\n"
        + ("-1 A -1 -1\n" * protein)
        + "".join(f"{i + 1} A -1 -1\n" for i in range(dna))
    )
    (common / "anm.par").write_text(str(protein) + "\n")
    xyz = np.zeros((n, 15))
    xyz[:, 0] = np.arange(n) % 8 * 10 + 100
    xyz[:, 1] = (np.arange(n) // 8) % 8 * 10 + 100
    xyz[:, 2] = np.arange(n) // 64 * 10 + 100
    xyz[:, 3] = 1
    xyz[:, 8] = 1
    xyz[:, 9:15] = 1e-8
    with (common / "conf.dat").open("w") as f:
        f.write("t = 0\nb = 1000 1000 1000\nE = 0 0 0\n")
        np.savetxt(f, xyz, fmt="%.15g")
    for seed in a.seeds:
        for backend in a.backends:
            d = common / (backend + "_" + str(seed))
            d.mkdir(exist_ok=True)
            text = f"""backend = {backend}
backend_precision = {a.precision}
sim_type = MD
seed = {seed}
steps = 20000
restart_step_counter = true
verlet_skin = .2
T = 296K
dt = .0001
thermostat = bussi
bussi_tau = 10
newtonian_steps = 1
refresh_vel = true
interaction_type = DNANM
parfile = {common.resolve()}/anm.par
salt_concentration = .5
external_forces = false
fix_diffusion = false
topology = {common.resolve()}/topology.top
conf_file = {common.resolve()}/conf.dat
trajectory_file = trajectory.dat
energy_file = energy.dat
lastconf_file = last_conf.dat
time_scale = linear
print_conf_interval = 100
print_energy_every = 100
max_io = 1000
"""
            if backend == "CUDA":
                text += "CUDA_list = verlet\nuse_edge = true\n"
            (d / "input").write_text(text)
            r = subprocess.run(
                [a.binary, "input"],
                cwd=d,
                capture_output=True,
                text=True,
                timeout=120,
                env=dict(os.environ, OMP_NUM_THREADS="1"),
            )
            (d / "run.log").write_text(r.stdout + r.stderr)
            if r.returncode:
                raise RuntimeError(r.stderr[-2000:])
            frames = []
            lines = (d / "trajectory.dat").read_text().splitlines()
            for start in range(0, len(lines), n + 3):
                frames.append(
                    np.array(
                        [
                            [float(x) for x in row.split()]
                            for row in lines[start + 3 : start + 3 + n]
                        ]
                    )
                )
            all_frames = np.array(frames)
            assert np.isfinite(all_frames).all()
            histories[(protein, seed, backend)] = np.stack(
                [
                    0.5 * np.sum(all_frames[:, :, 9:12] ** 2, axis=(1, 2)),
                    0.5 * np.sum(all_frames[:, protein:, 12:15] ** 2, axis=(1, 2)),
                ],
                axis=1,
            )
            frames = all_frames[100:]
            dna_kr = np.sum(frames[:, protein:, 12:15] ** 2, axis=(1, 2)) * 0.5
            protein_kr = np.sum(frames[:, :protein, 12:15] ** 2, axis=(1, 2)) * 0.5
            expected = dna * 1.5 * 296 / 3000
            record = {
                "protein_beads": protein,
                "dna_beads": dna,
                "backend": backend,
                "seed": seed,
                "DNA_rot_energy": float(dna_kr.mean()),
                "expected_DNA_rot_energy": expected,
                "relative_error": float(abs(dna_kr.mean() - expected) / expected)
                if expected
                else float(abs(dna_kr.mean())),
                "protein_rot_energy_max": float(protein_kr.max()),
                "frames": len(frames),
            }
            results.append(record)
            print(record, flush=True)
(a.out / "report.json").write_text(json.dumps(results, indent=2))
assert all(
    r["relative_error"] < 0.08 and r["protein_rot_energy_max"] == 0 for r in results
), "Incorrect rotational temperature or fictitious protein rotation"

if {"CPU", "CUDA"} <= set(a.backends):
    parity = {}
    for protein in [0, 484, 64]:
        for seed in a.seeds:
            cpu = histories[(protein, seed, "CPU")]
            cuda = histories[(protein, seed, "CUDA")]
            parity[f"{protein}_{seed}"] = float(
                np.max(np.abs(cpu - cuda)) / np.max(np.abs(cpu))
            )
    (a.out / "history_parity.json").write_text(json.dumps(parity, indent=2))
    assert max(parity.values()) < 1e-6, "Bussi CPU/CUDA random streams differ"
