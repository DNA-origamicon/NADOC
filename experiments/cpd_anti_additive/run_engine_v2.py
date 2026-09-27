"""Native equivalence and bounded vacuum smoke of a frozen anti engineering fixture."""

import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import warnings

import numpy as np
import openmm as mm
from openmm import app, unit as u

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.preliminary_protocol import require, STATE
from experiments.cpd_anti_additive.validation_gate import checked, read, source
from experiments.cpd_anti_additive.prepare_engine_v2 import geometry_check, save
from backend.core.dcd_fast import read_layout, read_frame

ART = REPO/'.development-artifacts'


def binary(path, values):
    values = np.asarray(values, dtype=np.float64)
    path.write_bytes(struct.pack('i', len(values))+values.tobytes())


def read_binary(path, count):
    content = path.read_bytes()
    assert struct.unpack('i', content[:4])[0]==count and len(content)==4+24*count
    result = np.frombuffer(content[4:], dtype=np.float64).reshape(count, 3)
    assert np.isfinite(result).all()
    return result


def configuration(extra):
    return '\n'.join(['structure fragment.psf', 'coordinates fragment.pdb', 'binCoordinates start.coor',
        'paraTypeCharmm on', 'parameters candidate.prm', 'exclude scaled1-4', 'oneFourScaling 1',
        'cutoff 100', 'switching off', 'pairlistdist 102', 'margin 2', 'stepspercycle 1',
        'rigidBonds none', 'timestep 1', *extra])+'\n'


def native(executable, folder, config):
    (folder/'run.conf').write_text(config)
    with (folder/'run.log').open('w') as handle:
        result = subprocess.run([str(executable), '+p1', 'run.conf'], cwd=folder,
                                stdout=handle, stderr=subprocess.STDOUT)
    log = (folder/'run.log').read_text()
    assert result.returncode==0 and 'End of program' in log and 'FATAL ERROR' not in log
    titles = None
    energies = []
    for line in log.splitlines():
        if line.startswith('ETITLE:'):
            titles = line.split()[1:]
        if line.startswith('ENERGY:'):
            values = np.array([float(v) for v in line.split()[1:]])
            assert titles and len(titles)==len(values) and np.isfinite(values).all()
            energies.append(dict(zip(titles, values.tolist())))
    assert energies
    return energies, [line for line in log.splitlines() if re.search(r'warning', line, re.I)]


def fixture(folder, source_folder, candidate, xyz):
    folder.mkdir()
    shutil.copyfile(source_folder/'fragment.psf', folder/'fragment.psf')
    shutil.copyfile(candidate/'comparator_last.prm', folder/'candidate.prm')
    psf = app.CharmmPsfFile(str(folder/'fragment.psf'))
    with (folder/'fragment.pdb').open('w') as handle:
        app.PDBFile.writeFile(psf.topology, xyz*u.angstrom, handle)
    binary(folder/'start.coor', xyz)
    return psf


def run():
    policy, receipt = require('engine')
    candidate = Path(receipt['candidate'])
    root = ART/'cpd-anti-native-engine-v2'
    root.mkdir(exist_ok=False)
    (root/'executed_source.py').write_text(Path(__file__).read_text())
    executable = Path('/home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3')
    plan = dict(input_lock=source(STATE/'engine_input_lock.json'), policy=source(
        REPO/'experiments/cpd_anti_additive/preliminary_policy_v2.json'), namd=source(executable),
        native_coordinates='Double precision binary, not rounded PDB', cases=receipt['case_ids'],
        minimization_steps=1000, smoke_steps=100000, timestep_fs=1, temperature_K=300,
        seed=41017, environment='Vacuum, unswitched full intramolecular interactions; implementation test only',
        limitations=receipt['limitations'], simulation_ready=False,
        sources=[source(candidate/label/name) for label in receipt['case_ids']
                 for name in ('starting_A.txt', 'minimum_A.txt', 'fragment.psf', 'system.xml')])
    save(root/'plan.json', plan)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        params = app.CharmmParameterSet(str(candidate/'comparator_last.prm'))
    records = []
    for label in receipt['case_ids']:
        src = candidate/label
        psf = app.CharmmPsfFile(str(src/'fragment.psf'))
        original = mm.XmlSerializer.deserialize((src/'system.xml').read_text())
        reload = psf.createSystem(params, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False)
        integrators = [mm.VerletIntegrator(.001) for _ in range(2)]
        contexts = [mm.Context(s, i, mm.Platform.getPlatformByName('Reference'))
                    for s, i in zip((original, reload), integrators)]
        for geometry in ('starting', 'minimum'):
            xyz = np.loadtxt(src/f'{geometry}_A.txt')
            folder = root/f'{label}-{geometry}'
            fixture(folder, src, candidate, xyz)
            states = []
            for ctx in contexts:
                ctx.setPositions(xyz*u.angstrom)
                state = ctx.getState(getEnergy=True, getForces=True)
                states.append((state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole),
                    np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))))
            (energy, force), (reloaded_e, reloaded_f) = states
            assert abs(energy-reloaded_e)<=policy['engine']['static_export_energy_kcal']
            assert np.max(abs(force-reloaded_f))<=policy['engine']['static_export_force_kcal_A']
            values, notes = native(executable, folder, configuration(
                ['outputName static', 'temperature 0', 'run 0', 'output onlyforces static']))
            nf = read_binary(folder/'static.force', len(xyz))
            de = float(abs(values[-1]['POTENTIAL']-energy))
            df = float(np.max(abs(nf-force)))
            settings = policy['engine']
            passed = bool(de<=max(settings['native_equivalence_absolute_energy_kcal'],
                                 settings['native_equivalence_relative_limit']*abs(energy))
                and df<=max(settings['native_equivalence_absolute_force_kcal_A'],
                            settings['native_equivalence_relative_limit']*np.max(abs(force))))
            records.append(dict(case=label, geometry=geometry, energy_error_kcal=de,
                max_force_error_kcal_A=df, reference_energy_kcal=energy,
                reference_max_force_kcal_A=float(np.max(abs(force))), passed=passed,
                warnings=notes, log=source(folder/'run.log'), forces=source(folder/'static.force')))
            save(root/'progress.json', dict(native_equivalence=records))
            if not passed:
                save(root/'assessment.json', dict(native_equivalence=records, passed=False, simulation_ready=False))
                raise RuntimeError('Native equivalence failed; no smoke')
        del contexts, integrators
    smoke(root, candidate, executable, receipt, records)


def smoke(root, candidate, executable, receipt, records):
    src = candidate/'two-nucleosides'
    xyz = np.loadtxt(src/'minimum_A.txt')
    folder = root/'smoke'
    psf = fixture(folder, src, candidate, xyz)
    values, notes = native(executable, folder, configuration(['outputName smoke',
        'temperature 0', 'seed 41017', 'outputEnergies 1000', 'restartfreq 10000',
        'DCDfile smoke.dcd', 'DCDfreq 1000',
        'langevin on', 'langevinTemp 300', 'langevinDamping 1', 'langevinHydrogen off',
        'minimize 1000', 'reinitvels 300', 'run 100000']))
    layout = read_layout(folder/'smoke.dcd')
    assert layout.n_atoms==62 and layout.n_frames>=100
    frames = []
    for i in range(layout.n_frames):
        x, _ = read_frame(folder/'smoke.dcd', layout, i)
        assert np.isfinite(x).all()
        check = geometry_check(psf, xyz, x)
        frames.append(dict(frame=i, stereo_preserved=check['stereo_preserved'],
            covalent_ratio_range=check['covalent_ratio_range'], graph_distances_passed=check['graph_distances_passed']))
    final = read_binary(folder/'smoke.coor', 62)
    final_check = geometry_check(psf, xyz, final)
    passed = all(r['stereo_preserved'] and r['graph_distances_passed'] for r in frames)
    passed = passed and final_check['stereo_preserved'] and final_check['graph_distances_passed']
    report = dict(native_equivalence=records, smoke=dict(passed=bool(passed), duration_ps=100,
        frames=frames, final_geometry=final_check, final_step=values[-1]['TS'], warnings=notes,
        trajectory=source(folder/'smoke.dcd'), log=source(folder/'run.log')),
        engineering_test_passed=bool(passed), full_DNA_NAMD_tested=False,
        preliminary_research_qualified=False, simulation_ready=False, limitations=receipt['limitations'],
        plan=source(root/'plan.json'))
    save(root/'assessment.json', report)
    print(json.dumps(dict(engineering_test_passed=bool(passed), native_comparisons=len(records),
        max_force_error_kcal_A=max(r['max_force_error_kcal_A'] for r in records),
        frames=len(frames), full_DNA_NAMD_tested=False), indent=2))
    if not passed:
        raise RuntimeError('Smoke geometry integrity failed; retain trajectory')


def resume_smoke():
    _, receipt = require('engine')
    parent = ART/'cpd-anti-native-engine-v2'
    plan = read(parent/'plan.json')
    records = read(parent/'progress.json')['native_equivalence']
    expected = {(c, g) for c in receipt['case_ids'] for g in ('starting', 'minimum')}
    assert {(r['case'], r['geometry']) for r in records}==expected and all(r['passed'] for r in records)
    for ref in plan['sources']+[s for r in records for s in (r['log'], r['forces'])]:
        checked(ref)
    assert plan['input_lock']==source(STATE/'engine_input_lock.json')
    root = ART/'cpd-anti-native-smoke-v2b'
    root.mkdir(exist_ok=False)
    (root/'executed_source.py').write_text(Path(__file__).read_text())
    plan.update(prior_equivalence=source(parent/'progress.json'), prior_smoke_log=source(parent/'smoke/run.log'),
        correction='Enable Langevin before first startup. Prior run stopped before dynamics; no scientific criterion changed.',
        cumulative_minimization_steps=2000)
    save(root/'plan.json', plan)
    smoke(root, Path(receipt['candidate']), checked(plan['namd']), receipt, records)


if __name__ == '__main__':
    if sys.argv[1:] == ['resume-smoke']:
        resume_smoke()
    elif not sys.argv[1:]:
        run()
    else:
        raise ValueError('Expected no argument or resume-smoke')
