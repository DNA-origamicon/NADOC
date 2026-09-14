"""Stage one brush from supplied parameterized chains and a periodic gold slab.

Writes coordinates and VMD/NAMD inputs only; never runs MD or submits jobs.
Missing chemistry assets produce an actionable report, not guessed parameters.
"""
from __future__ import annotations
import argparse
import json
import re
import shutil
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from .campaign import digest, validate
from .structure import read_pair, place_chain, write_chain
from .render import build_tcl, configurations, RUN_SCRIPT


def asset_paths(registry_path, n):
    registry_path = Path(registry_path)
    registry = json.loads(registry_path.read_text())
    if registry.get('schema_version') != 1:
        raise ValueError('Unsupported asset schema')
    surface = registry.get('surface', {})
    chain = registry.get('chains', {}).get(str(n), {})
    errors = []
    resolved = {}
    for label, entry in [('surface', surface), ('chain', chain)]:
        for key in ('psf', 'pdb'):
            value = entry.get(key)
            path = (registry_path.parent / value).resolve() if value else None
            if path is None or not path.is_file():
                errors.append(f'{label}.{key}: parameterized asset missing')
            else:
                resolved[f'{label}_{key}'] = path
        for key in ('source', 'parameters'):
            if not entry.get(key):
                errors.append(f'{label}.{key}: missing provenance/parameter list')
    if chain.get('repeat_units') != n:
        errors.append('chain.repeat_units: does not match selected length')
    for key in ('anchor_index', 'end_index', 'chemistry'):
        if not chain.get(key):
            errors.append(f'chain.{key}: required')
    if surface.get('model') != 'neutral_fixed_gold' or not surface.get('periodic_xy_verified'):
        errors.append('surface: requires neutral_fixed_gold and commensurate periodic XY evidence')
    if not registry.get('compatibility_evidence'):
        errors.append('compatibility_evidence: document parameter ordering, mixing rules and cross interactions')
    if not registry.get('water_ions_parameters'):
        errors.append('water_ions_parameters: missing')
    parameters = []
    for name in [*surface.get('parameters', []), *chain.get('parameters', []), *registry.get('water_ions_parameters', [])]:
        p = (registry_path.parent / name).resolve()
        if not p.is_file():
            errors.append(f'parameter file missing: {p}')
        elif p not in parameters:
            parameters.append(p)
    return registry, resolved, parameters, errors


def stage(campaign, case_id, registry_path, output):
    campaign, output = Path(campaign), Path(output)
    spec = json.loads((campaign / 'campaign.json').read_text()); validate(spec)
    row = next((r for r in json.loads((campaign / 'plan.json').read_text())['cases'] if r['id'] == case_id), None)
    if row is None:
        raise ValueError('Unknown case')
    registry, paths, parameters, errors = asset_paths(registry_path, row['repeat_units'])
    if errors:
        raise ValueError('Cannot stage:\n' + '\n'.join(errors))
    surface, chain = registry['surface'], registry['chains'][str(row['repeat_units'])]
    if not np.allclose(surface['box_xy_nm'], spec['box_nm'][:2], atol=1e-6, rtol=0):
        raise ValueError('Slab periodic dimensions do not match box')
    if not 0 < surface['top_z_nm'] < spec['graft_plane_nm']:
        raise ValueError('Graft plane must lie above the slab')
    slab = read_pair(paths['surface_psf'], paths['surface_pdb'])
    peg = read_pair(paths['chain_psf'], paths['chain_pdb'])
    if any(abs(float(a[6])) > 1e-8 for a in slab['atoms']):
        raise ValueError('This pilot requires neutral fixed gold atoms')
    if abs(sum(float(a[6]) for a in peg['atoms'])) > 1e-5:
        raise ValueError('Neutral capped PEG template required; charged/thiolate chemistry needs another protocol')
    if len({a[1] for a in peg['atoms']}) != 1:
        raise ValueError('Chain template must contain exactly one segment')
    segments = sorted({a[1] for a in slab['atoms']})
    tokens = segments + [a[2] for a in peg['atoms']] + [a[4] for a in peg['atoms']]
    if any(not re.fullmatch(r'[A-Za-z0-9_]+', x) for x in tokens) or any(s.startswith('P') or s.startswith('WT') or s == 'ION' for s in segments):
        raise ValueError('Unsafe/reserved segment or atom identifiers')
    actual_top = float(slab['xyz'][:, 2].max()) / 10
    if abs(actual_top - surface['top_z_nm']) > .01 or slab['xyz'][:, 2].min() < 0:
        raise ValueError('Slab coordinates do not match declared top plane')
    coords = [place_chain(peg, chain['anchor_index'], chain['end_index'], (x, y, spec['graft_plane_nm']), angle, spec['box_nm'])
              for x, y, angle in row['sites_nm_deg']]
    if any(c[:, 2].min() <= actual_top * 10 + .5 for c in coords):
        raise ValueError('Chain template penetrates slab; supply a different conformer')
    # A short-distance gate detects severe overlaps, not force-field validation.
    # Periodicity only in XY; using a very long z period leaves z unwrapped here.
    box = np.array([spec['box_nm'][0] * 10, spec['box_nm'][1] * 10, 1e6])
    points = np.vstack([slab['xyz'], *coords]) % box
    groups = np.concatenate([np.full(len(slab['atoms']), -1), *[np.full(len(c), i) for i, c in enumerate(coords)]])
    pairs = cKDTree(points, boxsize=box).query_pairs(1.2, output_type='ndarray')
    if len(pairs) and np.any(groups[pairs[:, 0]] != groups[pairs[:, 1]]):
        raise ValueError('Inter-chain or chain-slab overlap below 1.2 A; prepare another template/site configuration')
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite {output}')
    output.mkdir(parents=True)
    (output / 'chains').mkdir(); (output / 'forcefield').mkdir(); (output / 'output').mkdir()
    for kind in ('psf', 'pdb'):
        shutil.copyfile(paths[f'surface_{kind}'], output / f'surface.{kind}')
    for i, coord in enumerate(coords):
        write_chain(peg, coord, f'P{i:03X}', output / 'chains' / f'P{i:03X}')
    sources = []
    for i, path in enumerate(parameters):
        target = output / 'forcefield' / f'p{i:03d}.str'
        shutil.copyfile(path, target)
        sources.append(dict(path=str(path), sha256=digest(path), packaged_as=str(target.relative_to(output))))
    anchor = peg['atoms'][chain['anchor_index'] - 1]
    (output / 'build.tcl').write_text(build_tcl(spec, row, segments, (anchor[2], anchor[4]), actual_top))
    for name, conf in configurations(spec, row['seed'], len(parameters)).items():
        (output / name).write_text(conf)
    (output / 'run.sh').write_text(RUN_SCRIPT); (output / 'run.sh').chmod(0o755)
    shutil.copyfile(Path(__file__).with_name('verify_package.py'), output / 'verify_inputs.py')
    manifest = dict(status='staged_not_solvated_not_engine_verified', case=row, campaign=spec,
                    registry=registry, registry_sha256=digest(registry_path), parameters=sources,
                    inputs={key:dict(path=str(path), sha256=digest(path)) for key, path in paths.items()},
                    files=[dict(path=str(p.relative_to(output)), sha256=digest(p)) for p in sorted(output.rglob('*')) if p.is_file()])
    (output / 'package.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--campaign', type=Path, required=True)
    p.add_argument('--assets', type=Path, required=True)
    p.add_argument('--case', required=True)
    p.add_argument('--output', type=Path)
    p.add_argument('--check-assets', action='store_true')
    args = p.parse_args()
    if args.check_assets:
        rows = json.loads((args.campaign / 'plan.json').read_text())['cases']
        row = next(r for r in rows if r['id'] == args.case)
        errors = asset_paths(args.assets, row['repeat_units'])[3]
        print(json.dumps(dict(status='missing_assets' if errors else 'assets_present_not_validated', gaps=errors), indent=2))
        return
    if args.output is None:
        p.error('--output required when staging')
    stage(args.campaign, args.case, args.assets, args.output)
    print(f'Staged {args.output}; next: vmd -dispdev text -e build.tcl from that directory; no MD launched')


if __name__ == '__main__':
    main()
