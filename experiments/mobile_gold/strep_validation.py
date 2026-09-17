"""GPU mechanics and generated streptavidin/biotin handle integration checks."""
import argparse
import json
from pathlib import Path
import subprocess
import time
import numpy as np
from experiments.mobile_gold.validate import run_case
from backend.core.models import Design, Nanoparticle
from backend.core.streptavidin import build_streptavidin_coating
from backend.core.gold_strep_dna import build_dna
from backend.core.oxdna_job import new_oxdna_job
from backend.core.oxdna_protocol import OxdnaStageSpec, render_stage_input
from backend.core.oxdna_runner import prepare_oxdna_job
from backend.api.crud import _geometry_for_design
from backend.core.constants import NM_TO_OXDNA


def main(root, binary):
    root.mkdir(parents=True, exist_ok=False)
    records = []
    core = (3., 100., 360., .01, .0008)
    dt = 1e-4
    for precision in ('float', 'mixed'):
        # Contact away from the gold surface, with nonzero reaction torque.
        final, rec = run_case(root, 'coat_contact_'+precision,
            [[5, 1.2, 0], [0, 0, 0]], cores=[core],
            coating=[(0, 5, 0, 0, 1)], dt=dt, precision=precision, binary=binary)
        np.testing.assert_allclose(final[0, 9:12]/dt, [0, 20, 0], atol=.001)
        np.testing.assert_allclose(final[1, 9:12]*100/dt, [0, -20, 0], atol=.001)
        np.testing.assert_allclose(final[1, 12:15]*360/dt, [0, 0, -100], atol=.005)
        records.append(rec)
        dna = np.array([6.5, .6, 0]); back = np.array([-.34, .3408, 0])
        site = np.array([5., 0, 0]); delta = dna+back-site
        force = -1.424*(np.linalg.norm(delta)-.8)*delta/np.linalg.norm(delta)
        final, rec = run_case(root, 'pocket_graft_'+precision, [dna, [0, 0, 0]],
            cores=[core], grafts=[(0, 0, *site, .8, 1.424)],
            coating=[(0, -5, 0, 0, 1)], dt=dt, precision=precision, binary=binary)
        np.testing.assert_allclose(final[0, 9:12]/dt, force, atol=.001)
        np.testing.assert_allclose(final[1, 9:12]*100/dt, -force, atol=.001)
        np.testing.assert_allclose(final[1, 12:15]*360/dt, np.cross(site, -force), atol=.005)
        records.append(rec)
    final, rec = run_case(root, 'composite_contact',
        [[50, 50, 50], [0, 0, 0], [5, 1.9, 0]],
        cores=[core, (1., 100., 40., .01, .0008)],
        coating=[(0, 5, 0, 0, 1)], dt=dt, binary=binary)
    np.testing.assert_allclose(final[1, 9:12]*100/dt, [0, -10, 0], atol=.002)
    np.testing.assert_allclose(final[2, 9:12]*100/dt, [0, 10, 0], atol=.002)
    np.testing.assert_allclose(final[1, 12:15]*360/dt, [0, 0, -50], atol=.01)
    records.append(rec)
    for mode in ('adsorption', 'biotin_tether'):
        p = Nanoparticle(diameter_nm=10, coating=build_streptavidin_coating(
            10, count_override=1, mode=mode))
        r, h, s = build_dna(p, 'ACGTACGTACGTACGT'); p.biotin_dna = [r]
        d = Design(nanoparticles=[p], helices=[h], strands=[s])
        stage = OxdnaStageSpec(mode, 'production', 'MD', 30000, 'CUDA', seed=191,
            max_backbone_force=5, max_backbone_force_far=10, print_conf_interval_override=1000)
        job = new_oxdna_job(mode, [stage.to_status()])
        info = prepare_oxdna_job(d, _geometry_for_design(d), job, root, [stage])
        jd = job.job_dir(root)
        (jd/'input').write_text(render_stage_input(stage, 'topology.top', 'conf.dat'))
        start = time.perf_counter()
        with (jd/'run.log').open('w') as log:
            subprocess.run([binary, 'input'], cwd=jd, stdout=log, stderr=subprocess.STDOUT,
                           timeout=120, check=True)
        elapsed = time.perf_counter()-start
        rows = np.loadtxt(jd/'last_conf.dat', skiprows=3)
        assert np.isfinite(rows).all()
        g = info['mobile_gold']['grafts'][0]; c = rows[-1]; x = rows[g['dna']]
        rot = np.column_stack((c[3:6], np.cross(c[6:9], c[3:6]), c[6:9]))
        bb = x[:3]-.34*x[3:6]+.3408*np.cross(x[6:9], x[3:6])
        distance = np.linalg.norm(bb-c[:3]-rot@np.array(g['site']))/NM_TO_OXDNA
        records.append(dict(mode=mode, steps=stage.steps, wall_s=elapsed,
            steps_per_s=stage.steps/elapsed, linker_nm=float(distance),
            core_displacement_nm=float(np.linalg.norm(c[:3])/NM_TO_OXDNA)))
    (root/'results.json').write_text(json.dumps(records, indent=2)+'\n')
    print(json.dumps(records, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--binary', required=True)
    args = parser.parse_args()
    main(args.output, str(Path(args.binary).resolve()))
