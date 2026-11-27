"""Post-process a completed campaign; no new simulations or altered acceptance checks."""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t

from backend.core.oxdna_vmmc_precision import histogram_blocks, inefficiency, tm_of


def analyse(root, output):
    root = Path(root).resolve(strict=True)
    output = Path(output).resolve()
    output.mkdir(exist_ok=False)
    final = json.loads((root/'result.json').read_text())
    if final['tm_c'] is None:
        raise ValueError('The pooled curve must bracket melting before estimating a sampling trend.')
    ts = np.asarray(final['temperatures_c'])
    n_pairs = int((root/'topology.top').read_text().split()[0])//2
    arrays, states = [], []
    paths = final.get('production_directories') or [[str(root/f'replica_{i}_block_{j:02}') for j in range(final['completed_blocks'])] for i in range(4)]
    for replica in range(4):
        blocks, sequence = [], []
        for path in paths[replica]:
            directory = Path(path)
            data, cadence = histogram_blocks(directory/'traj_hist.dat', n_pairs, ts)
            blocks.append(data)
            energy = np.loadtxt(directory/'energy.dat')
            sequence.extend(energy[energy[:, 0] > 0, -2].astype(int).tolist())
        arrays.append(np.concatenate(blocks))
        states.append(np.asarray(sequence))
    prefixes = []
    for count in range(1, final['completed_blocks']+1):
        length = count*len(arrays[0])//final['completed_blocks']
        estimates = [tm_of(a[:length].sum(axis=0), ts) for a in arrays]
        valid = all(v is not None for v in estimates)
        half = float(student_t.ppf(.975, 3)*np.std(estimates, ddof=1)/2) if valid else None
        prefixes.append(dict(sweeps_per_replica=length*cadence, tm_replicas_c=estimates,
                             replica_sd_c=float(np.std(estimates, ddof=1)) if valid else None,
                             halfwidth_c=half,
                             variance_cost_c2_million_sweeps=half**2*length*cadence/1e6 if valid else None))
    # A stationary delta-method diagnostic: time-batch variance of the Tm
    # influence, evaluated separately in each replica. It is not an accepted CI.
    batch_variances, chain_diagnostics = [], []
    influences = []
    for a, q in zip(arrays, states):
        totals = a.sum(axis=0)
        index = int(np.argmin(abs(ts-final['tm_c'])))
        slope = float(np.gradient(np.log(totals[1]/totals[0]), ts)[index])
        u, b = a[:, 0, index], a[:, 1, index]
        influence = -(b/b.mean()-u/u.mean())/slope
        influences.append(influence)
        g = inefficiency(influence)
        boundary = np.r_[0, np.where(np.diff(q > 0))[0]+1, len(q)]
        dwell = np.diff(boundary)*cadence
        chain_diagnostics.append(dict(estimated_inefficiency=g,
                                      estimated_effective_blocks=len(a)/g,
                                      correlation_scale_sweeps=g*cadence,
                                      recorded_transitions=len(boundary)-2,
                                      longest_observed_dwell_sweeps=int(max(dwell)),
                                      dwell_qualification='First/last dwell censored; events faster than recording cadence may be missed.'))
    for length in [1, 5, 10, 25, 50, 100, 175, 250, 350, 500]:
        batches = [x[:len(x)//length*length].reshape(-1, length).mean(axis=1) for x in influences]
        variances = [float(np.var(b, ddof=1)/len(b)) for b in batches]
        batch_variances.append(dict(batch_sweeps=length*cadence, batches_per_replica=len(batches[0]),
                                    pooled_mean_variance_c2=sum(variances)/16,
                                    diagnostic_normal_halfwidth_c=1.96*np.sqrt(sum(variances)/16),
                                    qualification='Assumes stationary influence and independent batches; inspect for a plateau, not a convergence certificate.'))
    # All non-overlapping windows, including failures to bracket Tm. Never
    # summarize only successful windows as if they were representative.
    windows = []
    for size in [250, 500, 750]:
        estimates = [tm_of(a[start:start+size].sum(axis=0), ts)
                     for a in arrays for start in range(0, len(a)-size+1, size)]
        windows.append(dict(window_sweeps=size*cadence, total_windows=len(estimates),
                            unbracketed=sum(v is None for v in estimates), estimates_c=estimates,
                            sd_c=None if any(v is None for v in estimates) else float(np.std(estimates, ddof=1))))
    valid = [r for r in prefixes if r['halfwidth_c'] is not None]
    x = np.array([r['sweeps_per_replica']/1e6 for r in valid])
    h = np.array([r['halfwidth_c'] for r in valid])
    exponent = float(np.polyfit(np.log(x), np.log(h), 1)[0])
    recent_exponent = float(np.polyfit(np.log(x[-4:]), np.log(h[-4:]), 1)[0])
    coefficient_range = [float(min(h*h*x)), float(max(h*h*x))]
    elapsed = final['elapsed_seconds']
    ancestor = root
    while 'continuation' in (manifest := json.loads((ancestor/'manifest.json').read_text())):
        ancestor = Path(manifest['continuation']['parent'])
        elapsed += json.loads((ancestor/'result.json').read_text())['elapsed_seconds']
    events = [json.loads(line) for line in (ancestor/'events.jsonl').read_text().splitlines()]
    preparation = next(e['elapsed_seconds'] for e in events if e['event']=='equilibration_complete')
    seconds_per_million = (elapsed-preparation)/(final['production_steps_per_replica']/1e6)
    projection = dict(per_design_target_halfwidth_c=1, million_sweeps_per_replica=coefficient_range,
                      four_worker_wall_hours=[(preparation+seconds_per_million*c)/3600 for c in coefficient_range],
                      conservative_delta_target_million_sweeps_per_design_replica=[2*c for c in coefficient_range],
                      qualification='Conditional inverse-square planning range across correlated prefixes, NOT a confidence interval or validated forecast. Assumes four replicas, unchanged mixing and stationary variance. Delta planning allocates ±0.707C per design.')
    report = dict(prefixes=prefixes, batch_variances=batch_variances, chain_diagnostics=chain_diagnostics,
                  cumulative_warm_wall_minutes=elapsed/60,
                  nonoverlapping_windows=windows, descriptive_log_log_exponent=exponent,
                  recent_four_prefix_log_log_exponent=recent_exponent,
                  fit_qualification='Nested prefixes are correlated; no independent regression error bars or convergence claim.',
                  conditional_projection=projection,
                  conclusion='Current data do not establish a stable inverse-square uncertainty trend; more independent long-time evidence is needed.')
    (output/'sampling_trend.json').write_text(json.dumps(report, indent=2)+'\n')
    with (output/'prefix_variability.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(prefixes[0]))
        writer.writeheader()
        writer.writerows(prefixes)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 3, figsize=(13, 4), constrained_layout=True)
    for replica in range(4):
        ax[0].plot([r['sweeps_per_replica']/1e6 for r in prefixes],
                   [np.nan if r['tm_replicas_c'][replica] is None else r['tm_replicas_c'][replica] for r in prefixes], 'o-', label=f'Replica {replica+1}')
    ax[0].set(xlabel='Million sweeps per replica', ylabel='Cumulative Tm (°C)')
    ax[0].legend(fontsize=8)
    ax[1].plot(x, h, 'o-', label='Observed replica-based 95% half-width')
    extended = np.geomspace(x[0], coefficient_range[1], 100)
    ax[1].fill_between(extended, np.sqrt(coefficient_range[0]/extended), np.sqrt(coefficient_range[1]/extended), alpha=.15, label='Conditional 1/√sampling envelope')
    ax[1].axhline(1, color='gray', ls=':')
    ax[1].set(xscale='log', yscale='log', xlabel='Million sweeps per replica', ylabel='Half-width (°C)')
    ax[1].legend(fontsize=7)
    ax[2].plot([r['batch_sweeps']/1e6 for r in batch_variances], [r['diagnostic_normal_halfwidth_c'] for r in batch_variances], 'o-')
    ax[2].set(xscale='log', xlabel='Time-batch length (million sweeps)', ylabel='Stationarity-assuming half-width (°C)')
    ax[2].text(.03, .96, 'Long batches: only 3–7 per replica\nNot an accepted confidence interval', transform=ax[2].transAxes, va='top', fontsize=8)
    fig.suptitle('Sampling versus variability · 4 independent VMMC replicas · provisional diagnostics')
    fig.savefig(output/'sampling_trend.png', dpi=170)
    fig.savefig(output/'sampling_trend.pdf')
    plt.close(fig)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = analyse(args.campaign, args.output)
    print(json.dumps({'exponent': result['descriptive_log_log_exponent'], 'projection': result['conditional_projection'],
                      'chains': result['chain_diagnostics'], 'windows': result['nonoverlapping_windows']}, indent=2))
