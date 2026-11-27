"""Export a compact timing/precision table and scientific figure for a benchmark."""
import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np

from backend.core.oxdna_vmmc_precision import histogram_blocks, yield_curve


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    parser.add_argument('--prior-attempt-seconds', type=float, default=0)
    args = parser.parse_args()
    root = args.campaign.resolve(strict=True)
    manifest = json.loads((root/'manifest.json').read_text())
    reports = [json.loads(p.read_text()) for p in sorted(root.glob('checkpoint_*.json'))]
    if not reports:
        raise ValueError('No completed precision checkpoint.')
    rows = []
    for r in reports:
        cpu_seconds = 0.
        for p in root.glob('*/execution.json'):
            if p.parent.name.startswith('replica_') and int(p.parent.name.rsplit('_', 1)[1]) >= r['completed_blocks']:
                continue
            cpu_seconds += json.loads(p.read_text())['elapsed_seconds']
        rows.append(dict(wall_minutes=r['elapsed_seconds']/60,
                         end_to_end_minutes=(r['elapsed_seconds']+args.prior_attempt_seconds)/60,
                         native_worker_hours=cpu_seconds/3600,
                         steps_per_replica=r['production_steps_per_replica'],
                         tm_c=r['tm_c'], ci95_lower_c=r['ci95_c'][0] if r['ci95_c'] else None,
                         ci95_upper_c=r['ci95_c'][1] if r['ci95_c'] else None,
                         tm_halfwidth_c=r['halfwidth_c'],
                         replica_mean_tm_c=float(np.mean(r['replica_tm_c'])) if all(t is not None for t in r['replica_tm_c']) else None,
                         diagnostic_replica_ci95_lower_c=r.get('between_replica_ci95_c', [None, None])[0],
                         diagnostic_replica_ci95_upper_c=r.get('between_replica_ci95_c', [None, None])[1],
                         approximate_equal_precision_delta_halfwidth_c=math.sqrt(2)*r['halfwidth_c'] if r['halfwidth_c'] else None,
                         status=r['status'], reasons='; '.join(r['reasons'])))
    with (root/'precision_vs_time.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    final = reports[-1]
    budget = manifest['wall_budget_seconds']
    forecast = None
    if final['halfwidth_c'] and not final['reasons']:
        forecast = {str(target): final['elapsed_seconds']/60*(final['halfwidth_c']/target)**2
                    for target in (.35, .7, 1.)}
    summary = dict(final=final, timeline=rows, manifest=manifest,
                   prior_attempt_seconds=args.prior_attempt_seconds,
                   configured_wall_budget_seconds=budget,
                   approximate_minutes_for_per_design_halfwidth=forecast,
                   forecast_qualification='Inverse-square scaling heuristic; includes setup overhead, assumes stationary sampling and unchanged mixing. Not a convergence guarantee.',
                   delta_qualification='The sqrt(2) projection assumes a second independent design with comparable precision. No modified/CPD design was simulated.')
    (root/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')

    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), constrained_layout=True)
    ts = np.asarray(final['temperatures_c'])
    n_pairs = int((root/'topology.top').read_text().split()[0])//2
    for replica in range(4):
        arrays = [histogram_blocks(root/f'replica_{replica}_block_{block:02}'/'traj_hist.dat', n_pairs, ts)[0]
                  for block in range(final['completed_blocks'])]
        curve = yield_curve(np.concatenate(arrays).sum(axis=0))
        axes[0].plot(ts, curve, label=f"Replica {replica+1} ({'bound' if replica%2 == 0 else 'unbound'} start)", alpha=.8)
    axes[0].plot(ts, final['duplex_yield'], color='black', lw=2, label='Pooled')
    axes[0].axhline(.5, color='gray', ls=':')
    if final['ci95_c']:
        axes[0].axvspan(*final['ci95_c'], color='gray', alpha=.18, label='Approx. 95% Tm interval')
    axes[0].set(xlabel='Temperature (°C)', ylabel='Bulk duplex fraction', ylim=(0, 1))
    axes[0].legend(fontsize=7)
    valid = [r for r in rows if r['tm_halfwidth_c'] is not None]
    if valid:
        x = [r['wall_minutes'] for r in valid]
        axes[1].plot(x, [r['tm_halfwidth_c'] for r in valid], 'o-', label='Tm half-width')
        axes[1].plot(x, [r['approximate_equal_precision_delta_halfwidth_c'] for r in valid], 's--', label='Projected ΔTm half-width')
    provisional = [r for r in rows if r['diagnostic_replica_ci95_lower_c'] is not None]
    if provisional:
        axes[1].plot([r['wall_minutes'] for r in provisional],
                     [(r['diagnostic_replica_ci95_upper_c']-r['diagnostic_replica_ci95_lower_c'])/2 for r in provisional],
                     'x:', color='darkorange', label='Replica-only interval (provisional)')
    axes[1].axhline(1, color='gray', ls=':', label='±1°C target')
    axes[1].set(xlabel='Wall time, including preparation (min)', ylabel='Approx. 95% interval half-width (°C)', ylim=(0, None))
    axes[1].legend(fontsize=8)
    fig.suptitle(f"{n_pairs}-bp VMMC benchmark · {manifest['workers']} CPU cores · {manifest['salt_M']:g} M salt · source box retained\n"+
                 ('Diagnostics unresolved — provisional estimates' if final['reasons'] else 'Sampling diagnostics passed; model accuracy not assessed'), fontsize=11)
    fig.savefig(root/'precision_benchmark.png', dpi=170)
    fig.savefig(root/'precision_benchmark.pdf')
    plt.close(fig)
    print(json.dumps(rows[-1]), flush=True)


if __name__ == '__main__':
    main()
