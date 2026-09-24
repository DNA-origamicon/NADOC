"""Re-minimize every saved frame outside the unchanged polarization domain."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
from openmm import unit as u

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.core.dcd_fast import read_layout, read_frame
from experiments.cpd_drude_recovery.campaign import AdiabaticNonbonded, source, write
from experiments.cpd_drude_recovery.nucleotide import atoms_and_terms

parser = argparse.ArgumentParser()
parser.add_argument('--trajectory-root', type=Path, required=True)
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--candidate', type=Path)
parser.add_argument('--all-frames', action='store_true')
args = parser.parse_args()
root = args.root.resolve()
root.mkdir(exist_ok=False)
origin = args.trajectory_root.resolve()
recovery = Path('.development-artifacts/cpd-drude-anti-graph-recovery-v1').resolve()
frozen = args.candidate.resolve() if args.candidate else recovery / 'corrected_parameters.training_frozen.json'
physical = AdiabaticNonbonded(recovery, frozen)
model = physical.model
_, atoms, sections = atoms_and_terms((origin / 'candidate.psf').read_text())
serials = {int(row[5][1:]): i-1 for i, row in atoms.items() if row[5].startswith('X')}
pairs = []
for a, b in sections['NBOND'][3]:
    if atoms[a][5] == 'DRUD':
        pairs.append((b-1, a-1))
    elif atoms[b][5] == 'DRUD':
        pairs.append((a-1, b-1))
assert len(pairs) == 20
parents, children = np.array(pairs).T
write(root / 'plan.json', {
    'simulation_ready': False, 'gate_effect': 'none',
    'selection': 'Every saved frame, no subsampling.' if args.all_frames else 'Every saved frame with any parent-Drude distance >0.20 A; no subsampling.',
    'scope': 'Fixed nuclear geometries, stationary polarization only; no Hessian or QM certificate.',
    'sources': [source(p) for p in (origin/'plan.json', origin/'trajectory_audit.json', frozen, Path(__file__))],
})
records = []
total = 0
for case in json.loads((origin/'plan.json').read_text())['cases']:
    path = origin / (case['id']+'.dcd')
    layout = read_layout(path)
    total += layout.n_frames
    for frame in range(layout.n_frames):
        xyz = read_frame(path, layout, frame)[0].astype(float)
        dynamic = np.linalg.norm(xyz[parents]-xyz[children], axis=1)
        if not args.all_frames and dynamic.max() <= .2:
            continue
        nuclei = xyz[[serials[i] for i in range(36)]]
        error = None
        try:
            physical.energy_gradient(nuclei)
        except ValueError as exc:
            error = str(exc)
        state = model.context.getState(getPositions=True, getForces=True)
        positions = np.asarray(state.getPositions(asNumpy=True).value_in_unit(u.angstrom))
        forces = np.asarray(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
        residual = float(abs(forces[model.drude_indices]).max())
        assert residual < 1e-4
        induced = np.linalg.norm(positions[model.drude_indices]-positions[:20], axis=1)
        records.append({'case': case['id'], 'frame': frame, 'dynamic_max_angstrom': float(dynamic.max()),
                        'stationary_max_angstrom': float(induced.max()),
                        'stationary_worst_site': physical.d.POLARIZABLE[int(induced.argmax())],
                        'stationary_force_max': residual, 'inside_domain': bool(induced.max() <= .2),
                        'evaluator_error': error})
write(root/'assessment.json', {'simulation_ready': False, 'gate_effect': 'none',
    'total_saved_frames': total, 'frames_reminimized': len(records), 'excursion_frames': sum(r['dynamic_max_angstrom']>.2 for r in records),
    'stationary_outside_domain_frames': sum(not r['inside_domain'] for r in records),
    'records': records, 'trajectory_sources': [source(origin/(c['id']+'.dcd')) for c in json.loads((origin/'plan.json').read_text())['cases']]})
print(json.dumps({'frames': total, 'frames_reminimized': len(records), 'excursions': sum(r['dynamic_max_angstrom']>.2 for r in records), 'stationary_failures': sum(not r['inside_domain'] for r in records)}))
