"""Build and run NVT dynamics or NPT Monte Carlo for PEG EOS reproduction."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from experiments.peg_chudoba.storage import create_run_directory

from backend.core.oxdna_protocol import OxdnaStageSpec,render_stage_input
from backend.physics.oxdna_peg import PegParameters
from experiments.peg_chudoba.solution import initial_solution,REPEAT_MASS


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--sampling',choices=['md','npt','hmc'],default='md')
    ap.add_argument('--hmc-steps',type=int,default=100)
    ap.add_argument('--hmc-volume-attempts',type=int,default=1)
    ap.add_argument('--initial-run',type=Path,default=None)
    ap.add_argument('--list-type',choices=['cells','verlet'],default=None)
    ap.add_argument('--pivot-prob',type=float,default=None)
    ap.add_argument('--volume-delta',type=float,default=.04)
    ap.add_argument('--cutoff',choices=['raw','shifted','zero_tail'],default='raw')
    ap.add_argument('--pressure-kpa',type=float,default=10)
    ap.add_argument('--n' ,type=int,default=135)
    ap.add_argument('--chains',type=int,default=108)
    ap.add_argument('--concentration',type=float,default=20)
    ap.add_argument('--temperature',type=float,default=294)
    ap.add_argument('--steps',type=int,default=100000)
    ap.add_argument('--dt-fs',type=float,default=2)
    ap.add_argument('--seed',type=int,default=301)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();args.output=create_run_directory(args.output)
    if args.list_type is None:
        args.list_type='cells' if args.sampling=='npt' else 'verlet'
    if args.sampling in ('md','hmc') and args.list_type!='verlet':
        ap.error('CUDA dynamics requires the Verlet list')
    if args.pivot_prob is None:args.pivot_prob=min(.01,1.5/args.n)
    if args.pivot_prob<=0 or args.volume_delta<=0:
        ap.error('Move weights and volume delta must be positive')
    initial_source=None
    replica_id=args.seed;sampling_generation=0
    if args.initial_run:
        source=args.initial_run.resolve()
        prior=json.loads((source/'run.json').read_text())
        replica_id=prior.get('replica_id',prior['seed'])
        sampling_generation=prior.get('sampling_generation',0)+1
        if prior.get('n')!=args.n or prior.get('chains')!=args.chains or prior.get('status') not in ('completed','interrupted'):
            ap.error('Initial run must be a finished solution with matching chain counts and lengths')
        settings={k.strip():v.strip() for line in (source/'input').read_text().splitlines() if '=' in line for k,v in [line.split('=',1)]}
        if settings.get('peg_chudoba')!='true':ap.error('Initial run must use chemical Chudoba PEG')
        conf=source/'last_conf.dat'
        with conf.open() as stream:
            stream.readline();sides=np.array([float(x) for x in stream.readline().split('=')[1].split()])*.8518
        if not np.allclose(sides,sides[0]):ap.error('Initial solution box must be cubic')
        box=float(sides[0]);xyz=np.atleast_2d(np.loadtxt(conf,skiprows=3))[:,:3]*.8518
        if len(xyz)!=args.n*args.chains:ap.error('Initial configuration particle count mismatch')
        initial_source=dict(directory=str(source),conf_sha256=hashlib.sha256(conf.read_bytes()).hexdigest(),
                            run_sha256=hashlib.sha256((source/'run.json').read_bytes()).hexdigest())
        args.concentration=len(xyz)*REPEAT_MASS/(.602214076*box**3)
    else:
        xyz,box=initial_solution(args.n,args.chains,args.concentration,args.seed)
    count=len(xyz)
    (args.output/'conf.dat').write_text(f't = 0\nb = {box/.8518} {box/.8518} {box/.8518}\nE = 0 0 0\n'+''.join(
        ' '.join(map(str,p/.8518))+' 1 0 0 0 0 1 0 0 0 0 0 1e-6\n' for p in xyz))
    (args.output/'topology.top').write_text(f'{count} {args.chains}\n'+''.join(
        f'{i//args.n+1} 500 {i+1 if (i+1)%args.n else -1} {i-1 if i%args.n else -1}\n' for i in range(count)))
    time_unit=np.sqrt(44*.8518**2/24.943387854)
    stage=OxdnaStageSpec('solution','production','MD',args.steps,'CUDA' if args.sampling in ('md','hmc') else 'CPU',dt=args.dt_fs/1000/time_unit,
        thermostat='langevin',interaction='DNA2PEG',peg_parameters=PegParameters().engine_parameters(),seed=args.seed)
    inp=render_stage_input(stage,'topology.top','conf.dat')
    inp='\n'.join(line for line in inp.splitlines() if not line.startswith('list_type ='))
    inp+=f'\nlist_type = {args.list_type}\n'
    inp='\n'.join(line for line in inp.splitlines() if not line.startswith(('T =','print_conf_interval =','print_energy_every =')))
    interval=max(1,args.steps//1000)
    inp+=f'\nT = {args.temperature}K\nT_force_value = true\npeg_chudoba = true\npeg_chudoba_pure = true\ngamma_trans = {time_unit}\n'
    inp+=f'print_conf_interval = {max(1,args.steps//40)}\nprint_energy_every = {max(1,args.steps//100)}\nCUDA_update_stress_tensor_every = {interval}\n'
    inp+='''data_output_1 = {
 name = thermo.dat
 print_every = '''+str(interval)+'''
 col_1 = {
 type = step
 }
 col_2 = {
 type = pressure
 }
 col_3 = {
 type = density
 }
}
'''
    inp+=f"""data_output_2 = {{
 name = shape.dat
 print_every = {interval}
 col_1 = {{
 type = step
 }}
 col_2 = {{
 type = peg_chain_shape
 }}
}}
"""
    inp+=f'\npeg_chudoba_shift = {str(args.cutoff=="shifted").lower()}\n'
    inp+=f'peg_chudoba_zero_tail = {str(args.cutoff=="zero_tail").lower()}\n'
    if args.sampling in ('npt','hmc'):
        pressure_unit=24.943387854/.8518**3*1e27/6.02214076e23
        sim_type='MC2' if args.sampling=='npt' else 'PEG_HMC'
        inp=inp.replace('sim_type = MD',f'sim_type = {sim_type}').replace('type = pressure','type = density')
        inp+=f'\nP = {args.pressure_kpa/pressure_unit}\n'
    if args.sampling=='hmc':
        if args.hmc_steps<1 or args.hmc_volume_attempts<1:
            ap.error('Solution HMC requires positive trajectory length and volume attempt count')
        inp+=f'\npeg_hmc_steps = {args.hmc_steps}\npeg_hmc_volume_attempts = {args.hmc_volume_attempts}\npeg_hmc_volume_delta = {args.volume_delta}\n'
    if args.sampling=='npt':
        inp+="""move_1 = {
 type = translation
 delta = 0.04
 prob = 1
}
move_2 = {
 type = pivot
 delta = 1
prob = PIVOT_WEIGHT
}
move_3 = {
 type = molecule_volume
delta = VOLUME_DELTA
 prob = """+str(5/count)+"""
}
"""
        inp=inp.replace('PIVOT_WEIGHT',str(args.pivot_prob)).replace('VOLUME_DELTA',str(args.volume_delta))
    (args.output/'input').write_text(inp)
    binary=Path.home()/'.local/share/nadoc/engines/oxdna-chudoba/build/bin/oxDNA'
    library=binary.parent.parent/'src/liboxdna_common.so'
    meta=vars(args).copy();meta['output']=str(args.output.resolve())
    meta['initial_run']=str(args.initial_run.resolve()) if args.initial_run else None
    meta['initial_source']=initial_source
    meta.update(replica_id=replica_id,sampling_generation=sampling_generation)
    meta.update(box_nm=box,particles=count,status='running',started_unix=time.time(),
        physical_duration_ns=args.steps*args.dt_fs/1e6 if args.sampling=="md" else None,binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        shared_library_sha256=hashlib.sha256(library.read_bytes()).hexdigest(),
        purpose='Solution sampling allocation; equilibrium and convergence must be assessed separately')
    (args.output/'run.json').write_text(json.dumps(meta,indent=2)+'\n')
    with (args.output/'engine.log').open('w') as log:
        run=subprocess.run([str(binary),'input'],cwd=args.output,stdout=log,stderr=subprocess.STDOUT)
    final_conf=args.output/'last_conf.dat'
    completed_steps=int(final_conf.open().readline().split('=')[1]) if final_conf.exists() else 0
    status='failed' if run.returncode else ('completed' if completed_steps>=args.steps else 'interrupted')
    meta.update(returncode=run.returncode,status=status,completed_steps=completed_steps,elapsed_seconds=time.time()-meta['started_unix'])
    (args.output/'run.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(json.dumps(meta,indent=2));raise SystemExit(run.returncode)


if __name__=='__main__':main()
