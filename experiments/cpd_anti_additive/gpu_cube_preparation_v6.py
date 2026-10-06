"""One audited, restartable final-composition preparation per invocation."""
import argparse
import importlib.util
import os
from pathlib import Path
import sys
import time
import traceback

REPO = Path(os.environ.get('NADOC_REPO_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.validation_gate import read, checked, source
from experiments.cpd_anti_additive.sella_pilot import save, now


def admission(plan):
    if not plan['authorized'] or not 0 < plan['hard_seconds'] < 16 * 3600:
        raise ValueError('Explicit bounded job admission required')
    if time.time() >= plan['deadline_epoch']:
        raise ValueError('Job deadline expired; audit before admitting another chunk')
    for pin in plan['inputs']:
        checked(pin)
    return plan


def load_engine(plan):
    spec = importlib.util.spec_from_file_location('frozen_cube_engine', checked(plan['engine']))
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    engine.ROOT = Path(plan['root'])
    engine.ASSEMBLY = read(engine.ROOT / 'assembly.json')
    case = next(c for c in engine.ASSEMBLY['cases'] if c['case'] == plan['case'])
    engine.N = case['atoms']
    engine.NW = engine.ASSEMBLY['waters']
    engine.NSOL = case['solute_atoms']
    engine.MASS = case['mass_Da']
    # Check authorization/deadline at every native launch; expensive file pins are
    # verified once at admission and all generated native inputs are retained.
    def authorize():
        if time.time() >= plan['deadline_epoch']:
            raise ValueError('Job deadline expired')
        checked(plan['authorization'])
        return plan
    engine.authorize = authorize
    return engine


def run(plan_path):
    plan = admission(read(plan_path))
    m = load_engine(plan)
    case, rep, seed = plan['case'], plan['replica'], plan['seed']
    folder = m.ROOT / case
    deadline = plan['deadline_epoch']
    import numpy as np
    if rep == 1:
        initial_box = np.array(m.ASSEMBLY['box_A'])
        initial = m.physical(case, m.read_binary(folder/'start.coor', m.N), initial_box)
        assert m.geometry_passed(initial['geometry']) and initial['image_clearance_A'] > 12
        assert initial['min_water_OO_A'] > 1.5 and initial['max_OH_error_beyond_storage_A'] < 1e-5
        save(folder/'initial_review.json', initial)
        energies, forces = [], []
        for mode, resident in [('reference', False), ('resident', True)]:
            out = folder/f'static-{mode}'
            rows = m.native(out, m.config(case, folder/'start.coor', resident=resident)+'run 0\noutput onlyforces result\n', deadline, 4, resident)
            energies.append(rows[-1]['POTENTIAL'])
            forces.append(m.read_binary(out/'result.force', m.N))
        de = abs(energies[0]-energies[1]); df = float(abs(forces[0]-forces[1]).max())
        el = max(.001, 1e-4*abs(energies[0])); fl = max(.001, 1e-4*float(abs(forces[0]).max()))
        save(folder/'static_assessment.json', dict(passed=bool(de <= el and df <= fl), energy_error_kcal=de, energy_limit_kcal=el, force_error_kcal_A=df, force_limit_kcal_A=fl))
        assert de <= el and df <= fl
        out = folder/'minimize'
        m.native(out, m.config(case, folder/'start.coor')+'minimize 1000\noutput result.restart\noutput result\n', deadline)
        g = m.physical(case, m.read_binary(out/'result.coor', m.N), initial_box)
        save(out/'geometry.json', g)
        assert g['passed']
    else:
        assert read(folder/'static_assessment.json')['passed']
        assert read(folder/'minimize/geometry.json')['passed']
    replica = folder/f'replica-{rep}'
    out = replica/'heat'
    cfg = m.config(case, folder/'minimize/result.coor', seed=seed, stride=500)+'reinitvels 50\n'
    for target in range(75, 301, 25):
        cfg += f'langevinTemp {target}\nrun 2500\n'
    rows = m.native(out, cfg+'output result.restart\noutput result\n', deadline)
    heat = m.review(case, out, 0, 25000, 500, rows, deadline)
    npt = m.run_stage(case, replica/'npt', out/'result.restart', 25000, 500000, seed+1000, 1000, deadline)
    restart = m.run_stage(case, replica/'restart', replica/'npt/result.restart', 525000, 5000, seed+2000, 1000, deadline)
    save(replica/'preparation_assessment.json', dict(at=now(), case=case, replica=rep, seed=seed, heat=heat, npt=npt, restart=restart,
         plan=source(plan_path), review_required_before_next_job=True, simulation_ready=False, minimum_certified=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.plan)
    except BaseException:
        args.plan.with_suffix('.failure.txt').write_text(traceback.format_exc())
        raise
