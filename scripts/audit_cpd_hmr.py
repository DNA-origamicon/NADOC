"""Independently audit saved CPD HMR validation inputs, logs and binary endpoints.

Read-only: writes one report; does not alter or publish molecular structures.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

import numpy as np

from backend.core.md_shell_reprep import read_namd_coor
from backend.core.photoproduct_psf_audit import parse_psf_atoms, parse_psf_index_section
from backend.core.namd_topology import charmm_atom_name


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def normalized_psf(path):
    """Remove only the mass column, independently of the HMR implementation."""
    lines = path.read_text().splitlines()
    i = next(i for i, line in enumerate(lines) if '!NATOM' in line)
    n = int(lines[i].split()[0])
    for j in range(i+1, i+1+n):
        fields = lines[j].split()
        fields[7] = '<mass>'
        lines[j] = ' '.join(fields)
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    protocol = json.loads((root/'protocol.json').read_text())
    records = json.loads((root/'results.json').read_text())
    assert len(records) == 16
    reports = []
    for record in records:
        jid, start, dt = record['job'], record['start'], record['dt_fs']
        arm = root/f'{jid}_{start}_{dt}fs'
        inputs = json.loads((arm/'inputs.json').read_text())
        assert all(digest(i['path']) == i['sha256'] for i in inputs['inputs'])
        manifest_path = next(Path(i['path']) for i in inputs['inputs'] if i['path'].endswith('photoproduct_forcefield_manifest.json'))
        manifest = json.loads(manifest_path.read_text())
        for a in manifest['assets']:
            assert digest(manifest_path.parent/'forcefield'/a['relative_path']) == a['sha256']
        source = next(Path(i['path']) for i in inputs['inputs'] if i['path'].endswith('.psf'))
        psf = Path(inputs['psf']['path'])
        assert digest(psf) == inputs['psf']['sha256']
        assert normalized_psf(source) == normalized_psf(psf)
        original = parse_psf_atoms(source.read_text())
        atoms = parse_psf_atoms(psf.read_text())
        assert len(original) == len(atoms) and all(a.mass > 0 for a in atoms)
        mass_delta = sum(a.mass-b.mass for a,b in zip(atoms, original))
        assert abs(mass_delta) < 1e-6
        assert all(a.mass == b.mass for a,b in zip(atoms,original) if a.resname == 'TIP3')
        patch = manifest['topology_and_placement_audits']['photoproduct_patch_audit']['patches'][0]
        ends = {e['endpoint']: (e['segid'], str(e['resid'])) for e in patch['endpoints']}
        idx = {a.identity: a.index-1 for a in atoms}
        chem_asset = next(a for a in manifest['assets'] if a['kind']=='chemical_definition')
        chem = json.loads((manifest_path.parent/'forcefield'/chem_asset['relative_path']).read_text())

        def ref(r):
            n, name = r.split(':')
            return idx[(*ends[int(n)], charmm_atom_name(name))]

        cross = np.array([[ref(b['atom_1']), ref(b['atom_2'])] for b in chem['graph_delta']['bonds_added']])
        heavy = {a.index-1 for a in original if (a.segid,a.resid) in ends.values() and a.mass > 2}
        bonds = np.array(parse_psf_index_section(psf.read_text(), '!NBOND', 2))-1
        local_bonds = np.array([b for b in bonds if any(i in heavy for i in b) and all(original[i].mass > 2 for i in b)])
        stage_reports = {}
        for stage in ('npt', 'nve'):
            conf = (arm/f'{stage}.conf').read_text()
            directives = {}
            for line in conf.splitlines():
                fields = line.split()
                if len(fields)>1 and not line.lstrip().startswith('#'):
                    directives[fields[0].lower()] = fields[1]
            assert float(directives['timestep']) == dt
            assert directives['rigidbonds'] == 'all' and directives['gpuresident']=='on'
            assert directives['fullelectfrequency']=='1'
            assert [float(directives[k]) for k in ['switchdist','cutoff','pairlistdist','pmegridspacing']] == [8,10,12,1.5]
            assert directives['langevin'] == ('on' if stage=='npt' else 'off')
            assert directives['langevinpiston'] == ('on' if stage=='npt' else 'off')
            log = (arm/f'{stage}.log').read_text()
            assert 'End of program' in log and not re.search(r'^(?:ERROR:|FATAL ERROR)',log,re.M)
            columns = next(l.split()[1:] for l in log.splitlines() if l.startswith('ETITLE:'))
            table = np.array([list(map(float,l.split()[1:])) for l in log.splitlines() if l.startswith('ENERGY:')])
            assert np.isfinite(table).all()
            duration = protocol[f'{stage}_ps']
            if stage == 'nve':
                duration = protocol.get('nve_ps_by_job', {}).get(jid, duration)
            assert table[-1,columns.index('TS')] == duration*1000/dt
            coords = read_namd_coor(arm/f'{stage}.coor')
            assert coords.shape == (len(atoms),3) and np.isfinite(coords).all()
            xsc = np.loadtxt(arm/f'{stage}.xsc')
            box = xsc[[1,5,9]]

            def difference(a,b):
                v=coords[a]-coords[b]
                return v-box*np.round(v/box)

            lengths=np.linalg.norm(difference(cross[:,0],cross[:,1]),axis=1)
            assert np.all((lengths>=1.2)&(lengths<=1.9))
            local_lengths=np.linalg.norm(difference(local_bonds[:,0],local_bonds[:,1]),axis=1)
            # Additional gross bond-integrity diagnostic, not a new fitted target.
            assert np.all((local_lengths>=1.0)&(local_lengths<=2.1))
            volumes=[]
            for center in chem['product_stereocenters']:
                vectors=np.array([difference(ref(r),ref(center['atom'])) for r in center['signed_volume_reference_atoms']])
                volume=float(np.linalg.det(vectors))
                assert volume*(1 if center['expected_signed_volume']=='positive' else -1)>0
                volumes.append(volume)
            drift=None
            if stage=='nve':
                tail=table[len(table)//2:]
                times=tail[:,columns.index('TS')]*dt*1e-6
                energy=tail[:,columns.index('TOTAL')]
                drift=float(np.dot(times-times.mean(),energy-energy.mean())/np.sum((times-times.mean())**2)/len(atoms))
                assert abs(drift)<=protocol['maximum_abs_drift_kcal_mol_ns_atom']
                assert abs(drift-record['nve']['drift_kcal_mol_ns_atom'])<1e-9
            stage_reports[stage]=dict(log_sha256=digest(arm/f'{stage}.log'),conf_sha256=digest(arm/f'{stage}.conf'),
                endpoint_sha256=digest(arm/f'{stage}.coor'),crosslinks_A=lengths.tolist(),
                lesion_heavy_bond_range_A=[float(local_lengths.min()),float(local_lengths.max())],
                stereocenter_determinants_A3=volumes,drift_kcal_mol_ns_atom=drift)
        reports.append(dict(job=jid,start=start,dt_fs=dt,atom_count=len(atoms),mass_delta_Da=mass_delta,stages=stage_reports))
    for jid in protocol['jobs']:
        for start in protocol['starts']:
            pair={r['dt_fs']: r for r in reports if r['job']==jid and r['start']==start}
            assert set(pair)=={2,4}
            drift=lambda dt:abs(pair[dt]['stages']['nve']['drift_kcal_mol_ns_atom'])
            assert drift(4)-drift(2)<=protocol['maximum_paired_abs_drift_excess']
    report=dict(passed=True,worker_sha256=digest(__file__),protocol_sha256=digest(root/'protocol.json'),arms=reports)
    (root/'independent_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Independent audit passed:',len(reports),'arms',flush=True)


if __name__ == '__main__':
    main()
