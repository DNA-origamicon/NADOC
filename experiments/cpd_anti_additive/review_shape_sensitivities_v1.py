"""Audit frozen shape targets and local parameter response without new potential calls.

Linear minimax proposals are diagnostics, not evaluated fits or feasibility proofs
for the nonlinear molecular model. Historical artifacts are never rewritten.
"""
import argparse
import math
import os
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import minimize

REPO = Path(os.environ.get("NADOC_REPO_ROOT", Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.sella_pilot import BOHR, now, save, projected_metrics
from experiments.cpd_anti_additive.shape_fit_v2 import aligned_residual

ART = REPO / ".development-artifacts"


def layout(points):
    blocks = [slice(0, 23)]
    cursor = 23
    for p in points:
        length = 3 * sum(e != "H" for e in p["elements"])
        blocks.append(slice(cursor, cursor + length))
        cursor += length
    return blocks, slice(cursor, cursor + 23), slice(cursor + 23, cursor + 29)


def gate_values(r, blocks, torsions, reps):
    """Ratios to the existing gates; all ratios <= 1 is linearized feasibility."""
    energy = r[blocks[0]] * math.sqrt(23)
    shapes = [np.linalg.norm(r[b]) * math.sqrt(23) for b in blocks[1:]]
    return np.r_[np.linalg.norm(energy) / math.sqrt(23), abs(energy) / 2,
                 shapes, abs(r[torsions]) * math.sqrt(23),
                 abs(r[reps]) * math.sqrt(3)]


def propose(r, jac, x, radius, blocks, torsions, reps):
    """Convex epigraph problem using squared norms and analytic derivatives."""
    norm_blocks = [(blocks[0], 1.)] + [(b, 23.) for b in blocks[1:]]
    scalar_ids = np.r_[np.arange(23), np.arange(torsions.start, torsions.stop),
                       np.arange(reps.start, reps.stop)]
    scales = np.r_[np.full(23, math.sqrt(23) / 2),
                   np.full(23, math.sqrt(23)), np.full(6, math.sqrt(3))]

    def constraints(z):
        v = r + jac @ z[:-1]
        norms = [z[-1] - scale * (v[b] @ v[b]) for b, scale in norm_blocks]
        return np.r_[norms, z[-1] - (v[scalar_ids] * scales) ** 2]

    def derivative(z):
        v = r + jac @ z[:-1]
        rows = [-2 * scale * (v[b] @ jac[b]) for b, scale in norm_blocks]
        rows.extend(-2 * v[scalar_ids, None] * scales[:, None] ** 2 * jac[scalar_ids])
        return np.c_[np.array(rows), np.ones(len(rows))]

    z0 = np.r_[np.zeros(len(x)), max(gate_values(r, blocks, torsions, reps)) ** 2]
    result = minimize(lambda z: z[-1] + 1e-8 * (z[:-1] @ z[:-1]), z0,
                      jac=lambda z: np.r_[2e-8 * z[:-1], 1.], method="SLSQP",
                      bounds=list(zip(np.maximum(-radius, -5 - x),
                                      np.minimum(radius, 5 - x))) + [(0, None)],
                      constraints=[dict(type="ineq", fun=constraints, jac=derivative)],
                      options=dict(maxiter=400, ftol=1e-10))
    v = r + jac @ result.x[:-1]
    return dict(radius_kcal=radius, success=bool(result.success), message=result.message,
                iterations=result.nit, minimum_constraint_slack=float(min(constraints(result.x))),
                predicted_max_gate_ratio=float(max(gate_values(v, blocks, torsions, reps))),
                predicted_objective=float(v @ v), parameters=(x + result.x[:-1]).tolist(),
                step=result.x[:-1].tolist(), predicted_shapes_A=[float(np.linalg.norm(v[b]) * .25 * math.sqrt(23)) for b in blocks[1:]],
                nonlinear_feasibility_established=False)


def run(out):
    out.mkdir(parents=True, exist_ok=False)
    plan_path = ART / "cpd-anti-shape-inputs-v2-r2/receipt.json"
    plan = read(plan_path)
    points = read(checked(plan["points"]))
    blocks, torsions, reps = layout(points)
    refs = [source(plan_path), plan["points"]]
    reports, residuals = {}, {}
    for number in range(1, 70):
        root = ART / ("cpd-anti-shape-fit-v2-r2" if number <= 33 else "cpd-anti-shape-fit-recovery-v1") / f"model-{number:03d}"
        report = read(root / "assessment.json")
        r = np.load(root / "residual.npy")
        assert report["numerically_valid"] and len(report["results"]) == 26
        assert np.isclose(r @ r, report["objective"], atol=1e-12, rtol=0)
        for b, p, result in zip(blocks[1:], points, report["results"]):
            assert p["case_id"] == result["case_id"]
            x = np.loadtxt(checked(result["final_geometry"]))
            expected = aligned_residual(np.array(p["geometry_bohr"]) * BOHR, x, p["elements"]) / (.25 * math.sqrt(23))
            assert np.allclose(expected, r[b], atol=1e-11, rtol=0)
            assert np.isclose(np.linalg.norm(r[b]) * .25 * math.sqrt(23), result["branch_descriptors"]["basin_rmsd_A"], atol=1e-11, rtol=0)
        assert np.isclose(np.linalg.norm(r[:23]), report["energy"]["rmse_kcal"], atol=1e-11)
        assert np.allclose(r[torsions] * 20 * math.sqrt(23), [v["branch_descriptors"]["basin_max_torsion_deg"] for v in report["results"][:23]])
        assert np.allclose(r[reps] * np.r_[np.full(3, .03), np.full(3, 3.)] * math.sqrt(3),
                           [v["max_bond_A"] for v in report["representative_geometry"]] + [v["max_angle_deg"] for v in report["representative_geometry"]])
        reports[number], residuals[number] = report, r
        refs.extend([source(root / "assessment.json"), source(root / "residual.npy")])

    provenance = []
    for p in points[19:]:
        root = ART / "cpd-anti-prospective-qm-v2-r1" / p["case_id"]
        progress = read(root / "progress.json")
        last = progress["evaluations"][-1]
        result = read(checked(last["result"]))
        native_plan = read(root / "plan.json")
        coords = np.load(checked(result["geometry"]))
        assert np.array_equal(coords, np.array(p["geometry_bohr"]))
        assert last["energy"] == p["qm_energy_hartree"]
        assert read(root / "assessment.json")["joint_optimizer_converged"]
        # Canonical native metadata is recorded beside, never over, frozen inherited fields.
        row = dict(case_id=p["case_id"], actual_result=last["result"], actual_geometry=result["geometry"],
                   actual_plan=source(root / "plan.json"), actual_progress=source(root / "progress.json"),
                   actual_optimizer=native_plan["optimizer"], actual_constrained=True,
                   actual_force_metrics={k: last[k] for k in ("max_projected_atom_gradient", "rms_projected_atom_gradient")},
                   coordinates_bitwise_match=True, energy_exactly_matches=True,
                   inherited_template_metadata_fields=["qm_source", "geometry_source", "native", "final_result", "acquisition_plan", "independent_review", "constrained", "cached_gradient_metrics"],
                   runtime_constraint_correct=all(reports[n]["results"][points.index(p)]["constraint_applied"] for n in reports))
        provenance.append(row)
        refs.extend([last["result"], result["geometry"], row["actual_plan"], row["actual_progress"], source(root / "assessment.json")])

    centers = []
    for center in (1, 24, 47):
        x = np.array(reports[center]["parameters"])
        r = residuals[center]
        cols, probe_changes = [], []
        for j in range(22):
            number = center + j + 1
            step = np.array(reports[number]["parameters"]) - x
            assert np.count_nonzero(step) == 1 and abs(abs(step[j]) - .02) < 1e-12
            cols.append((residuals[number] - r) / step[j])
            motions = [np.linalg.norm((residuals[number] - r)[b]) * .25 * math.sqrt(23) for b in blocks[1:]]
            probe_changes.append(dict(index=j, variable=plan["variables"][j],
                                      maximum_aligned_motion_A=float(max(motions)),
                                      case_id=points[int(np.argmax(motions))]["case_id"]))
        jac = np.array(cols).T
        np.save(out / f"jacobian-{center:03d}.npy", jac)
        singular = np.linalg.svd(jac, compute_uv=False)
        proposals = [propose(r, jac, x, radius, blocks, torsions, reps) for radius in (.02, .1, .25, .5, 1.)]
        centers.append(dict(center=center, objective=reports[center]["objective"],
                            current_max_gate_ratio=float(max(gate_values(r, blocks, torsions, reps))),
                            singular_values=singular.tolist(), probes=probe_changes, linear_proposals=proposals))
        if center == 47:
            selected_x = np.array(reports[61]["parameters"])
            selected = [propose(residuals[61], jac, selected_x, radius, blocks, torsions, reps) for radius in (.02, .1, .25, .5, 1.)]
            # A withheld multivariable step already exposes the limits of local response.
            root = ART / "cpd-anti-shape-fit-recovery-v1/model-070"
            x70 = np.array(read(root / "request.json")["parameters"])
            predicted = r + jac @ (x70 - x)
            actual = read(root / "progress.json")[:23]
            predicted_shapes = [float(np.linalg.norm(predicted[b]) * .25 * math.sqrt(23)) for b in blocks[1:]]
            actual_shapes = [v["branch_descriptors"]["basin_rmsd_A"] for v in actual]
            withheld = dict(model=70, step_max_kcal=float(max(abs(x70 - x))),
                            predicted_shapes_A=predicted_shapes, actual_shapes_A=actual_shapes,
                            max_shape_prediction_error_A=float(max(abs(np.array(predicted_shapes) - actual_shapes))),
                            actual_shape_failures=sum(not v["branch_descriptor_match"] for v in actual),
                            full_objective_available=False)
    result = dict(at=now(), script=source(Path(__file__)), sources=refs,
                  verified_models=69, verified_coordinate_comparisons=69 * 23,
                  target_provenance=provenance, centers=centers,
                  selected61_linear_proposals=selected,
                  selected61_derivative_caveat="Jacobian at center47, .02 kcal/mol away; no Jacobian at model61 was acquired.",
                  withheld_prediction=withheld, no_new_potential_evaluations=True,
                  no_historical_inputs_modified=True, nonlinear_feasibility_established=False,
                  minimum_certified=False, simulation_ready=False)
    save(out / "assessment.json", result)
    print(dict(verified_models=69, corrected_provenance_records=4,
               selected61_predictions=[(v["radius_kcal"], v["predicted_max_gate_ratio"], v["success"]) for v in selected],
               largest_probe_motions=[max(v["maximum_aligned_motion_A"] for v in c["probes"]) for c in centers],
               withheld_max_shape_prediction_error_A=withheld["max_shape_prediction_error_A"]), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    run(parser.parse_args().output)
