"""Offline PEG-brush campaign planning. No scheduler submission or engine execution."""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def validate(spec):
    if spec['schema_version'] != 1:
        raise ValueError('Unsupported schema')
    numeric = [*spec['box_nm'], *spec['graft_density_nm2'], spec['temperature_K'],
               spec['tether_k_kcal_mol_A2'], spec['equilibration_ns'], spec['pilot_ns']]
    if len(spec['box_nm']) != 3 or any(not math.isfinite(x) or x <= 0 for x in numeric):
        raise ValueError('Dimensions, densities and durations must be positive finite values')
    if spec['surface_model'] != 'neutral_fixed_gold_harmonic_grafts':
        raise ValueError('Only the neutral fixed-gold harmonic-graft pilot is implemented')
    if spec['timestep_fs'] not in (1, 2):
        raise ValueError('Only 1 or 2 fs without hydrogen mass repartitioning')
    if not 0 < spec['graft_plane_nm'] < spec['box_nm'][2]:
        raise ValueError('Graft plane outside box')
    if not math.isfinite(spec['salt_NaCl_M']) or spec['salt_NaCl_M'] < 0:
        raise ValueError('NaCl concentration must be finite and nonnegative')
    if not spec['repeat_units'] or not spec['graft_density_nm2']:
        raise ValueError('Empty sweep')
    for value in [*spec['repeat_units'], spec['replicas'], spec['benchmark_steps'], spec['seed']]:
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError('Lengths, replica count, steps and seed must be positive integers')
    if len(set(spec['repeat_units'])) != len(spec['repeat_units']) or len(set(spec['graft_density_nm2'])) != len(spec['graft_density_nm2']):
        raise ValueError('Duplicate sweep points')


def graft_sites(box, density, seed):
    """Near-square periodic lattice, reporting achieved rather than requested density."""
    lx, ly, _ = box
    nx = max(1, round(lx * math.sqrt(density)))
    ny = max(1, round(ly * math.sqrt(density)))
    if nx * ny > 4096:
        raise ValueError('More than 4096 chains unsupported by four-character segment IDs')
    rng = random.Random(seed)
    phase_x, phase_y = rng.random(), rng.random()
    sites = [((i + phase_x) * lx / nx, (j + phase_y) * ly / ny, rng.random() * 360)
             for i in range(nx) for j in range(ny)]
    return sites, len(sites) / (lx * ly)


def cases(spec):
    validate(spec)
    result = []
    for i, (n, density, replica) in enumerate(itertools.product(
            spec['repeat_units'], spec['graft_density_nm2'], range(1, spec['replicas'] + 1))):
        seed = spec['seed'] + i
        sites, actual = graft_sites(spec['box_nm'], density, seed)
        name = f'n{n}_s{density:g}_r{replica}'.replace('.', 'p')
        result.append(dict(id=name, repeat_units=n, requested_density_nm2=density,
                           achieved_density_nm2=actual, replica=replica, seed=seed,
                           chains=len(sites), sites_nm_deg=sites))
    return result


def plan(spec_path, output):
    spec_path, output = Path(spec_path), Path(output)
    spec = json.loads(spec_path.read_text())
    rows = cases(spec)
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite {output}')
    output.mkdir(parents=True)
    (output / 'campaign.json').write_text(json.dumps(spec, indent=2) + '\n')
    report = dict(status='planned_not_built', source_sha256=digest(spec_path),
                  cases=rows, total_pilot_ns=sum(spec['pilot_ns'] for _ in rows),
                  exclusions=['electrode potential', 'Au-S bonding', 'DNA', 'physical kinetic calibration'])
    (output / 'plan.json').write_text(json.dumps(report, indent=2) + '\n')
    with (output / 'cases.csv').open('w', newline='') as f:
        columns = ['id', 'repeat_units', 'requested_density_nm2', 'achieved_density_nm2', 'replica', 'seed', 'chains']
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    for row in rows:
        job = output / row['id']
        job.mkdir()
        (job / 'case.json').write_text(json.dumps(row, indent=2) + '\n')
        with (job / 'grafts.csv').open('w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['segid', 'x_nm', 'y_nm', 'z_nm', 'rotation_deg'])
            writer.writerows((f'P{i:03X}', x, y, spec['graft_plane_nm'], angle)
                             for i, (x, y, angle) in enumerate(row['sites_nm_deg']))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', type=Path, default=HERE / 'campaign.json')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = plan(args.spec, args.output)
    print(f"Planned {len(report['cases'])} cases; {report['total_pilot_ns']:g} ns pilot allocation; no jobs launched")


if __name__ == '__main__':
    main()
