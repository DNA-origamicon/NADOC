"""Independent QM local stiffness diagnostic; not a torsional-barrier test."""

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import openmm as mm
from openmm import unit as u

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_published_comparator.local_benchmarks import REF, checked
from experiments.cpd_published_comparator.reconstruct import source, write


def main(root):
    manifest = json.loads((REF / 'minimum_response_fixed_improper_v1/linear_response_manifest.json').read_text())
    target = checked(manifest['sources']['qm_hessian'])
    hessian = np.loadtxt(target) * 627.5094740631 / .529177210903**2
    xp = checked(manifest['sources']['target_geometry'])
    xyz = np.array([list(map(float, l.split()[1:])) for l in xp.read_text().splitlines()[2:] if l.strip()])
    # Cartesian internal modes, deliberately not reported as normal frequencies.
    centered = xyz - xyz.mean(axis=0)
    rigid = np.column_stack([np.tile(v, (36, 1)).ravel() for v in np.eye(3)] +
                            [np.cross(np.tile(v, (36, 1)), centered).ravel() for v in np.eye(3)])
    basis = np.linalg.svd(rigid, full_matrices=True)[0][:, 6:]
    values, vectors = np.linalg.eigh(basis.T @ hessian @ basis)
    names = [r['stable_atom_key'] for r in json.loads(checked(manifest['sources']['stable_atom_map']).read_text())]
    heavy = np.array([not n.split(':')[1].startswith('H') for n in names])
    caps = np.array([n.split(':')[1] in ('CM', 'HCM1', 'HCM2', 'HCM3') for n in names])
    assert values[0] > 0
    results = []
    for policy in ['first', 'last']:
        system = mm.XmlSerializer.deserialize((root / f'{policy}_system.xml').read_text())
        x = np.loadtxt(root / f'{policy}_minimum_A.txt')
        a, _, bt = np.linalg.svd(centered.T @ (x - x.mean(axis=0)))
        rotation = a @ np.diag([1, 1, np.linalg.det(a @ bt)]) @ bt
        integrator = mm.VerletIntegrator(.001)
        context = mm.Context(system, integrator, mm.Platform.getPlatformByName('Reference'))

        def energy(pos, context=context):
            context.setPositions(pos * u.angstrom)
            return context.getState(getEnergy=True).getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)

        e0 = energy(x)
        modes = []
        for i in range(6):
            displacement = (basis @ vectors[:, i]).reshape(36, 3) @ rotation
            curvature = []
            for step in [.01, .005]:
                curvature.append((energy(x + step*displacement) + energy(x - step*displacement) - 2*e0) / step**2)
            modes.append({'mode': i+1, 'qm_curvature_kcal_mol_A2': float(values[i]),
                          'heavy_atom_displacement_fraction': float(np.sum(displacement[heavy]**2)),
                          'cap_displacement_fraction': float(np.sum(displacement[caps]**2)),
                          'mm_curvature_step_halving': curvature,
                          'mm_to_qm_ratio': float(curvature[-1]/values[i]),
                          'halving_relative_change': float(abs(curvature[1]-curvature[0])/max(abs(curvature[1]), 1e-12))})
        results.append({'policy': policy, 'six_softest_internal_cartesian_modes': modes})
        del context, integrator
    write(root / 'soft_mode_benchmark.json', {
        'scope': 'Local curvature along independent QM soft directions, rotated into each MM minimum frame. Not finite-conformation energies, frequencies, barriers, or experimental mechanics.',
        'interpretation_limit': 'Different minimum conformations, especially methyl rotations, can turn a QM soft displacement into MM bond/angle stretching. These ratios are directional diagnostics, not intrinsic stiffness ratios or an acceptance test; internal-coordinate mapping is needed before a mechanical interpretation.',
        'acceptance_threshold': None, 'simulation_ready': False, 'results': results,
        'sources': [source(target), source(xp), source(Path(__file__))],
    })
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, required=True)
    main(p.parse_args().root)
