"""Reproducible EM evaluator comparison; optical inputs only, no NADOC authoring.

Run with the isolated EM interpreter under just validate-safe and one BLAS thread.
"""
import argparse
import json
from pathlib import Path
import time
import numpy as np
from backend.physics.em_analysis import solve


def sphere(identity, center, diameter=20):
    return {'id': identity, 'center_nm': center, 'diameter_nm': diameter}


def run():
    import miepy  # noqa: F401 -- warm both evaluators equally before timing
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cases = [
        ('single', [sphere('a', [0, 0, 0], 5)], 25, 'parallel'),
        ('dimer-gap5', [sphere('a', [-12.5, 0, 0]), sphere('b', [12.5, 0, 0])], 33, 'parallel'),
        ('dimer-gap5-dense', [sphere('a', [-12.5, 0, 0]), sphere('b', [12.5, 0, 0])], 49, 'parallel'),
        ('four-asymmetric', [sphere('a', [0, 0, 0]), sphere('b', [25, 0, 0]),
                             sphere('c', [0, 27, 3], 25), sphere('d', [29, 28, 6], 15)], 33, 'perpendicular'),
    ]
    # User part is read only; include its exact optical snapshot when available.
    path = Path('workspace/Plasmonic_test.nadoc')
    if path.is_file():
        raw = json.loads(path.read_text())
        particles = [sphere(p['id'], [p['pose']['values'][i] for i in (3, 7, 11)], p['diameter_nm'])
                     for p in raw['nanoparticles']]
        cases.append(('Plasmonic_test', particles, 33, 'parallel'))
    measurements = []
    for name, particles, resolution, polarization in cases:
        payload = dict(particles=particles, resolution=resolution, polarization=polarization)
        start = time.perf_counter(); reference = solve(payload, reference=True); reference_time = time.perf_counter() - start
        start = time.perf_counter(); optimized = solve(payload); optimized_time = time.perf_counter() - start
        a, b = np.array(reference['intensity']), np.array(optimized['intensity'])
        np.testing.assert_allclose(a, b, rtol=1e-6, atol=1e-6)
        assert reference['outside'] == optimized['outside']
        assert reference['multipole_order'] == optimized['multipole_order']
        np.testing.assert_allclose(reference['peak_intensity'], optimized['peak_intensity'], rtol=1e-10)
        measurement = dict(name=name, resolution=resolution, particles=len(particles),
            reference_seconds=reference_time, optimized_seconds=optimized_time,
            speedup=reference_time/optimized_time, max_intensity_difference=float(np.max(np.abs(a-b))),
            multipole_order=optimized['multipole_order'], timings=optimized['timing_seconds'],
            input_sha256=optimized['source_sha256'], peak_intensity=optimized['peak_intensity'],
            peak_position_identical=reference['peak_position_nm'] == optimized['peak_position_nm'])
        measurements.append(measurement)
        print(json.dumps(measurement), flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(measurements, indent=2))


if __name__ == '__main__':
    run()
