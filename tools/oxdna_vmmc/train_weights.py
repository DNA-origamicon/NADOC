"""Learn flat pair-count umbrella weights from a completed prior histogram.

These are sampling biases, not interaction parameters. Analysis removes them;
the prior histogram's melting result is not imposed on new production data.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from tools.oxdna_umbrella.native import digest


def flat_weights(previous_weights, biased_counts):
    weights, counts = map(lambda a: np.asarray(a, dtype=float), (previous_weights, biased_counts))
    if weights.shape != counts.shape or weights.ndim != 1 or not np.isfinite(weights).all() or not np.isfinite(counts).all() or (weights <= 0).any() or (counts <= 0).any():
        raise ValueError('All pair-count states must have positive weights and observed counts.')
    result = weights/counts
    return result/result.max()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--histogram', type=Path, required=True)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    histogram = np.loadtxt(args.histogram, ndmin=2)
    weights = np.loadtxt(args.weights, ndmin=2)
    if weights.shape[1] != 2 or histogram.shape[1] < 3 or not np.array_equal(weights[:, 0], histogram[:, 0]) or not np.array_equal(weights[:, 0], np.arange(len(weights))):
        raise ValueError('Pair-count rows in the histogram and weights must match.')
    updated = flat_weights(weights[:, 1], histogram[:, 1])
    with args.output.open('x') as stream:
        np.savetxt(stream, np.column_stack((weights[:, 0], updated)), fmt=['%d', '%.16g'])
    manifest = dict(method='w_new(q) proportional to w_old(q)/biased_count(q)',
                    histogram=dict(path=str(args.histogram.resolve()), sha256=digest(args.histogram)),
                    previous_weights=dict(path=str(args.weights.resolve()), sha256=digest(args.weights)),
                    output_sha256=digest(args.output),
                    qualification='Prior training is reused. Future production must be independent and remove this bias; finite sampling error in these weights affects efficiency, not the target ensemble.')
    with args.output.with_suffix('.json').open('x') as stream:
        stream.write(json.dumps(manifest, indent=2)+'\n')


if __name__ == '__main__':
    main()
