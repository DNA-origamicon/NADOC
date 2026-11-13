"""Compare audited pre-change examples with the current public loop/skip command.

Run serially with `just validate-safe`, OPENBLAS_NUM_THREADS=1, OMP_NUM_THREADS=1.
Inputs are source.nadoc and before-{straight,rh,lh}.nadoc captured through the
previous live commands. Every newly authored part passes the publication guard.
Only compact measurements/axis plots and audited examples are retained. No NMA,
thermal trajectories, external service submission, or user workspace writes.
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np

from backend.api import headless_build as hb, state
from backend.core.models import Design
from backend.core.loop_skip_calculator import forbidden_loop_skip_bps
from backend.core.oxdna_health import measure_bundle_twist, measure_bundle_twist_profile
from backend.physics.fem_solver import predict_shape
from scripts.agent_structure_guard import audit, publish


def axis_records(shape):
    return [dict(helix_id=a['helix_id'], bp_index=a['bp_index'],
                 backbone_position=a['position']) for a in shape['axis']]


def main(directory):
    directory = Path(directory)
    source = Design.model_validate_json((directory/'source.nadoc').read_text())
    audit(source)
    for name, angle in [('rh',180),('lh',-180)]:
        target = directory/f'after-{name}.nadoc'
        if target.exists():
            prior = Design.model_validate_json(target.read_text())
            audit(prior)
            if prior.deformations[-1].params.total_degrees != angle:
                raise ValueError(f'Unexpected comparison input: {target}')
            continue
        with hb.scratch_session(source.lattice_type):
            state.load_design(source.model_copy(deep=True))
            hb.add_twist(0,255,total_degrees=angle)
            d = hb.apply_loop_skip_deformations()
            publish(d,target)
            audit(Design.model_validate_json(target.read_text()))
    results = []
    for name in ['source','before-straight','before-rh','after-rh','before-lh','after-lh']:
        d = Design.model_validate_json((directory/f'{name}.nadoc').read_text())
        proof = audit(d)
        forbidden = forbidden_loop_skip_bps(d)
        assert all(m.bp_index not in forbidden[h.id] for h in d.helices for m in h.loop_skips)
        for steps in ([20,40] if name.startswith('after') else [20]):
            print(f'Solve {name}, {steps} increments', flush=True)
            start = time.monotonic()
            shape = predict_shape(d,nonlinear=True,n_steps=steps,with_rmsf=False,
                                  with_thermal_fluctuations=False,material='cando')
            points = axis_records(shape)
            coords = np.array([p['backbone_position'] for p in points])
            assert np.isfinite(coords).all()
            result = dict(name=name, increments=steps, seconds=round(time.monotonic()-start,2),
                          twist_deg=measure_bundle_twist(points),
                          twist_profile=measure_bundle_twist_profile(points),
                          loops=sum(m.delta>0 for h in d.helices for m in h.loop_skips),
                          skips=sum(m.delta<0 for h in d.helices for m in h.loop_skips),
                          net_per_helix={h.id:sum(m.delta for m in h.loop_skips) for h in d.helices},
                          replay=proof)
            results.append(result)
            print({k:v for k,v in result.items() if k not in {'axis','net_per_helix','replay','twist_profile'}},flush=True)
            (directory/'results.json').write_text(json.dumps(results,indent=2))
    plot(directory,results)


def plot(directory,results):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1,2,figsize=(12,4),layout='constrained')
    for r in results:
        if r['increments'] != 20:
            continue
        profile=np.asarray(r['twist_profile'])
        axes[0].plot(profile[:,0]-profile[0,0],profile[:,1],label=r['name'])
    axes[0].set(xlabel='Axial distance (nm)',ylabel='Cumulative RH-positive twist (°)',title='Native CanDo-style FEM · 3×6 square · 256 bp')
    axes[0].legend(fontsize=8);axes[0].grid(alpha=.2)
    names=['before-rh','after-rh','before-lh','after-lh']
    rows=[next(r for r in results if r['name']==n) for n in names]
    axes[1].bar(names,[r['twist_deg'] for r in rows]);axes[1].axhline(0,color='black',lw=.5)
    axes[1].set(ylabel='Predicted global twist (°)',title='Requested twist: RH +180° / LH −180°')
    for i,r in enumerate(rows):
        axes[1].annotate(f"{r['twist_deg']:.1f}°",(i,r['twist_deg']),ha='center',va='bottom')
    fig.savefig(directory/'comparison.png',dpi=170);plt.close(fig)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    main(parser.parse_args().directory)
