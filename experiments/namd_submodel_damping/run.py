"""Prepare and run a bounded central-region comparison using native NAMD.

Source Design bytes are retained unchanged. All derived PSF/PDBs, masks, inputs,
seeds and native logs remain in a new output directory. No managed job is changed.
"""

import argparse
import hashlib
import json
import re
import subprocess
import time
from pathlib import Path

import numpy as np
from backend.core.models import Design
from backend.core.md_protocols import (
    prepare_equilibrium_aware_namd,
    SegmentSpec,
    _segment_conf,
    build_production_conf,
    write_hmr_psf,
)
from backend.core.namd_topology import build_charmm_psfgen_topology
from backend.core.namd_submodel import (
    package_builder,
    crop_topology,
    sections,
    canonical_bonded_lines,
)
from backend.core.md_shell_reprep import read_namd_coor


def dump(path, value):
    path.write_text(json.dumps(value, indent=2))


def marker(path, lines, values, coordinates=None):
    out = []
    for i, line in enumerate(lines):
        if coordinates is not None:
            line = line[:30] + "".join(f"{v:8.3f}" for v in coordinates[i]) + line[54:]
        out.append(line[:60] + f"{values[i]:6.2f}" + line[66:])
    path.write_text("\n".join(out) + "\nEND\n")


def boundary_atoms(full_psf, receipt):
    """Freeze every retained residue in any bonded term crossing the cut."""
    parsed = sections(full_psf)
    rows = [s.split() for s in parsed["NATOM"][1]]
    retained = {i + 1 for i in receipt["retained_source_indices"]}
    boundary = set()
    for key, arity in [
        ("NBOND", 2),
        ("NTHETA", 3),
        ("NPHI", 4),
        ("NIMPHI", 4),
        ("NCRTERM", 8),
    ]:
        if key not in parsed:
            continue
        flat = list(map(int, " ".join(parsed[key][1]).split()))
        for offset in range(0, len(flat), arity):
            term = flat[offset : offset + arity]
            if not all(i in retained for i in term):
                boundary.update(
                    (rows[i - 1][1], rows[i - 1][2]) for i in term if i in retained
                )
    output = [
        i
        for i, source in enumerate(receipt["retained_source_indices"])
        if tuple(rows[source][1:3]) in boundary
    ]
    assert not set(output).intersection(receipt["mobile_output_indices"])
    return output


def restraint_block(filename):
    return f"constraints on\nconsref {filename}\nconskfile {filename}\nconskcol B\nconsexp 2\n"


def set_boundary(text, fixed_file, restrained_file=None):
    text = re.sub(
        r"^[ \t]*(?:fixedAtoms(?:File|Col|Forces)?|GPUresident|langevinPiston)\s+[^\n]*\n?",
        "",
        text,
        flags=re.M | re.I,
    )
    prefix = "langevinPiston off\n"
    if fixed_file:
        prefix += f"fixedAtoms on\nfixedAtomsFile {fixed_file}\nfixedAtomsCol B\nfixedAtomsForces off\n"
    if restrained_file:
        text = re.sub(
            r"^\s*constraints\s+off\s*$",
            restraint_block(restrained_file).rstrip(),
            text,
            flags=re.M,
        )
    return prefix + text


def run_native(binary, pkg, name, root):
    print("NATIVE", pkg.name, name, flush=True)
    started = time.time()
    log = pkg / (name + ".native.log")
    with log.open("w") as output:
        result = subprocess.run(
            [str(binary), "+p4", "+setcpuaffinity", "+devices", "0", name + ".conf"],
            cwd=pkg,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
    text = log.read_text()
    outcome = {
        "stage": name,
        "package": str(pkg),
        "exit_code": result.returncode,
        "seconds": time.time() - started,
        "success": result.returncode == 0 and "End of program" in text,
    }
    with (root / "execution.jsonl").open("a") as out:
        out.write(json.dumps(outcome) + "\n")
    if not outcome["success"]:
        raise RuntimeError(f"Native failure; inspect {log}")


def run_production(root, binary, steps, packages):
    trials_path = root / "trials.json"
    trials = json.loads(trials_path.read_text()) if trials_path.exists() else []
    for seed in (77, 177):
        for condition in ("full", "fixed", "gamma_0.1", "gamma_1", "gamma_5"):
            kind = "full" if condition == "full" else "crop"
            info = packages[kind]
            pkg = Path(info["package"])
            stem = info["stem"]
            m = json.loads((pkg / "manifest.json").read_text())
            name = f"{condition}_seed{seed}"
            if any(trial["name"] == name for trial in trials):
                continue
            if (pkg / (name + ".conf")).exists():
                attempt = pkg / "failed_attempts" / name
                attempt.mkdir(parents=True, exist_ok=False)
                for suffix in (".conf", ".native.log"):
                    (pkg / (name + suffix)).rename(attempt / (name + suffix))
                for output in (pkg / "output").glob(name + ".*"):
                    output.rename(attempt / output.name)
            spec = SegmentSpec(
                name=name,
                stage="Bounded shell damping comparison",
                percent=100,
                steps=steps,
                temp=300,
                damping=1,
                scale=None,
                npt=False,
                previous="common_relax",
                reinit=True,
                dcd_freq=250,
                timestep_fs=4,
            )
            text = build_production_conf(
                spec,
                stem,
                tuple(m["box_ang"]),
                False,
                seed=seed,
                fast=True,
                timestep_fs=4,
                npt=False,
                damping=1,
                force_resident=False,
            )
            # Fresh velocity draw with HMR masses; every condition starts at its common checkpoint.
            text = re.sub(r"^binVelocities[^\n]*\n", "", text, flags=re.M)
            text = "temperature 300\n" + text
            if condition == "fixed":
                text = set_boundary(text, "all_shell_fixed.pdb")
            elif condition.startswith("gamma_"):
                text = set_boundary(text, "outer_fixed.pdb", "buffer_reference.pdb")
                text = re.sub(
                    r"^langevinDamping[^\n]*\n",
                    f"langevinFile {condition}.pdb\nlangevinCol B\n",
                    text,
                    flags=re.M,
                )
                text = re.sub(r"^langevinHydrogen[^\n]*\n", "", text, flags=re.M)
            else:
                text = set_boundary(text, None)
            (pkg / (name + ".conf")).write_text(text)
            run_native(binary, pkg, name, root)
            trials.append(
                {
                    "condition": condition,
                    "seed": seed,
                    "package": str(pkg),
                    "stem": stem,
                    "name": name,
                    "frames_expected": steps // 250,
                }
            )
            dump(root / "trials.json", trials)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--binary", type=Path, required=True)
    ap.add_argument(
        "--steps",
        type=int,
        default=12500,
        help="4 fs production steps per seed (default 50 ps)",
    )
    ap.add_argument("--resume-production", action="store_true")
    args = ap.parse_args()
    root = args.output.resolve()
    if args.resume_production:
        snapshot = (root / "source-design.json").read_bytes()
        assert args.source.read_bytes() == snapshot
        experiment = json.loads((root / "experiment.json").read_text())
        assert args.steps == experiment["production_steps"]
        packages = json.loads((root / "packages.json").read_text())
        assert set(packages) == {"crop", "full"}
        run_production(root, args.binary, args.steps, packages)
        assert args.source.read_bytes() == snapshot
        print("CAMPAIGN COMPLETE", flush=True)
        return
    root.mkdir(parents=True, exist_ok=False)
    source = args.source.resolve()
    snapshot = source.read_bytes()
    (root / "source-design.json").write_bytes(snapshot)
    design = Design.from_json(snapshot.decode())
    full = build_charmm_psfgen_topology(design)
    positions = np.array(
        [
            [float(s[i : i + 8]) / 10 for i in (30, 38, 46)]
            for s in full.pdb_text.splitlines()
            if s.startswith(("ATOM  ", "HETATM"))
        ]
    )
    center = (positions.min(0) + positions.max(0)) / 2
    half = np.array([3.2, 3.2, 2.38])
    box = dict(
        shape="box",
        min_corner=(center - half).tolist(),
        max_corner=(center + half).tolist(),
        rotation=[0, 0, 0, 1],
        shell_nm=2,
        visible=True,
    )
    _, receipt = crop_topology(full, box)
    (root / "source.psf").write_text(full.psf_text)
    (root / "source.pdb").write_text(full.pdb_text)
    dump(root / "region.json", box)
    dump(root / "selection.json", receipt)
    experiment = {
        "source": str(source),
        "source_sha256": hashlib.sha256(snapshot).hexdigest(),
        "box": box,
        "production_steps": args.steps,
        "timestep_fs": 4,
        "seeds": [77, 177],
        "core_solvent_damping_ps_inv": 1,
        "shell_damping_ps_inv": [0.1, 1, 5],
        "buffer_restraint_kcal_mol_A2": 0.1,
        "temperature_K": 300,
        "salt_mM": 150,
        "Mg_mM": 0,
        "solvent_padding_nm": 2,
        "controls": ["full", "fixed"],
        "hypothesis": "A mobile restrained shell may better approximate full-model local fluctuations than a fixed shell. Gamma affects kinetics; do not optimize against one trajectory.",
        "limits": "Two short 50 ps velocity seeds per condition; independently solvated full/crop systems, common crop start, no convergence claim. Newly mobile boundary atoms retain complete bonded terms.",
    }
    dump(root / "experiment.json", experiment)
    packages = {}
    for kind in ("crop", "full"):
        jobdir = root / kind
        kwargs = {}
        if kind == "crop":
            kwargs["package_builder"] = package_builder(box)
        print("PREPARE", kind, flush=True)
        rel, stem, _ = prepare_equilibrium_aware_namd(
            design,
            jobdir,
            fixed_cell=True,
            gpu_resident_mode="off",
            padding_nm=2,
            box_mode="bbox",
            minimize_steps=4800,
            adaptive_minimization=False,
            ion_conc_mM=150,
            mg_conc_mM=0,
            salt_mode="custom",
            **kwargs,
        )
        pkg = jobdir / rel
        m = json.loads((pkg / "manifest.json").read_text())
        for psf in pkg.glob("*.psf"):
            psf.write_text(canonical_bonded_lines(psf.read_text()))
        atom_lines = [
            s
            for s in (pkg / (stem + ".pdb")).read_text().splitlines()
            if s.startswith(("ATOM  ", "HETATM"))
        ]
        rows = [
            s.split() for s in sections((pkg / (stem + ".psf")).read_text())["NATOM"][1]
        ]
        heavy = np.array([float(row[7]) > 2 for row in rows])
        n = len(rows)
        fixed_file = restrained_file = None
        if kind == "crop":
            frozen = boundary_atoms(full.psf_text, receipt)
            core = set(receipt["mobile_output_indices"])
            retained = len(receipt["retained_source_indices"])
            buffer = sorted(set(range(retained)) - core - set(frozen))
            assert buffer, "Shell contains no movable buffer atoms"
            weights = np.zeros(n)
            weights[buffer] = 0.1
            weights[~heavy] = 0
            flags = np.zeros(n)
            flags[frozen] = 1
            marker(pkg / "outer_fixed.pdb", atom_lines, flags)
            marker(pkg / "buffer_initial.pdb", atom_lines, weights)
            flags[:retained] = 1
            flags[list(core)] = 0
            marker(pkg / "all_shell_fixed.pdb", atom_lines, flags)
            fixed_file = "outer_fixed.pdb"
            restrained_file = "buffer_initial.pdb"
            dump(
                root / "buffer.json",
                {
                    "frozen_indices": frozen,
                    "buffer_indices": buffer,
                    "core_indices": sorted(core),
                    "retained_atoms": retained,
                    "total_atoms": n,
                    "buffer_heavy_atoms": int(heavy[buffer].sum()),
                },
            )
        minimum = m["minimization"]["name"]
        conf = pkg / (minimum + ".conf")
        conf.write_text(set_boundary(conf.read_text(), fixed_file, restrained_file))
        run_native(args.binary, pkg, minimum, root)
        spec = SegmentSpec(
            name="common_relax",
            stage="20 ps common preparation",
            percent=100,
            steps=10000,
            temp=300,
            damping=1,
            scale=None,
            npt=False,
            previous=minimum,
            reinit=True,
            dcd_freq=500,
            timestep_fs=2,
        )
        text = _segment_conf(
            spec, stem, tuple(m["box_ang"]), False, seed=42, force_resident=False
        )
        (pkg / "common_relax.conf").write_text(
            set_boundary(text, fixed_file, restrained_file)
        )
        run_native(args.binary, pkg, "common_relax", root)
        write_hmr_psf(pkg / (stem + ".psf"), pkg / (stem + "_hmr.psf"))
        if kind == "crop":
            marker(
                pkg / "buffer_reference.pdb",
                atom_lines,
                weights,
                read_namd_coor(pkg / "output/common_relax.coor"),
            )
            for gamma in (0.1, 1, 5):
                values = heavy.astype(float)
                values[buffer] = gamma
                values[~heavy] = 0
                values[frozen] = 0
                marker(pkg / f"gamma_{gamma:g}.pdb", atom_lines, values)
        packages[kind] = {"package": str(pkg), "stem": stem, "atoms": n}
        dump(root / "packages.json", packages)
    run_production(root, args.binary, args.steps, packages)
    assert source.read_bytes() == snapshot, (
        "Source changed during campaign; inspect independently, never overwrite it."
    )
    print("CAMPAIGN COMPLETE", flush=True)


if __name__ == "__main__":
    main()
