"""Freeze corrected-graph/native-LJ water predictions without reading QM targets."""

import argparse
import importlib
import importlib.util
import json
import math
from pathlib import Path
import sys

import numpy as np
from openmm import app, unit as u

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import (
    EVIDENCE,
    PROBE,
    source,
    checked,
    write,
    audit_graph,
)


def main(root, batch_root, recovery):
    root.mkdir(exist_ok=False)
    batch_path = batch_root / "batch.json"
    batch = json.loads(batch_path.read_text())
    frozen_path = recovery / "corrected_parameters.training_frozen.json"
    fit = json.loads(frozen_path.read_text())
    charges = json.loads(checked(fit["permanent_charges"]).read_text())["charges_e"]
    old = EVIDENCE / "anti-cpd-drude-water-fit-v2/fit_water.py"
    text = (
        old.read_text()
        .replace(
            str(EVIDENCE / "anti-cpd-drude-electrostatic-fit-v3"),
            str(recovery.resolve()),
        )
        .replace(
            'P2 / "fitted_parameters.preholdout.json"',
            'P2 / "corrected_parameters.training_frozen.json"',
        )
    )
    evaluator = root / "polarization_evaluator.py"
    evaluator.write_text(text)
    sys.path.insert(0, str(recovery.resolve()))
    d = importlib.import_module("drude_model")
    assert Path(d.__file__).resolve().parent == recovery.resolve()
    spec = importlib.util.spec_from_file_location("corrected_water_probe", evaluator)
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    assert w._graph_distances is d._graph_distances
    registry = json.loads(
        Path("backend/data/forcefield/photoproduct_registry.json").read_text()
    )
    graph = audit_graph(d.ATOM_NAMES, d._bonds(), registry)
    params = app.CharmmParameterSet(
        *[
            str(PROBE / name)
            for name in ("master.rtf", "na.rtf", "master.prm", "na.prm")
        ]
    )
    types = dict(w.ATOM_TYPES)
    types["H6"] = "HDA1A"
    water_type = params.atom_types_str["ODW"]
    pairs = {}
    for name in d.ATOM_NAMES:
        atom_type = types[name.split(":")[1]]
        atom = params.atom_types_str[atom_type]
        nbfix = atom.nbfix.get("ODW")
        if nbfix:
            rmin, epsilon = nbfix[:2]
        else:
            rmin = atom.rmin + water_type.rmin
            epsilon = math.sqrt(abs(atom.epsilon * water_type.epsilon))
        pairs[name] = {
            "type": atom_type,
            "epsilon_kcal_mol": epsilon,
            "rmin_angstrom": rmin,
            "native_nbfix": bool(nbfix),
        }
    write(
        root / "policy.json",
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "role": "Frozen corrected electrostatics plus native intermolecular LJ/NBFIX diagnostic; no historical fitted water parameters, no target energy scale or distance shift.",
            "batch": source(batch_path),
            "frozen": source(frozen_path),
            "upstream_evaluator": source(old),
            "adapted_evaluator": source(evaluator),
            "script": source(Path(__file__)),
            "forcefield_sources": [
                source(PROBE / n)
                for n in ("master.rtf", "na.rtf", "master.prm", "na.prm")
            ],
            "graph": graph,
            "pairs": pairs,
            "monomer_reference": "Exact relaxed CPD electrostatic energy; isolated rigid SWM4-NDP has zero electrostatic/spring energy because all intramolecular pairs excluded and Drude is at parent.",
            "qm_values_read": False,
        },
    )
    p = fit["parameters"]
    monomer = d.AntiCpdDrudeModel(
        charges, p["alpha_angstrom3"], p["thole"], p["anisotropy"]
    )
    monomer.set_external_charge(0)
    baseline = monomer.relax()
    monomer_energy = float(
        monomer.context.getState(getEnergy=True)
        .getPotentialEnergy()
        .value_in_unit(u.kilocalorie_per_mole)
    )
    model = w.PolarizationEnergy()
    records = []
    for case in batch["cases"]:
        checked(case["source_manifest"])
        for rec in case["geometry_sources"].values():
            checked(rec)
        xyz = np.array(
            [
                [float(x) for x in line.split()[1:]]
                for line in case["molecule"].splitlines()
                if len(line.split()) == 4
            ]
        )
        assert xyz.shape == (39, 3) and np.max(abs(xyz[:36] - model.atom_xyz)) < 1e-9
        water = xyz[-3:]
        combined, maxdisp = model._minimize(model._positions(water))
        forces = np.asarray(
            model.context.getState(getForces=True)
            .getForces(asNumpy=True)
            .value_in_unit(u.kilocalorie_per_mole / u.angstrom)
        )
        force_max = float(abs(forces[[*model.cpd_drudes, model.water_drude]]).max())
        polar = combined - monomer_energy
        lj = 0.0
        for i, name in enumerate(d.ATOM_NAMES):
            pair = pairs[name]
            distance = np.linalg.norm(xyz[i] - water[0])
            ratio = (pair["rmin_angstrom"] / distance) ** 6
            lj += pair["epsilon_kcal_mol"] * (ratio**2 - 2 * ratio)
        records.append(
            {
                "case_id": case["id"],
                "partition": case["partition"],
                "electrostatic_and_induction_kcal_mol": polar,
                "lj_kcal_mol": float(lj),
                "total_interaction_kcal_mol": float(polar + lj),
                "maximum_drude_displacement_angstrom": maxdisp,
                "maximum_drude_force_kcal_mol_angstrom": force_max,
                "numerical_domain_passed": maxdisp <= 0.2 and force_max <= 1e-4,
            }
        )
    write(
        root / "predictions.json",
        {
            "simulation_ready": False,
            "gate_effect": "none",
            "qm_values_read": False,
            "policy": source(root / "policy.json"),
            "isolated_cpd_energy_kcal_mol": monomer_energy,
            "isolated_cpd_displacement_angstrom": baseline[
                "maximum_displacement_angstrom"
            ],
            "records": records,
        },
    )
    print(
        "Frozen predictions:",
        len(records),
        "numerical-domain failures:",
        sum(not r["numerical_domain_passed"] for r in records),
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--batch-root", type=Path, required=True)
    p.add_argument("--recovery", type=Path, required=True)
    a = p.parse_args()
    main(a.root.resolve(), a.batch_root.resolve(), a.recovery.resolve())
