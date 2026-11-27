"""Compare one-step CPU/GPU trajectories on an unchanged existing duplex frame.

Use a frame spanning a minimum-image boundary to exercise the repaired CUDA path.
No synthetic coordinates or molecular structures are created.
"""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
import numpy as np
from backend.core.oxdna_vmmc import duplex_pairs
from tools.oxdna_umbrella.native import input_text,restraint,execute,digest,scratch_root


def validate(job_dir,conf,binary,report,old_binary=None):
    job_dir,conf,binary,report=map(lambda p:Path(p).resolve(),(job_dir,conf,binary,report))
    pairs=duplex_pairs(job_dir/'topology.top');a=[p[0] for p in pairs];b=[p[1] for p in pairs]
    box=np.array(list(map(float,conf.read_text().splitlines()[1].split('=')[1].split())))
    grid_max=float(np.ceil(np.linalg.norm(box)/2+.01));velocities={}
    with tempfile.TemporaryDirectory(prefix='nadoc-umbrella-force-',dir=scratch_root()) as tmp:
        tmp=Path(tmp)
        for name in ['topology.top','oxDNA2_sequence_dependent_parameters.txt','vmmc_op.txt']:shutil.copy2(job_dir/name,tmp/name)
        shutil.copy2(conf,tmp/'conf.dat')
        cases=[('cpu',binary,'CPU'),('gpu',binary,'CUDA')]
        if old_binary:cases.append(('old_gpu',Path(old_binary).resolve(),'CUDA'))
        for name,engine,backend in cases:
            text=input_text(tmp,tmp/'conf.dat',backend,1,192,70,.3,a,b,dt=.001,output_every=1,trajectory_every=1,thermostat='no',refresh_vel=False)
            execute(engine,tmp/name,text,restraint(a,b,2.,1.,grid_max))
            velocities[name]=np.loadtxt(tmp/name/'last_conf.dat',skiprows=3)[:,9:12]
        errors={name:float(np.max(np.abs(value-velocities['cpu']))) for name,value in velocities.items() if name!='cpu'}
    result={'source':str(conf),'source_sha256':digest(conf),'max_absolute_velocity_error':errors,'tolerance':1e-5}
    report.write_text(json.dumps(result,indent=2)+'\n')
    if errors['gpu']>result['tolerance']:raise ValueError('CPU/CUDA restraint force parity failed.')
    print(json.dumps(result),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['job-dir','conf','binary','report']:parser.add_argument('--'+name,required=True)
    parser.add_argument('--old-binary')
    args=vars(parser.parse_args());validate(args['job_dir'],args['conf'],args['binary'],args['report'],args['old_binary'])
