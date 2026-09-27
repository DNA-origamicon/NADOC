"""Independently inspect a terminal local construction; never extend or promote it."""

import json
from pathlib import Path
import sys

import numpy as np
import openmm as mm
from openmm import app, unit as u

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.preliminary_protocol import require
from experiments.cpd_anti_additive.validation_gate import read, checked, source
from experiments.cpd_anti_additive.prepare_engine_v2 import save
from backend.core.atomistic import VDW_RADIUS
from backend.core.ring_piercing import _scan, ring_names_for

ART = REPO / '.development-artifacts'


def signed_volume(positions):
    a, b, c, d = np.asarray(positions)
    return float(np.dot(b-a, np.cross(c-a, d-a)))


def adjacency(psf):
    neighbors = [[] for _ in psf.atom_list]
    for b in psf.bond_list:
        neighbors[b.atom1.idx].append(b.atom2.idx)
        neighbors[b.atom2.idx].append(b.atom1.idx)
    return neighbors


def review(root):
    policy, receipt = require('engine')
    output = root / 'independent_review.json'
    assert not output.exists(), 'Do not overwrite the independent review'
    result = read(root / 'assessment.json')
    plan = read(checked(result['plan']))
    for ref in plan['sources']:
        checked(ref)
    checked(plan['source_code'])
    x = np.loadtxt(ART / 'cpd-anti-placement-review-v2/current_A.txt')
    y = np.loadtxt(checked(result['coordinates']))
    assert x.shape == y.shape == (3043, 3) and np.isfinite(y).all()
    dna = ART / 'cpd-anti-dna-topology-v2b'
    topology = read(dna / 'assessment.json')
    for ref in topology['outputs'].values():
        checked(ref)
    psf = app.CharmmPsfFile(str(dna / 'anti.psf'))
    assert len(psf.atom_list) == 3043 and len(psf.residue_list) == 96
    atoms = psf.atom_list
    ids = {f'{e["endpoint"]}:{a.name}': a.idx for e in topology['endpoints']
           for a in atoms if (a.system, a.residue.idx) == (e['segid'], e['resid'])}
    mobile = sorted(a.idx for a in atoms if any(a.system == e['segid'] and
                    abs(a.residue.idx-e['resid']) <= 2 for e in topology['endpoints']))
    assert mobile == plan['mobile_indices'] and len(mobile) == 322
    mobile_set = set(mobile)
    fixed = sorted(set(range(len(x)))-mobile_set)
    fixed_unchanged = np.array_equal(x[fixed], y[fixed])
    neighbors = adjacency(psf)
    labels = [f'{a.system}:{a.residue.idx}:{a.name}' for a in atoms]
    source_sugars = []
    for a in atoms:
        if a.name not in ("C1'", "C3'", "C4'"):
            continue
        ns = neighbors[a.idx]
        assert len(ns) == 4
        before, after = signed_volume(x[ns]), signed_volume(y[ns])
        source_sugars.append(dict(atom=labels[a.idx], indices=ns, reference_A3=before,
                                 candidate_A3=after, preserved=bool(before*after > 0)))
    assert len(source_sugars) == 288
    # Derive the ten local stereocenters directly from original QM fragments,
    # independently of the construction script's chemical-definition routine.
    qm_centers = []
    candidate = Path(receipt['candidate'])
    for endpoint in (1, 2):
        folder = candidate / f'endpoint-{endpoint}'
        names = read(folder / 'atom_map.json')
        fragment = app.CharmmPsfFile(str(folder / 'fragment.psf'))
        ref = np.loadtxt(folder / 'starting_A.txt')
        local_ns = adjacency(fragment)
        for atom in ('C5', 'C6', "C1'", "C3'", "C4'"):
            key = f'{endpoint}:{atom}'
            ns = local_ns[names.index(key)]
            mapped = [ids[names[i]] for i in ns]
            expected, actual = signed_volume(ref[ns]), signed_volume(y[mapped])
            qm_centers.append(dict(key=key, indices=mapped, reference_A3=expected,
                candidate_A3=actual, preserved=bool(expected*actual > 0),
                reference=source(folder / 'starting_A.txt')))
    elements = [a.element.symbol for a in psf.topology.atoms()]
    # Direct pair distances and independently reconstructed 1-2/1-3/1-4 exclusions.
    heavy = [i for i, element in enumerate(elements) if element != 'H']
    clashes = []
    seen_pairs = set()
    for i in mobile:
        if elements[i] == 'H':
            continue
        skip, frontier = {i}, {i}
        for _ in range(3):
            frontier = {k for j in frontier for k in neighbors[j]}-skip
            skip.update(frontier)
        for j in heavy:
            pair = tuple(sorted((i, j)))
            if j in skip or pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            distance = float(np.linalg.norm(y[i]-y[j]))
            ratio = distance/(10*(VDW_RADIUS[elements[i]]+VDW_RADIUS[elements[j]]))
            if ratio < .5:
                clashes.append(dict(indices=[i, j], atoms=[labels[i], labels[j]],
                                    distance_A=distance, vdw_ratio=ratio))
    bonds = {tuple(sorted((b.atom1.idx, b.atom2.idx))) for b in psf.bond_list}
    rings = []
    for residue in psf.residue_list:
        named = {a.name: a.idx for a in residue.atoms}
        for kind, names in ring_names_for(named):
            rings.append((f'{residue.system}:{residue.idx}/{kind}', kind, [named[n] for n in names]))
    rings.append(('anti lesion', 'cyclobutane', [ids[k] for k in ('1:C5', '1:C6', '2:C5', '2:C6')]))
    # Expand the neighbor radius to cover the measured longest bond and ring.
    # This avoids trusting the normal-geometry fixed-radius acceleration alone.
    heavy_bonds = [b for b in sorted(bonds) if all(elements[i] != 'H' for i in b)]
    max_bond_half = max(np.linalg.norm(y[a]-y[b])/2 for a, b in heavy_bonds)
    max_ring_radius = max(np.linalg.norm(y[indices]-y[indices].mean(axis=0), axis=1).max()
                          for _, _, indices in rings)
    search_nm = float((max_bond_half+max_ring_radius+.01)/10)
    piercings = _scan(y/10, heavy_bonds, rings, max_report=10000, search_nm=search_nm)
    system = mm.XmlSerializer.deserialize((dna / 'coverage_system.xml').read_text())
    integrator = mm.VerletIntegrator(.001)
    context = mm.Context(system, integrator, mm.Platform.getPlatformByName('Reference'))
    context.setPositions(y*u.angstrom)
    state = context.getState(getEnergy=True, getForces=True)
    energy = state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
    force = np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
    assert np.isfinite(energy) and np.isfinite(force).all()
    retained_force = np.loadtxt(root / 'forces_kcal_A.txt')
    force_error = float(np.max(abs(force-retained_force)))
    energy_error = float(abs(energy-result['potential_energy_kcal']))
    settings = policy['engine']
    equivalence = bool(force_error <= max(settings['native_equivalence_absolute_force_kcal_A'],
        settings['native_equivalence_relative_limit']*np.max(abs(force))) and
        energy_error <= max(settings['native_equivalence_absolute_energy_kcal'],
        settings['native_equivalence_relative_limit']*abs(energy)))
    bond_rows = []
    for f in system.getForces():
        if not isinstance(f, mm.HarmonicBondForce):
            continue
        for k in range(f.getNumBonds()):
            a, b, equilibrium, spring = f.getBondParameters(k)
            if tuple(sorted((a, b))) not in bonds:
                continue
            length = float(np.linalg.norm(y[a]-y[b]))
            eq = equilibrium.value_in_unit(u.angstrom)
            bond_rows.append(dict(indices=[a, b], atoms=[labels[a], labels[b]], length_A=length,
                equilibrium_A=eq, ratio=length/eq, mobile_touching=a in mobile_set or b in mobile_set))
    assert len(bond_rows) == len(bonds)
    local_bonds_pass = all(.7 < b['ratio'] < 1.3 for b in bond_rows if b['mobile_touching'])
    all_bonds_pass = all(.7 < b['ratio'] < 1.3 for b in bond_rows)
    stereo_pass = all(r['preserved'] for r in source_sugars+qm_centers)
    integrity = bool(result['error'] is None and fixed_unchanged and stereo_pass and
                     not clashes and not piercings and local_bonds_pass)
    stationary = bool(np.max(abs(force[mobile])) <= plan['stationary_report_threshold_kcal_A'])
    base = [i for key, i in ids.items() if "'" not in key and key.split(':')[1] not in ('P', 'OP1', 'OP2')]
    displacement = np.linalg.norm(y-x, axis=1)
    max_base = float(displacement[base].max())
    report = dict(assessment=source(root / 'assessment.json'),
        independently_checked_coordinate_integrity=integrity,
        agrees_with_construction_integrity=integrity == result['coordinate_integrity_passed'],
        fixed_coordinates_exactly_retained=fixed_unchanged, source_sugar_centers=source_sugars,
        original_QM_centers=qm_centers, stereochemistry_passed=stereo_pass,
        severe_clashes=clashes, ring_piercings=piercings, ring_search_radius_nm=search_nm,
        covalent_bonds=bond_rows, local_bond_integrity=local_bonds_pass,
        whole_model_bond_integrity=all_bonds_pass,
        reference_energy_kcal=float(energy), max_mobile_reference_force_kcal_A=float(abs(force[mobile]).max()),
        cpu_reference_energy_error_kcal=energy_error, cpu_reference_force_error_kcal_A=force_error,
        cpu_reference_agrees=equivalence, mobile_stationary=stationary,
        max_base_displacement_A=max_base, inherited_base_displacement_screen_passed=max_base <= 3.5,
        final_coordinates=source(root / 'candidate_A.txt'), retained_forces=source(root / 'forces_kcal_A.txt'),
        minimum_certified=False, full_DNA_NAMD_tested=False, simulation_ready=False,
        reviewer=source(Path(__file__)),
        limitations=['No Hessian or unconstrained-minimum certification',
                     'No inference of continuous nonpiercing between saved optimizer checkpoints',
                     'Geometry integrity and force convergence do not establish QM accuracy or app eligibility'])
    save(output, report)
    print(json.dumps({k: report[k] for k in ('independently_checked_coordinate_integrity',
        'agrees_with_construction_integrity', 'stereochemistry_passed', 'whole_model_bond_integrity',
        'max_mobile_reference_force_kcal_A', 'cpu_reference_agrees', 'mobile_stationary',
        'max_base_displacement_A', 'inherited_base_displacement_screen_passed')}, indent=2))


if __name__ == '__main__':
    review(Path(sys.argv[1]).resolve())
