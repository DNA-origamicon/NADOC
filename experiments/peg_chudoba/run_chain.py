"""Reproducible PEG-only chain dynamics. Run with python -m ...run_chain.

Engine mass 1 is interpreted as 44 g/mol for these PEG-only systems, giving
time_unit=sqrt(44*0.8518**2/24.943387854) ps. This is not a DNA time mapping.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from experiments.peg_chudoba.storage import create_run_directory

from backend.core.oxdna_protocol import OxdnaStageSpec, render_stage_input
from backend.physics.oxdna_peg import PegParameters


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--cutoff',choices=['raw','shifted','zero_tail'],default='raw')
    ap.add_argument('--sampling',choices=['md','mc','pivot','hmc'],default='md')
    ap.add_argument('--hmc-steps',type=int,default=100)
    ap.add_argument('--pivot-prob',type=float,default=None)
    ap.add_argument('--initial-run',type=Path,default=None)
    ap.add_argument('--n',type=int,default=36)
    ap.add_argument('--temperature',type=float,default=294)
    ap.add_argument('--steps',type=int,default=1000000)
    ap.add_argument('--seed',type=int,default=101)
    ap.add_argument('--dt-fs',type=float,default=10)
    ap.add_argument('--backend',choices=['CPU','CUDA'],default='CUDA')
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.sampling in ('mc','pivot'): args.backend="CPU"
    if args.sampling=='hmc':
        args.backend='CUDA'
        if args.hmc_steps<1:ap.error('HMC trajectory length must be positive')
    if args.sampling=='pivot':
        if args.pivot_prob is None:args.pivot_prob=min(.1,3/args.n)
        if args.pivot_prob<=0:ap.error('Pivot probability weight must be positive')
    args.output=create_run_directory(args.output)
    binary=Path.home()/'.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA'
    rng=np.random.default_rng(args.seed)
    xyz=[np.zeros(3)]
    # Extended trans zigzag with small out-of-plane perturbations avoids a
    # singular straight-chain dihedral and provides a reproducible start.
    for i in range(args.n-1):
        vector=np.array([np.cos(np.deg2rad(25)),(-1)**i*np.sin(np.deg2rad(25)),rng.normal(0,.015)])
        xyz.append(xyz[-1]+.33*vector/np.linalg.norm(vector))
    xyz=np.array(xyz)
    box=max(20.,args.n*.33*1.5)/.8518
    xyz=(xyz-xyz.mean(axis=0))/.8518+box/2
    initial_source=None
    replica_id=args.seed;sampling_generation=0
    if args.initial_run:
        source=args.initial_run.resolve()
        prior=json.loads((source/'run.json').read_text())
        replica_id=prior.get('replica_id',prior['seed'])
        sampling_generation=prior.get('sampling_generation',0)+1
        if prior.get('n')!=args.n or prior.get('status') not in ('completed','interrupted') or prior.get('chains',1)!=1:
            ap.error('Initial run must be a finished single chain of the requested length')
        settings={k.strip():v.strip() for line in (source/'input').read_text().splitlines() if '=' in line for k,v in [line.split('=',1)]}
        if settings.get('peg_chudoba')!='true':ap.error('Initial run must use chemical Chudoba PEG')
        conf=source/'last_conf.dat'
        with conf.open() as stream:
            stream.readline();sides=np.array([float(x) for x in stream.readline().split('=')[1].split()])
        if not np.allclose(sides,sides[0]):ap.error('Initial chain box must be cubic')
        box=float(sides[0]);xyz=np.atleast_2d(np.loadtxt(conf,skiprows=3))[:,:3]
        if len(xyz)!=args.n:ap.error('Initial configuration particle count mismatch')
        initial_source=dict(directory=str(source),conf_sha256=hashlib.sha256(conf.read_bytes()).hexdigest(),
            run_sha256=hashlib.sha256((source/'run.json').read_bytes()).hexdigest())
    (args.output/'conf.dat').write_text(f't = 0\nb = {box} {box} {box}\nE = 0 0 0\n'+''.join(
        ' '.join(map(str,p))+' 1 0 0 0 0 1 0 0 0 0 0 1e-6\n' for p in xyz))
    (args.output/'topology.top').write_text(f'{args.n} 1\n'+''.join(
        f'1 500 {i+1 if i+1<args.n else -1} {i-1}\n' for i in range(args.n)))
    unit_ps=np.sqrt(44*.8518**2/24.943387854)
    interval=max(1,args.steps//2000)
    stage=OxdnaStageSpec('chain','production','MD',args.steps,args.backend,
        dt=args.dt_fs/1000/unit_ps,thermostat='langevin',interaction='DNA2PEG',
        peg_parameters=PegParameters().engine_parameters(),seed=args.seed)
    inp=render_stage_input(stage,'topology.top','conf.dat')
    lines=[x for x in inp.splitlines() if not x.startswith(('T =','print_conf_interval =','print_energy_every ='))]
    inp='\n'.join(lines)+f'\nT = {args.temperature}K\npeg_chudoba = true\npeg_chudoba_pure = true\nT_force_value = true\ngamma_trans = {unit_ps}\nprint_conf_interval = {interval}\nprint_energy_every = {interval}\n'
    if args.sampling=='mc':
        inp=inp.replace('sim_type = MD','sim_type = MC')
        inp+='\nensemble = nvt\ndelta_translation = 0.04\ndelta_rotation = 0.1\ncheck_energy_every = 1\n'
    if args.sampling=='hmc':
        inp=inp.replace('sim_type = MD','sim_type = PEG_HMC')
        inp+=f'\npeg_hmc_steps = {args.hmc_steps}\n'
    if args.sampling=='pivot':
        inp=inp.replace('sim_type = MD','sim_type = MC2')
        inp+="""
move_1 = {
 type = translation
 delta = 0.04
 prob = 1
}
move_2 = {
 type = pivot
 delta = 1.0
prob = PIVOT_WEIGHT
}
""".replace('PIVOT_WEIGHT',str(args.pivot_prob))
    inp+=f'\npeg_chudoba_shift = {str(args.cutoff=="shifted").lower()}\n'
    inp+=f'peg_chudoba_zero_tail = {str(args.cutoff=="zero_tail").lower()}\n'
    (args.output/'input').write_text(inp)
    manifest=vars(args).copy();manifest['output']=str(args.output.resolve())
    manifest['initial_run']=str(args.initial_run.resolve()) if args.initial_run else None
    manifest['initial_source']=initial_source
    manifest.update(replica_id=replica_id,sampling_generation=sampling_generation)
    library=binary.parent.parent/'src/liboxdna_common.so'
    manifest.update(shared_library=str(library),shared_library_sha256=hashlib.sha256(library.read_bytes()).hexdigest(),time_unit_ps=unit_ps,physical_duration_ns=args.steps*args.dt_fs/1e6 if args.sampling=="md" else None,
        binary=str(binary),binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        status='running',started_unix=time.time())
    (args.output/'run.json').write_text(json.dumps(manifest,indent=2)+'\n')
    with (args.output/'engine.log').open('w') as log:
        run=subprocess.run([str(binary),'input'],cwd=args.output,stdout=log,stderr=subprocess.STDOUT)
    final_conf=args.output/'last_conf.dat'
    completed_steps=int(final_conf.open().readline().split('=')[1]) if final_conf.exists() else 0
    status='failed' if run.returncode else ('completed' if completed_steps>=args.steps else 'interrupted')
    manifest.update(returncode=run.returncode,elapsed_seconds=time.time()-manifest['started_unix'],
        status=status,completed_steps=completed_steps)
    (args.output/'run.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(manifest,indent=2))
    raise SystemExit(run.returncode)


if __name__=='__main__':
    main()
