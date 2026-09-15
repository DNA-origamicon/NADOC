"""Common native runner for frozen A/B inputs and derived physical metrics."""

from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import time

import numpy as np

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
ENGINE_ROOT = ROOT / "engines"
T = 296 / 3000


def fixture(name):
    d = ROOT / "fixtures" / name
    if d.exists():
        return d
    d.mkdir(parents=True)
    if name in ["ads5", "ads10", "biotin10"]:
        source = REPO / "workspace/validation/strep_physical_20260913/common" / name
        for old, new in [
            ("topology.top", "topology.top"),
            ("relaxed.dat", "conf.dat"),
            ("anm.par", "anm.par"),
            ("equil_forces.txt", "forces.txt"),
        ]:
            shutil.copy2(source / old, d / new)
    elif name == "dna":
        source = ROOT / "source/examples/PERSISTENCE_LENGTH"
        shutil.copy2(source / "init.top", d / "topology.top")
        shutil.copy2(source / "init.conf", d / "conf.dat")
    elif name in ["protein", "cage"]:
        source = (
            ROOT
            / "source/examples/DNANM"
            / ("KDPG" if name == "protein" else "hybrid_cage")
        )
        for old, new in (
            [
                ("generated.top", "topology.top"),
                ("s1.dat", "conf.dat"),
                ("kdpg_anm.par", "anm.par"),
            ]
            if name == "protein"
            else [
                ("acc2.top", "topology.top"),
                ("acc2_relaxed.dat", "conf.dat"),
                ("ac.par", "anm.par"),
                ("acforceponly.txt", "forces.txt"),
            ]
        ):
            shutil.copy2(source / old, d / new)
    else:
        raise ValueError(name)
    return d


def settings_for(name, backend, steps, seed=1919, thermostat="bussi", cadence=None):
    common = fixture(name)
    d = dict(
        backend=backend,
        backend_precision="mixed",
        sim_type="MD",
        interaction_type="DNANM" if (common / "anm.par").exists() else "DNA2",
        steps=steps,
        seed=seed,
        dt=0.0001 if name in ["ads5", "ads10", "biotin10"] else 0.002,
        T="296K",
        thermostat=thermostat,
        bussi_tau=1000,
        newtonian_steps=53,
        refresh_vel="true",
        fix_diffusion="false",
        restart_step_counter="true",
        salt_concentration=0.5,
        verlet_skin=0.2,
        CUDA_list="verlet",
        use_edge="true",
        CUDA_sort_every=0,
        topology=common / "topology.top",
        conf_file=common / "conf.dat",
        parfile=common / "anm.par",
        external_forces=str((common / "forces.txt").exists()).lower(),
        external_forces_file=common / "forces.txt",
        trajectory_file="trajectory.dat",
        lastconf_file="last_conf.dat",
        energy_file="energy.dat",
        time_scale="linear",
        print_conf_interval=cadence or max(1, steps // 200),
        print_energy_every=cadence or max(1, steps // 200),
        max_io=1000,
        no_stdout_energy="true",
    )
    if thermostat in ["john", "brownian", "langevin"]:
        d["diff_coeff"] = 2.5
        d["newtonian_steps"] = 103
    return d


def frames(path, n):
    rows = []
    times = []
    with path.open() as f:
        while True:
            line = f.readline()
            if not line:
                break
            times.append(int(line.split("=")[1]))
            f.readline()
            f.readline()
            rows.append(
                np.array([[float(v) for v in f.readline().split()] for _ in range(n)])
            )
    a = np.array(rows)
    if not (len(a) and a.shape[1:] == (n, 15) and np.isfinite(a).all()):
        raise ValueError("Malformed or nonfinite trajectory")
    return np.array(times), a


def metrics(folder, settings, summary_only=False):
    top = Path(settings["topology"]).read_text().splitlines()[0].split()
    n = int(top[0])
    protein = int(top[3]) if len(top) >= 5 else 0
    last = np.loadtxt(folder / "last_conf.dat", skiprows=3)
    if last.shape != (n, 15) or not np.isfinite(last).all():
        raise ValueError("Malformed or nonfinite final configuration")
    final_step = int(
        (folder / "last_conf.dat").read_text().splitlines()[0].split("=")[1]
    )
    if final_step != int(settings["steps"]):
        raise ValueError("Incomplete simulation")
    result = dict(
        final_step=final_step,
        particles=n,
        protein=protein,
        point_L_max=float(np.abs(last[:protein, 12:15]).max()) if protein else 0.0,
        final_configuration_sha256=hashlib.sha256(
            (folder / "last_conf.dat").read_bytes()
        ).hexdigest(),
    )
    if summary_only:
        return result
    ts, a = frames(folder / "trajectory.dat", n)
    v = a[:, :, 9:12]
    series = dict(
        total_physical_K=0.5
        * (np.sum(v * v, axis=(1, 2)) + np.sum(a[:, protein:, 12:15] ** 2, axis=(1, 2)))
    )
    if protein:
        series["protein_T"] = np.mean(v[:, :protein] ** 2, axis=(1, 2)) * 3000
        series["protein_Rg_nm"] = (
            np.sqrt(
                np.mean(
                    np.sum(
                        (a[:, :protein, :3] - a[:, :protein, :3].mean(axis=1)[:, None])
                        ** 2,
                        axis=2,
                    ),
                    axis=1,
                )
            )
            * 0.8518
        )
    if protein < n:
        series["DNA_trans_T"] = np.mean(v[:, protein:] ** 2, axis=(1, 2)) * 3000
        series["DNA_rot_T"] = np.mean(a[:, protein:, 12:15] ** 2, axis=(1, 2)) * 3000
        series["DNA_tip_radius_nm"] = np.linalg.norm(a[:, -1, :3], axis=1) * 0.8518
    if (
        "repulsive_sphere_moving" in Path(settings["external_forces_file"]).read_text()
        if str(settings["external_forces"]).lower() in ["true", "1"]
        else False
    ):
        text = Path(settings["external_forces_file"]).read_text()
        radius = float(re.search(r"^r0 = (.+)$", text, re.M).group(1)) * 0.8518 + 0.8
        series["core_clearance_nm"] = (
            np.min(np.linalg.norm(a[:, :, :3], axis=2) * 0.8518, axis=1) - radius
        )
        if np.min(series["core_clearance_nm"]) < 0:
            result["core_penetration"] = True
        anchors = []
        tethers = []
        for block in re.findall(r"\{([^{}]+)\}", text):
            d = dict(re.findall(r"^(\w+)\s*=\s*(.+)$", block, re.M))
            if d.get("type") == "trap":
                anchors.append((int(d["particle"]), np.fromstring(d["pos0"], sep=",")))
            if d.get("type") == "mutual_trap" and int(d["particle"]) < int(
                d["ref_particle"]
            ):
                tethers.append((int(d["particle"]), int(d["ref_particle"])))
        series["anchor_rms_nm"] = (
            np.sqrt(
                np.mean(
                    [np.sum((a[:, i, :3] - p) ** 2, axis=1) for i, p in anchors], axis=0
                )
            )
            * 0.8518
        )
        series["tether_length_nm"] = (
            np.mean(
                [np.linalg.norm(a[:, i, :3] - a[:, j, :3], axis=1) for i, j in tethers],
                axis=0,
            )
            * 0.8518
        )
    result["means_second_half"] = {
        k: float(x[len(x) // 2 :].mean()) for k, x in series.items()
    }
    result["series"] = {k: x.tolist() for k, x in series.items()}
    result["sample_steps"] = ts.tolist()
    return result


def run(label, variant, settings, summary_only=False, timeout=600):
    folder = ROOT / "runs" / label
    folder.mkdir(parents=True, exist_ok=True)
    text = "".join(f"{key} = {value}\n" for key, value in settings.items())
    (folder / "input").write_text(text)
    engine = ENGINE_ROOT / variant / "bin/oxDNA"
    start = time.monotonic()
    with (folder / "run.log").open("w") as log:
        proc = subprocess.run(
            [str(engine), "input"],
            cwd=folder,
            stdout=log,
            stderr=subprocess.STDOUT,
            env=dict(os.environ, OMP_NUM_THREADS="1"),
            timeout=timeout,
        )
    elapsed = time.monotonic() - start
    output = (folder / "run.log").read_text(errors="replace")
    native = re.search(r"Total Running Time: ([\d.eE+-]+) s", output)
    result = dict(
        label=label,
        variant=variant,
        backend=settings["backend"],
        thermostat=settings["thermostat"],
        seed=int(settings["seed"]),
        steps=int(settings["steps"]),
        wall_seconds=elapsed,
        native_seconds=float(native.group(1)) if native else None,
        exit_code=proc.returncode,
        input_sha256=hashlib.sha256(text.encode()).hexdigest(),
    )
    try:
        if proc.returncode:
            raise RuntimeError(output[-1500:])
        result.update(metrics(folder, settings, summary_only))
    except Exception as exc:
        result["error"] = str(exc) or type(exc).__name__
    (folder / "result.json").write_text(json.dumps(result, indent=2))
    print(
        label,
        result["exit_code"],
        round(elapsed, 3),
        result.get("error", "")[:100],
        flush=True,
    )
    return result
