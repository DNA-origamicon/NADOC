"""Rebuild and compare the corrected anti-CPD electrostatic engine probe."""

import argparse
import importlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import (
    EVIDENCE,
    source,
    checked,
    write,
    audit_graph,
)
from experiments.cpd_drude_recovery.nucleotide import atoms_and_terms

NAMD = Path(
    "/home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++.cpu/namd3"
)
OLD = EVIDENCE / "anti-cpd-drude-electrostatic-fit-v3/namd_openmm_spotcheck"


def main(root, recovery):
    root.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(recovery.resolve()))
    d = importlib.import_module("drude_model")
    assert Path(d.__file__).resolve().parent == recovery.resolve()
    frozen = recovery / "corrected_parameters.training_frozen.json"
    fit = json.loads(frozen.read_text())
    charges = json.loads(checked(fit["permanent_charges"]).read_text())["charges_e"]
    params = fit["parameters"]
    model = d.AntiCpdDrudeModel(
        charges, params["alpha_angstrom3"], params["thole"], params["anisotropy"]
    )
    policy = json.loads((OLD / "spotcheck_policy.json").read_text())
    policy.update(
        frozen_parameter_sha256=source(frozen)["sha256"],
        corrected_graph=True,
        method="CPU NAMD zero-temperature damped Drude dynamics; fixed cores, fixedAtomsForces on",
        displacement_comparison="Full per-Drude vectors plus historical magnitude diagnostic",
        simulation_ready=False,
        gate_effect="none",
    )
    write(root / "policy.json", policy)
    rtf = (OLD / "cpd.rtf").read_text().splitlines()
    oldnames = [line.split()[1] for line in rtf if line.startswith("ATOM ")][:-1]
    assert len(oldnames) == len(d.NAMES)
    mapping = dict(zip(oldnames, d.NAMES))
    out = []
    for line in rtf:
        fields = line.split()
        if fields and fields[0] == "ATOM" and fields[1] in mapping:
            name = mapping[fields[1]]
            line = f"ATOM {fields[1]} {fields[2]} {charges[name]:.12f}"
            if name in params["alpha_angstrom3"]:
                line += f" ALPHA {-params['alpha_angstrom3'][name]:.12f} THOLE {params['thole'][name]:.12f}"
        elif fields and fields[0] == "ANISOTROPY":
            a11, a22 = params["anisotropy"][mapping[fields[1]]]
            line = " ".join(fields[:5]) + f" A11 {a11:.12f} A22 {a22:.12f}"
        if line == "BOND C51 C52":
            line = "BOND C51 C62"
        if line == "BOND C61 C62":
            line = "BOND C61 C52"
        out.append(line)
    (root / "cpd.rtf").write_text("\n".join(out) + "\n")
    for filename in [
        "build.tcl",
        "cpd_input.pdb",
        "q_input.pdb",
        "master.prm",
        "cpd.prm",
    ]:
        shutil.copy2(OLD / filename, root / filename)
    with (root / "psfgen.log").open("w") as log:
        subprocess.run(
            [shutil.which("psfgen"), "build.tcl"],
            cwd=root,
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
        )
    psf = (root / "cpd_q.psf").read_text()
    lines, atoms, sections = atoms_and_terms(psf)
    nuclei = {
        i: d.ATOM_NAMES.index(mapping[a[4]])
        for i, a in atoms.items()
        if a[4] in mapping and mapping[a[4]] in d.ATOM_NAMES
    }
    bonds = [
        (nuclei[a], nuclei[b])
        for a, b in sections["NBOND"][3]
        if a in nuclei and b in nuclei
    ]
    registry = json.loads(
        Path("backend/data/forcefield/photoproduct_registry.json").read_text()
    )
    graph = audit_graph(d.ATOM_NAMES, bonds, registry)
    assert {tuple(sorted(x)) for x in bonds} == {tuple(sorted(x)) for x in d._bonds()}
    assert len(nuclei) == 36
    atomrows = list(atoms.values())
    dr = [i for i, a in enumerate(atomrows) if a[5] == "DRUD"]
    parents = [i - 1 for i in dr]
    assert [mapping[atomrows[i][4]] for i in parents] == d.POLARIZABLE
    qi = next(i for i, a in enumerate(atomrows) if a[4] == "Q")
    qd = np.array([float(atomrows[i][6]) for i in dr])
    for i, line in enumerate(lines):
        f = line.split()
        if len(f) > 7 and f[0] == str(qi + 1) and f[4] == "Q":
            f[6] = "0.000000"
            lines[i] = " ".join(f)
    (root / "cpd_q0.psf").write_text("\n".join(lines) + "\n")
    pdb = (root / "cpd_built.pdb").read_text().splitlines()
    pdbatoms = [line for line in pdb if line.startswith(("ATOM", "HETATM"))]
    assert len(pdbatoms) == len(atomrows)
    (root / "fixed.pdb").write_text(
        "\n".join(
            line[:54] + f"{0 if i in dr else 1:6.2f}" + line[60:]
            for i, line in enumerate(pdbatoms)
        )
        + "\nEND\n"
    )
    xyz = np.zeros((len(atomrows), 3))
    for i, a in enumerate(atomrows):
        if a[4] in mapping:
            xyz[i] = model.site_xyz[d.NAMES.index(mapping[a[4]])]
        elif i in dr:
            xyz[i] = xyz[i - 1] + np.array([0.001, 0, 0])
        elif i == qi:
            xyz[i] = [50, 50, 50]
        else:
            raise ValueError("Unknown atom")

    def save_coor(path, positions):
        path.write_bytes(
            struct.pack("<i", len(atomrows))
            + np.asarray(positions, dtype="<f8").tobytes()
        )

    def read_coor(path):
        data = path.read_bytes()
        assert struct.unpack("<i", data[:4])[0] == len(atomrows)
        return np.frombuffer(data, dtype="<f8", offset=4).reshape(-1, 3).copy()

    config = (OLD / "dyn_baseline.conf").read_text()

    def run(label, positions, psf_name):
        save_coor(root / f"{label}_start.coor", positions)
        text = config.replace("cpd_q0.psf", psf_name).replace(
            "outputName dyn_baseline", f"outputName {label}"
        )
        text = text.replace(
            "coordinates cpd_built.pdb",
            f"coordinates cpd_built.pdb\nbinCoordinates {label}_start.coor",
        )
        (root / f"{label}.conf").write_text(text)
        with (root / f"{label}.log").open("w") as log:
            subprocess.run(
                [str(NAMD), "+p2", f"{label}.conf"],
                cwd=root,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=300,
            )
        result = read_coor(root / f"{label}.coor")
        print("Completed", label, flush=True)
        return result

    write(
        root / "inputs.json",
        {
            "graph": graph,
            "frozen": source(frozen),
            "model": source(recovery / "drude_model.py"),
            "namd": source(NAMD),
            "rtf": source(root / "cpd.rtf"),
            "psf": source(root / "cpd_q.psf"),
            "historical_policy": source(OLD / "spotcheck_policy.json"),
            "simulation_ready": False,
        },
    )
    base = run("baseline", xyz, "cpd_q0.psf")
    model.set_external_charge(0)
    ob = model.relax()
    grid = np.loadtxt(d.P1 / "bundle/cases/case-000/grid.dat")
    records = []
    for cid in policy["case_ids"]:
        line = next(
            l
            for l in (OLD / f"case{cid:03d}_input.pdb").read_text().splitlines()
            if l.startswith("ATOM") and l[12:16].strip() == "Q"
        )
        pos = np.array([float(line[i : i + 8]) for i in (30, 38, 46)])
        start = base.copy()
        start[qi] = pos
        current = run(f"case{cid:03d}", start, "cpd_q.psf")
        nd = (current[dr] - current[parents]) - (base[dr] - base[parents])
        oe, omu, orr = model.response(pos, grid, ob)
        od = (orr["drude_positions_nm"] - ob["drude_positions_nm"]) * 10
        nmu = (qd[:, None] * nd).sum(axis=0) / d.BOHR_ANGSTROM
        ne = d.BOHR_ANGSTROM * (
            (
                1 / np.linalg.norm(grid[:, None, :] - current[None, dr, :], axis=2)
                - 1 / np.linalg.norm(grid[:, None, :] - base[None, dr, :], axis=2)
            )
            @ qd
        )
        record = {
            "case_id": cid,
            "dipole_relative_error": float(
                np.linalg.norm(nmu - omu) / np.linalg.norm(omu)
            ),
            "drude_vector_relative_error": float(
                np.linalg.norm(nd - od) / np.linalg.norm(od)
            ),
            "esp_relative_rms": float(np.linalg.norm(ne - oe) / np.linalg.norm(oe)),
            "maximum_core_motion_angstrom": float(
                np.max(np.linalg.norm(current[parents] - base[parents], axis=1))
            ),
            "openmm_drude_force_rms": orr["drude_force_rms_kj_mol_nm"],
        }
        records.append(record)
        write(root / "partial_results.json", records)
    tol = policy["relative_tolerance"]
    checks = {
        k: all(r[k] <= tol for r in records)
        for k in (
            "dipole_relative_error",
            "drude_vector_relative_error",
            "esp_relative_rms",
        )
    }
    checks["cores_fixed"] = all(
        r["maximum_core_motion_angstrom"] < 1e-10 for r in records
    )
    write(
        root / "assessment.json",
        {
            "passed": all(checks.values()),
            "checks": checks,
            "records": records,
            "simulation_ready": False,
            "gate_effect": "none",
            "scope": "Corrected electrostatic engine response only; no LJ/bonded/full nucleotide validation",
        },
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--recovery", type=Path, required=True)
    a = p.parse_args()
    main(a.root.resolve(), a.recovery.resolve())
