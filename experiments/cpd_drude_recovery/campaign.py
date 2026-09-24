"""Isolated anti-CPD Drude graph audit and adiabatic bonded-fit diagnostics.

Never updates a force-field registry or upstream acceptance artifact. The input
directory contains the preserved P2 evaluator with its anti graph corrected.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import sys

import numpy as np
import openmm as mm
from openmm import app, unit as u

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
EVIDENCE = Path("/media/jojo/Archive/NADOC_archive/photoproduct_evidence")
OLD = EVIDENCE / "alpine-qm-primary-syn-anti-fit-v1/local-run-v1"
PROBE = (
    OLD
    / "gate-troubleshooting-v1/anisotropic-offcenter-crossvalidation-v1/drude-engine-probe-v1"
)


def source(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def checked(record):
    path = Path(record["path"])
    if source(path)["sha256"] != record["sha256"]:
        raise ValueError(f"Source hash mismatch: {path}")
    return path


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + "\n")


def audit_graph(names, bonds, registry):
    """Compare explicit endpoint crosslinks to the registered chemical graph."""
    if len(names) != len(set(names)):
        raise ValueError("Duplicate stable atom identities")
    if any(a == b or min(a, b) < 0 or max(a, b) >= len(names) for a, b in bonds):
        raise ValueError("Invalid bond atom index")
    if len({tuple(sorted(b)) for b in bonds}) != len(bonds):
        raise ValueError("Duplicate covalent bond")
    actual = {
        tuple(sorted((names[a], names[b])))
        for a, b in bonds
        if names[a].split(":")[0] != names[b].split(":")[0]
    }
    product = next(p for p in registry["products"] if p["id"] == "tt-cpd-cis-anti-i")
    expected = {
        tuple(sorted(pair.split("--")))
        for pair in product["graph_delta"]["bonds_added"]
    }
    if actual != expected:
        raise ValueError(f"Anti graph mismatch: expected {expected}, found {actual}")
    return {"passed": True, "crosslinks": sorted(actual)}


class AdiabaticNonbonded:
    """Relax induced particles while differentiating the physical nuclear surface."""

    def __init__(self, recovery, frozen_parameters=None):
        sys.path.insert(0, str(Path(recovery).resolve()))
        self.d = importlib.import_module("drude_model")
        if Path(self.d.__file__).resolve().parent != Path(recovery).resolve():
            raise ValueError(
                "Imported a different Drude model than the pinned recovery"
            )
        registry = json.loads(
            (REPO / "backend/data/forcefield/photoproduct_registry.json").read_text()
        )
        self.graph_audit = audit_graph(self.d.ATOM_NAMES, self.d._bonds(), registry)
        frozen_path = (
            Path(frozen_parameters)
            if frozen_parameters is not None
            else (
                EVIDENCE
                / "anti-cpd-drude-electrostatic-fit-v3/fitted_parameters.preholdout.json"
            )
        )
        frozen = json.loads(frozen_path.read_text())
        charges = json.loads(checked(frozen["permanent_charges"]).read_text())[
            "charges_e"
        ]
        self.model = self.d.AntiCpdDrudeModel(
            charges,
            **{
                "alpha": frozen["parameters"]["alpha_angstrom3"],
                "thole": frozen["parameters"]["thole"],
                "anisotropy": frozen["parameters"]["anisotropy"],
            },
        )
        self.model.set_external_charge(0)
        # P3's six NBFIX terms involve water only, so do not enter this vacuum baseline.
        self.types = {
            "CM": "CD33A",
            "N1": "ND2R6C",
            "C2": "CD2O4A",
            "O2": "OD2C1B",
            "N3": "ND2R6C",
            "C4": "CD2O4A",
            "O4": "OD2C1B",
            "C5": "CD30A",
            "C7": "CD33A",
            "C6": "CD31A",
            "H3": "HDP1A",
            "H6": "HDA1A",
        }
        self.types.update(
            {name: "HDA3A" for name in ["HCM1", "HCM2", "HCM3", "H51", "H52", "H53"]}
        )
        # HDA1 in the old water evaluator is not an official type. HDA1A is
        # the published methine-H analog for CD31A; use its actual LJ records.
        reference = app.CharmmParameterSet(
            str(PROBE / "master.rtf"), str(PROBE / "master.prm"), str(PROBE / "na.prm")
        )
        idx = self.d._atom_index()
        for ring in (1, 2):
            for lp, o, c, n in [
                ("LP2A", "O2", "C2", "N1"),
                ("LP2B", "O2", "C2", "N3"),
                ("LP4A", "O4", "C4", "N3"),
                ("LP4B", "O4", "C4", "C5"),
            ]:
                index = self.d.NAMES.index(f"{ring}:{lp}")
                theta = np.deg2rad(110)
                site = mm.LocalCoordinatesSite(
                    [idx[f"{ring}:{a}"] for a in (o, c, n)],
                    [1, 0, 0],
                    [-1, 1, 0],
                    [0, 1, -1],
                    mm.Vec3(0.035 * np.cos(theta), 0.035 * np.sin(theta), 0),
                )
                self.model.system.setVirtualSite(index, site)
        for i, name in enumerate(self.d.ATOM_NAMES):
            typ = reference.atom_types_str[self.types[name.split(":")[1]]]
            eps, half = abs(typ.epsilon), typ.rmin
            q, _, _ = self.model.nonbonded.getParticleParameters(i)
            self.model.nonbonded.setParticleParameters(
                i, q, 2 * half / (10 * 2 ** (1 / 6)), 4.184 * eps
            )
        graph = self.d._graph_distances()
        for i, name in enumerate(self.d.ATOM_NAMES):
            ti = reference.atom_types_str[self.types[name.split(":")[1]]]
            for j in range(i):
                tj = reference.atom_types_str[
                    self.types[self.d.ATOM_NAMES[j].split(":")[1]]
                ]
                if tj.name in ti.nbfix:
                    raise ValueError(
                        "An intramolecular NBFIX requires explicit implementation"
                    )
                if graph[i, j] != 3:
                    continue
                qi = self.model.nonbonded.getParticleParameters(i)[0]
                qj = self.model.nonbonded.getParticleParameters(j)[0]
                self.model.nonbonded.addException(
                    j,
                    i,
                    qi * qj,
                    (ti.rmin_14 + tj.rmin_14) / (10 * 2 ** (1 / 6)),
                    4.184 * np.sqrt(abs(ti.epsilon_14 * tj.epsilon_14)),
                )
        self.model.context.reinitialize(preserveState=True)
        self.max_displacement = 0.0
        self.max_drude_force = 0.0

    def energy_gradient(self, xyz):
        m = self.model
        p = m.base_positions.copy()
        p[:36] = np.asarray(xyz) / 10
        p[m.drude_indices] = p[:20]
        m.context.setPositions(p)
        m.context.computeVirtualSites()
        mm.LocalEnergyMinimizer.minimize(m.context, 1e-7, 2000)
        s = m.context.getState(getEnergy=True, getForces=True, getPositions=True)
        xyz_nm = s.getPositions(asNumpy=True).value_in_unit(u.nanometer)
        f = s.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole / u.angstrom)
        if np.max(np.abs(f[m.drude_indices])) > 1e-7:
            # L-BFGS can terminate on an energy-resolution plateau. A local
            # force-root refinement makes the nuclear finite differences smooth.
            from scipy.optimize import root

            fixed = np.array(xyz_nm)

            def induced_force(flat):
                p = fixed.copy()
                p[m.drude_indices] = flat.reshape(-1, 3)
                m.context.setPositions(p)
                m.context.computeVirtualSites()
                state = m.context.getState(getForces=True)
                return np.array(
                    state.getForces(asNumpy=True).value_in_unit(
                        u.kilocalorie_per_mole / u.angstrom
                    )
                )[m.drude_indices].reshape(-1)

            solution = root(
                induced_force,
                fixed[m.drude_indices].reshape(-1),
                method="hybr",
                options={"xtol": 1e-10},
            )
            induced_force(solution.x)
            s = m.context.getState(getEnergy=True, getForces=True, getPositions=True)
            xyz_nm = s.getPositions(asNumpy=True).value_in_unit(u.nanometer)
            f = s.getForces(asNumpy=True).value_in_unit(
                u.kilocalorie_per_mole / u.angstrom
            )
        displacement = (
            np.linalg.norm(xyz_nm[m.drude_indices] - xyz_nm[:20], axis=1) * 10
        )
        dforce = float(np.max(np.abs(f[m.drude_indices])))
        self.max_displacement = max(self.max_displacement, float(max(displacement)))
        self.max_drude_force = max(self.max_drude_force, dforce)
        if not np.isfinite(f).all() or not np.isfinite(displacement).all():
            raise ValueError("Non-finite Drude relaxation")
        if max(displacement) > 0.2 or dforce > 1e-4:
            raise ValueError(
                f"Drude relaxation failed: displacement={max(displacement)}, force={dforce}"
            )
        return float(s.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)), -f[
            :36
        ].reshape(-1)

    def hessian(self, xyz, step):
        flat = np.asarray(xyz).reshape(-1)
        result = np.empty((len(flat), len(flat)))
        for i in range(len(flat)):
            a, b = flat.copy(), flat.copy()
            a[i] += step
            b[i] -= step
            result[:, i] = (
                self.energy_gradient(a.reshape(-1, 3))[1]
                - self.energy_gradient(b.reshape(-1, 3))[1]
            ) / (2 * step)
        return result


def build_bonded_basis(
    root,
    model,
    promote_pyrimidine=False,
    pyrimidine_scope="all",
    include_methyl=False,
    promote_hydrogen=False,
    split_h6_endpoints=False,
):
    from backend.parameterization.photoproduct_openmm_fit_basis import (
        build_openmm_linear_fit_basis,
    )
    from backend.parameterization.photoproduct_qm import parse_xyz

    plan = json.loads(
        (OLD / "bundle/results/anti_promoted_bonded_fit_plan.json").read_text()
    )
    plan_bonds = {
        tuple(sorted(t["atoms"]))
        for t in plan["transfer_candidates"]
        if t["category"] == "bonds"
    }
    plan_bonds.update(
        tuple(sorted(t["atoms"]))
        for group in plan["uncovered_parameter_groups"]
        if group["category"] == "bonds"
        for t in group["occurrences"]
    )
    model_bonds = {
        tuple(sorted((model.d.ATOM_NAMES[a], model.d.ATOM_NAMES[b])))
        for a, b in model.d._bonds()
    }
    if model_bonds != plan_bonds:
        raise ValueError(
            "Drude graph differs from the independently audited QM bonded plan"
        )
    old_camp = json.loads(
        (
            OLD / "bundle/results/response_campaign/response_campaign_manifest.json"
        ).read_text()
    )
    old_response = json.loads(
        checked(old_camp["training_datasets"][0]["response_manifest"]).read_text()
    )
    old_basis = json.loads(
        checked(old_response["sources"]["fit_basis_manifest"]).read_text()
    )
    old_skel = json.loads(
        checked(old_basis["sources"]["skeleton_manifest"]).read_text()
    )
    pdb_path = checked(old_skel["outputs"]["model_pdb"])
    map_path = checked(old_camp["shared_sources"]["stable_atom_map"])
    atom_map = json.loads(map_path.read_text())
    names = [a["stable_atom_key"] for a in atom_map]
    if names != model.d.ATOM_NAMES:
        raise ValueError("QM and Drude atom orders differ")
    xyz = np.array(
        [
            a[1:]
            for a in parse_xyz(
                checked(old_response["sources"]["target_geometry"]).read_text()
            )[0]
        ]
    )
    idx = {a: i for i, a in enumerate(names)}
    params = app.CharmmParameterSet(
        str(PROBE / "master.rtf"), str(PROBE / "master.prm"), str(PROBE / "na.prm")
    )
    table = {
        "bonds": params.bond_types,
        "angles": params.angle_types,
        "dihedrals": params.dihedral_types,
    }
    nuclear = mm.System()
    old_system = mm.XmlSerializer.deserialize(
        checked(old_response["sources"]["linear_fit_system"]).read_text()
    )
    for i in range(36):
        nuclear.addParticle(old_system.getParticleMass(i))
    bf, af, tf = (
        mm.HarmonicBondForce(),
        mm.HarmonicAngleForce(),
        mm.PeriodicTorsionForce(),
    )
    nuclear.addForce(bf)
    nuclear.addForce(af)
    nuclear.addForce(tf)
    fixed, promoted = [], []
    new_groups = {}
    for item in plan["transfer_candidates"]:
        cat = item["category"]
        atoms = item["atoms"]
        types = tuple(model.types[a.split(":")[1]] for a in atoms)
        key = min(types, types[::-1])
        v = table[cat].get(types)
        if v is None and cat == "dihedrals":
            v = table[cat].get(("X", types[1], types[2], "X"))
        local = tuple(a.split(":")[1] for a in atoms)
        promoted_atoms = {"N1", "C2", "N3", "C4", "C5", "C6", "O2", "O4"}
        if include_methyl:
            promoted_atoms.update({"C7", "CM"})
        promoted_core = (
            promote_pyrimidine
            and (pyrimidine_scope == "all" or cat in {"bonds", "angles"})
            and all(a in promoted_atoms for a in local)
        )
        promoted_hydrogen = (
            promote_hydrogen
            and cat in {"bonds", "angles"}
            and any(a.startswith("H") for a in local)
        )
        if promoted_hydrogen:
            # Equivalent methyl hydrogens share parameters across both endpoints;
            # N-methyl, C5-methyl, amide and methine environments remain distinct.
            local = tuple(
                "HCM"
                if a.startswith("HCM")
                else "HC7"
                if a in {"H51", "H52", "H53"}
                else a
                for a in local
            )
        if v is None or promoted_core or promoted_hydrogen:
            # Distinguish chemically different positions formerly sharing native
            # types (C2 and C4 carbonyls); preserve endpoint sharing as a hypothesis.
            label = (
                "-".join(min(local, local[::-1]))
                if promoted_core or promoted_hydrogen
                else "-".join(key)
            )
            if split_h6_endpoints and cat == "bonds" and set(local) == {"C6", "H6"}:
                label += "-endpoint" + atoms[0].split(":")[0]
            gid = (
                cat
                + (
                    ":drude-hydrogen-"
                    if promoted_hydrogen
                    else ":drude-pyrimidine-"
                    if promoted_core
                    else ":drude-missing-"
                )
                + label
            )
            g = new_groups.setdefault(
                gid,
                {
                    "id": gid,
                    "category": cat,
                    "types": list(key),
                    "variables": {"unassigned": None},
                    "occurrences": [],
                },
            )
            g["occurrences"].append(deepcopy(item))
            promoted.append(
                {
                    "category": cat,
                    "atoms": atoms,
                    "types": types,
                    "reason": "hydrogen-transfer-stationarity-failure"
                    if promoted_hydrogen
                    else "pyrimidine-transfer-geometry-failure"
                    if promoted_core
                    else "missing-Drude-parameter",
                }
            )
            continue
        ii = [idx[a] for a in atoms]
        if cat == "bonds":
            bf.addBond(*ii, v.req / 10, 2 * v.k * 4.184 * 100)
        if cat == "angles":
            af.addAngle(*ii, np.deg2rad(v.theteq), 2 * v.k * 4.184)
            ub = params.urey_bradley_types.get(types)
            if ub is not None and ub.k:
                bf.addBond(ii[0], ii[2], ub.req / 10, 2 * ub.k * 4.184 * 100)
        if cat == "dihedrals":
            for t in v:
                tf.addTorsion(*ii, int(t.per), np.deg2rad(t.phase), 4.184 * t.phi_k)
        fixed.append({"category": cat, "atoms": atoms, "drude_types": types})
    # Keep sp2 central-atom planar terms as declared Drude analog priors.
    # Their altered neighboring types require the downstream geometry audit;
    # they are not stereocenters and must not be assigned a chiral-basin gate.
    ip = mm.CustomTorsionForce("k*atan2(sin(theta-theta0),cos(theta-theta0))^2")
    ip.addPerTorsionParameter("k")
    ip.addPerTorsionParameter("theta0")
    for ring in (1, 2):
        atoms = [f"{ring}:{a}" for a in ("C2", "N1", "N3", "O2")]
        types = tuple(model.types[a.split(":")[1]] for a in atoms)
        v = params.improper_types[types]
        ip.addTorsion(*[idx[a] for a in atoms], [4.184 * v.k, np.deg2rad(v.phieq)])
        for labels in [("C4", "N3", "C5", "O4"), ("N1", "C6", "C2", "CM")]:
            atoms = [f"{ring}:{a}" for a in labels]
            original_types = {
                "C4": ("CD2O4A", "ND2R6C", "CD2R6J", "OD2C1B"),
                "N1": ("CD33A", "CD2O4A", "CD2R6H", "ND2R6C"),
            }[labels[0]]
            v = params.improper_types[original_types]
            ip.addTorsion(*[idx[a] for a in atoms], [4.184 * v.k, np.deg2rad(v.phieq)])
    nuclear.addForce(ip)
    plan["transfer_candidates"] = []
    plan["uncovered_parameter_groups"].extend(new_groups.values())
    plan["hypothesis_id"] = "anti-drude-corrected-graph-diagnostic-v1"
    write(root / "bonded_fit_plan.json", plan)
    write(
        root / "bonded_transfer_audit.json",
        {
            "fixed_drude_occurrences": fixed,
            "promoted_missing_occurrences": promoted,
            "planarity_analogy_priors": "MTHY C4 and N1 improper curvatures; changed neighbor types require geometry validation",
            "simulation_ready": False,
            "sources": {
                name: source(PROBE / name)
                for name in ("master.rtf", "master.prm", "na.prm")
            },
        },
    )
    (root / "nuclear_fixed_bonded.xml").write_text(mm.XmlSerializer.serialize(nuclear))
    write(
        root / "nuclear_skeleton_manifest.json",
        {
            "schema": "nadoc.photoproduct-openmm-candidate-skeleton.v1",
            "status": "candidate_incomplete_missing_bonded_terms",
            "simulation_ready": False,
            "gate_effect": "none",
            **{k: plan[k] for k in ("product_id", "model_id", "hypothesis_id")},
            "sources": {"fit_plan": source(root / "bonded_fit_plan.json")},
            "outputs": {
                "system_xml": source(root / "nuclear_fixed_bonded.xml"),
                "model_pdb": source(pdb_path),
                "stable_atom_map": source(map_path),
            },
            "scope": "Nuclear bonded terms only; adiabatic Drude nonbonded baseline added separately.",
        },
    )
    build_openmm_linear_fit_basis(
        skeleton_manifest_path=root / "nuclear_skeleton_manifest.json",
        fit_plan_path=root / "bonded_fit_plan.json",
        output_dir=root / "basis",
        torsion_periodicities=range(1, 5),
        improper_equilibrium_mode="fixed_qm_reference",
        angle_urey_bradley_mode="omit",
    )
    return old_camp, xyz


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recovery", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--promote-pyrimidine", action="store_true")
    parser.add_argument("--promote-hydrogen", action="store_true")
    parser.add_argument("--split-h6-endpoints", action="store_true")
    parser.add_argument("--include-methyl-attachments", action="store_true")
    parser.add_argument("--electrostatics", type=Path)
    parser.add_argument(
        "--pyrimidine-scope", choices=("all", "bonds-angles"), default="all"
    )
    args = parser.parse_args()
    if args.split_h6_endpoints and not args.promote_hydrogen:
        parser.error("--split-h6-endpoints requires --promote-hydrogen")
    root = args.output.resolve()
    root.mkdir(exist_ok=False)
    (root / "campaign_snapshot.py").write_text(Path(__file__).read_text())
    write(
        root / "policy.json",
        {
            "schema": "nadoc.cpd-drude-bonded-diagnostic-policy.v1",
            "simulation_ready": False,
            "gate_effect": "none",
            "scope": "User-authorized isolated bonded diagnostics; P2 graph recovery and P3 target audit remain release prerequisites.",
            "fit_partition": ["minimum", "conformer-001", "conformer-004"],
            "validation_partition": ["conformer-002", "conformer-003"],
            "finite_difference_step_angstrom": 0.0001,
            "fd_halving_relative_rms_max": 0.001,
            "energy_gradient_max_abs_error_kcal_mol_angstrom": 0.001,
            "maximum_drude_displacement_angstrom": 0.2,
            "maximum_drude_force_kcal_mol_angstrom": 0.0001,
            "new_missing_drude_terms": "Promote to fit; no additive coefficient transfer.",
            "nonbonded_convention": "Official LJ including special 1-4 terms; H6 uses CD31A/HDA1A methine analog. No water NBFIX in vacuum.",
            "promote_pyrimidine_heavy_atom_terms": args.promote_pyrimidine,
            "pyrimidine_scope": args.pyrimidine_scope,
            "include_methyl_attachments": args.include_methyl_attachments,
            "promote_hydrogen_bonds_angles": args.promote_hydrogen,
            "split_h6_endpoints": args.split_h6_endpoints,
            "h6_split_hypothesis": (
                "Prospective diagnostic: distinguish endpoint C6-H6 stiffness and equilibrium length because the asymmetric anti geometry and frozen electrostatics give conflicting shared-bond stationarity/curvature targets. Preserve all other groups, datasets, derivative tolerances and release gates. Rank must be rechecked; no parameter is set from the diagnostic frequencies."
                if args.split_h6_endpoints
                else None
            ),
            "electrostatics": source(args.electrostatics)
            if args.electrostatics
            else None,
            "acceptance": "No scientific P4 pass from this diagnostic; fit identifiability and numerical derivative checks are mandatory.",
            "sources": {
                "code": source(__file__),
                "recovered_model": source(args.recovery / "drude_model.py"),
                "invalidation": source(args.recovery / "upstream_invalidation.json"),
            },
        },
    )
    model = AdiabaticNonbonded(args.recovery, args.electrostatics)
    write(root / "graph_audit.json", model.graph_audit)
    campaign, xyz = build_bonded_basis(
        root,
        model,
        args.promote_pyrimidine,
        args.pyrimidine_scope,
        args.include_methyl_attachments,
        args.promote_hydrogen,
        args.split_h6_endpoints,
    )
    e, g = model.energy_gradient(xyz)
    finite = []
    for k in (0, 9, 21, 27, 51, 57, 65, 83, 107):
        a, b = xyz.reshape(-1).copy(), xyz.reshape(-1).copy()
        a[k] += 1e-5
        b[k] -= 1e-5
        fd = (
            model.energy_gradient(a.reshape(-1, 3))[0]
            - model.energy_gradient(b.reshape(-1, 3))[0]
        ) / 2e-5
        finite.append(
            {
                "coordinate": k,
                "analytic": float(g[k]),
                "finite_difference": fd,
                "error": float(fd - g[k]),
            }
        )
    passed = max(abs(v["error"]) for v in finite) <= 0.001
    write(
        root / "derivative_preflight.json",
        {"passed": passed, "checks": finite, "energy_kcal_mol": e},
    )
    if not passed:
        raise ValueError(
            "Adiabatic nuclear gradient failed finite-difference preflight"
        )
    from backend.parameterization.photoproduct_openmm_linear_response import (
        build_openmm_linear_response,
    )
    from backend.parameterization.photoproduct_qm import parse_xyz
    from backend.parameterization.photoproduct_response_campaign import (
        build_openmm_response_campaign,
    )

    paths = {"training": [], "validation": []}
    for part in paths:
        for item in campaign[part + "_datasets"]:
            old_r = json.loads(checked(item["response_manifest"]).read_text())
            name = Path(item["response_manifest"]["path"]).parent.name
            out = root / "responses" / name
            print("Building", part, name, flush=True)
            build_openmm_linear_response(
                fit_basis_manifest_path=root / "basis/linear_fit_basis_manifest.json",
                hessian_targets_path=checked(item["hessian_targets"]),
                output_dir=out,
                step_angstrom=0.0001,
            )
            target_xyz = np.array(
                [
                    a[1:]
                    for a in parse_xyz(
                        checked(old_r["sources"]["target_geometry"]).read_text()
                    )[0]
                ]
            )
            energy, gradient = model.energy_gradient(target_xyz)
            h = model.hessian(target_xyz, 0.0001)
            hh = model.hessian(target_xyz, 0.00005)
            error = float(np.linalg.norm(h - hh) / max(np.linalg.norm(hh), 1e-12))
            if error > 0.001:
                raise ValueError(f"Drude Hessian step-halving failed: {name}: {error}")
            hessian = (hh + hh.T) / 2
            arrpath = out / "linear_response_arrays.npz"
            with np.load(arrpath) as data:
                arrays = dict(data)
            arrays["base_gradient_kcal_mol_angstrom"] += gradient
            arrays["base_hessian_kcal_mol_angstrom2"] += hessian
            arrays["residual_gradient"] -= gradient
            rows, cols = arrays["hessian_upper_row"], arrays["hessian_upper_column"]
            arrays["residual_hessian_upper"] -= hessian[rows, cols]
            inv = np.repeat(1 / np.sqrt(arrays["masses_amu"]), 3)
            proj = arrays["rigid_body_projector"]
            arrays["projected_residual_gradient"] -= proj @ (inv * gradient)
            ph = proj @ (inv[:, None] * hessian * inv[None, :]) @ proj
            arrays["projected_residual_hessian_upper"] -= ph[rows, cols]
            np.savez_compressed(arrpath, **arrays)
            manifest = json.loads((out / "linear_response_manifest.json").read_text())
            manifest["outputs"]["linear_response_arrays"] = source(arrpath)
            manifest["adiabatic_drude_baseline"] = {
                "energy_kcal_mol": energy,
                "step_halving_relative_error": error,
                "maximum_raw_asymmetry": float(np.max(abs(hh - hh.T))),
                "policy": source(root / "policy.json"),
            }
            write(out / "linear_response_manifest.json", manifest)
            paths[part].append(out / "linear_response_manifest.json")
    result = build_openmm_response_campaign(
        training_response_paths=paths["training"],
        validation_response_paths=paths["validation"],
        output_dir=root / "response_campaign",
    )
    write(
        root / "stage_assessment.json",
        {
            "status": "bonded_response_diagnostic_complete",
            "simulation_ready": False,
            "gate_effect": "none",
            "parameter_count": result["parameter_count"],
            "maximum_drude_displacement_angstrom": model.max_displacement,
            "maximum_drude_force_kcal_mol_angstrom": model.max_drude_force,
            "next": "Inspect identifiability before quantitative fit; upstream graph/water validation remains open.",
        },
    )


if __name__ == "__main__":
    main()
