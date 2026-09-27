"""Finite isolated full-DNA native smoke following reviewed source repair.

No fitting, further minimization, product promotion, or minimum claim. Native
NoCutoff comparisons cover solute and a solvent/ion fixture; full PME is tested
by NAMD dynamics, not misrepresented as an independent PME equivalence check.
"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import warnings

import numpy as np
import openmm as mm
from openmm import app, unit as u
import parmed

REPO = Path(os.environ.get('NADOC_REPO_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.sella_pilot import save, now
from experiments.cpd_anti_additive.preliminary_protocol import POLICY, require
from experiments.cpd_anti_additive.run_engine_v2 import binary, read_binary
from experiments.cpd_anti_additive.solvated_construction_v1 import configuration, geometry
from backend.core.dcd_fast import read_layout, read_frame, UnsupportedDCD

ART = REPO/'.development-artifacts'
ROOT = ART/'cpd-anti-solvated-engine-v2e'
PREVIOUS = ART/'cpd-anti-solvated-engine-v2'
PARENT = ART/'cpd-anti-stereo-protected-construction-v2'
NAMD = Path('/home/jojo/Applications/NAMD_Git-2025-12-04_Source/Linux-x86_64-g++/namd3')
N = 30867


def prepare():
    require('conformational')
    review = read(PARENT/'independent_review.json')
    assert review['geometry_eligible_for_engine_review']
    checked(review['construction_assessment'])
    assert read(ART/'cpd-anti-native-precision-diagnostic-v1/assessment.json')['passed']
    ROOT.mkdir(exist_ok=False)
    shutil.copyfile(Path(__file__), ROOT/'worker.py')
    sources = [POLICY, NAMD, ROOT/'worker.py', PARENT/'independent_review.json',
        PARENT/'plan.json', PARENT/'inputs_lock.json', PARENT/'parent_assembly.json',
        ART/'cpd-anti-conformational-native-v2-r1/independent_review.json',
        ART/'cpd-anti-conformational-fit-v2-r1/candidate/assessment.json',
        REPO/'experiments/cpd_anti_additive/solvated_construction_v1.py',
        REPO/'backend/core/dcd_fast.py', PREVIOUS/'assessment.json',
        PREVIOUS/'anti/solvent_static/run.log', PREVIOUS/'control/solvent_static/run.log',
        ART/'cpd-anti-solvated-engine-v2b/preparation_failure.json',
        ART/'cpd-anti-solvated-engine-v2c/preparation_failure.json',
        ART/'cpd-anti-solvated-engine-v2d/assessment.json',
        ART/'cpd-anti-native-precision-diagnostic-v1/assessment.json']
    plan = dict(created_at=now(), sources=[source(p) for p in sources], cases=['anti','control'],
        scope='Isolated solvated full-DNA NAMD engineering smoke; no normal app integration or preliminary research qualification',
        inputs='Explicit four-coordinate source repair followed by the reviewed 10000-step construction; all artificial restraints removed',
        gate_scope='Original v2 engine chemistry/coverage/E-F/integration criteria; unchanged .01 stationarity and3.5 product-placement screens remain failed and separately reported',
        static_comparison='OpenMM Reference NoCutoff versus NAMD unswitched 1000 A cutoff at identical double coordinates: each full 3043-atom solute plus a two-water/Na/Cl fixture. This is not independent full periodic PME equivalence.',
        steps_per_case=100000, duration_ps_per_case=100, timestep_fs=1, temperature_K=300,
        normal_masses=True, hydrogen_mass_repartitioning=False, rigid_bonds='water',
        ensemble='Fixed-cell NVT; Langevin damping1/ps, hydrogen thermostat off',
        seed=41017, saved_frame_steps=1000, additional_minimization_steps=0,
        max_attempts=1, max_continuations=0, native_workers=8, memory_gib=12,
        startup_repair='V2 solute E/F passed; empty NTITLE caused native solvent-fixture rejection before energy. V2b preparation lost its title in conversion; V2c direct writer changed charge-group records. Both caught before launch. Convert to CharmmPsfFile, then set its title and write; only title differs from v2. All failures retained, zero prior MD/minimization, no physical budget extension.',
        precision_revision='V2d solvent-force differences .001587/.001767 failed .001; zero MD. Identical diagnostic with bondedGPU0 gives .00002503/.00002430. Use CPU bonded terms for BOTH static comparison and dynamics, keeping GPU nonbonded/PME. Same potential/coordinates/tolerances; old failures retained.',
        bondedGPU=0, precision_reference='https://www.ks.uiuc.edu/Research/namd/cvs/ug/node103.html',
        hard_seconds=5960, previous_construction_seconds=read(PARENT/'assessment.json')['elapsed_seconds'],
        previous_static_seconds=read(PREVIOUS/'assessment.json')['elapsed_seconds'],
        native_hard_hours_including_construction=2,
        stop='First saved solute inversion, bond outside .7-1.3 equilibrium, severe contact ratio<.5 or ring piercing; native fatal/nonfinite E-F/integration or wall cap. Stop affected case and preserve evidence. No extension.',
        limitations=['7/19 exposed profile geometry descriptors fail; four prospective QM targets missing',
            'Not stationary, not minimum-certified; product-placement screen fails',
            'Single-seed 100ps engineering test, no equilibration/ensemble/mechanics claim',
            'Control shares box/protocol but has a different prior conditioning history; no causal comparison',
            'Geometry checks apply to saved 1ps frames and final coordinates, not a proof between frames'],
        simulation_ready=False)
    assert plan['previous_construction_seconds'] + plan['previous_static_seconds'] + plan['hard_seconds'] < 7200
    save(ROOT/'plan.json', plan)
    shutil.copytree(PARENT/'forcefield', ROOT/'forcefield')
    shutil.copyfile(PARENT/'parent_assembly.json', ROOT/'assembly.json')
    for case in plan['cases']:
        folder = ROOT/case
        folder.mkdir()
        for name in ['system.psf','system.pdb','solute.psf','geometry_reference.json','source_A.txt']:
            shutil.copyfile(PARENT/case/name, folder/name)
        shutil.copyfile(PARENT/case/'unrestrained-05000/result.coor', folder/'start.coor')
        x = read_binary(folder/'start.coor', N)
        g = geometry(folder, x)
        assert geometry_passed(g)
        save(folder/'starting_review.json', g)
        # PDB is only an atom-index container; all native coordinates use doubles.
        for kind in ['solute_static', 'solvent_static']:
            out = folder/kind; out.mkdir()
            if kind == 'solute_static':
                shutil.copyfile(folder/'solute.psf', out/'fixture.psf')
                coordinates = x[:3043]
            else:
                ids = list(range(3043,3049)) + [3043+3*9223,3043+3*9223+124]
                structure = parmed.load_file(str(folder/'system.psf'))
                mask = [int(i in ids) for i in range(N)]
                subset = parmed.charmm.CharmmPsfFile.from_structure(structure[mask])
                subset.title = ['Isolated two-water NaCl static fixture; original atom parameters']
                subset.write_psf(str(out/'fixture.psf'))
                coordinates = x[ids]
                save(out/'indices.json', ids)
            psf = app.CharmmPsfFile(str(out/'fixture.psf'))
            assert len(psf.atom_list) == len(coordinates)
            with (out/'fixture.pdb').open('w') as f:
                app.PDBFile.writeFile(psf.topology, coordinates*u.angstrom, f)
            binary(out/'start.coor', coordinates)
        (folder/'smoke').mkdir()
        box = read(ROOT/'assembly.json')['box_A']
        cfg = configuration(folder, (folder/'start.coor').resolve(),
            dict(fixed_solute=False, k_kcal_A2=0), 0, box)
        cfg = cfg.replace('outputEnergies 50', 'outputEnergies 1000')
        cfg = cfg.replace('DCDfreq 50', 'DCDfreq 1000\nrestartfreq 1000')
        cfg = cfg.replace('run 0', 'bondedGPU 0\nrun 0')
        cfg = cfg.replace('run 0', '\n'.join(['seed 41017','langevin on',
            'langevinTemp 300','langevinDamping 1','langevinHydrogen off',
            'reinitvels 300','run 100000']))
        assert all(term not in cfg for term in ['extraBonds','fixedAtoms','constraints on','minimize'])
        (folder/'smoke/run.conf').write_text(cfg)
    save(ROOT/'inputs_lock.json', dict(created_at=now(), files=[source(p) for p in sorted(ROOT.rglob('*')) if p.is_file()]))
    print('Prepared', ROOT, flush=True)


def geometry_passed(g):
    return bool(g['stereo_passed'] and g['bond_integrity_passed']
        and g['contacts']['severe_clash_count'] == 0 and g['contacts']['all_piercing_count'] == 0)


def parse_log(path, terminal=True):
    text = path.read_text()
    assert 'FATAL ERROR' not in text
    if terminal:
        assert 'End of program' in text
    rows = []
    for line in text.splitlines():
        if line.startswith('ETITLE:'):
            titles = line.split()[1:]
        if line.startswith('ENERGY:'):
            # Live trailing partial lines wait for the next poll.
            if not terminal and not text.endswith('\n') and line == text.splitlines()[-1]:
                continue
            values = np.array([float(v) for v in line.split()[1:]])
            assert len(values) == len(titles) and np.isfinite(values).all()
            rows.append(dict(zip(titles, values.tolist())))
    if terminal:
        assert rows
    return rows


def static(case, kind, remaining):
    folder = ROOT/case/kind
    psf = app.CharmmPsfFile(str(folder/'fixture.psf'))
    x = read_binary(folder/'start.coor', len(psf.atom_list))
    paths = [ROOT/'forcefield'/n for n in ['par_all36_na.prm','par_all36_cgenff.prm']]
    if case == 'anti':
        paths.append(ROOT/'forcefield/anti_dna_overlay.prm')
    paths.append(ROOT/'forcefield/water_ions.prm')
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        params = app.CharmmParameterSet(*(str(p) for p in paths))
        system = psf.createSystem(params, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False)
    (folder/'system.xml').write_text(mm.XmlSerializer.serialize(system))
    it = mm.VerletIntegrator(.001)
    ctx = mm.Context(system, it, mm.Platform.getPlatformByName('Reference'))
    ctx.setPositions(x*u.angstrom)
    s = ctx.getState(getEnergy=True, getForces=True)
    e = s.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
    f = np.array(s.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
    assert np.isfinite(e) and np.isfinite(f).all()
    del ctx,it
    np.savez(folder/'reference.npz', energy_kcal=e, forces_kcal_A=f)
    cfg = ['structure fixture.psf','coordinates fixture.pdb','binCoordinates start.coor',
        'paraTypeCharmm on'] + ['parameters '+str(p.resolve()) for p in paths]
    cfg += ['exclude scaled1-4','oneFourScaling 1','cutoff 1000','switching off',
        'pairlistdist 1002','margin 2','stepspercycle 1','rigidBonds none','timestep 1',
        'temperature 0','outputName static','bondedGPU 0','run 0','output onlyforces static']
    (folder/'run.conf').write_text('\n'.join(cfg)+'\n')
    with (folder/'run.log').open('w') as log:
        p = subprocess.run([str(NAMD),'+p1','run.conf'], cwd=folder, stdout=log,
            stderr=subprocess.STDOUT, timeout=remaining())
    assert p.returncode == 0
    rows = parse_log(folder/'run.log')
    nf = read_binary(folder/'static.force', len(x))
    settings = read(POLICY)['engine']
    de = abs(rows[-1]['POTENTIAL']-e); df = float(abs(nf-f).max())
    elimit = max(settings['native_equivalence_absolute_energy_kcal'], settings['native_equivalence_relative_limit']*abs(e))
    flimit = max(settings['native_equivalence_absolute_force_kcal_A'], settings['native_equivalence_relative_limit']*float(abs(f).max()))
    result = dict(case=case, fixture=kind, atoms=len(x), passed=bool(de<=elimit and df<=flimit),
        energy_error_kcal=de, force_error_kcal_A=df, energy_limit_kcal=elimit,
        force_limit_kcal_A=flimit, reference_energy_kcal=e, reference_max_force_kcal_A=float(abs(f).max()),
        log=source(folder/'run.log'), forces=source(folder/'static.force'), reference=source(folder/'reference.npz'))
    save(folder/'assessment.json', result)
    print('Static',case,kind,result['passed'],de,df,flush=True)
    assert result['passed'], 'Native static mismatch; no dynamics for this case'
    return result


def smoke(case, remaining):
    folder = ROOT/case; out = folder/'smoke'; frames = []; rows = []
    dcd = out/'result.dcd'; proc = None
    def consume():
        if not dcd.exists() or dcd.stat().st_size < 300:
            return
        try:
            layout = read_layout(dcd)
        except (UnsupportedDCD, EOFError):
            if proc.poll() is not None:
                raise
            return
        assert layout.n_atoms == N and layout.nsavc == 1000
        for i in range(len(frames), layout.n_frames):
            x, _ = read_frame(dcd, layout, i)
            assert np.isfinite(x).all()
            g = geometry(folder, x)
            record = dict(frame=i, step=layout.istart+i*layout.nsavc, geometry=g)
            frames.append(record)
            save(out/'frames.json',frames)
            save(ROOT/'progress.json',dict(case=case,saved_frames=len(frames),latest_step=record['step'],geometry_passed=geometry_passed(g),at=now()))
            if record['step']%10000 == 0:
                print('MD',case,record['step'],'stereo',g['stereo_passed'],'bonds',g['bond_ratio_range'],flush=True)
            assert geometry_passed(g), 'Saved dynamics frame failed geometry gate; no continuation'
    try:
        with (out/'run.log').open('w') as log:
            proc = subprocess.Popen([str(NAMD),'+p8','run.conf'],cwd=out,stdout=log,stderr=subprocess.STDOUT)
            while proc.poll() is None:
                remaining()
                consume()
                rows = parse_log(out/'run.log', terminal=False)
                time.sleep(1)
            consume()
        assert proc.returncode == 0
        rows = parse_log(out/'run.log')
        assert rows[-1]['TS'] == 100000 and len(frames) >= 100 and frames[-1]['step'] == 100000
        final = geometry(folder, read_binary(out/'result.coor', N))
        force = read_binary(out/'result.force', N)
        assert geometry_passed(final)
        result = dict(case=case, passed=True, duration_ps=100, final_step=rows[-1]['TS'],
            saved_frames=len(frames), final_geometry=final, max_final_force_kcal_A=float(abs(force).max()),
            finite_energy_rows=len(rows), temperature_range_K=[min(r['TEMP'] for r in rows),max(r['TEMP'] for r in rows)],
            log=source(out/'run.log'), trajectory=source(dcd), final_coordinates=source(out/'result.coor'),
            final_forces=source(out/'result.force'), frames=source(out/'frames.json'),
            minimum_certified=False, preliminary_research_qualified=False, simulation_ready=False)
        save(out/'assessment.json',result)
        return result
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill(); proc.wait(timeout=10)


def run():
    for record in read(ROOT/'inputs_lock.json')['files']:
        checked(record)
    assert not read(ART/'cpd-anti-validation-v1/campaign_pause.json')['paused']
    start = time.monotonic(); plan = read(ROOT/'plan.json')
    with (ROOT/'started.json').open('x') as f:
        import json
        json.dump(dict(at=now(),plan=source(ROOT/'plan.json')),f)
    def remaining():
        value = plan['hard_seconds']-(time.monotonic()-start)
        if value <= 0:
            raise RuntimeError('Two-case6000s cap reached; no continuation')
        return value
    reports = []
    for case in plan['cases']:
        comparisons = []; result = None; error = None
        try:
            for kind in ['solute_static','solvent_static']:
                comparisons.append(static(case, kind, remaining))
            result = smoke(case, remaining)
        except Exception as exc:
            error = repr(exc)
            (ROOT/case/'failure_traceback.txt').write_text(traceback.format_exc())
        report = dict(case=case, error=error, static_comparisons=comparisons, smoke=result,
            engine_passed=bool(error is None and result and result['passed']),
            minimum_certified=False, preliminary_research_qualified=False, simulation_ready=False)
        save(ROOT/case/'assessment.json',report); reports.append(report)
    passed = all(r['engine_passed'] for r in reports)
    save(ROOT/'assessment.json',dict(at=now(),plan=source(ROOT/'plan.json'),
        cases=[source(ROOT/r['case']/'assessment.json') for r in reports], engineering_test_passed=passed,
        full_DNA_dynamics_tested=any(r['smoke'] is not None for r in reports), elapsed_seconds=time.monotonic()-start,
        limitations=plan['limitations'], minimum_certified=False, preliminary_research_qualified=False,simulation_ready=False))
    if not passed:
        raise RuntimeError('Isolated full-DNA engineering failed; retain all evidence and do not extend')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('action',choices=['prepare','run'])
    globals()[parser.parse_args().action]()
