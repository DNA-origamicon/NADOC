"""One-factor native tests; no production binaries are changed."""

import sys, json
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[2] / "scripts/validation/oxdna_physics_audit"))
import thermostat_audit as t
import pair_audit as p

results = []


def save():
    (ROOT / "functional.json").write_text(json.dumps(results, indent=2))


for variant in ["baseline", "current_k", "combined_epsilon1", "combined_epsilon2"]:
    t.ROOT = ROOT / "functional" / variant
    t.ENGINE = ROOT / "engines" / variant / "bin/oxDNA"
    for backend in ["CPU", "CUDA"]:
        a = t.fixture(protein=0)
        a[:, 9:12] *= np.sqrt(2)
        r = t.run(
            "weak_" + backend,
            backend,
            "bussi",
            a,
            0,
            1,
            stride=1,
            settings="newtonian_steps = 1\nbussi_tau = 1000000000",
        )
        r.update(
            test="weak_current_K",
            variant=variant,
            relative_change=r["final_relative_K"] / r["initial_relative_K"] - 1,
        )
        results.append(r)
        save()
for variant in ["baseline", "rigid_mask"]:
    t.ROOT = ROOT / "functional" / variant
    t.ENGINE = ROOT / "engines" / variant / "bin/oxDNA"
    for backend in ["CPU", "CUDA"]:
        for thermostat in ["john", "langevin"]:
            for protein in [0, 32, 64]:
                for sort in [0, 103] if backend == "CUDA" and protein == 32 else [0]:
                    name = f"mask_{backend}_{thermostat}_{protein}_{sort}"
                    r = t.run(
                        name,
                        backend,
                        thermostat,
                        t.fixture(protein=protein),
                        protein,
                        1000,
                        stride=100,
                        settings=f"newtonian_steps = 10\ndiff_coeff = .1\nCUDA_sort_every = {sort}",
                    )
                    r.update(
                        test="point_mask", variant=variant, protein=protein, sort=sort
                    )
                    if variant == "rigid_mask":
                        a = np.loadtxt(
                            ROOT
                            / "functional/baseline/thermostats"
                            / name
                            / "last_conf.dat",
                            skiprows=3,
                        )
                        b = np.loadtxt(
                            t.ROOT / "thermostats" / name / "last_conf.dat", skiprows=3
                        )
                        r["physical_max_abs_difference"] = float(
                            max(
                                abs(a[:, :3] - b[:, :3]).max(),
                                abs(a[:, 9:12] - b[:, 9:12]).max(),
                                abs(a[protein:, 3:9] - b[protein:, 3:9]).max()
                                if protein < 64
                                else 0,
                                abs(a[protein:, 12:] - b[protein:, 12:]).max()
                                if protein < 64
                                else 0,
                            )
                        )
                    results.append(r)
                    save()
for variant in [
    "baseline",
    "gpu_epsilon1",
    "cpu_epsilon2",
    "combined_epsilon1",
    "combined_epsilon2",
]:
    p.ROOT = ROOT / "functional" / variant
    p.ENGINE = ROOT / "engines" / variant / "bin/oxDNA"
    p.main()
print("Functional tests complete", flush=True)
