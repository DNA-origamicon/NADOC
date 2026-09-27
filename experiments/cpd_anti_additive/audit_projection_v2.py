"""Compare the cached geomeTRIC convergence projection with the exact constraint tangent."""

import json
from pathlib import Path
import re
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
RUNTIME = REPO / '.development-artifacts/cpd-geometric-runtime-v1'
sys.path.insert(0, str(RUNTIME))
from geometric.internal import DelocalizedInternalCoordinates
from geometric.molecule import Molecule
from geometric.prepare import parse_constraints
from experiments.cpd_anti_additive.validation_gate import read, checked, source
from experiments.cpd_anti_additive.prepare_engine_v2 import save
from experiments.cpd_anti_additive.geometric_pilot import BOHR
from backend.parameterization.photoproduct_qm import _dihedral_degrees

ART = REPO / '.development-artifacts'


def norms(g):
    atom = np.linalg.norm(np.asarray(g).reshape(-1, 3), axis=1)
    return dict(max_atom_au=float(atom.max()), rms_atom_au=float(np.sqrt(np.mean(atom**2))))


def build(plan, xyz, text, graph):
    molecule = Molecule()
    molecule.elem = plan['elements']; molecule.xyzs = [xyz*BOHR]
    molecule.bonds = [tuple(b['indices']) for b in graph['bonds']]
    molecule.top_settings['read_bonds'] = True
    molecule.build_topology(force_bonds=False)
    constraints, values = parse_constraints(molecule, text)
    ic = DelocalizedInternalCoordinates(molecule, build=True, connect=False, addcart=False,
        constraints=constraints, cvals=values[0], conmethod=0)
    return ic, constraints[0]


def main():
    parent = ART / 'cpd-anti-default-constraint-v2'
    output = ART / 'cpd-anti-default-constraint-projection-review-v1'
    output.mkdir(exist_ok=False)
    (output / 'executed_source.py').write_text(Path(__file__).read_text())
    plan = read(parent / 'plan.json')
    for ref in plan['runtime_sources']:
        checked(ref)
    progress = read(parent / 'progress.json')['evaluations']
    graph = read(checked(plan['record']['model_graph']))
    constraints_text = (parent / 'constraints.txt').read_text()
    first = read(checked(progress[0]['result']))
    seed = np.load(checked(first['geometry']))
    ic, constraint = build(plan, seed, constraints_text, graph)
    records = []
    final = None
    for number, row in enumerate(progress, 1):
        result = read(checked(row['result']))
        xyz = np.load(checked(result['geometry'])); g = np.asarray(result['gradient']).ravel()
        normal = constraint.derivative(xyz).ravel()
        tangent = g-normal*np.dot(normal, g)/np.dot(normal, normal)
        projected = ic.calcGradProj(xyz.ravel(), g)
        removed = g-projected
        projection_axis = ic.wilsonB(xyz.ravel())[ic.cDLC[0]]
        angle = np.arccos(np.clip(abs(np.dot(normal, projection_axis))/
                                 (np.linalg.norm(normal)*np.linalg.norm(projection_axis)), -1, 1))*180/np.pi
        row_report = dict(evaluation=number, source=row['result'], energy_hartree=result['energy'],
            exact_cartesian_tangent=norms(tangent), initial_DLC_projection=norms(projected),
            removed_force=norms(removed), constraint_axis_misalignment_deg=float(angle),
            exact_stationarity_passed=bool(norms(tangent)['max_atom_au'] < 1.5e-5 and norms(tangent)['rms_atom_au'] < 1e-5))
        records.append(row_report)
        final = xyz, g, normal, tangent, projected
    xyz, g, normal, tangent, projected = final
    fresh_ic, fresh_constraint = build(plan, xyz, constraints_text, graph)
    refreshed = fresh_ic.calcGradProj(xyz.ravel(), g)
    # Independent finite difference of the actual frozen dihedral verifies the
    # analytic normal, without reusing geomeTRIC's derivative implementation.
    fd = np.zeros(xyz.size); h = 1e-5; ids = plan['record']['torsion_indices']
    for i in range(xyz.size):
        plus, minus = xyz.ravel().copy(), xyz.ravel().copy()
        plus[i] += h; minus[i] -= h
        fd[i] = ((_dihedral_degrees(*plus.reshape(-1, 3)[ids])-
                  _dihedral_degrees(*minus.reshape(-1, 3)[ids])+180) % 360-180)/(2*h)
    fd /= np.linalg.norm(fd); normalized = normal/np.linalg.norm(normal)
    normal_error = min(np.max(abs(fd-normalized)), np.max(abs(fd+normalized)))
    assert normal_error < 1e-8
    native_log = (parent / 'geometric.log').read_text()
    stripped = re.sub(r'\x1b\[[0-9;]*m', '', native_log)
    values = re.findall(r'Grad_T\s*=\s*([\d.eE+-]+)\s*/\s*([\d.eE+-]+)', stripped)
    assert values
    native_rms, native_max = map(float, values[-1])
    native_reproduced = abs(norms(projected)['max_atom_au']-native_max) < 5e-10
    refreshed_difference = float(np.max(abs(refreshed-tangent)))
    report = dict(records=records, native_last_report=dict(max_atom_au=native_max, rms_atom_au=native_rms),
        initial_basis_reproduces_native_report=native_reproduced,
        analytic_finite_difference_normal_max_error=float(normal_error),
        final_exact_cartesian_tangent=norms(tangent), final_refreshed_DLC_projection=norms(refreshed),
        refreshed_minus_exact_max_component_au=refreshed_difference,
        native_optimizer_converged=True, exact_force_gate_passed=records[-1]['exact_stationarity_passed'],
        minimum_certified=False, new_QM_evaluations=0,
        parent=source(parent / 'plan.json'), progress=source(parent / 'progress.json'),
        failed_review=source(parent / 'independent_review_failure.json'),
        projection_implementation=source(RUNTIME / 'geometric/internal.py'), reviewer=source(Path(__file__)),
        interpretation='A cached projection comparison is diagnostic evidence; no changed force threshold, minimum certification or automatic optimizer continuation.')
    save(output / 'assessment.json', report)
    print(json.dumps({k: v for k, v in report.items() if k not in ('records', 'parent', 'progress', 'failed_review',
                                                               'projection_implementation', 'reviewer')}, indent=2))


if __name__ == '__main__':
    main()
