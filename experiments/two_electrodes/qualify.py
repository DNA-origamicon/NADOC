"""Guarded, isolated EW3DC native qualification. Never registers a managed job.

Run from repository root, after a user opens just test-session:
 scripts/test_guard.sh two-electrode-qualification 0 1 -- uv run python -m experiments.two_electrodes.qualify --output /path/to/new/directory
"""
import argparse
import json
import re
import struct
import subprocess
import time
from pathlib import Path

import numpy as np

from backend.core.md_charge import parse_psf_atoms
from backend.core.namd_runner import find_namd
from backend.core.namd_slab import slab_energy_forces, render_slab_tcl
from backend.core.namd_two_electrode_package import build_qualification_package, qualification_config


def read_force(path, n):
    data = Path(path).read_bytes()
    if len(data) != 4+24*n or struct.unpack('<i',data[:4])[0] != n:
        raise ValueError('Unexpected NAMD binary force format')
    force = np.frombuffer(data[4:],dtype='<f8').reshape(n,3)
    if not np.isfinite(force).all():
        raise ValueError('Nonfinite native forces')
    return force


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--namd',default=None)
    parser.add_argument('--existing',action='store_true',help='Validate an existing isolated qualification package')
    parser.add_argument('--devices',default='0')
    parser.add_argument('--gap-nm',type=float,default=10.)
    parser.add_argument('--width-nm',type=float,default=4.)
    parser.add_argument('--depth-nm',type=float,default=4.)
    parser.add_argument('--salt-mM',type=float,default=300.)
    parser.add_argument('--steps',type=int,default=200)
    args = parser.parse_args()
    marker = Path('.nadoc-test-session')
    if not marker.exists() or int(marker.read_text().splitlines()[0]) <= time.time():
        parser.error('Native qualification requires a user-opened just test-session; invoke through scripts/test_guard.sh.')
    if args.steps < 20 or args.steps % 20:
        parser.error('Steps must be a positive multiple of 20, at least 20')
    spec = dict(normal='z',gap_nm=args.gap_nm,width_nm=args.width_nm,depth_nm=args.depth_nm,working_charge_C_m2=-.0413)
    package = args.output.resolve()
    manifest = json.loads((package/'manifest.json').read_text()) if args.existing else build_qualification_package(package,spec,salt_mM=args.salt_mM)
    if manifest.get('schema') != 'nadoc.two_electrode_qualification.v1':
        parser.error('Not an isolated two-electrode qualification package')
    axis=manifest['normal_axis']
    binary = args.namd or find_namd()
    report = {'binary':str(binary),'manifest':manifest,'runs':{},'checks':{},'qualified':False}
    path = package/'qualification.json'
    def save():
        path.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    save()
    def run(name,conf):
        (package/f'{name}.conf').write_text(conf)
        begin=time.monotonic()
        timed_out=False
        with (package/f'{name}.log').open('w') as log:
            try:
                result=subprocess.run([str(binary),'+p2','+setcpuaffinity','+devices',args.devices,f'{name}.conf'],cwd=package,stdout=log,stderr=subprocess.STDOUT,timeout=600)
                exit_code=result.returncode
            except subprocess.TimeoutExpired:
                timed_out=True;exit_code=None
        text=(package/f'{name}.log').read_text(errors='replace')
        fatal=bool(re.search(r'FATAL ERROR|ERROR:|nan\b',text,re.I))
        record=dict(exit_code=exit_code,timed_out=timed_out,seconds=time.monotonic()-begin,passed=exit_code==0 and not fatal)
        titles = re.findall(r'^ETITLE:\s*(.*)$',text,re.M)
        energies = re.findall(r'^ENERGY:\s*(.*)$',text,re.M)
        if titles and energies:
            try:
                energy=dict(zip(titles[-1].split(), map(float,energies[-1].split())))
                if all(np.isfinite(v) for v in energy.values()):record['energy']=energy
                else:record['passed']=False
            except ValueError:
                record['passed']=False
        if not record['passed']:
            record['tail']=text[-4000:]
        report['runs'][name]=record;save()
        return record['passed']
    try:
        atoms=parse_psf_atoms((package/'system.psf').read_text())
        charges=[a.charge for a in atoms]
        positions=[[float(row[i:i+8]) for i in (30,38,46)] for row in (package/'system.pdb').read_text().splitlines() if row.startswith(('ATOM  ','HETATM'))]
        base=qualification_config(manifest,prefix='offload')
        # Uncorrected probe has exactly the same coordinates and confinement; no dynamics.
        script=(package/'slab.tcl').read_text()
        (package/'uncorrected.tcl').write_text(re.sub(r'^set slab_coefficient .*$', 'set slab_coefficient 0.0',script,flags=re.M))
        results={}
        for name,conf in [('offload',base),('uncorrected',base.replace('slab.tcl','uncorrected.tcl').replace('output/offload','output/uncorrected')),
                          ('resident',qualification_config(manifest,resident=True,prefix='resident'))]:
            if run(name,conf):results[name]=read_force(package/'output'/f'{name}.force',len(atoms))
        expected_energy, expected_forces=slab_energy_forces(positions,charges,[10*v for v in manifest['cell_nm']],axis)
        expected=np.array(expected_forces)
        if {'offload','uncorrected'} <= results.keys():
            error=float(np.max(np.abs(results['offload']-results['uncorrected']-expected)))
            report['checks']['native_correction_force']={'max_error_kcal_mol_A':error,'passed':error<1e-3}
        if all('MISC' in report['runs'].get(k,{}).get('energy',{}) for k in ('offload','uncorrected')):
            delta=report['runs']['offload']['energy']['MISC']-report['runs']['uncorrected']['energy']['MISC']
            error=abs(delta-expected_energy)
            report['checks']['native_correction_energy']={'absolute_error_kcal_mol':error,'passed':error<1e-3}
        if {'offload','resident'} <= results.keys():
            error=float(np.sqrt(np.mean((results['offload']-results['resident'])**2)))
            report['checks']['resident_force_agreement']={'rms_error_kcal_mol_A':error,'passed':error<1e-3}
        # Vacuum-size control: identical physical coordinates and charges, increasing cell normal.
        previous=results.get('offload')
        for factor in (4.,5.):
            variant={**manifest,'cell_nm':list(manifest['cell_nm'])}
            variant['cell_nm'][axis]=manifest['spec']['gap_nm']*factor
            name=f'vacuum_{int(factor)}'
            (package/f'{name}.tcl').write_text(render_slab_tcl(charges,[10*v for v in variant['cell_nm']],axis,
                mobile_ids=range(2*manifest['sites_per_electrode']+1,len(atoms)+1),bounds=tuple(manifest['normal_bounds_A'])))
            conf=qualification_config(variant,prefix=name).replace('slab.tcl',f'{name}.tcl')
            if run(name,conf):
                current=read_force(package/'output'/f'{name}.force',len(atoms))
                if previous is not None:
                    error=float(np.sqrt(np.mean((current-previous)**2)))
                    report['checks'][name]={'rms_force_change_kcal_mol_A':error,'passed':error<1e-3}
                previous=current
        # Both modes start from the same input and independently minimize. This is stability,
        # not a bitwise trajectory comparison. No production validity follows from 200 steps.
        for resident in (False,True):
            name='resident_dynamics' if resident else 'offload_dynamics'
            run(name,qualification_config(manifest,resident=resident,steps=args.steps,minimize=100,prefix=name))
        required={'native_correction_energy','native_correction_force','resident_force_agreement','vacuum_4','vacuum_5'}
        report['qualified']=required<=report['checks'].keys() and all(v['passed'] for v in report['checks'].values()) and all(v['passed'] for v in report['runs'].values())
        report['scope']='Bare-wall force, vacuum-size and short 2 fs execution qualification only; no Debye convergence, 4 fs, gold, PEG, DNA or managed-job qualification.'
    except Exception as error:
        report['error']=f'{type(error).__name__}: {error}'
    finally:
        save()
    print(path)
    if not report['qualified']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
