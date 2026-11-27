"""Time COM umbrellas on a completed native job, preserving its model and forces.

This supplements pure-DNA size tests; a hybrid job is not a controlled N-only test.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import numpy as np
from tools.oxdna_umbrella.native import restraint,execute,digest,scratch_root


def benchmark(job_dir,stage_name,binary,report):
    job_dir,binary,report=map(lambda p:Path(p).resolve(),(job_dir,binary,report))
    stage=job_dir/stage_name
    original=(stage/'input.txt').read_text()
    # Do not silently ignore unsupported parameter dependencies.
    parameters=dict(line.split('=',1) for line in original.splitlines() if '=' in line and not line.lstrip().startswith('#'))
    parameters={k.strip():v.strip() for k,v in parameters.items()}
    if parameters.get('sim_type')!='MD':raise ValueError('Expected an existing MD job.')
    topology=(job_dir/'topology.top').read_text().splitlines()
    dna=[i for i,row in enumerate(topology[1:]) if int(row.split()[0])>0]
    a,b=dna[:8],dna[-8:]
    if len(a)!=8 or set(a)&set(b):raise ValueError('Need two disjoint DNA groups.')
    rows=[]
    with tempfile.TemporaryDirectory(prefix='nadoc-umbrella-job-scale-',dir=scratch_root()) as tmp:
        tmp=Path(tmp)
        if shutil.disk_usage(tmp).free<250_000_000:raise ValueError('Need 250 MB free.')
        files={}
        for name,source in [('topology.top',job_dir/'topology.top'),('conf.dat',stage/'last_conf.dat'),('base_forces.txt',Path(parameters['external_forces_file']))]:
            shutil.copy2(source,tmp/name);files[name]={'source':str(source),'sha256':digest(source)}
        if 'parfile' in parameters:
            source=Path(parameters['parfile']);shutil.copy2(source,tmp/'anm.par');files['anm.par']={'source':str(source),'sha256':digest(source)};parameters['parfile']=str(tmp/'anm.par')
        if 'seq_dep_file' in parameters:
            source=Path(parameters['seq_dep_file']);shutil.copy2(source,tmp/'sequence.txt');files['sequence.txt']={'source':str(source),'sha256':digest(source)};parameters['seq_dep_file']=str(tmp/'sequence.txt')
        conf=np.loadtxt(tmp/'conf.dat',skiprows=3);box=np.array(list(map(float,(tmp/'conf.dat').read_text().splitlines()[1].split('=')[1].split())))
        delta=conf[b,:3].mean(0)-conf[a,:3].mean(0);delta-=box*np.rint(delta/box)
        force=(tmp/'base_forces.txt').read_text()+'\n'+restraint(a,b,np.linalg.norm(delta),1.,float(np.ceil(np.linalg.norm(box)/2+1)))
        for backend in ['CPU','CUDA']:
            for repeat in range(2):
                steps=200 if backend=='CPU' else 2000
                cfg={**parameters,'backend':backend,'backend_precision':'double' if backend=='CPU' else 'mixed','steps':str(steps),'seed':'92741','topology':str(tmp/'topology.top'),'conf_file':str(tmp/'conf.dat'),'external_forces_file':'forces.txt','trajectory_file':'trajectory.dat','lastconf_file':'last_conf.dat','energy_file':'energy.dat','print_conf_interval':str(steps),'print_energy_every':str(steps),'no_stdout_energy':'true','CUDA_sort_every':'0'}
                text='\n'.join(f'{k} = {v}' for k,v in cfg.items())+'\n'
                text+=f'''data_output_1 = {{
name = samples.dat
print_every = {steps}
col_1 = {{ type = step }}
col_2 = {{
type = distance
particle_1 = {','.join(map(str,a))}
particle_2 = {','.join(map(str,b))}
PBC = true
}}
}}
'''
                directory=tmp/f'{backend}_{repeat}';execution=execute(binary,directory,text,force)
                log=(directory/'native.log').read_text();seconds=float(re.search(r'Total Running Time: ([\d.e+-]+) s',log)[1])
                row={'backend':backend,'repeat':repeat,'steps':steps,'native_seconds':seconds,'native_steps_per_second':steps/seconds,'wall_seconds':execution['wall_seconds']};rows.append(row)
                result={'particles':len(conf),'dna_nucleotides':len(dna),'interaction':parameters['interaction_type'],'temperature':parameters['T'],'salt':parameters.get('salt_concentration'),'sources':files,'rows':rows,'qualification':'Existing hybrid/surface job; all original model parameters and external forces retained, plus one 8+8 DNA COM umbrella. Not a matched pure-DNA scaling or melting convergence test.'}
                report.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(row),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['job-dir','stage','binary','report']:parser.add_argument('--'+name,required=True)
    args=vars(parser.parse_args());benchmark(args['job_dir'],args['stage'],args['binary'],args['report'])
