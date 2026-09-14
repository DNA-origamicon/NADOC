"""Follow-up controls triggered by failures in the predeclared DNA2 matrix."""

import json, random
import numpy as np
from ab_common import ROOT, settings_for, run

rows = []


def add(r):
    rows.append(r)
    (ROOT / "additional.json").write_text(json.dumps(rows, indent=2))


conf = ROOT / "dna_impulse.dat"
a = np.loadtxt(conf, skiprows=3)
values = {}
for temperature in ["280K", "296K", "320K"]:
    for dt in [1e-6, 1e-5]:
        for explicit in [False, True]:
            for backend in ["CPU", "CUDA"]:
                s = settings_for("dna", backend, 1, thermostat="no", cadence=1)
                s.update(dt=dt, T=temperature, conf_file=conf, refresh_vel="false")
                if explicit:
                    s.update(
                        use_average_seq="false",
                        seq_dep_file=ROOT
                        / "source/oxDNA2_average_sequence_parameters.txt",
                    )
                label = f"dna_average_file_{temperature}_{dt}_{explicit}_{backend}"
                r = run(label, "baseline", s, True)
                r.update(
                    test="average_parameter_file",
                    explicit=explicit,
                    temperature=temperature,
                    dt=dt,
                )
                if "error" not in r:
                    v = (
                        np.loadtxt(ROOT / "runs" / label / "last_conf.dat", skiprows=3)[
                            :, 9:
                        ]
                        - a[:, 9:]
                    ) / dt
                    values[temperature, dt, explicit, backend] = v
                    if backend == "CUDA":
                        c = values[temperature, dt, explicit, "CPU"]
                        r["CPU_GPU_force_error"] = float(
                            np.linalg.norm(v[:, :3] - c[:, :3])
                            / np.linalg.norm(c[:, :3])
                        )
                        r["CPU_GPU_torque_error"] = float(
                            np.linalg.norm(v[:, 3:] - c[:, 3:])
                            / np.linalg.norm(c[:, 3:])
                        )
                    if explicit and backend == "CPU":
                        c = values[temperature, dt, False, "CPU"]
                        r["CPU_default_vs_file_error"] = float(
                            np.linalg.norm(v - c) / np.linalg.norm(c)
                        )
                add(r)
for backend in ["CPU", "CUDA"]:
    for dt in [0.001, 0.0005, 0.00025]:
        s = settings_for(
            "dna", backend, round(1 / dt), thermostat="no", cadence=round(0.01 / dt)
        )
        s.update(
            dt=dt,
            conf_file=conf,
            refresh_vel="false",
            use_average_seq="false",
            seq_dep_file=ROOT / "source/oxDNA2_average_sequence_parameters.txt",
        )
        r = run(f"dna_file_nve_{backend}_{dt}", "baseline", s, True)
        r.update(test="explicit_average_nve", dt=dt)
        if "error" not in r:
            e = np.loadtxt(ROOT / "runs" / r["label"] / "energy.dat")
            total = e[:, 1] + e[:, 2]
            r["relative_energy_range"] = float(np.ptp(total) / abs(total[0]))
        add(r)
rng = random.Random(62971)
for geometry, candidate, cadence in [
    ("dna_prepared", "explicit_average", None),
    ("cage", "rigid_mask", 100),
]:
    for backend in ["CPU", "CUDA"] if geometry == "dna_prepared" else ["CUDA"]:
        for rep in range(5):
            order = ["baseline", candidate]
            rng.shuffle(order)
            for arm in order:
                steps = 2000 if backend == "CPU" else 10000
                s = settings_for(
                    "dna" if geometry == "dna_prepared" else geometry,
                    backend,
                    steps,
                    6001 + rep,
                    "john",
                    cadence=cadence or steps,
                )
                variant = "baseline"
                if geometry == "dna_prepared":
                    s["conf_file"] = (
                        ROOT
                        / "runs/perf_dna_john_rigid_mask_CPU_0_baseline/last_conf.dat"
                    )
                    if arm == candidate:
                        s.update(
                            use_average_seq="false",
                            seq_dep_file=ROOT
                            / "source/oxDNA2_average_sequence_parameters.txt",
                        )
                else:
                    s.update(T="300K", diff_coeff=2.5, newtonian_steps=103)
                    variant = arm
                label = f"additional_perf_{geometry}_{backend}_{rep}_{arm}"
                r = run(label, variant, s, True)
                r.update(
                    test="performance",
                    geometry=geometry if cadence is None else geometry + "_with_output",
                    candidate=candidate,
                    arm=arm,
                    replicate=rep,
                )
                # Summary pairs configuration arms, even when both use the same executable.
                r["engine_variant"] = r["variant"]
                r["variant"] = arm
                add(r)
print("Additional controls complete", flush=True)
