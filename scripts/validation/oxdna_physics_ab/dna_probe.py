import json
import numpy as np
from ab_common import ROOT, fixture, settings_for, run

rows = []


def add(r):
    rows.append(r)
    (ROOT / "dna_probe.json").write_text(json.dumps(rows, indent=2))


f = fixture("dna")
prepared = ROOT / "runs/perf_dna_john_rigid_mask_CPU_0_baseline/last_conf.dat"
a = np.loadtxt(f / "conf.dat", skiprows=3)
a[:, 3:6] /= np.linalg.norm(a[:, 3:6], axis=1)[:, None]
a[:, 6:9] /= np.linalg.norm(a[:, 6:9], axis=1)[:, None]
normalized = ROOT / "dna_normalized.dat"
with normalized.open("w") as out:
    out.write("t = 0\nb = 90 90 90\nE = 0 0 0\n")
    np.savetxt(out, a, fmt="%.17g")
for name, conf in [
    ("original", f / "conf.dat"),
    ("normalized", normalized),
    ("prepared", prepared),
]:
    for edge in ["true", "false"]:
        for backend in ["CPU", "CUDA"]:
            s = settings_for("dna", backend, 100, thermostat="no", cadence=1)
            s.update(conf_file=conf, use_edge=edge)
            r = run(f"dna_probe_{name}_{edge}_{backend}", "baseline", s, True)
            r.update(test="initial_geometry", geometry=name, edge=edge)
            add(r)
# Valid, identical prepared input for matching ordinary DNA performance.
for thermostat, candidate in [("bussi", "current_k"), ("john", "rigid_mask")]:
    for backend in ["CPU", "CUDA"]:
        for rep in range(3):
            for variant in (
                ["baseline", candidate] if rep % 2 else [candidate, "baseline"]
            ):
                steps = 2000 if backend == "CPU" else 10000
                s = settings_for(
                    "dna", backend, steps, 5001 + rep, thermostat, cadence=steps
                )
                s["conf_file"] = prepared
                r = run(
                    f"dna_prepared_perf_{thermostat}_{backend}_{rep}_{variant}",
                    variant,
                    s,
                    True,
                )
                r.update(
                    test="performance",
                    geometry="dna_prepared",
                    candidate=candidate,
                    replicate=rep,
                )
                add(r)
print("DNA starting-state probe complete", flush=True)
