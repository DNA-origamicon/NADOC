"""Compact static, exportable benchmark comparisons; never label pilots converged."""
import argparse
import csv
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator
import numpy as np


def report(root):
    root = Path(root)
    cases = json.loads((root/'benchmark.json').read_text())
    rows = []
    for case in cases:
        macro = sum(r['unbound_to_six_pairs_or_back_passages'] for r in case['replicas'])
        rows.append({'method': case['case'], 'wall_minutes': case['wall_seconds']/60,
                     'p_bound_bound_start': case['p_bound_by_initial_state']['bound'],
                     'p_bound_unbound_start': case['p_bound_by_initial_state']['unbound'],
                     'initial_state_gap': case['initial_state_probability_gap'],
                     'q0_crossings': case['recorded_crossings'], 'q0_q6_passages': macro,
                     'mean_correlated_weight_ess': np.mean([r['approximate_correlated_weight_ess'] for r in case['replicas']]),
                     'tm_precision_certified': False})
    with (root/'comparison.csv').open('w') as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    names = {'unbiased': 'No bias', 'com': 'Distance only',
             'hb_cutoff': 'Pairing only', 'mixed': 'Pairing + distance'}
    labels = [names.get(r['method'], r['method'].replace('_', ' ')) for r in rows]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.5), constrained_layout=True)
    positions = np.arange(len(rows))
    axes[0].bar(positions, [r['wall_minutes'] for r in rows], color='#356b9a')
    axes[0].set_ylabel('End-to-end elapsed time (minutes)')
    axes[0].set_title('Training + equilibration + production')
    axes[1].bar(positions-.18, [r['p_bound_bound_start'] for r in rows], .36, label='Bound starts', color='#356b9a')
    axes[1].bar(positions+.18, [r['p_bound_unbound_start'] for r in rows], .36, label='Separated starts', color='#d7863d')
    axes[1].set_ylim(0, 1.05)
    axes[1].set_ylabel('Reweighted single-box bound probability')
    axes[1].set_title('Agreement is necessary, not sufficient')
    axes[1].legend(fontsize=8)
    axes[2].bar(positions, [r['q0_q6_passages'] for r in rows], color='#4a8d68')
    axes[2].set_ylabel('Recorded passages, q=0 ↔ q≥6')
    axes[2].set_title('Fixed-bias production only')
    axes[2].yaxis.set_major_locator(MaxNLocator(integer=True))
    for axis in axes:
        axis.set_xticks(positions, labels, rotation=20)
        axis.spines[['top', 'right']].set_visible(False)
    fig.suptitle('8-bp DNA2 hybrid benchmark — provisional sampling diagnostics', fontsize=13)
    fig.savefig(root/'comparison.png', dpi=160)
    fig.savefig(root/'comparison.pdf')
    plt.close(fig)
    fig, axes = plt.subplots(len(cases), 2, figsize=(11, 2.1*len(cases)), squeeze=False,
                             constrained_layout=True, sharey=True)
    for row, case in enumerate(cases):
        directory = root/case['case']
        protocol = json.loads((directory/'manifest.json').read_text())['protocol']
        for col, initial in enumerate(('Bound', 'Separated')):
            axis = axes[row, col]
            for i in range(col, protocol['walkers'], 2):
                data = np.loadtxt(directory/'production'/f'replica_{i}'/'samples.dat')
                data = data[data[:, 0] >= protocol['equil_steps']]
                axis.plot((data[:, 0]-protocol['equil_steps'])/1e6, data[:, 2], lw=.6,
                          alpha=.75, label=f'Replica {i+1}')
            axis.set_title(f"{case['case']} — {initial.lower()} starts", fontsize=10)
            axis.set_ylim(-.3, 8.3)
            axis.set_ylabel('Native base pairs')
            axis.legend(fontsize=7, loc='lower right')
            axis.spines[['top', 'right']].set_visible(False)
    for axis in axes[-1]:
        axis.set_xlabel('Production MD steps (millions)')
    fig.savefig(root/'pairing_traces.png', dpi=160)
    fig.savefig(root/'pairing_traces.pdf')
    plt.close(fig)
    print(json.dumps(rows, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root')
    report(parser.parse_args().root)
