"""Replay native energies/forces and gates for the bounded shape refinement."""
import argparse
import math
import os
from pathlib import Path
import sys

import numpy as np

REPO = Path(os.environ.get("NADOC_REPO_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.readiness_fit_v3 import ROOT, ART, validate
from experiments.cpd_anti_additive import shape_fit_v2 as frozen
from experiments.cpd_anti_additive.validation_gate import read, checked, source, geometry_match
from experiments.cpd_anti_additive.sella_pilot import now, save, BOHR, projected_metrics, geometry_audit
from experiments.cpd_anti_additive.prepare_engine_v2 import geometry_check
from experiments.cpd_anti_additive.readiness_fit_v3 import layout, gate_values
from backend.parameterization.photoproduct_qm import _dihedral_degrees


def audit(output):
    import openmm as mm
    from openmm import app, unit
    assert not output.exists()
    receipt, plan = validate()
    close = read(ROOT / "assessment.json")
    points = read(checked(plan["points"])) + read(checked(plan["representatives"]))
    blocks, torsions, reps = layout(points[:24])
    psfs = {p["endpoint"]: app.CharmmPsfFile(str(Path(plan["parent"]) / f"endpoint-{p['endpoint']}" / "fragment.psf")) for p in points}
    model_reviews = []
    for record in close["history"]:
        report = read(checked(record["assessment"]))
        residual = np.load(Path(record["assessment"]["path"]).with_name("residual.npy"))
        assert np.isclose(residual @ residual, report["objective"], atol=1e-11, rtol=0)
        assert np.isclose(max(gate_values(residual, blocks, torsions, reps)), record["score"], atol=1e-11, rtol=0)
        par = frozen.parameters(checked(report["candidate"]))
        contexts, integrators = {}, []
        for endpoint, psf in psfs.items():
            system = psf.createSystem(par, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False)
            integrator = mm.VerletIntegrator(.001)
            contexts[endpoint] = mm.Context(system, integrator, mm.Platform.getPlatformByName("Reference"))
            integrators.append(integrator)
        rows, energies, rep_metrics = [], [], []
        for i, (p, result) in enumerate(zip(points, report["results"])):
            assert p["case_id"] == result["case_id"]
            raw = np.load(checked(result["raw_evaluations"]))
            q = np.array(p["geometry_bohr"]) * BOHR
            assert np.array_equal(raw["coordinates_A"][0], q)
            errors = []
            context = contexts[p["endpoint"]]
            for x, gradient, energy in zip(raw["coordinates_A"], raw["gradients_kcal_A"], raw["energies_kcal"]):
                context.setPositions(x * unit.angstrom)
                state = context.getState(getEnergy=True, getForces=True)
                native_e = state.getPotentialEnergy().value_in_unit(unit.kilocalorie_per_mole)
                native_g = -np.asarray(state.getForces(asNumpy=True).value_in_unit(unit.kilocalorie_per_mole / unit.angstrom))
                errors.append((abs(native_e - energy), float(abs(native_g - gradient).max())))
            assert np.max(errors) < 1e-7
            x = np.loadtxt(checked(result["final_geometry"]))
            assert np.array_equal(x, raw["coordinates_A"][-1])
            assert abs(native_e - result["energy_kcal"]) < 1e-8
            constrained = p["branch"] != "remote-unconstrained"
            assert constrained == result["constraint_applied"]
            torsion_error = abs((_dihedral_degrees(*x[p["record"]["torsion_indices"]]) - p["actual_dihedral_deg"] + 180) % 360 - 180)
            assert np.isclose(torsion_error, result["torsion_difference_deg"], atol=1e-10, rtol=0)
            forces = ([projected_metrics(x, native_g, p["record"]["torsion_indices"], h=h)["max_projected_atom_gradient"] for h in (1e-4, 1e-5, 1e-6)]
                      if constrained else [float(np.linalg.norm(native_g, axis=1).max())])
            chemistry = geometry_check(psfs[p["endpoint"]], q, x)
            match = geometry_match(q, x, p["elements"], p["heavy_torsion_indices"])
            for k, value in match.items():
                assert np.isclose(value, result["branch_descriptors"][k], rtol=0, atol=1e-10)
            numerical = (max(forces) < .001 and chemistry["stereo_preserved"] and chemistry["graph_distances_passed"]
                         and (not constrained or torsion_error < .01) and result["native_optimizer_converged"])
            assert numerical == result["independent_stationarity_and_chemistry_passed"]
            shape = match["basin_rmsd_A"] <= .25 and match["basin_max_torsion_deg"] <= 20
            assert shape == result["branch_descriptor_match"]
            if i >= 24:
                rep_metrics.append(frozen.representative_geometry(psfs[p["endpoint"]], p["atom_map"], q, x))
            else:
                assert np.allclose(residual[blocks[i+1]], frozen.aligned_residual(q, x, p["elements"]) / (.25 * math.sqrt(24)), atol=1e-11, rtol=0)
                assert abs(residual[torsions][i] * 20 * math.sqrt(24) - match["basin_max_torsion_deg"]) < 1e-9
            rows.append(dict(case_id=p["case_id"], evaluations=len(errors), max_energy_replay_error_kcal=max(v[0] for v in errors),
                             max_force_replay_error_kcal_A=max(v[1] for v in errors), max_projected_forces=forces,
                             numerically_valid=bool(numerical), shape_passed=bool(shape), **match,
                             final_geometry=result["final_geometry"], raw_evaluations=result["raw_evaluations"]))
            energies.append(native_e)
        energy_errors = frozen.relative(energies[:24], points[:24]) - np.array([p["qm_relative_kcal_mol"] for p in points[:24]])
        rms = float(np.sqrt(np.mean(energy_errors ** 2)))
        legacy_rms = float(np.sqrt(np.mean(energy_errors[:23] ** 2)))
        assert abs(legacy_rms-report["energy"]["legacy23_rmse_kcal"]) < 1e-8
        maximum = float(abs(energy_errors).max())
        assert np.allclose(residual[:24] * math.sqrt(24), energy_errors, atol=1e-8, rtol=0)
        assert np.allclose(residual[reps] * np.r_[np.full(3, .03), np.full(3, 3.)] * math.sqrt(3),
                           [v["max_bond_A"] for v in rep_metrics] + [v["max_angle_deg"] for v in rep_metrics], atol=1e-9, rtol=0)
        passed = all(v["numerically_valid"] for v in rows) and all(v["shape_passed"] for v in rows[:24]) and rms <= 1 and legacy_rms <= 1 and maximum <= 2 and all(v["passed"] for v in rep_metrics)
        assert passed == report["development_parameter_passed"]
        model_reviews.append(dict(number=record["number"], assessment=record["assessment"], rows=rows,
                                  energy_rmse_kcal=rms, energy_max_abs_kcal=maximum, representative_geometry=rep_metrics,
                                  development_parameter_passed=bool(passed)))
        contexts.clear()
        del context, integrators, integrator

    chosen = read(checked(close["selected"]["assessment"]))
    fixtures = {label: frozen.BASE / label for label in ("endpoint-1", "endpoint-2", "core", "endpoint-2-remote", "two-nucleosides")}
    exports = frozen.export_check(checked(plan["baseline_parameters"]), checked(chosen["candidate"]), plan["variables"], chosen["parameters"], fixtures)
    qm_rows = []
    for p in points[19:23]:
        folder = ART / "cpd-anti-prospective-qm-v2-r1" / p["case_id"]
        last = read(folder / "progress.json")["evaluations"][-1]
        result = read(checked(last["result"]))
        native_plan = read(folder / "plan.json")
        coords = np.load(checked(result["geometry"]))
        assert np.array_equal(coords, p["geometry_bohr"])
        assert result["energy"] == p["qm_energy_hartree"]
        metrics = [projected_metrics(coords, result["gradient"], p["record"]["torsion_indices"], h=h) for h in (1e-4, 1e-5, 1e-6)]
        assert all(m["max_projected_atom_gradient"] < 1.5e-5 and m["rms_projected_atom_gradient"] < 1e-5 for m in metrics)
        chemistry = geometry_audit(coords, native_plan, read(checked(native_plan["record"]["model_graph"])))
        assert chemistry["chemistry_passed"] and chemistry["constraint_passed"]
        checked(result["native"])
        qm_rows.append(dict(case_id=p["case_id"], actual_result=last["result"], actual_native=result["native"],
                            projected_metrics=metrics, chemistry=chemistry, target_coordinates_verified=True))
    validate()
    save(output, dict(at=now(), verifier=source(Path(__file__)), closeout=source(ROOT / "assessment.json"), models=model_reviews,
                      total_native_evaluations=sum(v["evaluations"] for m in model_reviews for v in m["rows"]),
                      selected_export_checks=exports, prospective_target_metadata_sidecar=qm_rows,
                      all_checks_passed=True, historical_hashes_unchanged=True, no_new_optimization=True,
                      minimum_certified=False, simulation_ready=False))
    print(dict(models=len(model_reviews), native_evaluations=sum(v["evaluations"] for m in model_reviews for v in m["rows"]),
               selected=close["selected"]["number"], development_parameter_passed=close["development_parameter_passed"], all_checks_passed=True), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    audit(parser.parse_args().output)
