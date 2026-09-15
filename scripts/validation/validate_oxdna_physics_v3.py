"""Final native regressions and randomized same-machine timings for physics v3.

Uses the frozen A/B fixtures and retains all raw inputs/results under workspace.
Run sequentially after builds/tests complete; no other local simulation may overlap.
"""

from pathlib import Path
import argparse
import hashlib
import json
import random
import sys
import numpy as np
from scipy import stats

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
ROOT = REPO / "workspace/validation/physics_implementation_20260913/native"
FROZEN = REPO / "workspace/validation/physics_ab_20260913"
sys.path.insert(0, str(REPO / "scripts/validation/oxdna_physics_ab"))
import ab_common as ab

sys.path.insert(0, str(REPO / "scripts/validation/oxdna_physics_audit"))
import thermostat_audit as t
from backend.core.oxdna_runner import find_oxdna, oxdna_supports_physics_v3

p = argparse.ArgumentParser()
p.add_argument("--pairs", type=int, default=12)
args = p.parse_args()
ROOT.mkdir(parents=True, exist_ok=True)
(ROOT / "engines").mkdir(exist_ok=True)
for name, target in [
    ("baseline", FROZEN / "engines/baseline"),
    ("v3", Path(find_oxdna()).resolve().parent.parent),
]:
    link = ROOT / "engines" / name
    if not link.exists():
        link.symlink_to(target, target_is_directory=True)
if not (ROOT / "fixtures").exists():
    (ROOT / "fixtures").symlink_to(FROZEN / "fixtures", target_is_directory=True)
ab.ROOT = ROOT
ab.ENGINE_ROOT = ROOT / "engines"
assert oxdna_supports_physics_v3(str(ab.ENGINE_ROOT / "v3/bin/oxDNA"))
rows = []


def save(row):
    rows.append(row)
    (ROOT / "results.json").write_text(json.dumps(rows, indent=2))


# Raw ideal DNA previously emitted NaN on CUDA, both edge and non-edge paths.
for backend in ["CPU", "CUDA"]:
    for edge in ["true", "false"] if backend == "CUDA" else ["false"]:
        for variant in ["baseline", "v3"]:
            s = ab.settings_for("dna", backend, 100, thermostat="john", cadence=100)
            s["use_edge"] = edge
            r = ab.run(f"raw_{backend}_{edge}_{variant}", variant, s, True)
            r.update(test="raw_ideal_DNA", edge=edge)
            save(r)
            if variant == "v3" or backend == "CPU":
                assert "error" not in r and r["exit_code"] == 0, r

# Recheck the installed engine, not just the previously isolated candidate.
for variant in ["baseline", "v3"]:
    t.ROOT = ROOT / "functional" / variant
    t.ENGINE = ab.ENGINE_ROOT / variant / "bin/oxDNA"
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
            test="weak_coupling",
            variant=variant,
            relative_change=r["final_relative_K"] / r["initial_relative_K"] - 1,
        )
        save(r)
        if variant == "v3":
            assert abs(r["relative_change"]) < 0.001
        for thermostat in ["john", "langevin"]:
            for sort in [0, 103] if backend == "CUDA" else [0]:
                name = f"mask_{backend}_{thermostat}_{sort}"
                r = t.run(
                    name,
                    backend,
                    thermostat,
                    t.fixture(protein=32),
                    32,
                    1000,
                    stride=100,
                    settings=f"newtonian_steps = 10\ndiff_coeff = .1\nCUDA_sort_every = {sort}",
                )
                r.update(test="point_rotations", variant=variant)
                if variant == "v3":
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
                    delta = max(
                        abs(a[:, :3] - b[:, :3]).max(),
                        abs(a[:, 9:12] - b[:, 9:12]).max(),
                        abs(a[32:, 3:9] - b[32:, 3:9]).max(),
                        abs(a[32:, 12:] - b[32:, 12:]).max(),
                    )
                    r["physical_max_abs_difference"] = float(delta)
                    assert delta == 0 and r["point_final_L2"] == 0
                save(r)

# Paired timings use identical inputs and output cadence within each comparison.
# Prepared DNA avoids counting the baseline startup failure as a speed advantage.
prepared = FROZEN / "runs/perf_dna_john_rigid_mask_CPU_0_baseline/last_conf.dat"
rng = random.Random(20260913)
for geometry, thermostat in [
    ("biotin10", "bussi"),
    ("biotin10", "john"),
    ("dna", "bussi"),
]:
    for backend in ["CPU", "CUDA"]:
        steps = 2000 if backend == "CPU" else 10000
        for rep in range(args.pairs):
            order = ["baseline", "v3"]
            rng.shuffle(order)
            for variant in order:
                s = ab.settings_for(
                    geometry, backend, steps, 7101 + rep, thermostat, cadence=steps
                )
                if geometry == "dna":
                    s.update(
                        conf_file=prepared,
                        use_average_seq="false",
                        seq_dep_file=REPO
                        / "backend/data/oxdna/oxDNA2_average_sequence_parameters.txt",
                    )
                r = ab.run(
                    f"timing_{geometry}_{thermostat}_{backend}_{rep}_{variant}",
                    variant,
                    s,
                    True,
                )
                r.update(test="timing", geometry=geometry, replicate=rep)
                save(r)
                assert "error" not in r and r["exit_code"] == 0, r

summary = []
for geometry, thermostat in [
    ("biotin10", "bussi"),
    ("biotin10", "john"),
    ("dna", "bussi"),
]:
    for backend in ["CPU", "CUDA"]:
        selected = [
            r
            for r in rows
            if r["test"] == "timing"
            and r["geometry"] == geometry
            and r["thermostat"] == thermostat
            and r["backend"] == backend
        ]
        pairs = {
            i: {r["variant"]: r for r in selected if r["replicate"] == i}
            for i in range(args.pairs)
        }
        logs = np.array(
            [
                np.log(v["v3"]["wall_seconds"] / v["baseline"]["wall_seconds"])
                for v in pairs.values()
            ]
        )
        half = stats.t.ppf(0.975, len(logs) - 1) * logs.std(ddof=1) / np.sqrt(len(logs))
        bounds = np.exp([logs.mean() - half, logs.mean() + half]).tolist()
        summary.append(
            dict(
                geometry=geometry,
                thermostat=thermostat,
                backend=backend,
                pairs=len(logs),
                ratio=float(np.exp(logs.mean())),
                ci95=bounds,
                resolved_slowdown=bounds[0] > 1,
            )
        )
report = dict(
    controls_complete=True,
    timings=summary,
    engine_sha256={
        v: hashlib.sha256((ab.ENGINE_ROOT / v / "bin/oxDNA").read_bytes()).hexdigest()
        for v in ["baseline", "v3"]
    },
    limitation="Step throughput does not establish time to equilibrium or experimental agreement; useful-sample validation remains tech debt.",
)
report["engine_library_sha256"] = {
    v: hashlib.sha256(
        (ab.ENGINE_ROOT / v / "lib/liboxdna_common.so").read_bytes()
    ).hexdigest()
    for v in ["baseline", "v3"]
}
(ROOT / "summary.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
