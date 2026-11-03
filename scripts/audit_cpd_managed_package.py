"""Inspect a prepared managed CPD job without executing any simulation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from backend.core.cpd_forcefield import packaged_photoproduct_manifest
from backend.core.namd_topology import charmm_atom_name
from backend.core.photoproduct_psf_audit import parse_psf_atoms, parse_psf_index_section
from backend.core.photoproduct_chemistry import audit_product_chirality, load_chemical_definition


def audit(job_dir: Path, *, completed: bool = False) -> dict:
    job = json.loads((job_dir / 'job.json').read_text())
    assert job['status'] == ('completed' if completed else 'queued')
    if not completed:
        assert not any(job.get(k) for k in ('namd_pid', 'slurm_job_id', 'runpod_pod_id'))
    assert job['prep_params']['autostart'] is False
    package = job_dir / job['package_subdir']
    manifest = json.loads((package / 'manifest.json').read_text())
    product = packaged_photoproduct_manifest(package)  # verifies every pinned asset hash
    assert product['qualification'] == 'experimental-mvp'
    psf = (package / manifest['files']['topology']).read_text()
    atoms = parse_psf_atoms(psf)
    identities = {a.identity: a for a in atoms}
    bonds = {frozenset(b) for b in parse_psf_index_section(psf, '!NBOND', 2)}
    lines = (package / manifest['files']['coordinates']).read_text().splitlines()
    coords = {(l[72:76].strip(), l[22:26].strip(), l[12:16].strip()):
              [float(l[i:i+8]) for i in (30, 38, 46)]
              for l in lines if l.startswith(('ATOM  ', 'HETATM'))}
    assert len(coords) == len(atoms)
    if completed:
        from backend.core.md_shell_reprep import read_namd_coor
        final = next(s for s in reversed(job['segments']) if not s.get('skipped'))
        xyz = read_namd_coor(package / 'output' / (final['name'] + '.coor'))
        assert len(xyz) == len(atoms)
        coords = {a.identity: xyz[a.index - 1] for a in atoms}
    chemistry = []
    patches = product['topology_and_placement_audits']['photoproduct_patch_audit']['patches']
    for lesion, patch in zip(product['lesions'], patches, strict=True):
        ends = {e['endpoint']: (e['segid'], str(e['resid'])) for e in patch['endpoints']}
        definition = load_chemical_definition(lesion['product'], lesion['stereochemistry'])
        refs = {r for c in definition['product_stereocenters']
                for r in [c['atom'], *c['signed_volume_reference_atoms']]}
        core = {}
        for ref in refs:
            number, name = ref.split(':')
            key = (*ends[int(number)], charmm_atom_name(name))
            core[ref] = coords[key]
            if name.startswith('H'):
                assert identities[key].mass < 1.1
        stereo = audit_product_chirality(definition, core)
        assert stereo['passed'], stereo
        for bond in definition['graph_delta']['bonds_added']:
            pair = []
            for ref in (bond['atom_1'], bond['atom_2']):
                n, name = ref.split(':')
                pair.append(identities[(*ends[int(n)], charmm_atom_name(name))].index)
            assert frozenset(pair) in bonds
        chemistry.append({'isomer': lesion['stereochemistry'], 'chirality': stereo,
                          'two_covalent_crosslinks': True})
    for extra in package.glob('*.enm.extra'):
        for line in extra.read_text().splitlines():
            fields = line.split()
            if fields and fields[0] == 'bond':
                assert frozenset(int(i) + 1 for i in fields[1:3]) not in bonds, extra.name
    configs = sorted(package.glob('*.conf'))
    for conf in configs:
        directives = {}
        for line in conf.read_text().splitlines():
            fields = line.split('#', 1)[0].split()
            if len(fields) >= 2:
                directives.setdefault(fields[0].lower(), []).append(fields[1])
        assert float(directives['timestep'][0]) <= 2
        assert '_hmr' not in directives['structure'][0]
        params = directives.get('parameters', [])
        for asset in product['assets']:
            if asset['kind'] == 'parameters':
                assert 'forcefield/' + asset['relative_path'] in params, conf.name
        for name in params:
            assert (package / name).is_file(), (conf.name, name)
    expected = {'done', 'completed'} if completed else {'pending'}
    assert all(s['status'] in expected for s in job['segments'])
    assert job['minimization']['status'] in expected
    return {'job_id': job['job_id'], 'package': str(package.resolve()),
            'atoms': len(atoms), 'configurations': len(configs),
            'relaxation_stages': len(manifest['segments']), 'chemistry': chemistry,
            'parameter_hashes_verified': len(product['assets']),
            'all_timesteps_at_most_2_fs': True, 'no_hmr': True, 'not_started': not completed,
            'completed': completed, 'early_stop_enabled': job['early_stop_relax'],
            'health_samples': job.get('health_samples', []),
            'adaptive_minimization': {f.name: f.read_text().strip()
                for f in (package / 'output').glob('*.adaptive_min.txt')},
            'skipped_segments': [s['name'] for s in job['segments'] if s.get('skipped')],
            'psf_sha256': hashlib.sha256(psf.encode()).hexdigest()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job_dir', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--completed', action='store_true')
    args = parser.parse_args()
    result = json.dumps(audit(args.job_dir, completed=args.completed), indent=2) + '\n'
    if args.output:
        args.output.write_text(result)
    print(result)
