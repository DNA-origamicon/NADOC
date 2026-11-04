"""Paired native integrator validation on read-only, existing CPD job packages.

No authored structures or force-field changes. Derived PSFs use the production
HMR operation; source manifests, coordinates, and complete job histories remain
owned by the original jobs. Run only on explicit scientific user authorization.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from backend.core.cpd_forcefield import packaged_photoproduct_manifest
from backend.core.md_protocols import write_hmr_psf
from backend.core.namd_topology import charmm_atom_name
from backend.core.photoproduct_chemistry import audit_product_chirality, load_chemical_definition
from backend.core.photoproduct_psf_audit import parse_psf_atoms

JOBS = ('edb512c46112', 'e345c67349bf', '35254aa13b01', '395337bdb061')
POLICY = dict(
    schema='nadoc.cpd-hmr-validation.v1',
    npt_ps=25, nve_ps=10, starts=['reseed', 'production_endpoint'],
    seeds=[731041, 731042], timesteps_fs=[4, 2], hmr_factor=3,
    crosslink_range_A=[1.2, 1.9], maximum_abs_drift_kcal_mol_ns_atom=0.01,
    maximum_paired_abs_drift_excess=0.005,
    temperature_mean_range_K=[285, 315],
    scope='Numerical stability only; not equilibrium, kinetic or thermodynamic equivalence.',
)


def pin(path):
    with Path(path).open('rb') as stream:
        return dict(path=str(Path(path).resolve()), sha256=hashlib.file_digest(stream, 'sha256').hexdigest())


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def replace(conf, key, value):
    pattern = rf'^{key}\s+.*$'
    if re.search(pattern, conf, re.M | re.I):
        return re.sub(pattern, f'{key} {value}', conf, flags=re.M | re.I)
    return conf + f'{key} {value}\n'


def energies(log):
    rows = []
    fields = []
    for line in log.splitlines():
        if line.startswith('ETITLE:'):
            fields = line.split()[1:]
        if line.startswith('ENERGY:'):
            rows.append(dict(zip(fields, map(float, line.split()[1:]))))
    return rows


def geometry(psf, dcd, manifest):
    import MDAnalysis as mda
    from MDAnalysis.lib.distances import minimize_vectors

    u = mda.Universe(str(psf), str(dcd))
    lesion = manifest['lesions'][0]
    definition = load_chemical_definition(lesion['product'], lesion['stereochemistry'])
    patch = manifest['topology_and_placement_audits']['photoproduct_patch_audit']['patches'][0]
    ends = {e['endpoint']: (e['segid'], int(e['resid'])) for e in patch['endpoints']}
    idx = {(a.segid, int(a.resid), a.name): a.index for a in u.atoms}

    def ref(r):
        n, name = r.split(':')
        return idx[(*ends[int(n)], charmm_atom_name(name))]

    bonds = np.array([[ref(b['atom_1']), ref(b['atom_2'])] for b in definition['graph_delta']['bonds_added']])
    refs = sorted({r for c in definition['product_stereocenters'] for r in [c['atom'], *c['signed_volume_reference_atoms']]})
    ci = np.array([ref(r) for r in refs])
    trace = []
    for ts in u.trajectory:
        xyz = ts.positions
        core = xyz[ci[0]] + minimize_vectors(xyz[ci] - xyz[ci[0]], ts.dimensions)
        chir = audit_product_chirality(definition, dict(zip(refs, core)))
        lengths = np.linalg.norm(minimize_vectors(xyz[bonds[:, 0]] - xyz[bonds[:, 1]], ts.dimensions), axis=1)
        trace.append(dict(frame=int(ts.frame), finite=bool(np.isfinite(xyz).all()),
                          chirality_passed=bool(chir['passed']), crosslinks_A=lengths.tolist()))
    u.trajectory.close()
    return dict(frames=len(trace), passed=bool(trace) and all(
        r['finite'] and r['chirality_passed'] and all(1.2 <= x <= 1.9 for x in r['crosslinks_A']) for r in trace), trace=trace)


def run_stage(root, conf, stage, dt, natoms, psf, manifest, namd):
    (root / f'{stage}.conf').write_text(conf)
    t = time.monotonic()
    with (root / f'{stage}.log').open('w') as stream:
        p = subprocess.run([namd, '+p4', '+setcpuaffinity', f'{stage}.conf'], cwd=root,
                           stdout=stream, stderr=subprocess.STDOUT, timeout=1800)
    log = (root / f'{stage}.log').read_text()
    rows = energies(log)
    errors = re.findall(r'^(?:FATAL ERROR|ERROR:).*$', log, re.M)
    result = dict(returncode=p.returncode, wall_seconds=time.monotonic()-t, errors=errors,
                  normal_exit='End of program' in log, energy_samples=len(rows),
                  finite=bool(rows) and all(np.isfinite(list(r.values())).all() for r in rows))
    result['passed'] = result['normal_exit'] and not errors and p.returncode == 0 and result['finite']
    if rows:
        result['last_step'] = rows[-1]['TS']
        result['mean_temperature_K'] = float(np.mean([r['TEMP'] for r in rows[len(rows)//2:]]))
        result['passed'] &= result['last_step'] == round(POLICY[f'{stage}_ps']*1000/dt)
        if stage == 'nve':
            tail = rows[len(rows)//2:]
            slope = np.polyfit([r['TS']*dt*1e-6 for r in tail], [r['TOTAL'] for r in tail], 1)[0]/natoms
            result['drift_kcal_mol_ns_atom'] = float(slope)
            result['passed'] &= abs(slope) <= POLICY['maximum_abs_drift_kcal_mol_ns_atom']
        else:
            result['passed'] &= 285 <= result['mean_temperature_K'] <= 315
    result['passed'] = bool(result['passed'])
    if result['normal_exit']:
        result['geometry'] = geometry(psf, root/f'{stage}.dcd', manifest)
        result['passed'] &= result['geometry']['passed']
    save(root/f'{stage}.json', result)
    print(root.name, stage, {k:v for k,v in result.items() if k != 'geometry'}, flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    if shutil.disk_usage(root).free < 10*1024**3:
        raise RuntimeError('Need 10 GiB headroom for bounded native validation')
    namd = str(Path(shutil.which('namd3')).resolve())
    save(root/'protocol.json', dict(**POLICY, worker=pin(__file__), engine=pin(namd), jobs=JOBS))
    results = []
    for jid in JOBS:
        jd = Path('workspace/md_jobs')/jid
        job = json.loads((jd/'job.json').read_text())
        pkg = (jd/job['package_subdir']).resolve()
        manifest = packaged_photoproduct_manifest(pkg)
        stem = job['name_stem']
        source_conf = pkg/f"{job['segments'][0]['name']}.conf"
        base = source_conf.read_text()
        for start_index, start in enumerate(POLICY['starts']):
            checkpoint = f'{stem}_00_reseed' if start_index == 0 else job['segments'][0]['name']
            for dt in POLICY['timesteps_fs']:
                arm = root/f'{jid}_{start}_{dt}fs'
                arm.mkdir()
                # Read-only source links preserve original ownership and histories.
                for name in ['forcefield', f'{stem}.psf', f'{stem}.pdb', 'mgh_extrabonds.txt']:
                    (arm/name).symlink_to(pkg/name)
                src = pkg/f'{stem}.psf'
                psf = arm/f'{stem}_hmr.psf' if dt == 4 else src
                nh = write_hmr_psf(src, psf) if dt == 4 else 0
                atoms = parse_psf_atoms(src.read_text())
                if dt == 4:
                    modified = parse_psf_atoms(psf.read_text())
                    assert all(a.identity == b.identity and a.atom_type == b.atom_type and a.charge == b.charge for a,b in zip(atoms,modified))
                    assert abs(sum(a.mass for a in atoms)-sum(a.mass for a in modified)) < 1e-5
                    assert all(a.mass > 0 for a in modified)
                inputs = [pin(jd/'job.json'), pin(pkg/'photoproduct_forcefield_manifest.json'), pin(source_conf), pin(src)]
                inputs += [pin(pkg/'output'/f'{checkpoint}.{ext}') for ext in ['coor','xsc']]
                save(arm/'inputs.json', dict(source_job=jid, inputs=inputs, source_assets=manifest['assets'],
                     operation='write_hmr_psf factor=3; fresh mass-consistent 300 K velocities; paired NPT/NVE',
                     repartitioned_hydrogens=nh, psf=pin(psf)))
                conf = re.sub(r'^\s*(?:binVelocities|run|outputName|dcdFile|xstFile)\s+.*\n?', '', base, flags=re.M|re.I)
                for key, value in dict(structure=psf.name, timestep=dt, seed=POLICY['seeds'][start_index],
                    binCoordinates=str(pkg/'output'/f'{checkpoint}.coor'), extendedSystem=str(pkg/'output'/f'{checkpoint}.xsc'),
                    temperature=300, firsttimestep=0, outputEnergies=50, dcdFreq=round(1000/dt),
                    restartfreq=round(25000/dt), xstFreq=round(1000/dt), outputName='npt', dcdFile='npt.dcd',
                    xstFile='npt.xst', stepspercycle=10).items():
                    conf = replace(conf, key, value)
                conf += f'run {round(POLICY["npt_ps"]*1000/dt)}\n'
                npt = run_stage(arm, conf, 'npt', dt, len(atoms), psf, manifest, namd)
                record = dict(job=jid, isomer=manifest['lesions'][0]['stereochemistry'], start=start, dt_fs=dt, npt=npt)
                if npt['passed']:
                    conf = re.sub(r'^(?:run|temperature)\s+.*\n?', '', conf, flags=re.M|re.I)
                    for key, value in dict(binCoordinates='npt.coor', binVelocities='npt.vel', extendedSystem='npt.xsc',
                        langevin='off', langevinPiston='off', outputName='nve', dcdFile='nve.dcd', xstFile='nve.xst').items():
                        conf = replace(conf, key, value)
                    conf += f'run {round(POLICY["nve_ps"]*1000/dt)}\n'
                    record['nve'] = run_stage(arm, conf, 'nve', dt, len(atoms), psf, manifest, namd)
                record['passed'] = npt['passed'] and record.get('nve', {}).get('passed', False)
                assert all(pin(i['path']) == i for i in inputs)
                results.append(record)
                save(root/'results.json', results)
    pairs = []
    for jid in JOBS:
        for start in POLICY['starts']:
            arms = {r['dt_fs']: r for r in results if r['job']==jid and r['start']==start}
            excess = None
            passed = all(r['passed'] for r in arms.values())
            if passed:
                excess = abs(arms[4]['nve']['drift_kcal_mol_ns_atom']) - abs(arms[2]['nve']['drift_kcal_mol_ns_atom'])
                passed &= excess <= POLICY['maximum_paired_abs_drift_excess']
            pairs.append(dict(job=jid, start=start, passed=bool(passed), drift_excess=excess))
    save(root/'verdict.json', dict(passed=all(p['passed'] for p in pairs), pairs=pairs))


if __name__ == '__main__':
    main()
