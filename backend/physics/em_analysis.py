"""Read-only, full-wave gold sphere analysis. Executed in the isolated EM environment.

Coordinates and wavelength use nm throughout. MiePy uses exp(-i omega t), hence
passive gold has positive Im(epsilon). No molecular structure is authored here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

import numpy as np

GOLD_TABLE = Path(__file__).resolve().parents[1] / 'data/photophysics/gold_johnson_christy.yml'


def gold_permittivity(wavelength_nm=520.0):
    rows = []
    for line in GOLD_TABLE.read_text().splitlines():
        fields = line.split()
        if len(fields) == 3:
            try:
                rows.append([float(value) for value in fields])
            except ValueError:
                pass
    table = np.array(rows)
    wavelength_um = wavelength_nm / 1000
    if not table[0, 0] <= wavelength_um <= table[-1, 0]:
        raise ValueError('Wavelength is outside the gold optical-constant table.')
    n = np.interp(wavelength_um, table[:, 0], table[:, 1])
    k = np.interp(wavelength_um, table[:, 0], table[:, 2])
    return complex(n, k) ** 2


def analysis_geometry(particles):
    centers = np.array([p['center_nm'] for p in particles], dtype=float)
    radii = np.array([p['diameter_nm'] / 2 for p in particles], dtype=float)
    if not (1 <= len(particles) <= 4) or centers.shape != (len(particles), 3):
        raise ValueError('Select a scene containing one to four gold spheres.')
    if not np.all(np.isfinite(centers)) or not np.all(np.isfinite(radii)) or np.any((radii < 2.5) | (radii > 50)):
        raise ValueError('Finite coordinates and gold diameters from 5 to 100 nm are required.')
    gaps = [float(np.linalg.norm(centers[j] - centers[i]) - radii[i] - radii[j])
            for i in range(len(centers)) for j in range(i + 1, len(centers))]
    if gaps and min(gaps) < 2:
        raise ValueError('Experimental EM analysis requires metal surface gaps of at least 2 nm; contact and quantum-gap models are not implemented.')
    origin = centers.mean(axis=0)
    axis = centers[1] - centers[0] if len(centers) > 1 else np.array([1., 0., 0.])
    axis /= np.linalg.norm(axis)
    helper = np.eye(3)[np.argmin(np.abs(axis))]
    transverse = np.cross(helper, axis)
    transverse /= np.linalg.norm(transverse)
    basis = np.array([axis, transverse, np.cross(axis, transverse)])
    local = (centers - origin) @ basis.T
    lower = np.min(local - radii[:, None], axis=0) - 10
    upper = np.max(local + radii[:, None], axis=0) + 10
    if np.max(upper - lower) > 500:
        raise ValueError('The experimental field volume is limited to 500 nm per axis.')
    return centers, radii, origin, basis, local, lower, upper, gaps


def solve(payload, *, reference=False, arrays=False):
    import miepy
    from importlib.metadata import version

    started = time.monotonic()
    solver_version = version('miepy')
    # Only the pinned convention has been qualified against the independent
    # evaluator. Other installed versions retain their own field implementation.
    engine = payload.get('solver', 'multipole')
    if engine not in ('multipole', 'multipole_reference'):
        raise ValueError('Unknown EM solver.')
    optimized = not reference and engine == 'multipole' and solver_version == '1.1.0'
    if optimized:
        from backend.physics.em_field_evaluator import exterior_electric_field
        evaluate_field = exterior_electric_field
    else:
        evaluate_field = lambda cluster, points: cluster.E_field(*points.T, interior=False)
    compute = payload.get('compute_backend', 'cpu')
    if compute not in ('cpu', 'gpu'):
        raise ValueError('Unknown EM compute backend.')
    device = None
    if compute == 'gpu':
        if not optimized:
            raise ValueError('GPU sampling requires the qualified MiePy 1.1.0 multipole solver.')
        from backend.physics.em_gpu import exterior_electric_field, device_info
        evaluate_field = exterior_electric_field
        device = device_info()
    particles = payload['particles']
    _, radii, origin, basis, centers, lower, upper, gaps = analysis_geometry(particles)
    from backend.physics.em_shell import shell_parameters, apply_shell, coated_field
    shell = shell_parameters(particles, payload.get('shell') or {})
    thicknesses = np.array(shell['thickness_by_particle_nm'])
    coated = np.any(thicknesses > 0)
    if coated:
        for i in range(len(centers)):
            for j in range(i + 1, len(centers)):
                separation = np.linalg.norm(centers[j] - centers[i])
                if separation <= radii[i] + radii[j] + thicknesses[i] + thicknesses[j]:
                    raise ValueError(
                        'DNA dielectric shells overlap or touch. '
                        f'This pair has a {separation - radii[i] - radii[j]:.2f} nm metal gap, '
                        f'but its shells require {thicknesses[i] + thicknesses[j]:.2f} nm '
                        f'({thicknesses[i]:.2f} + {thicknesses[j]:.2f} nm). '
                        'Concentric-shell multipoles require separated shells. '
                        'Choose a measured smaller thickness or calculate without DNA coating; '
                        'compressed/interpenetrating DNA needs a spatial dielectric solver.')
        outer = radii + thicknesses
        lower = np.min(centers - outer[:, None], axis=0) - 10
        upper = np.max(centers + outer[:, None], axis=0) + 10
        if np.max(upper - lower) > 500:
            raise ValueError('Coated field volume exceeds 500 nm per axis.')
        exterior = evaluate_field
        evaluate_field = lambda cluster, points: coated_field(cluster, points, thicknesses, shell['refractive_index'], exterior)
    resolution = payload.get('resolution', 33)
    if resolution not in (25, 33, 49):
        raise ValueError('Grid resolution must be 25, 33 or 49.')
    polarization = payload.get('polarization', 'parallel')
    if polarization not in ('parallel', 'perpendicular'):
        raise ValueError('Unknown polarization.')
    wavelength = float(payload.get('wavelength_nm', 520))
    eps = gold_permittivity(wavelength)
    sampling = payload.get('sampling', 'uniform')
    if sampling not in ('uniform', 'adaptive', 'field_adaptive'):
        raise ValueError('Unknown sampling grid.')
    spatial = {}
    if sampling in ('adaptive', 'field_adaptive'):
        from backend.physics.em_sampling import adaptive_grid
        points, sizes, sampling_info = adaptive_grid(centers, radii, thicknesses, lower, upper, resolution)
        spatial = {'sample_positions_nm': points if arrays else points.tolist(),
                   'cell_sizes_nm': sizes if arrays else sizes.tolist()}
        shape = [len(points)]
    else:
        axes = [np.linspace(lo, hi, resolution) for lo, hi in zip(lower, upper)]
        points = np.stack(np.meshgrid(*axes, indexing='ij'), axis=-1).reshape(-1, 3)
        shape = [resolution] * 3
        sampling_info = {'layout': 'uniform', 'sample_count': len(points)}
    outside = np.all(np.linalg.norm(points[:, None, :] - centers[None, :, :], axis=-1) > radii[None, :] + 0.05, axis=1)
    probes = points[outside][::max(1, int(outside.sum()) // 160)]
    # Add gap-axis probes so a sparse volume sample cannot miss the interparticle gap.
    for i in range(len(centers)):
        for j in range(i + 1, len(centers)):
            direction = centers[j] - centers[i]
            direction /= np.linalg.norm(direction)
            a, b = centers[i] + direction * (radii[i] + .1), centers[j] - direction * (radii[j] + .1)
            probes = np.vstack([probes, np.linspace(a, b, 25)])
    probes = probes[np.all(np.linalg.norm(probes[:, None, :] - centers[None, :, :], axis=-1) > radii[None, :] + .05, axis=1)]
    # Probe convergence stays on the qualified CPU path; tiny GPU launches would
    # add overhead and should not change the selected truncation order.
    probe_field = evaluate_field
    if compute == 'gpu':
        from backend.physics.em_field_evaluator import exterior_electric_field as cpu_field
        probe_field = (lambda cluster, points: coated_field(cluster, points, thicknesses,
                       shell['refractive_index'], cpu_field)) if coated else cpu_field
    source = miepy.sources.plane_wave([1, 0] if polarization == 'parallel' else [0, 1])
    previous = None
    error = None
    preparation_seconds = time.monotonic() - started
    convergence_started = time.monotonic()
    for order in (4, 6, 8, 10, 12):
        cluster = miepy.sphere_cluster(position=centers, radius=radii,
            material=miepy.constant_material(eps=eps), source=source, wavelength=wavelength,
            lmax=order, medium=miepy.constant_material(index=1.333))
        if coated:
            apply_shell(cluster, thicknesses, shell['refractive_index'])
        fields = probe_field(cluster, probes)
        if previous is not None:
            error = float(np.max(np.linalg.norm(fields - previous, axis=0) / np.maximum(np.linalg.norm(fields, axis=0), 1.)))
            if error < .01:
                break
        previous = fields
    if error is None or not np.isfinite(error) or error >= .01:
        raise ValueError('Multipole probe convergence did not reach 1%. No field map was published; this geometry needs a higher-order solver.')
    convergence_seconds = time.monotonic() - convergence_started
    field_started = time.monotonic()
    def sample(sample_points):
        mask = np.all(np.linalg.norm(sample_points[:, None, :] - centers[None, :, :], axis=-1)
                      > radii[None, :] + .05, axis=1)
        intensity = np.zeros(len(sample_points))
        indices = np.flatnonzero(mask)
        batch = 65536 if compute == 'gpu' else 2048
        for offset in range(0, len(indices), batch):
            selected = indices[offset:offset + batch]
            fields = evaluate_field(cluster, sample_points[selected])
            intensity[selected] = np.sum(np.abs(fields) ** 2, axis=0)
        return intensity, mask

    values, outside = sample(points)
    if sampling == 'field_adaptive':
        from backend.physics.em_field_sampling import refine_field
        points, sizes, values, outside, refinement = refine_field(
            points, sizes, values, outside, sample, resolution)
        sampling_info.update(refinement)
        spatial = {'sample_positions_nm': points if arrays else points.tolist(),
                   'cell_sizes_nm': sizes if arrays else sizes.tolist()}
        shape = [len(points)]
    if not np.all(np.isfinite(values)):
        raise ValueError('Non-finite electric field encountered. No field map was published.')
    peak = int(np.argmax(values))
    field_seconds = time.monotonic() - field_started
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return {
        'quantity': '|E_total|²/|E_incident|²', 'wavelength_nm': wavelength, 'medium_index': 1.333,
        'solver': f'MiePy {solver_version} generalized multiparticle Mie',
        'field_evaluator': ('nadoc-cuda-exterior-vsh-v1' if compute == 'gpu' else
                            'nadoc-exterior-vsh-v1' if optimized else 'miepy-reference'),
        'compute_backend': compute, 'compute_device': device,
        'timing_seconds': {'preparation': preparation_seconds, 'convergence': convergence_seconds,
                           'field_grid': field_seconds},
        'source_sha256': hashlib.sha256(canonical.encode()).hexdigest(),
        'inputs': payload, 'dna_shell': shell, 'solver_option': engine, 'gold_epsilon': [eps.real, eps.imag],
        'gold_table_sha256': hashlib.sha256(GOLD_TABLE.read_bytes()).hexdigest(),
        'origin_nm': origin.tolist(), 'basis': basis.tolist(), 'lower_nm': lower.tolist(),
        'upper_nm': upper.tolist(), 'shape': shape, 'sampling': sampling_info, **spatial,
        # Archives retain the unrounded float64 field without allocating Python
        # scalars. The existing interactive JSON contract remains unchanged.
        'intensity': values if arrays else np.round(values, 6).tolist(),
        'outside': outside if arrays else outside.tolist(),
        'gap_nm': min(gaps) if gaps else None, 'multipole_order': order,
        'probe_relative_error': error, 'probe_count': len(probes),
        'peak_intensity': float(values[peak]), 'peak_position_nm': (origin + points[peak] @ basis).tolist(),
        'polarization_world': basis[0 if polarization == 'parallel' else 1].tolist(),
        'propagation_world': basis[2].tolist(), 'elapsed_seconds': time.monotonic() - started,
        'assumptions': ['Water background; spherical gold with bulk Johnson–Christy optical constants.',
            ('Full-coverage concentric effective DNA dielectric shells; origami body and substrate excluded.' if coated else 'DNA, ligands, coatings and substrates excluded from the optical medium.'),
            'Static snapshot; no thermal ensemble, heating, tunnelling or fluorescence-yield calculation.',
            'Metal interiors and a 0.05 nm surface margin are masked, not zero field.',
            '1% convergence is checked at probes, not a full grid-refinement certificate. Peak is a sampled grid maximum.'],
    }


if __name__ == '__main__':
    import contextlib
    import sys
    def output(request):
        with contextlib.redirect_stdout(sys.stderr):
            result = solve(request)
        print(json.dumps(result, allow_nan=False, separators=(',', ':')), flush=True)

    try:
        if sys.argv[1:] == ['--stream']:
            # One bounded volume at a time; imports are reused across frames.
            # Fail closed on the first invalid/nonconvergent frame, never reuse
            # stale fields or interpolate missing frames into scientific output.
            for line in sys.stdin:
                output(json.loads(line))
        elif not sys.argv[1:]:
            output(json.load(sys.stdin))
        else:
            raise ValueError('Usage: python -m backend.physics.em_analysis [--stream]')
    except Exception as exc:
        print(json.dumps({'error': str(exc)}), flush=True)
        sys.exit(1)
