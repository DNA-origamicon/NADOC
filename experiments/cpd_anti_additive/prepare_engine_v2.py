"""Assemble an isolated anti engineering candidate; no fitting or app integration."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import warnings

import numpy as np
import openmm as mm
from openmm import app, unit as u
from scipy.optimize import minimize

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.preliminary_protocol import require, STATE, lock_inputs
from experiments.cpd_anti_additive.validation_gate import source, checked, read
from experiments.cpd_anti_additive.refine_joint import load_cases, angle

ART = REPO/'.development-artifacts'
ROOT = ART/'cpd-anti-engine-candidate-v2g'
CAPS = {'CM', 'HCM1', 'HCM2', 'HCM3'}


def save(path, data):
    path.write_text(json.dumps(data, indent=2)+'\n')


def geometry_check(psf, initial, final):
    neighbors = [[] for _ in initial]
    ratios = []
    masses = np.array([1.008, 12.011, 14.007, 15.9994])
    radii = [.31, .76, .71, .66]
    def radius(atom):
        mass = atom.mass.value_in_unit(u.dalton)
        index = int(np.argmin(abs(masses-mass)))
        if abs(masses[index]-mass)>.1:
            raise ValueError('Unexpected element/mass in CHNO fixture')
        return radii[index]
    for bond in psf.bond_list:
        a, b = bond.atom1.idx, bond.atom2.idx
        neighbors[a].append(b)
        neighbors[b].append(a)
        ratios.append(np.linalg.norm(final[a]-final[b])/
                      (radius(bond.atom1)+radius(bond.atom2)))
    stereo = []
    for i, ns in enumerate(neighbors):
        if len(ns) != 4:
            continue
        def volume(x):
            a, b, c, d = x[ns]
            return float(np.dot(b-a, np.cross(c-a, d-a)))
        stereo.append(dict(index=i, preserved=bool(volume(initial)*volume(final)>0)))
    return dict(stereo_preserved=all(s['preserved'] for s in stereo), stereo=stereo,
        covalent_ratio_range=[float(min(ratios)), float(max(ratios))],
        graph_distances_passed=bool(min(ratios)>.7 and max(ratios)<1.3))


def relax(folder, params, names, xyz, target=None):
    psf = app.CharmmPsfFile(str(folder/'fragment.psf'))
    system = psf.createSystem(params, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False)
    (folder/'system.xml').write_text(mm.XmlSerializer.serialize(system))
    np.savetxt(folder/'starting_A.txt', xyz)
    save(folder/'atom_map.json', names)
    integrator = mm.VerletIntegrator(.001)
    ctx = mm.Context(system, integrator, mm.Platform.getPlatformByName('Reference'))

    def evaluate(flat):
        ctx.setPositions(np.asarray(flat).reshape(-1, 3)*u.angstrom)
        state = ctx.getState(getEnergy=True, getForces=True)
        return state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole), -np.array(
            state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom)).ravel()

    result = minimize(evaluate, xyz.ravel(), jac=True, method='L-BFGS-B',
        options=dict(maxiter=4000, gtol=1e-7, ftol=1e-15, maxls=40))
    final = result.x.reshape(-1, 3)
    energy, gradient = evaluate(result.x)
    np.savetxt(folder/'minimum_A.txt', final)
    centered = final-final.mean(axis=0)
    rigid = np.column_stack([np.tile(v, (len(final), 1)).ravel() for v in np.eye(3)]+
        [np.cross(np.tile(v, (len(final), 1)), centered).ravel() for v in np.eye(3)])
    basis = np.linalg.svd(rigid, full_matrices=True)[0][:, 6:]
    curvatures = []
    for step in (1e-4, 5e-5):
        hessian = np.empty((final.size, final.size))
        for j in range(final.size):
            plus, minus = final.ravel().copy(), final.ravel().copy()
            plus[j] += step
            minus[j] -= step
            hessian[:, j] = (evaluate(plus)[1]-evaluate(minus)[1])/(2*step)
        eigen = np.linalg.eigvalsh(basis.T@((hessian+hessian.T)/2)@basis)
        curvatures.append(dict(step_A=step, minimum_internal_curvature=float(eigen[0])))
    audit = geometry_check(psf, xyz, final)
    report = dict(atoms=len(names), names=names, optimizer_success=bool(result.success),
        optimizer_message=str(result.message), energy_kcal=energy, max_force=float(abs(gradient).max()),
        stationary=bool(abs(gradient).max()<.001), curvatures=curvatures,
        positive_curvature=all(c['minimum_internal_curvature']>0 for c in curvatures),
        geometry=audit, net_charge=float(sum(a.charge for a in psf.atom_list)),
        parameter_coverage=True, simulation_ready=False)
    if target is not None:
        bond_error = max(abs(np.linalg.norm(final[b.atom1.idx]-final[b.atom2.idx])-
                            np.linalg.norm(target[b.atom1.idx]-target[b.atom2.idx])) for b in psf.bond_list)
        angle_error = max(abs(angle(final, [a.atom1.idx, a.atom2.idx, a.atom3.idx])-
                             angle(target, [a.atom1.idx, a.atom2.idx, a.atom3.idx])) for a in psf.angle_list)
        report.update(max_all_bond_error_A=float(bond_error), max_all_angle_error_deg=float(angle_error),
                      all_geometry_quality_passed=bool(bond_error<=.03 and angle_error<=3))
    report['engineering_stability_passed'] = bool(report['stationary'] and report['positive_curvature']
        and audit['stereo_preserved'] and audit['graph_distances_passed'] and abs(report['net_charge'])<1e-8)
    save(folder/'assessment.json', report)
    del ctx, integrator
    return report, psf, final


def prepare():
    require('electrostatics')
    ROOT.mkdir(exist_ok=False)
    (ROOT/'executed_source.py').write_text(Path(__file__).read_text())
    fitpath = ART/'cpd-anti-charge-minima-fit-v2/assessment.json'
    fit, review = read(fitpath), read(fitpath.parent/'independent_review.json')
    assert fit['water_passed'] and review['all_water_passed'] and review['charge_fit']==source(fitpath)
    shifts = fit['charge_shifts_e']
    parent = ART/'cpd-anti-remote-coupled-v1/geometry-1'
    typed = ART/'cpd-anti-ordered-types-v1'
    inputs = [source(fitpath), source(fitpath.parent/'independent_review.json'),
              source(parent/'assessment.json'), source(parent/'comparator_last.prm'),
              source(typed/'assessment.json')]
    shutil.copyfile(parent/'comparator_last.prm', ROOT/'comparator_last.prm')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        params = app.CharmmParameterSet(str(ROOT/'comparator_last.prm'))
    cases = load_cases()
    dataset = read(checked(fit['dataset']))
    inputs.append(fit['dataset'])
    specs = [(c['id'], c, c['qm']) for c in cases]
    remote = next(c for c in dataset['cases'] if c['id']=='endpoint-2-remote')
    ep2 = next(c for c in cases if c['endpoint']==2)
    assert remote['names']==ep2['names']
    specs.append(('endpoint-2-remote', ep2, np.array(remote['xyz_A'])))
    results, fixtures = [], {}
    for label, case, xyz in specs:
        folder = ROOT/label
        folder.mkdir()
        original = typed/case['id']/'fragment.psf'
        inputs.extend([source(original), source(case['target'])])
        lines = original.read_text().splitlines()
        offset = next(i for i, line in enumerate(lines) if '!NATOM' in line)+1
        for i, name in enumerate(case['names']):
            fields = lines[offset+i].split()
            assert int(fields[0]) == i+1
            fields[6] = f"{float(fields[6])+shifts.get(name, 0):.12f}"
            lines[offset+i] = ' '.join(fields)
        (folder/'fragment.psf').write_text('\n'.join(lines)+'\n')
        report, psf, minimum = relax(folder, params, case['names'], xyz, target=xyz)
        results.append(dict(id=label, **report))
        fixtures[label] = (case['names'], psf, minimum)
        save(ROOT/'progress.json', dict(records=results))

    # Each sugar comes from its independently relaxed endpoint fragment. Only a
    # proper rigid-body alignment is used; this is an MM seed, never labelled QM.
    names1, psf1, x1 = fixtures['endpoint-1']
    names2, psf2, x2 = fixtures['endpoint-2-remote']
    common = sorted(n for n in set(names1)&set(names2)
                    if "'" not in n and n.split(':')[1] not in CAPS
                    and not n.split(':')[1].startswith('H'))
    p = x2[[names2.index(n) for n in common]]
    q = x1[[names1.index(n) for n in common]]
    uu, _, vv = np.linalg.svd((p-p.mean(axis=0)).T@(q-q.mean(axis=0)))
    sign = np.eye(3)
    sign[2, 2] = np.linalg.det(uu@vv)
    rotation = uu@sign@vv
    aligned = (x2-p.mean(axis=0))@rotation+q.mean(axis=0)
    joined = {}
    bonds = set()
    for endpoint, names, psf, xyz in [(1, names1, psf1, x1), (2, names2, psf2, aligned)]:
        for i, name in enumerate(names):
            if name.startswith(f'{endpoint}:') and name.split(':')[1] not in CAPS:
                joined[name] = (psf.atom_list[i], xyz[i])
        for bond in psf.bond_list:
            a, b = names[bond.atom1.idx], names[bond.atom2.idx]
            if all(n.split(':')[1] not in CAPS for n in (a, b)):
                bonds.add(tuple(sorted((a, b))))
    names = sorted(joined)
    assert len(names)==62 and all(n in joined for pair in bonds for n in pair)
    cross = {b for b in bonds if b[0].split(':')[0]!=b[1].split(':')[0]}
    assert cross == {('1:C5', '2:C6'), ('1:C6', '2:C5')}
    folder = ROOT/'two-nucleosides'
    folder.mkdir()
    rtf = ['* Isolated cis-anti engineering fixture; two independent nucleosides', '*', '36 1']
    for typ in sorted({joined[n][0].attype for n in names}):
        mass = params.atom_types_str[typ].mass.value_in_unit(u.dalton)
        rtf.append(f'MASS -1 {typ} {mass:.10f}')
    rtf.append('AUTO ANGLES DIHE')
    for endpoint in (1, 2):
        selected = [n for n in names if n.startswith(f'{endpoint}:')]
        rtf.extend([f'RESI AC{endpoint} {sum(joined[n][0].charge for n in selected):.12f}', 'GROUP'])
        for n in selected:
            atom = joined[n][0]
            rtf.append(f'ATOM {n.split(":")[1]} {atom.attype} {atom.charge:.12f}')
        for a, b in sorted(bonds-cross):
            if a.startswith(f'{endpoint}:'):
                rtf.append(f'BOND {a.split(":")[1]} {b.split(":")[1]}')
        rtf.extend(['IMPR C2 N1 N3 O2', 'IMPR C4 N3 C5 O4'])
    rtf.extend(['PRES AXL 0.0', 'BOND 1C5 2C6', 'BOND 1C6 2C5', 'END'])
    (folder/'fragment.rtf').write_text('\n'.join(rtf)+'\n')
    script = '\n'.join(['package require psfgen', 'resetpsf', 'topology fragment.rtf',
        'segment A { first NONE; last NONE; residue 1 AC1 }',
        'segment B { first NONE; last NONE; residue 1 AC2 }',
        'patch AXL A:1 B:1', 'regenerate angles dihedrals', 'writepsf fragment.psf', 'exit'])+'\n'
    (folder/'build.tcl').write_text(script)
    executable = Path('/home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/psfgen')
    inputs.append(source(executable))
    process = subprocess.run([str(executable), 'build.tcl'], cwd=folder, capture_output=True, text=True)
    (folder/'build.log').write_text(process.stdout+process.stderr)
    process.check_returncode()
    psf = app.CharmmPsfFile(str(folder/'fragment.psf'))
    ordered = [f'{1 if a.residue.resname=="AC1" else 2}:{a.name}' for a in psf.atom_list]
    assert len(set(ordered))==62 and set(ordered)==set(names)
    # psfgen writes only six charge decimals. Retain its raw graph and restore
    # the exact fitted assignments, preventing a rounding-induced net charge.
    shutil.copyfile(folder/'fragment.psf', folder/'psfgen_raw.psf')
    lines = (folder/'fragment.psf').read_text().splitlines()
    offset = next(i for i, line in enumerate(lines) if '!NATOM' in line)+1
    for i, name in enumerate(ordered):
        fields = lines[offset+i].split()
        charge = joined[name][0].charge
        assert int(fields[0])==i+1 and abs(float(fields[6])-charge)<=5.00001e-7
        fields[6] = f'{charge:.12f}'
        lines[offset+i] = ' '.join(fields)
    (folder/'fragment.psf').write_text('\n'.join(lines)+'\n')
    psf = app.CharmmPsfFile(str(folder/'fragment.psf'))
    native_bonds = {tuple(sorted((ordered[b.atom1.idx], ordered[b.atom2.idx]))) for b in psf.bond_list}
    assert native_bonds==bonds and len(psf.residue_list)==2
    xyz = np.array([joined[n][1] for n in ordered])
    report, _, _ = relax(folder, params, ordered, xyz)
    results.append(dict(id='two-nucleosides', **report))
    limitations = ['Conformational energy stage incomplete; no quantitative structural inference',
        'Historical geometry overlay changes CPD-specific sugar bonded terms; full DNA parent transfer unresolved',
        'Two capped nucleosides contain both sugars and anti links but no phosphate/backbone context',
        'Two-sugar seed assembled by proper rigid alignment of MM fragments; not a QM geometry',
        'No app or saved-design coordinates changed']
    report = dict(records=results, sources=inputs, preparation=source(Path(__file__)),
        engineering_stability_passed=all(r['engineering_stability_passed'] for r in results),
        graph=dict(atoms=62, residues=2, bonds=len(bonds), crosslinks=sorted(cross), phosphodiester_between_endpoints=False,
                   psfgen_charge_precision_restored=True, raw_psf=source(folder/'psfgen_raw.psf')),
        alignment_heavy_base_rms_A=float(np.sqrt(np.mean(np.sum(((p-p.mean(axis=0))@rotation+q.mean(axis=0)-q)**2,axis=1)))),
        limitations=limitations, simulation_ready=False, preliminary_research_qualified=False)
    save(ROOT/'assessment.json', report)
    if not report['engineering_stability_passed']:
        raise RuntimeError('Local engineering stability failed; retain evidence without native smoke')
    artifacts = inputs+[source(Path(__file__)), source(ROOT/'assessment.json'), source(ROOT/'comparator_last.prm')]
    for record in results:
        for filename in ('fragment.psf', 'system.xml', 'minimum_A.txt', 'atom_map.json', 'assessment.json'):
            artifacts.append(source(ROOT/record['id']/filename))
    receipt = dict(stage='engine', ready=True, case_ids=[r['id'] for r in results], artifacts=artifacts,
        candidate=str(ROOT.resolve()), limitations=limitations, engineering_only=True)
    save(STATE/'engine_inputs.json', receipt)
    lock_inputs('engine', STATE/'engine_inputs.json')
    print(json.dumps(dict(engineering_stability_passed=True, graph=report['graph'],
                         quality=[{k:r[k] for k in ('id', 'max_all_bond_error_A', 'max_all_angle_error_deg', 'all_geometry_quality_passed')}
                                  for r in results if 'all_geometry_quality_passed' in r]), indent=2))


if __name__ == '__main__':
    prepare()
