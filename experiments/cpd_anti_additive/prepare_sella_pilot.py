"""Freeze a fresh Sella attempt and verify its interface without new QM."""

import argparse
import importlib.metadata as metadata
import os
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.sella_pilot import (
    BOHR, FORCE_FACTOR, HARTREE_EV, geometry_audit, now, projected_metrics, save, xyz_text,
)
from experiments.cpd_anti_additive.validation_gate import checked, read, source


def prepare(root):
    import ase
    from ase import Atoms
    from ase.calculators.calculator import Calculator, all_changes
    import psi4
    import sella
    from sella import Constraints, Sella

    root.mkdir(parents=True, exist_ok=False)
    artifact = REPO / ".development-artifacts"
    original = artifact / "cpd-anti-lower-basin-profile-v1/endpoint-2-+15-lower-qm-basin/plan.json"
    old = read(original)
    graph = read(checked(old["record"]["model_graph"]))
    checked(old["record"]["scan_plan"])
    checked(old["seed_reference"])
    if [a["element"] for a in graph["atoms"]] != old["elements"] or graph["formal_charge"] != 0:
        raise ValueError("Graph/atom order/charge mismatch")
    crosslinks = {tuple(sorted(b["atoms"])) for b in graph["bonds"]
                 if b["atoms"][0].split(":")[0] != b["atoms"][1].split(":")[0]}
    if crosslinks != {("1:C5", "2:C6"), ("1:C6", "2:C5")}:
        raise ValueError("Unexpected anti crosslinks")
    runtime_files = sorted(Path(sella.__file__).parent.rglob("*.py"))
    runtime_files += [Path(ase.__file__).parent / name for name in
                      ("atoms.py", "calculators/calculator.py", "optimize/optimize.py")]
    runtime_files += [REPO / "experiments/cpd_anti_additive/validation_gate.py",
                      REPO / "backend/parameterization/photoproduct_qm.py"]
    plan = dict(schema="nadoc.cpd-anti-sella-pilot.v1", created_at=now(),
        scope="Fresh Sella constrained acquisition; no fitting, Hessian certification or MD",
        record=old["record"], elements=old["elements"], geometry_bohr=old["geometry_bohr"],
        method=old["method"], options=old["options"], psi4_version=psi4.__version__,
        versions={name: metadata.version(name) for name in
                  ("sella", "ase", "jax", "jaxlib", "numpy", "scipy", "ml_dtypes", "opt_einsum")},
        runtime_python=sys.executable, runtime_sources=[source(p) for p in runtime_files],
        sources=[source(original), old["record"]["model_graph"], old["record"]["scan_plan"],
                 old["seed_reference"], source(REPO/"experiments/cpd_anti_additive/preliminary_policy_v2.json")],
        seed_definition="Original +15 lower-basin seed before any of its 60-step trajectory; no endpoint restart",
        reuse_prior_gradients=False, reuse_optimizer_state=False, reuse_hessian=False,
        max_new_gradients=60, max_continuations=0, wall_seconds=21600,
        expected_seconds=10800, threads=4, memory_gib=6, service_memory_gib=10,
        scratch_dir=str(Path("/home/jojo/.cache/nadoc-qm")/root.name),
        limits=dict(max_gradient=1.5e-5, rms_gradient=1e-5, torsion_error_deg=.01),
        optimizer=dict(order=0, internal=True, eig=False, delta0=.1,
                       constraints_tol=1e-8, refine_initial_hessian=False, max_cpu_threads=1),
        intermediate_constraints="Report torsion deviations; final tolerance remains .01 degree. Chemistry screens apply to every trial.",
        minimum_certified=False, simulation_ready=False)
    audit = geometry_audit(np.array(plan["geometry_bohr"]), plan, graph)
    if not audit["chemistry_passed"] or not audit["constraint_passed"]:
        raise ValueError("Original seed failed identity/constraint screen")
    save(root/"plan.json", plan)
    (root/"starting.xyz").write_text(xyz_text(plan["elements"], plan["geometry_bohr"], plan["seed_definition"]))
    save(root/"starting_audit.json", audit)
    shutil.copyfile(__file__, root/"preparation_source.py")
    shutil.copyfile(REPO/"experiments/cpd_anti_additive/sella_pilot.py", root/"executed_source.py")

    # Reproduce the previous failed gradient with Sella's independently implemented normal.
    cached = artifact / "cpd-anti-default-constraint-v2/evaluation-026/result.json"
    result = read(cached)
    x = np.load(checked(result["geometry"]))
    checked(result["native"])
    atoms = Atoms(plan["elements"], positions=x*BOHR)
    constraint = Constraints(atoms)
    indices = plan["record"]["torsion_indices"]
    constraint.fix_dihedral(tuple(indices))
    normal = constraint.jacobian()[0].reshape(x.shape)
    gradient = np.array(result["gradient"])
    projected = gradient-normal*np.sum(normal*gradient)/np.sum(normal**2)
    maximum = float(np.linalg.norm(projected, axis=1).max())
    independent = projected_metrics(x, gradient, indices)
    if abs(maximum-independent["max_projected_atom_gradient"]) > 1e-10:
        raise ValueError("Sella constraint normal differs from independent Cartesian derivative")
    sella_angle = float(np.degrees(constraint.calc()[0]))
    if abs((sella_angle-plan["record"]["target_degrees"]+180) % 360-180) > .01:
        raise ValueError("Sella dihedral sign/convention mismatch")
    direction = np.linspace(-1., 1., x.size).reshape(x.shape)
    direction /= np.linalg.norm(direction)
    # Linear cached-energy model: derivative in eV/angstrom must equal negative ASE force.
    h = 1e-5
    energy_difference = (np.sum(gradient*(direction*h/BOHR))*HARTREE_EV -
                         np.sum(gradient*(-direction*h/BOHR))*HARTREE_EV)/(2*h)
    force_derivative = np.sum(gradient*FORCE_FACTOR*direction)
    if not np.isclose(energy_difference, force_derivative, atol=1e-12, rtol=1e-12):
        raise ValueError("Energy/force unit or sign mismatch")

    # Exercise the installed Sella/ASE/JAX stack on a tiny analytic potential, no QM.
    toy = Atoms("CCCC", positions=[[0, 1, 0], [0, 0, 0], [1, 0, 0], [1, 0, 1]])
    pairs = [(i, j) for i in range(4) for j in range(i+1, 4)]
    distances = np.array([np.linalg.norm(toy.positions[i]-toy.positions[j]) for i, j in pairs])
    distances[0] += .02
    class PairPotential(Calculator):
        implemented_properties = ["energy", "forces"]
        def calculate(self, atoms=None, properties=("energy", "forces"), system_changes=all_changes):
            super().calculate(atoms, properties, system_changes)
            energy, forces = 0., np.zeros((4, 3))
            for (i, j), target in zip(pairs, distances):
                delta = atoms.positions[i]-atoms.positions[j]
                distance = np.linalg.norm(delta)
                energy += .5*(distance-target)**2
                force = -(distance-target)*delta/distance
                forces[i] += force
                forces[j] -= force
            self.results = dict(energy=energy, forces=forces)
    toy.calc = PairPotential()
    constraint = Constraints(toy)
    constraint.fix_dihedral((0, 1, 2, 3))
    optimizer = Sella(toy, order=0, internal=True, eig=False, constraints=constraint,
                      max_cpu_threads=1, logfile=str(root/"analytic_preflight.log"))
    converged = bool(optimizer.run(fmax=1e-5, steps=30))
    metrics = projected_metrics(toy.positions/BOHR, -toy.get_forces()/FORCE_FACTOR, [0, 1, 2, 3])
    if not converged or metrics["max_projected_atom_gradient"] >= 1e-5/FORCE_FACTOR:
        raise ValueError("Analytic Sella preflight failed independent force convergence")
    save(root/"preflight.json", dict(passed=True, new_qm_evaluations=0,
         cached_source=source(cached), cached_sella_projected_max=maximum,
         cached_independent_projection=independent, sella_angle_degrees=sella_angle,
         energy_force_conversion_verified=True, analytic_sella_converged=converged,
         analytic_steps=optimizer.nsteps, analytic_independent_projection=metrics,
         versions=plan["versions"], seed_audit=source(root/"starting_audit.json")))
    save(root/"authorization.json", dict(user_authorized=True, recorded_at=now(),
         user_instruction="Ok, do a from scratch attempt to push the cis-anti CPD through Sella and see what we get.",
         rationale="Explicit new Sella attempt supersedes waiting on the different geomeTRIC restart option; old policies/verdicts unchanged.",
         plan=source(root/"plan.json"), worker=source(root/"executed_source.py"),
         preflight=source(root/"preflight.json"), max_continuations=0))
    print(f"Prepared {root}; no new QM; analytic optimizer steps={optimizer.nsteps}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    prepare(parser.parse_args().root.resolve())
