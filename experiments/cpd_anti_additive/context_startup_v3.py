"""Frozen matched startup and native checkpoint test; no 10 ns launch here."""
import argparse
import itertools
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

import numpy as np
from scipy.spatial import cKDTree

REPO = Path(os.environ.get('NADOC_REPO_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.sella_pilot import save, now
from experiments.cpd_anti_additive.run_engine_v2 import read_binary
from experiments.cpd_anti_additive.solvated_construction_v1 import geometry
from experiments.cpd_anti_additive.solvated_engine_v3 import geometry_passed, parse_log, NAMD
from backend.core.dcd_fast import read_layout, read_frame

ART = REPO / '.development-artifacts'
ROOT = ART / 'cpd-anti-context-v3'
ENGINE = ART / 'cpd-anti-solvated-engine-v3'
BOX = np.array([44.93, 67.438, 112.763])
N = 30867


def clearance(x):
    x = x[:3043]
    tree = cKDTree(x)
    return min(float(tree.query(x + np.array(s) * BOX)[0].min())
               for s in itertools.product([-1, 0, 1], repeat=3) if any(s))


def config(case, coor, seed, first=0, restart=None):
    """Same forcefield/PME as audited pilot, with all H bonds constrained at 2 fs."""
    base = (ENGINE / case / 'smoke/run.conf').read_text().splitlines()
    omit = {'structure', 'coordinates', 'binCoordinates', 'parameters', 'seed',
            'temperature', 'reinitvels', 'run', 'output', 'timestep', 'rigidBonds',
            'DCDfreq', 'restartfreq', 'outputEnergies'}
    lines = [line for line in base if line.split()[0] not in omit]
    lines += ['structure ' + str((ROOT / case / 'system.psf').resolve()),
              'coordinates ' + str((ROOT / case / 'system.pdb').resolve()),
              'binCoordinates ' + str(coor.resolve())]
    names = ['par_all36_na.prm', 'par_all36_cgenff.prm']
    if case == 'anti':
        names.append('anti_dna_overlay.prm')
    names.append('water_ions.prm')
    lines += ['parameters ' + str((ROOT / 'forcefield' / n).resolve()) for n in names]
    lines += ['rigidBonds all', 'rigidTolerance 0.00000001', 'rigidIterations 200',
              'timestep 2', 'DCDfreq 500', 'restartfreq 500', 'outputEnergies 500',
              f'seed {seed}', f'firsttimestep {first}', 'binaryoutput yes', 'binaryrestart yes']
    if restart is None:
        lines.append('temperature 0')
    else:
        lines += ['binVelocities ' + str(Path(str(restart) + '.vel').resolve()),
                  'extendedSystem ' + str(Path(str(restart) + '.xsc').resolve())]
    return '\n'.join(lines) + '\n'


def check_checkpoint(out, expected):
    records = []
    for ext in ['coor', 'vel']:
        x = read_binary(out / f'result.{ext}', N)
        assert np.isfinite(x).all()
        assert np.array_equal(x, read_binary(out / f'result.restart.{ext}', N))
        records.append(source(out / f'result.restart.{ext}'))
    xsc = np.loadtxt(out / 'result.restart.xsc')
    assert xsc[0] == expected
    assert np.array_equal(xsc, np.loadtxt(out / 'result.xsc'))
    assert np.allclose(xsc[[1, 5, 9]], BOX, atol=1e-10, rtol=0)
    return records + [source(out / 'result.restart.xsc')]


def review(case, out, first, last, frames):
    rows = parse_log(out / 'run.log')
    assert rows[0]['TS'] == first and rows[-1]['TS'] == last
    layout = read_layout(out / 'result.dcd')
    assert layout.n_atoms == N and layout.nsavc == 500 and layout.n_frames == frames
    assert layout.istart == first + 500
    assert layout.istart + (frames - 1) * 500 == last
    results = []
    for i in range(frames + 1):
        x = (read_frame(out / 'result.dcd', layout, i)[0] if i < frames
             else read_binary(out / 'result.coor', N))
        assert np.isfinite(x).all()
        g = geometry(ROOT / case, x)
        gap = clearance(x)
        results.append(dict(frame=i, final=i == frames, geometry=g, image_clearance_A=gap))
        if not geometry_passed(g) or gap <= 12:
            save(out / 'failed_frame_review.json', results)
            raise RuntimeError('Startup chemistry or periodic image gate failed')
    save(out / 'frames_review.json', results)
    cp = check_checkpoint(out, last)
    result = dict(at=now(), passed=True, first_step=first, last_step=last,
                  frames=frames, all_saved_geometries_passed=True,
                  min_image_clearance_A=min(r['image_clearance_A'] for r in results),
                  checkpoints=cp, log=source(out / 'run.log'),
                  config=source(out / 'run.conf'), trajectory=source(out / 'result.dcd'),
                  frame_review=source(out / 'frames_review.json'))
    save(out / 'assessment.json', result)
    return result, rows


def run():
    plan = read(ROOT / 'plan.json')
    for pin in plan['inputs']:
        checked(pin)
    assert read(checked(plan['engine_audit']))['engineering_test_passed']
    assert read(checked(plan['periodic_audit']))['passed']
    assert not read(ART / 'cpd-anti-validation-v1/campaign_pause.json')['paused']
    started = time.time()
    with (ROOT / 'started.json').open('x') as f:
        import json
        json.dump(dict(at=now(), epoch=started, deadline_epoch=min(started+36*3600,
                  plan['campaign_deadline_epoch']), plan=source(ROOT/'plan.json')), f, indent=2)
    deadline = min(started + plan['startup_max_hours'] * 3600, plan['campaign_deadline_epoch'])

    def native(out, text):
        out.mkdir(exist_ok=False)
        (out / 'run.conf').write_text(text)
        remaining = deadline - time.time()
        assert remaining > 0
        with (out / 'run.log').open('w') as log:
            p = subprocess.run([str(NAMD), '+p8', 'run.conf'], cwd=out,
                               stdout=log, stderr=subprocess.STDOUT, timeout=remaining)
        assert p.returncode == 0, f'Native failure: {out}'
        return parse_log(out / 'run.log')

    results = []
    try:
        # Deterministic common minimization once per chemistry, not three duplicate jobs.
        for case in plan['cases']:
            out = ROOT / case / 'minimize'
            text = config(case, ROOT / case / 'start.coor', plan['paired_seeds'][0])
            native(out, text + 'minimize 1000\noutput result\n')
            g = geometry(ROOT / case, read_binary(out / 'result.coor', N))
            gap = clearance(read_binary(out / 'result.coor', N))
            save(out / 'geometry.json', dict(geometry=g, image_clearance_A=gap))
            assert geometry_passed(g) and gap > 12
        for replica, seed in enumerate(plan['paired_seeds'], 1):
            for case in plan['cases']:
                folder = ROOT / case / f'replica-{replica}'
                folder.mkdir(exist_ok=False)
                out = folder / 'startup'
                text = config(case, ROOT / case / 'minimize/result.coor', seed)
                text += 'reinitvels 50\n'
                # 50 ps heating, then 50 ps NVT at 300 K; no position restraints.
                for target in range(75, 301, 25):
                    text += f'langevinTemp {target}\nrun 2500\n'
                text += 'run 25000\noutput result\n'
                native(out, text)
                a, rows = review(case, out, 0, 50000, 100)
                restart = folder / 'restart-test'
                text = config(case, out / 'result.restart.coor', seed + 1000,
                              first=50000, restart=out / 'result.restart')
                text += 'run 0\nrun 5000\noutput result\n'
                native(restart, text)
                b, rr = review(case, restart, 50000, 55000, 10)
                delta = abs(rr[0]['POTENTIAL'] - rows[-1]['POTENTIAL'])
                limit = max(.01, 1e-6 * abs(rows[-1]['POTENTIAL']))
                assert delta <= limit, 'Restart initial potential differs from saved endpoint'
                results.append(dict(case=case, replica=replica, seed=seed, startup=a,
                                    restart=b, restart_energy_error_kcal=delta,
                                    restart_energy_limit_kcal=limit))
                save(ROOT/'progress.json', dict(at=now(), completed=results))
        save(ROOT / 'startup_assessment.json', dict(at=now(), passed=True, results=results,
             elapsed_seconds=time.time()-started, context_10ns_complete=False,
             simulation_ready=False, minimum_certified=False))
    except BaseException:
        (ROOT / 'failure_traceback.txt').write_text(traceback.format_exc())
        save(ROOT / 'startup_assessment.json', dict(at=now(), passed=False, results=results,
             elapsed_seconds=time.time()-started, simulation_ready=False))
        raise


if __name__ == '__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    run()
