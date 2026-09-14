"""Render the measured scheduling comparison and scoped scientific verdicts."""
import argparse
import re
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from experiments.peg_chudoba.benchmark_scheduling import DEFAULT, HERE, read, write


def render(out):
    lines = ['# PEG scheduling and 294 K validation', '',
             f'Timing plan: [NARROW_VALIDATION.md]({HERE / "NARROW_VALIDATION.md"}); production criteria: [BOUNDED_VALIDATION.md]({HERE / "BOUNDED_VALIDATION.md"}).', '',
             'Benchmarks compare independent simulations on the existing workstation; unrelated processes remain running.',
             'Short timing trajectories are excluded from validation. ESS rates below are provisional.', '']
    benchmark = out/'benchmarks.json'
    if benchmark.exists():
        rows = read(benchmark)['batches']
        lines += ['| Workload | Round | Concurrent engines | Batch seconds | Aggregate steps/s | Provisional ESS/s |',
                  '|---|---:|---:|---:|---:|---:|']
        native = []
        for r in rows:
            lines.append(f'| {r["workload"]} | {r["round"]+1} | {r["concurrency"]} | {r["makespan_seconds"]:.2f} | '
                         f'{r["aggregate_steps_per_second"]:.2f} | {r["provisional_aggregate_ess_per_second"]:.4f} |')
            for run in r['runs']:
                log = (Path(run['directory'])/'engine.log').read_text()
                match = re.search(r'> SimBackend\s+(\d+(?:\.\d+)?)',log)
                native.append(dict(directory=run['directory'],native_cpu_timer_seconds=float(match[1]) if match else None,
                                   wrapper_wall_seconds=run['wall_seconds'],engine_wall_seconds=run['engine_seconds']))
        write(out/'native_timings.json',dict(runs=native,note='Native clock() is process CPU time, not GPU execution time.'))
        fig,axes = plt.subplots(1,2,figsize=(10,4))
        baseline = {(r['workload'],r['round']):r['makespan_seconds'] for r in rows if r['concurrency']==1}
        for name in sorted({r['workload'] for r in rows}):
            counts,medians,lows,highs = [],[],[],[]
            for count in sorted({r['concurrency'] for r in rows if r['workload']==name}):
                speedups = [baseline[name,r['round']]/r['makespan_seconds'] for r in rows
                            if r['workload']==name and r['concurrency']==count and (name,r['round']) in baseline]
                if not speedups:
                    continue
                counts.append(count);medians.append(np.median(speedups));lows.append(min(speedups));highs.append(max(speedups))
            ax = axes[1 if name.startswith('gpu') else 0]
            if counts:
                ax.errorbar(counts,medians,yerr=[np.array(medians)-lows,np.array(highs)-medians],
                            marker='o',capsize=3,label=name)
        for ax,title in zip(axes,('CPU independent simulations','GPU independent simulations')):
            ax.axhline(1,color='gray',linestyle='--',linewidth=1)
            ax.set(title=title,xlabel='Concurrent simulations',ylabel='Aggregate throughput / serial throughput')
            ax.set_xticks([1,2,4] if ax is axes[0] else [1,2])
            ax.set_ylim(bottom=0)
            ax.legend(fontsize=8)
        fig.suptitle('Matched workloads; points = median, bars = range across available timing rounds',fontsize=10)
        fig.tight_layout()
        fig.savefig(out/'scheduling_comparison.png',dpi=160)
        fig.savefig(out/'scheduling_comparison.svg')
        plt.close(fig)
        lines += ['', '![Matched scheduling comparison](scheduling_comparison.png)', '']
    selection_path = out/('active_selection.json' if (out/'active_selection.json').exists() else 'selection.json')
    if selection_path.exists():
        lines += ['', '## Selected execution strategies', '']
        for family,row in read(selection_path)['selected'].items():
            slots = row['concurrency']
            if 'cpu12_evidence' in row:
                evidence = read(Path(row['cpu12_evidence']))
                lines.append(f'- {family}: {slots} concurrent simulations; 12-worker benchmark throughput / four workers = '
                             f"{evidence['geometric_mean_speedup']:.2f}x (ideal 3x).")
                continue
            speedup = row['scores'][str(slots)]['geometric_mean_speedup']
            lines.append(f'- {family}: {slots} concurrent simulations; matched geometric-mean throughput speedup {speedup:.2f}x.')
        lines += ['', 'Selection favors less concurrency within 5% of the best measured stable speedup. '
                  'This is a choice among tested strategies, not a claim of a global hardware optimum.']
    if (out/'cpu12'/'REPORT.md').exists():
        lines += ['', 'Twelve-worker extension: [matched results and adoption](cpu12/REPORT.md).']
    if (out/'validation.json').exists():
        report = read(out/'validation.json')
        lines += ['', '## Scientific validation', '', f'**{report["status"]}**', '',
                  'Final journal main text and original simulation tables remain unverified. '
                  'The comparison tests the documented preprint/SI reconstruction.', '',
                  '| Chain length | RMS Rg (nm) | SEM (nm) | Marker deviation | Verdict |',
                  '|---:|---:|---:|---:|---|']
        for r in report['chains']:
            lines.append(f'| {r["n"]} | {r["rms_rg_nm"]:.5f} | {r["sem_nm"]:.5f} | '
                         f'{100*r["relative_difference"]:+.2f}% | {"pass" if r["passed"] else "unresolved"} |')
        lines += ['', '| Pressure (kPa) | Concentration (g/L) | SEM (g/L) | Marker deviation | Verdict |',
                  '|---:|---:|---:|---:|---|']
        for pressure,r in sorted(report['eos'].items(),key=lambda x:float(x[0])):
            lines.append(f'| {pressure} | {r["concentration_g_per_l"]:.5f} | {r["conservative_sem_g_per_l"]:.5f} | '
                         f'{100*r["relative_difference"]:+.2f}% | {"pass" if r["passed"] else "unresolved"} |')
        lines += ['', '| GPU state | RMS Rg (nm) | SEM (nm) | Minimum ESS | Verdict |',
                  '|---|---:|---:|---:|---|']
        for state,r in report['gpu'].items():
            lines.append(f'| {state} | {r["rms_rg_nm"]:.5f} | {r["conservative_sem_nm"]:.5f} | '
                         f'{r["minimum_seed_effective_samples"]:.1f} | {"pass" if r["passed"] else "unresolved"} |')
        if 'implementation' in report:
            lines += ['', 'Implementation provenance and N795 endpoint energies: '+
                      ('pass' if report['implementation']['passed'] else 'unresolved')+'.']
        for n,r in report.get('timestep_equivalence',{}).items():
            lines.append(f"Timestep equivalence N{n}: {'pass' if r['passed'] else 'unresolved'}.")
        lines += ['', 'Unlisted required states remain incomplete. A completed allocation is not evidence of convergence.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,default=DEFAULT)
    render(ap.parse_args().output.resolve())
