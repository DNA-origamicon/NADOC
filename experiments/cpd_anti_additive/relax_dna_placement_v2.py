"""One bounded, isolated coordinate-construction diagnostic at the frozen site.

No parameter fitting, dynamics, product integration, or minimum certification.
"""

import json
from pathlib import Path
import sys
import time

import numpy as np
import openmm as mm
from openmm import app, unit as u
from scipy.optimize import minimize

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.preliminary_protocol import require
from experiments.cpd_anti_additive.validation_gate import checked, read, source
from experiments.cpd_anti_additive.prepare_engine_v2 import save
from experiments.cpd_anti_additive.placement_review_v2 import audit, ring_names_for
from backend.core.cpd_product import _proper_kabsch
from backend.core.photoproduct_chemistry import audit_product_chirality

ART = REPO / '.development-artifacts'
ROOT = ART / 'cpd-anti-local-placement-v2'


def load():
    _, receipt = require('engine')
    dna = ART / 'cpd-anti-dna-topology-v2b'
    assessment = read(dna / 'assessment.json')
    independent = read(dna / 'independent_review.json')
    assert independent['passed'] and independent['assessment'] == source(dna / 'assessment.json')
    for record in assessment['outputs'].values():
        checked(record)
    psf = app.CharmmPsfFile(str(dna / 'anti.psf'))
    prior = ART / 'cpd-anti-placement-review-v2'
    x = np.loadtxt(prior / 'current_A.txt')
    seed = np.loadtxt(prior / 'rejected_candidate_A.txt')
    fragment = Path(receipt['candidate']) / 'two-nucleosides'
    names = read(fragment / 'atom_map.json')
    t = np.loadtxt(fragment / 'minimum_A.txt')
    ids = {f'{e["endpoint"]}:{a.name}': a.idx for e in assessment['endpoints']
           for a in psf.atom_list if (a.system, a.residue.idx) == (e['segid'], e['resid'])}
    mobile = np.array([a.idx for a in psf.atom_list if any(
        a.system == e['segid'] and abs(a.residue.idx-e['resid']) <= 2
        for e in assessment['endpoints'])], dtype=int)
    elements = [a.element.symbol for a in psf.topology.atoms()]
    labels = [f'{a.system}:{a.residue.idx}:{a.name}' for a in psf.atom_list]
    bonds = [(b.atom1.idx, b.atom2.idx) for b in psf.bond_list]
    rings = []
    for res in psf.residue_list:
        named = {a.name: a.idx for a in res.atoms}
        for kind, cycle in ring_names_for(named):
            rings.append((f'{res.system}:{res.idx}/{kind}', kind, [named[n] for n in cycle]))
    rings.append(('lesion', 'cyclobutane', [ids[k] for k in ('1:C5', '1:C6', '2:C5', '2:C6')]))
    definition = REPO / 'backend/data/forcefield/photoproducts/tt-cpd-cis-anti-i/chemical_definition.json'
    return dict(dna=dna, prior=prior, fragment=fragment, psf=psf, assessment=assessment,
                x=x, seed=seed, names=names, template=t, ids=ids, mobile=mobile,
                elements=elements, labels=labels, bonds=bonds, rings=rings, definition=definition)


def contact_check(d, xyz):
    return audit(xyz, d['bonds'], d['rings'], d['mobile'].tolist(), d['elements'], d['labels'])


def stereo_records(d):
    neighbors = [[] for _ in d['x']]
    for a, b in d['bonds']:
        neighbors[a].append(b)
        neighbors[b].append(a)
    records = []
    for atom in d['psf'].atom_list:
        if atom.name not in ("C1'", "C3'", "C4'"):
            continue
        ns = neighbors[atom.idx]
        assert len(ns) == 4
        p, q, r, s = d['x'][ns]
        records.append(dict(index=atom.idx, label=d['labels'][atom.idx], neighbors=ns,
                            reference_volume_A3=float(np.dot(q-p, np.cross(r-p, s-p)))))
    assert len(records) == 3 * 96
    return records


def stereo_check(d, xyz, records):
    failed = []
    for record in records:
        p, q, r, s = xyz[record['neighbors']]
        v = float(np.dot(q-p, np.cross(r-p, s-p)))
        if v * record['reference_volume_A3'] <= 0:
            failed.append(dict(**record, candidate_volume_A3=v))
    lesion = audit_product_chirality(read(d['definition']),
                                    {k: xyz[i].tolist() for k, i in d['ids'].items()})
    return dict(passed=not failed and lesion['passed'], sugars_checked=len(records),
                inverted_sugars=failed, lesion=lesion)


def prepare():
    d = load()
    ROOT.mkdir(exist_ok=False)
    (ROOT / 'executed_source.py').write_text(Path(__file__).read_text())
    records = stereo_records(d)
    save(ROOT / 'sugar_stereo_reference.json', records)
    # Preserve the alternative whole-nucleoside rigid construction and its rejection.
    keys = [f'{e}:{n}' for e in (1, 2) for n in ("O5'", "C5'", "C3'", "O3'")]
    rotation, translation, rms = _proper_kabsch(
        d['template'][[d['names'].index(k) for k in keys]], d['x'][[d['ids'][k] for k in keys]])
    alternative = d['x'].copy()
    for k in d['names']:
        if k in d['ids']:
            alternative[d['ids'][k]] = rotation @ d['template'][d['names'].index(k)] + translation
    np.savetxt(ROOT / 'rejected_whole_nucleoside_A.txt', alternative)
    save(ROOT / 'rejected_whole_nucleoside.json', dict(anchor_rms_A=rms,
        contacts=contact_check(d, alternative), retained_as_failure=True, used_for_relaxation=False))
    seed_contacts = contact_check(d, d['seed'])
    seed_stereo = stereo_check(d, d['seed'], records)
    assert seed_stereo['passed'] and seed_contacts['all_piercing_count'] == 0
    assert np.array_equal(d['seed'][np.setdiff1d(np.arange(len(d['x'])), d['mobile'])],
                          d['x'][np.setdiff1d(np.arange(len(d['x'])), d['mobile'])])
    save(ROOT / 'seed_review.json', dict(contacts=seed_contacts, stereo=seed_stereo,
        status='Strained construction seed only; explicitly fails rigid-placement acceptance',
        prior_rejection=source(d['prior'] / 'assessment.json')))
    paths = [d['dna'] / f for f in ('assessment.json', 'independent_review.json', 'anti.psf',
             'anti.pdb', 'coverage_system.xml', 'anti_dna_overlay.prm')]
    paths += [d['prior'] / f for f in ('assessment.json', 'current_A.txt', 'rejected_candidate_A.txt')]
    paths += [d['fragment'] / f for f in ('minimum_A.txt', 'atom_map.json')]
    paths += [d['definition'], ROOT / 'seed_review.json', ROOT / 'sugar_stereo_reference.json']
    save(ROOT / 'plan.json', dict(scope='Single local coordinate-construction diagnostic',
        sources=[source(p) for p in paths], source_code=source(Path(__file__)),
        method='L-BFGS-B on mobile coordinates only; unmodified full CHARMM vacuum energy',
        seed='Previously rejected rigid base placement; correct stereo, no ring piercing, short glycosidic bonds',
        mobile_residue_radius=2, mobile_indices=d['mobile'].tolist(), mobile_atoms=len(d['mobile']),
        fixed_atoms=len(d['x'])-len(d['mobile']), extra_restraints=False,
        expected_seconds=1200, hard_seconds=7200, max_iterations=5000, max_energy_evaluations=8000,
        max_trials=1, max_continuations=0, optimizer_gtol_kcal_A=.001,
        stationary_report_threshold_kcal_A=.01,
        integrity_checks=['Exact graph/types/charges and fixed-coordinate retention',
                          'All 288 source sugar and four anti lesion stereo centers preserved',
                          'No severe contacts at unchanged 0.5 vdW ratio screen',
                          'No detected ring piercing',
                          'Mobile-touching bond lengths within 0.7..1.3 of native equilibrium lengths'],
        bond_ratio_scope='Construction-integrity screen only, not QM geometry accuracy',
        retained_product_screen=dict(max_base_displacement_A=3.5, max_glycosidic_error_A=.4,
                                     original_anchor_rms_A=1.3951238472771426, max_rigid_anchor_rms_A=1.2),
        checkpoint_every_accepted_steps=25, stop_on_accepted_stereo_inversion=True,
        stop_on_checkpoint_ring_piercing=True, threads=2, platform='CPU',
        limitations=['Fixed outer coordinates; unsolvated charged DNA; no full unconstrained minimum',
                     'Unresolved conformational energies and older endpoint-2 basin loss retained',
                     'No dynamics or product geometry promotion'], simulation_ready=False))
    print(json.dumps(dict(prepared=True, root=str(ROOT.resolve()), mobile_atoms=len(d['mobile']),
                          initial_severe_contacts=seed_contacts['severe_clash_count']), indent=2))


def run():
    d = load()
    plan = read(ROOT / 'plan.json')
    checked(plan['source_code'])
    for record in plan['sources']:
        checked(record)
    assert plan['mobile_indices'] == d['mobile'].tolist()
    assert not (ROOT / 'started.json').exists(), 'Single attempt; no automatic restart'
    save(ROOT / 'started.json', dict(started_at=time.time(), plan=source(ROOT / 'plan.json')))
    records = read(ROOT / 'sugar_stereo_reference.json')
    system = mm.XmlSerializer.deserialize((d['dna'] / 'coverage_system.xml').read_text())
    integrator = mm.VerletIntegrator(.001)
    ctx = mm.Context(system, integrator, mm.Platform.getPlatformByName('CPU'), {'Threads': '2'})
    mobile = d['mobile']
    xyz = d['seed'].copy()
    accepted = xyz.copy()
    count = 0
    iterations = 0
    start = time.monotonic()
    error = None
    result = None

    def evaluate(flat):
        nonlocal count
        if count >= plan['max_energy_evaluations'] or time.monotonic()-start >= plan['hard_seconds']:
            raise RuntimeError('Finite evaluation/time budget exhausted')
        count += 1
        xyz[mobile] = np.asarray(flat).reshape(-1, 3)
        ctx.setPositions(xyz*u.angstrom)
        state = ctx.getState(getEnergy=True, getForces=True)
        e = state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
        g = -np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
        assert np.isfinite(e) and np.isfinite(g).all(), 'Nonfinite energy/force'
        return e, g[mobile].ravel()

    def callback(flat):
        nonlocal iterations, accepted
        iterations += 1
        proposed = d['seed'].copy()
        proposed[mobile] = np.asarray(flat).reshape(-1, 3)
        stereo = stereo_check(d, proposed, records)
        if not stereo['passed']:
            np.savetxt(ROOT / 'failed_stereo_A.txt', proposed)
            save(ROOT / 'failed_stereo.json', stereo)
            raise RuntimeError('Accepted optimizer step inverted stereo')
        accepted = proposed.copy()
        if iterations % plan['checkpoint_every_accepted_steps'] == 0:
            folder = ROOT / f'checkpoint-{iterations:05d}'
            folder.mkdir()
            np.savetxt(folder / 'coordinates_A.txt', proposed)
            contacts = contact_check(d, proposed)
            save(folder / 'review.json', dict(iterations=iterations, evaluations=count,
                stereo=stereo, contacts=contacts, elapsed_seconds=time.monotonic()-start))
            save(ROOT / 'progress.json', dict(iterations=iterations, evaluations=count,
                checkpoint=str(folder.resolve()), elapsed_seconds=time.monotonic()-start))
            if contacts['all_piercing_count']:
                raise RuntimeError('Ring piercing detected at checkpoint')

    with (ROOT / 'evaluations.jsonl').open('x') as handle:
        def objective(flat):
            energy, gradient = evaluate(flat)
            handle.write(json.dumps(dict(evaluation=count, energy_kcal=energy,
                max_mobile_force_kcal_A=float(abs(gradient).max()), elapsed_seconds=time.monotonic()-start))+'\n')
            handle.flush()
            return energy, gradient
        try:
            result = minimize(objective, d['seed'][mobile].ravel(), jac=True, method='L-BFGS-B',
                callback=callback, options=dict(maxiter=plan['max_iterations'],
                    maxfun=plan['max_energy_evaluations'], gtol=plan['optimizer_gtol_kcal_A'],
                    ftol=1e-13, maxls=30))
            accepted[mobile] = result.x.reshape(-1, 3)
        except Exception as exc:
            error = repr(exc)
    # Report final force independently of the optimizer success flag and its budget.
    ctx.setPositions(accepted*u.angstrom)
    final = ctx.getState(getEnergy=True, getForces=True)
    energy = final.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
    force = np.array(final.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
    np.savetxt(ROOT / 'candidate_A.txt', accepted)
    np.savetxt(ROOT / 'forces_kcal_A.txt', force)
    contacts = contact_check(d, accepted)
    stereo = stereo_check(d, accepted, records)
    fixed = np.setdiff1d(np.arange(len(accepted)), mobile)
    fixed_unchanged = np.array_equal(accepted[fixed], d['x'][fixed])
    mobile_set = set(mobile)
    bond_rows = []
    for f in system.getForces():
        if not isinstance(f, mm.HarmonicBondForce):
            continue
        for i in range(f.getNumBonds()):
            a, b, r0, k = f.getBondParameters(i)
            if (a, b) not in d['bonds'] and (b, a) not in d['bonds']:
                continue  # Urey-Bradley 1-3 terms are not covalent bonds.
            if a not in mobile_set and b not in mobile_set:
                continue
            length = float(np.linalg.norm(accepted[a]-accepted[b]))
            eq = r0.value_in_unit(u.angstrom)
            bond_rows.append(dict(indices=[a, b], labels=[d['labels'][a], d['labels'][b]],
                                  length_A=length, equilibrium_A=eq, ratio=length/eq))
    assert bond_rows
    bonds_pass = all(.7 < row['ratio'] < 1.3 for row in bond_rows)
    glyco = []
    for ep in (1, 2):
        a, b = d['ids'][f"{ep}:C1'"], d['ids'][f'{ep}:N1']
        ref = np.linalg.norm(d['template'][d['names'].index(f"{ep}:C1'")]-
                             d['template'][d['names'].index(f'{ep}:N1')])
        glyco.append(dict(endpoint=ep, current_A=float(np.linalg.norm(d['x'][a]-d['x'][b])),
            seed_A=float(np.linalg.norm(d['seed'][a]-d['seed'][b])),
            candidate_A=float(np.linalg.norm(accepted[a]-accepted[b])), reference_A=float(ref)))
    base_ids = [i for k, i in d['ids'].items() if "'" not in k and k in d['names']]
    displacement = np.linalg.norm(accepted-d['x'], axis=1)
    maxbase = float(displacement[base_ids].max())
    integrity = bool(error is None and fixed_unchanged and stereo['passed'] and bonds_pass
        and contacts['severe_clash_count'] == 0 and contacts['all_piercing_count'] == 0)
    report = dict(coordinate_integrity_passed=integrity, error=error,
        optimizer_success=bool(result is not None and result.success),
        optimizer_message=str(result.message) if result is not None else None,
        iterations=iterations, energy_evaluations=count, elapsed_seconds=time.monotonic()-start,
        potential_energy_kcal=float(energy), max_mobile_force_kcal_A=float(abs(force[mobile]).max()),
        max_fixed_reaction_force_kcal_A=float(abs(force[fixed]).max()),
        mobile_stationary=bool(abs(force[mobile]).max() <= plan['stationary_report_threshold_kcal_A']),
        minimum_certified=False, fixed_atoms_exactly_unchanged=fixed_unchanged,
        stereo=stereo, contacts=contacts, bond_integrity_passed=bonds_pass, bonds=bond_rows,
        glycosidic=glyco, max_base_displacement_A=maxbase,
        inherited_base_displacement_screen_passed=maxbase <= 3.5,
        max_mobile_displacement_A=float(displacement[mobile].max()),
        source_C1_separation_A=float(np.linalg.norm(d['x'][d['ids']["1:C1'"]]-d['x'][d['ids']["2:C1'"]])),
        candidate_C1_separation_A=float(np.linalg.norm(accepted[d['ids']["1:C1'"]]-accepted[d['ids']["2:C1'"]])),
        simulation_ready=False, full_DNA_NAMD_tested=False, app_promotion_authorized=False,
        dynamics_performed=False, plan=source(ROOT / 'plan.json'), coordinates=source(ROOT / 'candidate_A.txt'))
    save(ROOT / 'assessment.json', report)
    print(json.dumps({k: report[k] for k in ('coordinate_integrity_passed', 'error', 'optimizer_success',
        'iterations', 'energy_evaluations', 'max_mobile_force_kcal_A', 'mobile_stationary',
        'max_base_displacement_A', 'inherited_base_displacement_screen_passed')}, indent=2))
    if not integrity:
        raise RuntimeError('Coordinate construction failed its integrity audit; preserve all outputs')


if __name__ == '__main__':
    if sys.argv[1:] == ['prepare']:
        prepare()
    elif sys.argv[1:] == ['run']:
        run()
    else:
        raise ValueError('Expected prepare or run')
