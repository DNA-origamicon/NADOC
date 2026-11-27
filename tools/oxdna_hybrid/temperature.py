"""Exact DNA2 energy reevaluation of frozen-bias frames at target temperatures.

No constant-Hamiltonian temperature approximation: DNAnalysis reevaluates the
temperature-dependent interactions. Outputs are provisional until overlap and
independent-campaign convergence have been demonstrated.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import time

import numpy as np
from scipy.special import logsumexp
from scipy.stats import t

from tools.oxdna_hybrid.bias import BiasSpec, evaluate
from tools.oxdna_umbrella.analysis import bulk_yield
from tools.oxdna_umbrella.native import digest


def crossing(temperatures, fractions):
    temperatures, fractions = np.asarray(temperatures), np.asarray(fractions)
    if len(temperatures) < 2 or not np.isfinite(fractions).all():
        return None
    # Do not silently choose one of multiple crossings or extrapolate.
    ids = np.flatnonzero((fractions[:-1] >= .5) & (fractions[1:] < .5))
    if len(ids) != 1 or np.any(np.diff(fractions) > .02):
        return None
    i = ids[0]
    return float(temperatures[i]+(.5-fractions[i])*(temperatures[i+1]-temperatures[i])/(fractions[i+1]-fractions[i]))


def reweight(energies, cvs, bound, temperatures, source_temperature, spec, bias, sample_bias=None):
    temperatures = np.asarray(temperatures, dtype=float)
    source = np.flatnonzero(np.isclose(temperatures, source_temperature))
    if len(source) != 1 or energies.shape != (len(temperatures), len(cvs)):
        raise ValueError('Need source temperature and aligned energy matrix')
    kt = (temperatures+273.15)/3000
    kt0 = (source_temperature+273.15)/3000
    if sample_bias is None:
        sample_bias = evaluate(spec, bias, cvs)
    logits = (-energies/kt[:, None]+energies[source[0]]/kt0 + sample_bias/kt0)
    weights = np.exp(logits-logsumexp(logits, axis=1)[:, None])
    probabilities = weights @ bound
    return np.array([bulk_yield(p) for p in probabilities]), 1/np.sum(weights**2, axis=1)


def analyze(directory, binary, temperatures):
    directory, binary = Path(directory).resolve(), Path(binary).resolve(strict=True)
    manifest = json.loads((directory/'manifest.json').read_text())
    execution = json.loads((directory/'execution.json').read_text())
    library_candidates = [binary.parent.parent/'src/liboxdna_common.so', binary.parent.parent/'lib/liboxdna_common.so']
    if not any(p.exists() and digest(p) == manifest['library_sha256'] for p in library_candidates):
        raise ValueError('Analysis engine does not match sampling library')
    if digest(directory/'frozen_bias.npy') != execution['frozen_bias_sha256']:
        raise ValueError('Frozen bias changed')
    for name, expected in execution.get('output_sha256', {}).items():
        if digest(directory/name) != expected:
            raise ValueError(f'Native output changed since completion: {name}')
    protocol = manifest['protocol']
    temperatures = sorted(set([float(v) for v in temperatures]+[protocol['temperature']]))
    spec, bias = BiasSpec(**manifest['bias_spec']), np.load(directory/'frozen_bias.npy')
    reports = []
    started = time.monotonic()
    for i in range(protocol['walkers']):
        replica = directory/'production'/f'replica_{i}'
        tables = []
        for temperature in temperatures:
            tag = f'temperature_{temperature:g}'
            input_path = replica/(tag+'.input')
            if input_path.exists():
                raise ValueError('Temperature analysis already exists; refusing to overwrite')
            text = (replica/'input.txt').read_text()
            text = re.sub(r'^T = .*$', f'T = {temperature}C', text, flags=re.M)
            text = text.replace('data_output_1 =', 'analysis_data_output_1 =')
            text = text.replace('name = samples.dat', f'name = {tag}.dat')
            text = text.replace('external_forces = true', 'external_forces = false')
            input_path.write_text(text)
            with (replica/(tag+'.log')).open('w') as log:
                subprocess.run([str(binary), input_path.name], cwd=replica, stdout=log,
                               stderr=subprocess.STDOUT, check=True, timeout=120)
            data = np.loadtxt(replica/(tag+'.dat'), ndmin=2)
            data = data[(data[:, 0] >= protocol['equil_steps']) &
                        (data[:, 0] < protocol['equil_steps']+protocol['production_steps'])]
            # Checkpoints and periodic trajectory output may share a step.
            _, unique = np.unique(data[:, 0], return_index=True)
            data = data[np.sort(unique)]
            if not np.isfinite(data).all() or not len(data):
                raise ValueError('Nonfinite or empty analysis')
            if tables and not np.array_equal(data[:, :3], tables[0][:, :3]):
                raise ValueError('Temperature frames or pairing coordinates do not align')
            tables.append(data)
        n = int((directory/'inputs/topology.top').read_text().split()[0])
        energies = np.array([data[:, 4]*n for data in tables])
        recorded = np.loadtxt(replica/'samples.dat', ndmin=2)
        indices = np.searchsorted(recorded[:, 0], tables[0][:, 0])
        if np.any(indices >= len(recorded)) or not np.array_equal(recorded[indices, 0], tables[0][:, 0]):
            raise ValueError('Trajectory frames lack matching native energy samples')
        sample_bias = recorded[indices, 3]/(2 if spec.coordinate == 'com' else 1)
        curve, ess = reweight(energies, tables[0][:, 1], tables[0][:, 2] > 0,
                              temperatures, protocol['temperature'], spec, bias, sample_bias)
        reports.append({'replica': i, 'start': 'bound' if i % 2 == 0 else 'unbound',
                        'tm_c_provisional': crossing(temperatures, curve),
                        'bulk_bound_fraction': curve.tolist(), 'weight_ess': ess.tolist(),
                        'frames': len(tables[0])})
    tms = [r['tm_c_provisional'] for r in reports]
    interval = None
    if all(v is not None for v in tms):
        half = t.ppf(.975, len(tms)-1)*np.std(tms, ddof=1)/np.sqrt(len(tms))
        interval = [float(np.mean(tms)-half), float(np.mean(tms)+half)]
    result = {'temperatures_c': temperatures, 'replicas': reports,
              'between_replica_ci95_provisional': interval, 'analysis_seconds': time.monotonic()-started,
              'tm_precision_certified': False,
              'qualification': 'Exact temperature-dependent energies; shared learned bias. Replica spread is descriptive, not a validated total uncertainty or repeated-look stopping criterion.'}
    (directory/'temperature_analysis.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory')
    p.add_argument('--binary', required=True)
    p.add_argument('--temperatures', nargs='+', type=float, default=list(range(60, 81, 2)))
    args = p.parse_args()
    analyze(args.directory, args.binary, args.temperatures)
