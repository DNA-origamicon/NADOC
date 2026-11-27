"""Replay saved hills and quantify late changes in the learned bias shape."""
import argparse
import json
from pathlib import Path

import numpy as np

from tools.oxdna_hybrid.bias import BiasSpec, deposit


def analyze(directory):
    root = Path(directory)
    manifest = json.loads((root/'manifest.json').read_text())
    spec = BiasSpec(**manifest['bias_spec'])
    hills = [json.loads(line) for line in (root/'hills.jsonl').read_text().splitlines()]
    kt = (manifest['protocol']['temperature']+273.15)/3000
    table = np.zeros_like(spec.grid)
    snapshots = {}
    milestones = {max(1, round(len(hills)*fraction)) for fraction in (.25, .5, .75, 1.)}
    for index, record in enumerate(hills):
        if record['epoch'] != index:
            raise ValueError('Training history is not complete and ordered')
        table = deposit(spec, table, [value['cv'] for value in record['endpoints']], kt)
        if index+1 in milestones:
            snapshots[index+1] = table.copy()
    frozen = np.load(root/'frozen_bias.npy')
    error = float(np.max(np.abs(table-frozen)))
    if error > 1e-12:
        raise ValueError('Saved hill history does not reproduce frozen production bias')
    earlier = snapshots[max(1, round(len(hills)*.75))]
    difference = (table-earlier)/kt
    difference -= difference.mean()  # irrelevant additive energy offset
    result = {'epochs': len(hills), 'frozen_bias_replay_max_error': error,
              'last_quarter_shape_rms_change_kbt': float(np.sqrt(np.mean(difference**2))),
              'last_quarter_shape_max_change_kbt': float(np.max(np.abs(difference))),
              'final_bias_range_kbt': float(np.ptp(table)/kt),
              'qualification': 'Descriptive training drift, not a convergence or stopping test.'}
    (root/'training_analysis.json').write_text(json.dumps(result, indent=2)+'\n')
    np.savez(root/'training_bias_snapshots.npz', grid=spec.grid, **{f'epoch_{k}': v for k, v in snapshots.items()})
    print(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('directory')
    analyze(p.parse_args().directory)
