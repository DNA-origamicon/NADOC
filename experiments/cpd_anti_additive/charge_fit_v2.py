"""Fit CHARMM water minima and HF dipoles on a frozen, exposed anti dataset."""

import argparse
import json
from pathlib import Path
import sys
import warnings

import numpy as np
from scipy.optimize import minimize

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.validation_gate import checked, read, source, require_fit_ready
from experiments.cpd_anti_additive.preliminary_protocol import POLICY, STATE, begin_round, lock_inputs
from experiments.cpd_published_comparator.reconstruct import BASE, FF
from backend.parameterization.photoproduct_qm import parse_xyz
from backend.parameterization.photoproduct_nonbonded_fit import _interaction_row, _quadratic_grid_minimum

ART = REPO / ".development-artifacts"
DEBYE = 4.80320471257


def water_terms(xyz, lj, waters, nb):
    distances = np.linalg.norm(waters[:, None, :, :] - xyz[None, :, None, :], axis=-1)
    if np.any(distances <= 0):
        raise ValueError("Overlapping water probe")
    rows = (332.063713299 * np.array([-.834, .417, .417]) / distances).sum(axis=2)
    types = ["OGTIP3", "HGTIP3", "HGTIP3"]
    eps = np.sqrt(np.abs(np.array([x["epsilon_kcal_mol"] for x in lj])[:, None]
                        * np.array([nb[t]["epsilon_kcal_mol"] for t in types])[None, :]))
    rmin = np.array([x["rmin_half_angstrom"] for x in lj])[:, None] + np.array(
        [nb[t]["rmin_half_angstrom"] for t in types])[None, :]
    power = (rmin[None, :, :] / distances)**6
    return rows, (eps[None, :, :] * (power**2-2*power)).sum(axis=(1, 2))


def minimum(distances, energies):
    i = int(np.argmin(energies))
    if i in (0, len(energies)-1):
        return float(distances[i]), float(energies[i]), False
    # Center coordinates for a stable three-point quadratic interpolation.
    z = np.asarray(distances[i-1:i+2])-distances[i]
    a, b, c = np.polyfit(z, energies[i-1:i+2], 2)
    dx = float(np.clip(-b/(2*a), z[0], z[-1])) if a > 0 else 0.
    return float(distances[i]+dx), float(a*dx*dx+b*dx+c), bool(a > 0)


def prepare():
    from openmm import app
    root = ART / "cpd-anti-charge-minima-inputs-v2"
    root.mkdir(exist_ok=False)
    policy = read(POLICY)["electrostatics"]
    refs = []

    def pin(path):
        item = source(path)
        refs.append(item)
        return Path(item["path"])

    forcefields = [BASE/"top_all36_na.rtf", BASE/"par_all36_na.prm",
        FF/"top_all36_cgenff.rtf", FF/"par_all36_cgenff.prm",
        ART/"cpd-published-comparator-v1/comparator_last.prm"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        params = app.CharmmParameterSet(*(str(pin(p)) for p in forcefields))
    nb = {k: dict(epsilon_kcal_mol=v.epsilon, rmin_half_angstrom=v.rmin)
          for k, v in params.atom_types_str.items()}
    specs = [("endpoint-1-original", 1, "cpd-anti-boundary-esp-v2", "cpd-anti-water-curves-v2"),
             ("endpoint-2-original", 2, "cpd-anti-boundary-esp-v2", "cpd-anti-water-curves-v2"),
             ("endpoint-2-remote", 2, "cpd-anti-remote-esp-v1", "cpd-anti-remote-water-curves-v1")]
    cases = []
    curve_ids = []
    for label, endpoint, esp_root, water_root in specs:
        esp_folder = ART/esp_root/f"endpoint-{endpoint}"
        esp = read(pin(esp_folder/"esp_audit.json"))
        if esp.get("passed") is not True or esp["dipole"]["units"] != "atomic_unit_e_bohr":
            raise ValueError("Missing audited HF dipole")
        job = read(pin(checked(esp["job_manifest"])))
        xyz_path = pin(checked(job["source_xyz"]))
        atoms, _ = parse_xyz(xyz_path.read_text())
        xyz = np.asarray([a[1:] for a in atoms])
        names = job["atom_map"]
        assert len(names) == len(atoms) == 49 and len(set(names)) == 49
        baseline = "cpd-anti-additive-boundary-baseline-v1" if endpoint == 1 else "cpd-anti-additive-boundary-endpoint2-v1"
        psf = app.CharmmPsfFile(str(pin(ART/baseline/f"endpoint-{endpoint}/fragment.psf")))
        charge = np.array([a.charge for a in psf.atom_list])
        assert abs(charge.sum()) < 1e-8
        lj = [nb[a.attype] for a in psf.atom_list]
        assert all((a.attype, t) not in params.nbfix_types and (t, a.attype) not in params.nbfix_types
                   for a in psf.atom_list for t in ("OGTIP3", "HGTIP3"))
        grid = np.loadtxt(pin(checked(esp["grid"])))
        potential = np.loadtxt(pin(checked(esp["potentials"])))
        if potential.ndim > 1:
            potential = potential[:, -1]
        matrix = .529177210903 / np.linalg.norm(grid[:, None, :]-xyz[None, :, :], axis=2)
        curves = read(pin(ART/water_root/"assessment.json"))["records"]
        target_curves = []
        for curve in curves:
            ident = curve["identity"]
            if ident["model_id"] != job["model_id"]:
                continue
            if label.endswith("remote") and ident["probe_id"] == "1-O4":
                continue
            if curve.get("passed") is not True:
                raise ValueError(f"Required curve failed: {label}/{ident['probe_id']}")
            ds, energies = [], []
            for point in curve["points"]:
                folder = Path(point["job_dir"])
                manifest = pin(folder/"job_manifest.json")
                assert source(manifest)["sha256"] == point["job_manifest_sha256"]
                assert source(pin(folder/"output.dat"))["sha256"] == point["output_sha256"]
                water_job = read(manifest)
                assert water_job["source_xyz"]["sha256"] == source(xyz_path)["sha256"]
                assert water_job["atom_map"] == names and water_job["method"] == "hf"
                assert water_job["energy_scale"] == 1.16 and not water_job["counterpoise_corrected"]
                assert water_job["distance_offset_angstrom"] == -.2
                pin(checked(water_job["input"]))
                ds.append(point["distance_angstrom"])
                energies.append(point["scaled_target_kcal_mol"])
            distance, energy = _quadratic_grid_minimum(np.array(ds), np.array(energies))
            wat, _ = parse_xyz(pin(checked(water_job["water_xyz"])).read_text())
            water = np.asarray([a[1:] for a in wat])
            target = xyz[names.index(water_job["target_atom"])]
            probe = {"O": 0, "H1": 1, "H2": 2}[water_job["probe_atom"]]
            vector = water[probe]-target
            old_distance = np.linalg.norm(vector)
            direction = vector/old_distance
            lo, hi, step = policy["mm_distance_grid_A"]
            mm_ds = np.arange(lo, hi+step/2, step)
            waters = water[None, :, :] + (mm_ds-old_distance)[:, None, None]*direction[None, None, :]
            rows, lennard = water_terms(xyz, lj, waters, nb)
            # Independent reference implementation for vectorization/units.
            idx = int(np.argmin(abs(mm_ds-distance)))
            reference_row, reference_lj = _interaction_row(xyz, lj, waters[idx], nb)
            assert np.max(abs(rows[idx]-reference_row)) < 1e-9
            assert abs(lennard[idx]-reference_lj) < 1e-8
            case_id = f"{label}/{ident['probe_id']}"
            curve_ids.append(case_id)
            target_curves.append(dict(id=case_id, target_distance_A=distance-.2,
                target_energy_kcal=energy, distances_A=mm_ds.tolist(),
                rows=rows.tolist(), lj_kcal=lennard.tolist()))
        cases.append(dict(id=label, endpoint=endpoint, names=names, xyz_A=xyz.tolist(),
            charges=charge.tolist(), dipole_debye=(np.array(esp["dipole"]["vector"])*2.541746473).tolist(),
            esp_matrix=matrix.tolist(), esp_values=potential.tolist(), curves=target_curves))
    assert [len(c["curves"]) for c in cases] == [6, 6, 5]
    pin(ART/"cpd-anti-remote-water-extension-v2/contact_review.json")
    variable_keys = sorted(k for k in set(cases[0]["names"]) & set(cases[1]["names"])
        if "'" not in k and k.split(":")[1] not in
        ("CM", "HCM1", "HCM2", "HCM3", "H6", "H51", "H52", "H53"))
    assert len(variable_keys) == 20
    dataset = root/"dataset.json"
    dataset.write_text(json.dumps(dict(cases=cases, variable_keys=variable_keys,
        exposure="All development; not blind validation", sources=refs)))
    unique = {ref["path"]: ref for ref in refs}
    receipt = dict(stage="electrostatics", ready=True, case_ids=curve_ids + [c["id"]+"/dipole" for c in cases],
        dataset=source(dataset), artifacts=[source(dataset), source(Path(__file__))]+list(unique.values()),
        target_count=dict(curves=17, dipoles=3), excluded="Remote 1-O4 mixed-site curve")
    (STATE/"electrostatics_inputs.json").write_text(json.dumps(receipt, indent=2)+"\n")
    lock_inputs("electrostatics", STATE/"electrostatics_inputs.json")
    print(json.dumps(dict(dataset=str(dataset), curves=curve_ids, variables=variable_keys,
                          native_evaluations=0, fitting_started=False), indent=2))


def load_dataset(path):
    data = read(path)
    keys = data["variable_keys"]
    for case in data["cases"]:
        for key in ("xyz_A", "charges", "dipole_debye", "esp_matrix", "esp_values"):
            case[key] = np.asarray(case[key])
        mapping = np.zeros((len(case["names"]), len(keys)))
        for j, key in enumerate(keys):
            mapping[case["names"].index(key), j] = 1
        case["mapping"] = mapping
        for curve in case["curves"]:
            for key in ("rows", "distances_A", "lj_kcal"):
                curve[key] = np.asarray(curve[key])
    return data


def evaluate(delta, data):
    energy, distances, dipole, records = [], [], [], []
    for case in data["cases"]:
        q = case["charges"] + case["mapping"]@delta
        curves = []
        for curve in case["curves"]:
            r, e, bracketed = minimum(curve["distances_A"], curve["rows"]@q+curve["lj_kcal"])
            de, dr = e-curve["target_energy_kcal"], r-curve["target_distance_A"]
            energy.append(de/.2)
            distances.append(dr/.1)
            curves.append(dict(id=curve["id"], energy_error_kcal=de, distance_error_A=dr,
                               mm_distance_A=r, mm_energy_kcal=e, bracketed=bracketed))
        mu = q@case["xyz_A"]*DEBYE
        diff = mu-case["dipole_debye"]
        dipole.extend(diff/.5)
        esp = case["esp_matrix"]@q-case["esp_values"]
        records.append(dict(id=case["id"], names=case["names"], charges_e=q.tolist(),
            net_charge_e=float(q.sum()), dipole_vector_debye=mu.tolist(),
            dipole_vector_error_debye=float(np.linalg.norm(diff)),
            esp_relative_rmse=float(np.linalg.norm(esp)/np.linalg.norm(case["esp_values"])), water=curves))
    residual = np.r_[np.asarray(energy)/np.sqrt(len(energy)),
        np.asarray(distances)/np.sqrt(len(distances)), np.asarray(dipole)/np.sqrt(len(dipole)),
        .2*delta/.1/np.sqrt(len(delta))]
    return residual, records


def run(root):
    require_fit_ready(stage="electrostatics")
    policy, receipt, number = begin_round("electrostatics", root)
    root.mkdir(exist_ok=False)
    (root/"executed_source.py").write_text(Path(__file__).read_text())
    dataset = checked(receipt["dataset"])
    data = load_dataset(dataset)
    settings = policy["electrostatics"]
    _, baseline = evaluate(np.zeros(len(data["variable_keys"])), data)
    history = []

    def objective(delta):
        residual, _ = evaluate(delta, data)
        return float(residual@residual)

    def callback(delta):
        value = objective(delta)
        history.append(value)
        (root/"progress.json").write_text(json.dumps(dict(iterations=len(history), objective=value)))

    result = minimize(objective, np.zeros(len(data["variable_keys"])), method="SLSQP",
        bounds=[(-.15, .15)]*len(data["variable_keys"]),
        constraints=[dict(type="eq", fun=lambda q: q.sum(), jac=lambda q: np.ones(len(q)))],
        callback=callback, options=dict(maxiter=settings["max_optimizer_iterations"], ftol=1e-10))
    residual, records = evaluate(result.x, data)
    water = [w for r in records for w in r["water"]]
    constraints = bool(abs(result.x.sum()) < 1e-8 and np.max(abs(result.x)) <= .15000001)
    passed = bool(result.success and constraints and len(water) == 17 and all(
        w["bracketed"] and abs(w["energy_error_kcal"]) <= settings["maximum_minimum_energy_error_kcal"]
        and abs(w["distance_error_A"]) <= settings["maximum_minimum_distance_error_A"] for w in water))
    report = dict(policy=source(POLICY), dataset=source(dataset), round=number,
        optimizer_success=bool(result.success), optimizer_message=str(result.message),
        iterations=result.nit, objective=float(residual@residual), constraints_passed=constraints,
        water_passed=passed, charge_shifts_e=dict(zip(data["variable_keys"], result.x.tolist())),
        records=records, baseline=baseline, exposure="Development only",
        geometry_validation_pending=True, simulation_ready=False)
    (root/"assessment.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(dict(optimizer_success=report["optimizer_success"], water_passed=passed,
        max_water_energy_error_kcal=max(abs(w["energy_error_kcal"]) for w in water),
        max_water_distance_error_A=max(abs(w["distance_error_A"]) for w in water),
        iterations=result.nit), indent=2))
    if not result.success or not constraints:
        raise RuntimeError("Charge optimization/numerical constraints failed; retain result")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "run"])
    parser.add_argument("--root", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    else:
        if args.root is None:
            parser.error("run requires --root")
        run(args.root.resolve())
