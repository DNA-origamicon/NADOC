"""Experimental fixed-window CPU/CUDA umbrella campaign from an existing duplex export.

python -m tools.oxdna_umbrella.run --help
Preserves source inputs and refuses to overwrite an existing campaign.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
from dataclasses import dataclass,asdict
import json
import os
import signal
from pathlib import Path
import shutil
import time
import numpy as np
from backend.core.oxdna_vmmc import duplex_pairs
from tools.oxdna_umbrella.native import input_text,restraint,execute,digest,cancel_active
from tools.oxdna_umbrella.analysis import summarize


@dataclass(frozen=True)
class Protocol:
    windows:int=12
    equil_steps:int=100000
    production_steps:int=500000
    temperature_c:float=70.
    salt:float=.3
    stiffness:float=1.
    workers:int=4
    seed:int=782101
    backend:str='CUDA'
    dt:float=.005
    output_every:int=1000
    bootstrap:int=40

    def __post_init__(self):
        if not all(np.isfinite(v) for v in (self.temperature_c,self.salt,self.stiffness,self.dt)):
            raise ValueError('Protocol values must be finite.')
        if not (0<self.temperature_c<=150 and self.salt>0 and self.stiffness>0 and 0<self.dt<=.005):
            raise ValueError('Invalid thermodynamic, restraint or integration settings.')
        if self.output_every<1 or self.bootstrap<2:raise ValueError('Need positive output cadence and at least two bootstrap replicates.')


def campaign(job_dir,conf,binary,output,protocol,initial_campaign=None):
    job_dir,conf,binary,output=map(lambda p:Path(p).resolve(),(job_dir,conf,binary,output))
    if output.exists():raise ValueError('Campaign already exists; refusing to overwrite or mix attempts.')
    if protocol.windows<3 or protocol.workers<1 or protocol.backend not in {'CPU','CUDA'}:raise ValueError('Invalid campaign configuration.')
    if protocol.equil_steps<1 or protocol.production_steps<20*protocol.output_every:raise ValueError('Production needs at least 20 samples per window.')
    pairs=duplex_pairs(job_dir/'topology.top')
    if list(job_dir.glob('*cpd*')):raise ValueError('This prototype does not yet propagate CPD interactions; refusing to omit them.')
    if protocol.backend=='CUDA':
        marker=binary.parent.parent/'gpu-umbrella-build.json'
        receipt=json.loads(marker.read_text())
        if receipt['library_sha256']!=digest(binary.parent.parent/'lib/liboxdna_common.so'):
            raise ValueError('GPU periodic-restraint engine receipt does not match its library.')
    header=conf.read_text().splitlines()[:3];box=np.array(list(map(float,header[1].split('=')[1].split())))
    if not np.allclose(box,box[0]):raise ValueError('Initial validation is restricted to cubic boxes.')
    grid_max=float(np.ceil(np.linalg.norm(box)/2+.01))
    centers=np.linspace(.3,np.linalg.norm(box)/2-.15,protocol.windows)
    if shutil.disk_usage(output.parent).free<250_000_000:raise ValueError('At least 250 MB free required for campaign.')
    output.mkdir();inputs=output/'inputs';inputs.mkdir()
    files={}
    for name in ['topology.top','oxDNA2_sequence_dependent_parameters.txt','vmmc_op.txt']:
        shutil.copy2(job_dir/name,inputs/name);files[name]={'source':str(job_dir/name),'sha256':digest(inputs/name)}
    shutil.copy2(conf,inputs/'conf.dat');files['conf.dat']={'source':str(conf),'sha256':digest(conf)}
    manifest={'protocol':asdict(protocol),'centers':centers.tolist(),'grid_max':grid_max,'files':files,
              'accelerator_environment':{k:os.environ[k] for k in ('CUDA_MPS_PIPE_DIRECTORY','CUDA_VISIBLE_DEVICES') if k in os.environ},
              'binary':str(binary),'library_sha256':digest(binary.parent.parent/'lib/liboxdna_common.so'),
              'coordinate':'minimum-image distance between entire strand centers of mass',
              'bias':'single piecewise-linear pair potential, not doubled external energy',
              'scope':'Experimental fixed-temperature duplex association; no automatic Tm or CPD certification.'}
    if initial_campaign is not None:
        previous=Path(initial_campaign).resolve()
        previous_manifest=json.loads((previous/'manifest.json').read_text())
        if previous_manifest['centers']!=centers.tolist() or previous_manifest['files']['topology.top']['sha256']!=files['topology.top']['sha256']:
            raise ValueError('Continuation must retain topology and umbrella centers.')
        for key in ('temperature_c','salt','stiffness','dt'):
            if previous_manifest['protocol'][key]!=asdict(protocol)[key]:raise ValueError('Continuation must retain physical/bias/integration parameters.')
        if previous_manifest['files']['conf.dat']['sha256']!=files['conf.dat']['sha256']:
            raise ValueError('Continuation must reference the same original initial condition and box.')
        manifest['initial_campaign']=str(previous)
        manifest['window_initial_conditions']=[]
        for i in range(protocol.windows):
            source=previous/f'window_{i:03d}/sample/last_conf.dat'
            target=inputs/f'window_{i:03d}.dat';shutil.copy2(source,target)
            manifest['window_initial_conditions'].append({'source':str(source),'sha256':digest(target)})
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    group_a=[a for a,_ in pairs];group_b=[b for _,b in pairs]
    start=time.monotonic()
    def window(i):
        directory=output/f'window_{i:03d}';directory.mkdir()
        force=restraint(group_a,group_b,centers[i],protocol.stiffness,grid_max)
        reports=[];checkpoint=inputs/f'window_{i:03d}.dat' if initial_campaign is not None else inputs/'conf.dat'
        for role,steps in [('equil',protocol.equil_steps),('sample',protocol.production_steps)]:
            run=directory/role
            text=input_text(inputs,checkpoint,protocol.backend,steps,protocol.seed+2*i+(role=='sample'),protocol.temperature_c,protocol.salt,group_a,group_b,dt=protocol.dt,output_every=protocol.output_every,trajectory_every=max(protocol.output_every,steps//100))
            reports.append(execute(binary,run,text,force));checkpoint=run/'last_conf.dat'
        data=np.loadtxt(directory/'sample/samples.dat',ndmin=2)
        data=data[data[:,0]>0]
        if int(data[-1,0])!=protocol.production_steps:raise ValueError('Incomplete production window.')
        if data[:,1].max()>=grid_max:raise ValueError('Window left bias grid.')
        return i,data,reports
    samples=[None]*protocol.windows;reports=[None]*protocol.windows
    with ThreadPoolExecutor(max_workers=protocol.workers) as pool:
        futures=[pool.submit(window,i) for i in range(protocol.windows)]
        for future in as_completed(futures):
            try:i,data,report=future.result()
            except BaseException:
                cancel_active()
                raise
            samples[i]=data;reports[i]=report
            print(json.dumps({'event':'window_done','window':i,'q_range':[int(data[:,2].min()),int(data[:,2].max())],'seconds':sum(x['wall_seconds'] for x in report)}),flush=True)
    wall=time.monotonic()-start
    result=summarize(samples,centers,protocol.stiffness,protocol.temperature_c,grid_max,bootstrap=protocol.bootstrap)
    result.update(campaign_wall_seconds=wall,aggregate_md_steps_per_second=protocol.windows*(protocol.equil_steps+protocol.production_steps)/wall,execution=reports)
    (output/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'event':'campaign_done','seconds':wall,'p_bound_box':result['p_bound_box'],'status':result['status']}),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ['job-dir','conf','binary','output']:parser.add_argument('--'+key,required=True)
    parser.add_argument('--initial-campaign')
    defaults=Protocol()
    for key,value in asdict(defaults).items():parser.add_argument('--'+key.replace('_','-'),type=type(value),default=value)
    args=vars(parser.parse_args());protocol=Protocol(**{key:args.pop(key) for key in asdict(defaults)})
    signal.signal(signal.SIGTERM,lambda *_:cancel_active())
    signal.signal(signal.SIGINT,lambda *_:cancel_active())
    campaign(args['job_dir'],args['conf'],args['binary'],args['output'],protocol,args['initial_campaign'])
