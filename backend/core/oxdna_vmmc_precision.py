"""Correlation-aware Tm uncertainty from native VMMC cumulative histograms.

Histograms already include exact native temperature reweighting. No fitted
two-state enthalpy or temperature-independent-energy approximation is used.
Intervals describe sampling under the model, not force-field accuracy.
"""
import math
from pathlib import Path
import re

import numpy as np
from scipy.stats import t as student_t

from backend.core.oxdna_vmmc import melting_point


def histogram_blocks(path, n_pairs, temperatures):
    """Return equal-cadence increments, rejecting incomplete/corrupt histories."""
    text = Path(path).read_text()
    records = re.split(r'(?m)^#t\s*=\s*', text)[1:]
    previous = np.zeros((n_pairs+1, len(temperatures)+2))
    last_step = 0
    blocks, intervals = [], []
    for record in records:
        header, _, rows = record.partition('\n')
        step = int(header.split(';')[0])
        native_ts = np.array([float(v) for v in header.split('extr. Ts:')[1].split()])*3000-273.15
        if len(native_ts) != len(temperatures) or not np.allclose(native_ts, temperatures, atol=.002, rtol=0):
            raise ValueError('Native histogram temperatures differ from the protocol.')
        data = np.array([list(map(float, row.split())) for row in rows.splitlines() if row.strip()])
        if data.shape != (n_pairs+1, len(temperatures)+3):
            raise ValueError('Incomplete native histogram record.')
        if not np.array_equal(data[:, 0], np.arange(n_pairs+1)) or not np.isfinite(data).all() or (data < 0).any():
            raise ValueError('Invalid native histogram record.')
        current = data[:, 1:]
        if step < last_step:
            raise ValueError('Histogram step counter went backwards.')
        if step == last_step:
            previous = current
            continue
        delta = current-previous
        # Native cumulative output has six significant digits. Bound roundoff
        # explicitly; genuine decreasing cumulative counts remain an error.
        tolerance = 2e-5*np.maximum(current, previous)+1e-10
        if (delta < -tolerance).any():
            raise ValueError('Cumulative histogram decreased.')
        delta = np.maximum(delta, 0)
        blocks.append(np.stack((delta[0, 2:], delta[1:, 2:].sum(axis=0))))
        intervals.append(step-last_step)
        previous, last_step = current, step
    if not blocks or len(set(intervals)) != 1:
        raise ValueError('Need nonempty, equal-cadence histogram blocks.')
    return np.asarray(blocks), intervals[0]


def yield_curve(counts):
    """Two distinct complementary strands; bulk correction at fixed concentration."""
    unbound, bound = np.asarray(counts)
    denominator = 2*bound+unbound+np.sqrt(unbound*unbound+4*unbound*bound)
    return np.divide(2*bound, denominator, out=np.full_like(bound, np.nan), where=denominator > 0)


def tm_of(counts, temperatures):
    return melting_point(temperatures, yield_curve(counts))


def inefficiency(values):
    values = np.asarray(values, dtype=float)
    values = values-values.mean()
    if len(values) < 4 or np.dot(values, values) == 0:
        return float(len(values))  # A constant series cannot certify mixing.
    size = 1 << (2*len(values)-1).bit_length()
    transformed = np.fft.rfft(values, size)
    ac = np.fft.irfft(transformed*transformed.conjugate(), size)[:len(values)]
    ac /= ac[0]
    total = 0.
    for i in range(1, len(ac)-1, 2):
        pair = ac[i]+ac[i+1]
        if pair <= 0:
            break
        total += pair
    return max(1., 1+2*total)


def _batch_bootstrap(arrays, length, temperatures, repeats, seed):
    """Resample nonoverlapping time batches within each independent replica."""
    rng = np.random.default_rng(seed)
    batches = [a[:len(a)//length*length].reshape(-1, length, 2, a.shape[-1]).sum(axis=1) for a in arrays]
    if min(map(len, batches)) < 4:
        return None
    draws, individual = [], [[] for _ in arrays]
    group_difference = []
    for _ in range(repeats):
        counts = [b[rng.integers(0, len(b), len(b))].sum(axis=0) for b in batches]
        draws.append(tm_of(np.sum(counts, axis=0), temperatures))
        for i, c in enumerate(counts):
            individual[i].append(tm_of(c, temperatures))
        if len(counts) == 4:
            bound = tm_of(counts[0]+counts[2], temperatures)
            unbound = tm_of(counts[1]+counts[3], temperatures)
            group_difference.append(None if bound is None or unbound is None else bound-unbound)
    if any(x is None for x in draws) or any(x is None for row in individual for x in row):
        return None  # Never discard unbracketed resamples and narrow the interval.
    return dict(ci=np.quantile(draws, [.025, .975]).tolist(),
                replicas=[np.quantile(row, [.025, .975]).tolist() for row in individual],
                start_difference_ci=None if not group_difference or any(x is None for x in group_difference)
                else np.quantile(group_difference, [.025, .975]).tolist(),
                batches_per_replica=list(map(len, batches)))


def precision_report(arrays, temperatures, *, target=.7, seed=191171, bootstrap=1000, max_looks=16):
    """Conservative envelope of time-block bootstrap and between-replica Student t.

    Prespecified max_looks supplies Bonferroni correction for precision stopping.
    Ordinary 95% intervals are reported separately from the stopping interval.
    """
    arrays = [np.asarray(a, dtype=float) for a in arrays]
    if len(arrays) < 3 or any(a.ndim != 3 or a.shape[1:] != (2, len(temperatures)) or
                              not np.isfinite(a).all() or (a < 0).any() for a in arrays):
        raise ValueError('Need at least three valid independent histogram-block series.')
    if len(set(map(len, arrays))) != 1:
        raise ValueError('Replica sampling budgets must be equal.')
    totals = [a.sum(axis=0) for a in arrays]
    point = tm_of(np.sum(totals, axis=0), temperatures)
    replica_tm = [tm_of(a, temperatures) for a in totals]
    base = dict(tm_c=point, ci95_c=None, stopping_ci_c=None, halfwidth_c=None,
                replica_tm_c=replica_tm, target_halfwidth_c=target,
                nominal_target_met=False, early_stop_target_met=False,
                status='inconclusive', reasons=[], temperatures_c=list(temperatures),
                duplex_yield=yield_curve(np.sum(totals, axis=0)).tolist(),
                qualification='Sampling uncertainty only; no CPD/force-field uncertainty included.')
    if point is None or any(t is None for t in replica_tm):
        base['reasons'].append('Melting is not bracketed in every replica.')
        return base
    sem = float(np.std(replica_tm, ddof=1)/math.sqrt(len(arrays)))
    mean_tm = float(np.mean(replica_tm))
    half = float(student_t.ppf(.975, len(arrays)-1))*sem
    base.update(between_replica_ci95_c=[mean_tm-half, mean_tm+half], replica_tm_sem_c=sem)
    index = int(np.argmin(np.abs(np.asarray(temperatures)-point)))
    gs = []
    for a in arrays:
        u, b = a[:, 0, index], a[:, 1, index]
        gs.append(inefficiency(b/b.mean()-u/u.mean()) if u.mean() > 0 and b.mean() > 0 else float(len(a)))
    length = max(10, int(math.ceil(5*max(gs))))
    base.update(inefficiencies=gs, batch_length_histograms=length,
                effective_histogram_blocks=[len(a)/g for a, g in zip(arrays, gs)])
    # Check both an autocorrelation-based batch length and twice that length.
    checks = [_batch_bootstrap(arrays, multiplier*length, temperatures, bootstrap, seed+multiplier)
              for multiplier in (1, 2)]
    base['batch_checks'] = checks
    if any(c is None for c in checks):
        base['reasons'].append('Too few long time batches, or bootstrap curves do not bracket melting.')
        return base
    if min(checks[1]['batches_per_replica']) < 10:
        base['reasons'].append('Fewer than ten doubled-length time batches in a replica.')
    ci = [min(mean_tm-half, *(c['ci'][0] for c in checks)),
          max(mean_tm+half, *(c['ci'][1] for c in checks))]
    base.update(ci95_c=ci, halfwidth_c=max(point-ci[0], ci[1]-point), replica_tm_sem_c=sem)
    # Normal approximation to the bootstrap width, conservative t tail and
    # between-replica scatter for checkpoint-wise precision stopping.
    effective_sem = max(sem, *(max(point-c['ci'][0], c['ci'][1]-point)/1.96 for c in checks))
    stop_half = float(student_t.ppf(1-.05/(2*max_looks), len(arrays)-1))*effective_sem
    base['stopping_ci_c'] = [min(point, mean_tm)-stop_half, max(point, mean_tm)+stop_half]
    base['max_prespecified_looks'] = max_looks
    difference_ci = checks[1]['start_difference_ci']
    if difference_ci is not None and not difference_ci[0] <= 0 <= difference_ci[1]:
        base['reasons'].append('Bound-start and unbound-start estimates disagree.')
    # A late-time shift must not exceed the full run's statistical interval width.
    half_count = len(arrays[0])//2
    early = tm_of(sum(a[:half_count].sum(axis=0) for a in arrays), temperatures)
    late = tm_of(sum(a[half_count:].sum(axis=0) for a in arrays), temperatures)
    base.update(early_tm_c=early, late_tm_c=late)
    if early is None or late is None or abs(early-late) > ci[1]-ci[0]:
        base['reasons'].append('First-half and second-half melting estimates have unresolved drift.')
    if not base['reasons']:
        base['nominal_target_met'] = base['halfwidth_c'] <= target
        base['early_stop_target_met'] = max(point-base['stopping_ci_c'][0], base['stopping_ci_c'][1]-point) <= target
        base['status'] = 'target_met' if base['early_stop_target_met'] else 'continue_sampling'
    return base


def campaign_report(paths, temperatures, n_pairs, **options):
    arrays, transitions = [], []
    cadence = None
    for replica in paths:
        blocks, states = [], []
        for directory in replica:
            data, interval = histogram_blocks(Path(directory)/'traj_hist.dat', n_pairs, temperatures)
            if cadence is not None and interval != cadence:
                raise ValueError('Histogram output intervals differ between production blocks.')
            cadence = interval
            blocks.append(data)
            energy = np.loadtxt(Path(directory)/'energy.dat', ndmin=2)
            if energy.shape[1] != 7 or not np.isfinite(energy).all():
                raise ValueError('Invalid VMMC energy series.')
            states.extend((energy[energy[:, 0] > 0, -2] > 0).tolist())
        arrays.append(np.concatenate(blocks))
        transitions.append(int(np.count_nonzero(np.diff(states))))
    result = precision_report(arrays, temperatures, **options)
    result.update(histogram_interval_steps=cadence, recorded_transitions=transitions)
    if min(transitions) < 20:
        result['reasons'].append('Fewer than twenty recorded binding/unbinding transitions in a replica.')
        result['status'] = 'inconclusive'
        result['nominal_target_met'] = result['early_stop_target_met'] = False
    return result
