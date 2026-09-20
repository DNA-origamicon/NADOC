"""Compare absolute electrostatic-probe energy at identical native coordinates."""

import argparse
import importlib
import json
from pathlib import Path
import struct
import sys

import numpy as np
from openmm import unit as u

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source, checked, write
from experiments.cpd_drude_recovery.nucleotide import atoms_and_terms


def main(root, recovery):
    sys.path.insert(0, str(recovery.resolve()))
    d = importlib.import_module("drude_model")
    assert Path(d.__file__).resolve().parent == recovery.resolve()
    fitpath = recovery / "corrected_parameters.training_frozen.json"
    fit = json.loads(fitpath.read_text())
    charges = json.loads(checked(fit["permanent_charges"]).read_text())["charges_e"]
    p = fit["parameters"]
    model = d.AntiCpdDrudeModel(
        charges, p["alpha_angstrom3"], p["thole"], p["anisotropy"]
    )
    names = [
        l.split()[1]
        for l in (root / "cpd.rtf").read_text().splitlines()
        if l.startswith("ATOM ")
    ][:-1]
    mapping = dict(zip(names, d.NAMES))
    assert len(mapping) == len(d.NAMES)
    _, atoms, sections = atoms_and_terms((root / "cpd_q.psf").read_text())
    rows = list(atoms.values())
    n = len(rows)
    records = []
    for label in [
        "baseline",
        *[
            f"case{i:03d}"
            for i in json.loads((root / "policy.json").read_text())["case_ids"]
        ],
    ]:
        data = (root / f"{label}.coor").read_bytes()
        assert struct.unpack("<i", data[:4])[0] == n
        xyz = np.frombuffer(data, dtype="<f8", offset=4).reshape(n, 3)
        positions = model.base_positions.copy()
        for i, row in enumerate(rows):
            if row[4] in mapping:
                j = d.NAMES.index(mapping[row[4]])
            elif row[5] == "DRUD":
                j = model.drude_indices[d.POLARIZABLE.index(mapping[rows[i - 1][4]])]
            elif row[4] == "Q":
                j = model.external_index
            else:
                raise ValueError("Unmapped particle")
            positions[j] = xyz[i] / 10
        model.set_external_charge(0 if label == "baseline" else 0.5)
        model.context.setPositions(positions)
        omm = float(
            model.context.getState(getEnergy=True)
            .getPotentialEnergy()
            .value_in_unit(u.kilocalorie_per_mole)
        )
        fixed_bond_energy = 0.0
        for a, b in sections["NBOND"][3]:
            types = tuple(sorted([atoms[a][5], atoms[b][5]]))
            if "DRUD" in types:
                continue
            if types == ("CPDX", "CPDX"):
                req = 1.4
            elif types == ("CPDX", "LPDNA1"):
                req = 0.35
            else:
                raise ValueError("Unexpected probe bond type")
            fixed_bond_energy += (
                100 * (np.linalg.norm(xyz[a - 1] - xyz[b - 1]) - req) ** 2
            )
        text = (root / f"{label}.log").read_text()
        titles = next(
            l.split()[1:] for l in text.splitlines() if l.startswith("ETITLE:")
        )
        last = [l.split()[1:] for l in text.splitlines() if l.startswith("ENERGY:")][-1]
        energy = dict(zip(titles, map(float, last)))
        assert energy["TS"] == 20000 and abs(energy["KINETIC"]) < 1e-8
        for component in ["ANGLE", "DIHED", "IMPRP", "VDW", "BOUNDARY", "MISC"]:
            assert abs(energy[component]) < 1e-8
        namd = energy["POTENTIAL"] - fixed_bond_energy
        records.append(
            {
                "case": label,
                "namd_potential_kcal_mol": energy["POTENTIAL"],
                "dummy_nuclear_bonds_kcal_mol": float(fixed_bond_energy),
                "namd_corrected_probe_energy_kcal_mol": float(namd),
                "openmm_probe_energy_kcal_mol": omm,
                "difference_kcal_mol": float(namd - omm),
                "coordinates": source(root / f"{label}.coor"),
                "log": source(root / f"{label}.log"),
            }
        )
    write(
        root / "absolute_energy_diagnostic.json",
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "scope": "Absolute probe energy at identical NAMD coordinates, after analytic subtraction of dummy fixed nuclear/LP bonds. Not candidate bonded or full-nucleotide energy validation.",
            "precision_caveat": "NAMD energy printed to four decimals and PSF charges to six decimals; OpenMM uses full frozen charge precision.",
            "max_absolute_difference_kcal_mol": max(
                abs(r["difference_kcal_mol"]) for r in records
            ),
            "records": records,
            "fit": source(fitpath),
            "probe_parameters": source(root / "cpd.prm"),
            "psf": source(root / "cpd_q.psf"),
            "code": source(Path(__file__)),
        },
    )
    print(
        "Maximum absolute energy difference kcal/mol:",
        max(abs(r["difference_kcal_mol"]) for r in records),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--recovery", required=True, type=Path)
    a = p.parse_args()
    main(a.root, a.recovery)
