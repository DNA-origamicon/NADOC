"""Isolated replicated explicit-solvent cis-syn DNA stability campaign."""

import argparse
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import time
import warnings

import numpy as np
from openmm import app
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.core.namd_solvate import (
    _gmx_solvate,
    _extend_psf,
    _build_solvated_pdb,
    _Water,
)
from experiments.cpd_published_comparator.reconstruct import BASE, FF, source, write

CANDIDATE = Path(".development-artifacts/cpd-cis-syn-joint-v6").resolve()


def ideal_water(w):
    o = np.array([w.ox, w.oy, w.oz])
    a = np.array([w.h1x, w.h1y, w.h1z]) - o
    b = np.array([w.h2x, w.h2y, w.h2z]) - o
    a /= np.linalg.norm(a)
    b /= np.linalg.norm(b)
    mid = a + b
    mid /= np.linalg.norm(mid)
    side = a - b
    side /= np.linalg.norm(side)
    theta = np.radians(104.52 / 2)
    h1 = o + 0.09572 * (np.cos(theta) * mid + np.sin(theta) * side)
    h2 = o + 0.09572 * (np.cos(theta) * mid - np.sin(theta) * side)
    return _Water(*o, *h1, *h2)


def build(root, padding_nm=1.2, box_mode="bbox", box_size_nm=None):
    root.mkdir(exist_ok=False)
    (root / "executed_source.py").write_text(Path(__file__).read_text())
    write(
        root / "protocol.json",
        dict(
            simulation_ready=False,
            stage="replicated short stability pilot",
            systems=["cis-syn duplex", "matched undamaged duplex"],
            replicas_per_system=3,
            seeds=[41017, 52021, 63029],
            temperature_K=300,
            pressure_bar=1.01325,
            salt_mM=150,
            solvent="CHARMM TIP3P with CUFIX NaCl; no magnesium",
            padding_nm=padding_nm,
            box_mode=box_mode,
            box_size_nm=box_size_nm,
            dynamics={
                "timestep_fs": 2,
                "restrained_NPT_ps": 20,
                "restraint_release_NPT_ps": 40,
                "unrestrained_NPT_ps": 40,
                "production_NPT_ps": 100,
            },
            numerical_criteria={
                "no_fatal_errors": True,
                "all_stereochemical_signs_retained": True,
                "heavy_bond_range_A": [0.8, 2.1],
                "production_mean_temperature_K": [280, 320],
                "production_mean_density_g_ml": [0.9, 1.2],
            },
            diagnostics=[
                "CPD bond distributions",
                "DNA aligned heavy RMSD",
                "central base-pair contacts",
                "replica variation",
            ],
            limits=[
                "Short trajectories do not establish conformational convergence or experimental accuracy",
                "Control starts from damaged deposited coordinates, then independently relaxes; initial structure bias remains",
                "Independent glycosidic QM energetics and general strand integration remain pending",
            ],
            source=source(CANDIDATE / "final_audit.json"),
        ),
    )
    ff = root / "forcefield"
    ff.mkdir()
    for p in [
        BASE / "par_all36_na.prm",
        BASE / "par_all36m_prot.prm",
        BASE / "par_stub_ions_nbfix.str",
        BASE / "toppar_water_ions_cufix.str",
        FF / "par_all36_cgenff.prm",
    ]:
        shutil.copy2(p, ff / p.name)
    # The CPD aliases must inherit CUFIX pair corrections involving their parent types.
    aliases = json.loads((CANDIDATE / "typing_manifest.json").read_text())["aliases"]
    ion_text = (BASE / "toppar_water_ions_cufix.str").read_text()
    active = False
    rows = []
    for line in ion_text.splitlines():
        words = line.split("!", 1)[0].split()
        if not words:
            continue
        if words[0].upper() == "NBFIX":
            active = True
            continue
        if words[0].upper() == "END":
            active = False
        if active and len(words) >= 4:
            left = [words[0]] + [
                a["alias"] for a in aliases if a["original_type"] == words[0]
            ]
            right = [words[1]] + [
                a["alias"] for a in aliases if a["original_type"] == words[1]
            ]
            for a in left:
                for b in right:
                    if a.startswith("CS") or b.startswith("CS"):
                        rows.append([a, b, *words[2:]])
    text = (CANDIDATE / "comparator_last.prm").read_text().rsplit("END", 1)[
        0
    ] + "\nNBFIX\n"
    (ff / "cpd_solvated.prm").write_text(
        text + "\n".join(" ".join(r) for r in rows) + "\nEND\n"
    )
    write(
        root / "solvent_parameter_audit.json",
        dict(
            alias_nbfix_entries=rows,
            alias_nbfix_count=len(rows),
            sources=[
                source(CANDIDATE / "comparator_last.prm"),
                source(BASE / "toppar_water_ions_cufix.str"),
                source(ff / "cpd_solvated.prm"),
            ],
        ),
    )
    parameter_files = [
        ff / n
        for n in [
            "par_all36_na.prm",
            "par_all36m_prot.prm",
            "par_all36_cgenff.prm",
            "par_stub_ions_nbfix.str",
            "toppar_water_ions_cufix.str",
            "cpd_solvated.prm",
        ]
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        params = app.CharmmParameterSet(*map(str, parameter_files))
    cases = []
    for label, fixture in [("cpd", "duplex"), ("control", "undamaged_control")]:
        out = root / label
        out.mkdir()
        scratch = out / "build"
        scratch.mkdir()
        original = CANDIDATE / fixture
        psf = app.CharmmPsfFile(str(original / "system.psf"))
        raw = (original / "startup.coor").read_bytes()
        assert struct.unpack("i", raw[:4])[0] == 634
        coords = np.frombuffer(raw[4:], dtype=np.float64).reshape(-1, 3)
        lines = (original / "system.pdb").read_text().splitlines()
        i = 0
        for j, line in enumerate(lines):
            if line.startswith(("ATOM  ", "HETATM")):
                x, y, z = coords[i]
                lines[j] = line[:30] + f"{x:8.3f}{y:8.3f}{z:8.3f}" + line[54:]
                i += 1
        assert i == 634
        water, cell, dry = _gmx_solvate(
            "\n".join(lines) + "\n",
            padding_nm,
            scratch,
            box_mode=box_mode,
            box_size_nm=box_size_nm,
        )
        solute = (
            np.array(
                [
                    [float(l[k : k + 8]) for k in (30, 38, 46)]
                    for l in dry.splitlines()
                    if l.startswith(("ATOM  ", "HETATM"))
                ]
            )
            / 10
        )
        heavy = np.array(
            [
                a.mass.value_in_unit_system(__import__("openmm").unit.md_unit_system)
                > 2
                for a in psf.atom_list
            ]
        )
        oxy = np.array([[w.ox, w.oy, w.oz] for w in water])
        dist = cKDTree(solute[heavy]).query(oxy)[0]
        water = [ideal_water(w) for w, d in zip(water, dist) if d >= 0.24]
        oxy = np.array([[w.ox, w.oy, w.oz] for w in water])
        dist = cKDTree(solute[heavy]).query(oxy)[0]
        pairs = round(len(water) * 0.150 / 55.5)
        n_na = pairs + 18
        n_cl = pairs
        for replica, seed in enumerate([41017, 52021, 63029], 1):
            folder = out / f"replica-{replica}"
            folder.mkdir()
            rng = np.random.default_rng(seed)
            eligible = np.flatnonzero(dist >= 0.5)
            rng.shuffle(eligible)
            chosen = []
            for idx in eligible:
                if chosen:
                    delta = oxy[chosen] - oxy[idx]
                    delta -= np.array(cell) * np.round(delta / np.array(cell))
                    if min(np.linalg.norm(delta, axis=1)) < 0.5:
                        continue
                chosen.append(int(idx))
                if len(chosen) == n_na + n_cl:
                    break
            assert len(chosen) == n_na + n_cl
            na = [tuple(oxy[i]) for i in chosen[:n_na]]
            cl = [tuple(oxy[i]) for i in chosen[n_na:]]
            chosen_set = set(chosen)
            remaining = [w for i, w in enumerate(water) if i not in chosen_set]
            (folder / "system.psf").write_text(
                _extend_psf((original / "system.psf").read_text(), remaining, na, cl)
            )
            pdb = _build_solvated_pdb(dry, remaining, na, cl, cell, 634)
            (folder / "system.pdb").write_text(pdb)
            parsed = app.CharmmPsfFile(str(folder / "system.psf"))
            assert abs(sum(a.charge for a in parsed.atom_list)) < 1e-6
            parsed.loadParameters(params)
            mask = []
            for line in pdb.splitlines():
                if line.startswith(("ATOM  ", "HETATM")):
                    serial = int(line[6:11])
                    value = 1 if serial <= 634 and heavy[serial - 1] else 0
                    line = line[:60] + f"{value:6.2f}" + line[66:]
                mask.append(line)
            (folder / "restraints.pdb").write_text("\n".join(mask) + "\n")
            info = dict(
                system=label,
                replica=replica,
                seed=seed,
                cell_nm=cell,
                waters=len(remaining),
                sodium=n_na,
                chloride=n_cl,
                atoms=len(parsed.atom_list),
                solute_atoms=634,
                neutral=True,
                parameter_load="passed",
                folder=str(folder),
                source_psf=source(original / "system.psf"),
                source_coordinates=source(original / "startup.coor"),
            )
            write(folder / "build.json", info)
            cases.append(info)
            config = (
                f"""structure {folder}/system.psf
coordinates {folder}/system.pdb
paraTypeCharmm on
"""
                + "".join(f"parameters {p}\n" for p in parameter_files)
                + f"""exclude scaled1-4
oneFourScaling 1
switching on
switchdist 10
cutoff 12
pairlistdist 14
margin 2
cellBasisVector1 {cell[0] * 10} 0 0
cellBasisVector2 0 {cell[1] * 10} 0
cellBasisVector3 0 0 {cell[2] * 10}
cellOrigin {cell[0] * 5} {cell[1] * 5} {cell[2] * 5}
PME yes
PMEGridSpacing 1.0
rigidBonds all
rigidTolerance 0.00001
timestep 2
nonbondedFreq 1
fullElectFrequency 2
stepspercycle 10
CUDASOAintegrate on
langevin on
langevinTemp 300
langevinDamping 1
langevinHydrogen off
temperature 0
seed {seed}
useGroupPressure yes
useFlexibleCell no
useConstantArea no
langevinPistonTarget 1.01325
langevinPistonPeriod 200
langevinPistonDecay 100
langevinPistonTemp 300
langevinPiston on
wrapWater on
wrapAll off
outputName {folder}/trajectory
DCDfile {folder}/trajectory.dcd
dcdfreq 500
xstFreq 500
restartfreq 5000
outputEnergies 500
outputTiming 5000
constraints on
consref {folder}/restraints.pdb
conskfile {folder}/restraints.pdb
conskcol B
constraintScaling 1
minimize 10000
reinitvels 300
run 10000
constraintScaling 0.5
run 10000
constraintScaling 0.1
run 10000
constraintScaling 0
run 20000
run 50000
"""
            )
            (folder / "run.conf").write_text(config)
    write(root / "builds.json", dict(cases=cases, simulation_ready=False))
    print([(c["system"], c["replica"], c["atoms"]) for c in cases], flush=True)


def run(root, on_case=None):
    cases = json.loads((root / "builds.json").read_text())["cases"]
    status = []
    for c in cases:
        folder = Path(c["folder"])
        if (folder / "completion.json").exists():
            status.append(json.loads((folder / "completion.json").read_text()))
            continue
        assert not (folder / "run.log").exists(), "Retain failed runs; do not overwrite"
        started = time.time()
        with (folder / "run.log").open("w") as log:
            p = subprocess.Popen(
                ["namd3", "+p2", "+devices", "0", str(folder / "run.conf")],
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            write(
                root / "running.json",
                dict(
                    pid=p.pid,
                    system=c["system"],
                    replica=c["replica"],
                    folder=str(folder),
                    started=started,
                ),
            )
            code = p.wait()
        text = (folder / "run.log").read_text()
        rows = [l.split() for l in text.splitlines() if l.startswith("ENERGY:")]
        sane = all(
            float(row[12]) > 0.1
            and any(abs(float(row[i])) > 1e-6 for i in (2, 3, 6, 7))
            for row in rows
            if int(row[1]) > 10000
        )
        result = dict(
            system=c["system"],
            replica=c["replica"],
            exit_code=code,
            elapsed_s=time.time() - started,
            nonzero_dynamics=sane,
            last_step=int(rows[-1][1]) if rows else None,
            passed_execution=code == 0
            and "FATAL ERROR" not in text
            and bool(rows)
            and int(rows[-1][1]) == 110000
            and sane,
        )
        write(folder / "completion.json", result)
        status.append(result)
        write(root / "execution.json", dict(records=status, simulation_ready=False))
        print(result, flush=True)
        if not result["passed_execution"]:
            (root / "running.json").unlink(missing_ok=True)
            raise RuntimeError(f"Native run failed: {folder}")
        if on_case is not None:
            on_case(c)
    (root / "running.json").unlink(missing_ok=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--run", action="store_true")
    a = p.parse_args()
    if a.run:
        run(a.root.resolve())
    else:
        build(a.root.resolve())
