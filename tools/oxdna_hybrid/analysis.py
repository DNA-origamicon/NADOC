"""Conservative fixed-bias diagnostics; no precision claim from trapped trajectories."""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.special import logsumexp

from tools.oxdna_hybrid.bias import BiasSpec, evaluate
from tools.oxdna_umbrella.analysis import bulk_yield, statistical_inefficiency
from tools.oxdna_umbrella.native import digest


def probability(data, spec, bias, thermal_energy):
    # Native distances print to only four decimals. Use recorded bias energies
    # for weights, after diagnose() independently checks their consistency.
    logw = data[:, 3]/(2 if spec.coordinate == 'com' else 1)/thermal_energy
    w = np.exp(logw-logsumexp(logw))
    return float(np.clip(w @ (data[:, 2] > 0), 0, 1)), w


def diagnose(data, spec, bias, thermal_energy, bootstrap=200, seed=819):
    if len(data) < 20 or not np.isfinite(data).all():
        raise ValueError('Insufficient or nonfinite production samples')
    p, weights = probability(data, spec, bias, thermal_energy)
    expected_bias = evaluate(spec, bias, data[:, 1])
    # Native COM mode 1 and mode 2 each report the whole pair potential.
    measured_bias = data[:, 3]/(2 if spec.coordinate == 'com' else 1)
    error = float(np.max(np.abs(expected_bias-measured_bias)))
    coordinate_roundoff = 5e-5 if spec.coordinate == 'com' else 5e-7
    rounding_bound = float(np.max(np.abs(np.diff(bias)))/spec.spacing*coordinate_roundoff + 1e-6)
    if error > rounding_bound:
        raise ValueError(f'Native/reweighted bias mismatch: {error}')
    bound = data[:, 2] > 0
    transitions = int(np.count_nonzero(bound[1:] != bound[:-1]))
    macro = np.where(data[:, 2] == 0, 0, np.where(data[:, 2] >= 6, 1, -1))
    macro = macro[macro >= 0]
    passages = int(np.count_nonzero(macro[1:] != macro[:-1]))
    # Importance-weighted influence is relevant to the bound probability.
    influence = weights*len(weights)*(bound-p)
    g = max(statistical_inefficiency(influence), statistical_inefficiency(data[:, 1]),
            statistical_inefficiency(bound))
    block = max(1, int(np.ceil(5*g)))
    nblocks = len(data)//block
    reasons = []
    if transitions < 20:
        reasons.append('Fewer than 20 recorded binding/unbinding crossings')
    if nblocks < 10:
        reasons.append('Fewer than 10 correlation-length blocks')
    kish = float(1/np.sum(weights**2))
    if kish/g < 50:
        reasons.append('Low importance-weighted effective sample size')
    interval = None
    # A stationary, trapped series must never acquire a zero-width confidence interval.
    if not reasons:
        rng = np.random.default_rng(seed)
        estimates = []
        for _ in range(bootstrap):
            starts = rng.integers(0, len(data), size=int(np.ceil(len(data)/block)))
            ids = np.concatenate([(np.arange(block)+s) % len(data) for s in starts])[:len(data)]
            estimates.append(probability(data[ids], spec, bias, thermal_energy)[0])
        interval = np.quantile(estimates, [.025, .975]).tolist()
    first = probability(data[:len(data)//2], spec, bias, thermal_energy)[0]
    second = probability(data[len(data)//2:], spec, bias, thermal_energy)[0]
    return {'p_bound_box': p, 'bulk_bound_fraction': float(bulk_yield(p)),
            'conditional_ci95': interval, 'q_range': [int(data[:, 2].min()), int(data[:, 2].max())],
            'cv_range': [float(data[:, 1].min()), float(data[:, 1].max())],
            'recorded_crossings': transitions, 'statistical_inefficiency': g,
            'unbound_to_six_pairs_or_back_passages': passages,
            'weight_ess': kish, 'approximate_correlated_weight_ess': kish/g,
            'block_samples': block, 'blocks': nblocks,
            'half_run_probabilities': [first, second], 'bias_energy_max_error': error,
            'bias_energy_rounding_bound': rounding_bound,
            'reasons_precision_not_certified': reasons}


def analyze(directory):
    directory = Path(directory)
    manifest = json.loads((directory/'manifest.json').read_text())
    execution = json.loads((directory/'execution.json').read_text())
    if execution['status'] != 'completed' or digest(directory/'frozen_bias.npy') != execution['frozen_bias_sha256']:
        raise ValueError('Incomplete campaign or altered production bias')
    for name, expected in execution.get('output_sha256', {}).items():
        if digest(directory/name) != expected:
            raise ValueError(f'Native output changed since completion: {name}')
    spec = BiasSpec(**manifest['bias_spec'])
    bias = np.load(directory/'frozen_bias.npy')
    protocol = manifest['protocol']
    kt = (protocol['temperature']+273.15)/3000
    datasets, reports = [], []
    for i in range(protocol['walkers']):
        data = np.loadtxt(directory/'production'/f'replica_{i}'/'samples.dat', ndmin=2)
        # Native outputs at the beginning of a step; omit equilibration and final duplicate boundaries.
        data = data[(data[:, 0] >= protocol['equil_steps']) &
                    (data[:, 0] < protocol['equil_steps']+protocol['production_steps'])]
        if len(data) != protocol['production_steps']//protocol['cadence']:
            raise ValueError('Unexpected production cadence/count')
        report = diagnose(data, spec, bias, kt, seed=819+i)
        report.update(replica=i, start='bound' if i % 2 == 0 else 'unbound')
        reports.append(report)
        datasets.append(data)
    bound_start_p = probability(np.concatenate(datasets[::2]), spec, bias, kt)[0]
    unbound_start_p = probability(np.concatenate(datasets[1::2]), spec, bias, kt)[0]
    result = {'coordinate': spec.coordinate, 'temperature_c': protocol['temperature'],
              'analysis_source_sha256': digest(Path(__file__)),
              'wall_seconds': execution['wall_seconds'], 'replicas': reports,
              'p_bound_by_initial_state': {'bound': bound_start_p, 'unbound': unbound_start_p},
              'initial_state_probability_gap': abs(bound_start_p-unbound_start_p),
              'pooled_p_bound_box_provisional': probability(np.concatenate(datasets), spec, bias, kt)[0],
              'recorded_crossings': sum(r['recorded_crossings'] for r in reports),
              'tm_precision_certified': False,
              'qualification': 'Single-temperature diagnostics. No Tm precision certification; shared training bias is conditioned on, not independent campaign replication.'}
    (directory/'analysis.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory')
    analyze(parser.parse_args().directory)
