"""Bounded CPU/CUDA umbrella throughput benchmark of existing native examples.

Molecular files are copied unchanged. This measures speed, not melting convergence.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import tempfile
import numpy as np
from tools.oxdna_umbrella.native import input_text,restraint,execute,digest,scratch_root


def benchmark(source,binary,duplex_inputs,report):
    source,binary,duplex_inputs,report=map(lambda p:Path(p).resolve(),(source,binary,duplex_inputs,report))
    examples=source/'examples'
    cases=[('duplex',duplex_inputs/'topology.top',duplex_inputs/'conf.dat'),
           ('ssDNA100',examples/'TRAPS/ssdna100.top',examples/'TRAPS/ssdna100.dat'),
           ('duplex404',examples/'PERSISTENCE_LENGTH/init.top',examples/'PERSISTENCE_LENGTH/init.conf'),
           ('junction504',examples/'BOILERPLATE_Jupyter/75deg.top',examples/'BOILERPLATE_Jupyter/75deg.dat')]
    results=[]
    with tempfile.TemporaryDirectory(prefix='nadoc-umbrella-scaling-',dir=scratch_root()) as temporary:
        scratch=Path(temporary)
        if shutil.disk_usage(scratch).free<200_000_000:raise ValueError('Need 200 MB free scratch.')
        for name,top,conf in cases:
            if not top.is_file() or not conf.is_file():raise ValueError(f'Missing unchanged source: {conf}')
            inputs=scratch/name;inputs.mkdir()
            for src,dest in [(top,'topology.top'),(conf,'conf.dat'),(duplex_inputs/'oxDNA2_sequence_dependent_parameters.txt','oxDNA2_sequence_dependent_parameters.txt')]:shutil.copy2(src,inputs/dest)
            positions=np.loadtxt(conf,skiprows=3)[:,:3];n=len(positions)
            box=np.array(list(map(float,conf.read_text().splitlines()[1].split('=')[1].split())))
            group_a=list(range(8));group_b=list(range(n-8,n))
            delta=positions[group_b].mean(0)-positions[group_a].mean(0);delta-=box*np.rint(delta/box)
            center=np.linalg.norm(delta);grid_max=float(np.ceil(np.linalg.norm(box)/2+1))
            force=restraint(group_a,group_b,center,1.,grid_max)
            checkpoint=inputs/'conf.dat'
            for backend in ['CPU','CUDA']:
                for repeat in range(2):
                    steps=20000 if n<1000 else (1000 if backend=='CPU' else 10000)
                    directory=inputs/f'{backend}_{repeat}'
                    text=input_text(inputs,checkpoint,backend,steps,1927,70,.3,group_a,group_b,output_every=steps,trajectory_every=steps,op=False)
                    execution=execute(binary,directory,text,force)
                    log=(directory/'native.log').read_text()
                    native=float(re.search(r'Total Running Time: ([\d.e+-]+) s',log)[1])
                    row={'case':name,'nucleotides':n,'backend':backend,'repeat':repeat,'steps':steps,'native_seconds':native,'native_steps_per_second':steps/native,'wall_seconds':execution['wall_seconds'],
                         'topology_source':str(top),'topology_sha256':digest(top),'configuration_source':str(conf),'configuration_sha256':digest(conf)}
                    results.append(row);report.write_text(json.dumps({'qualification':'Throughput only. Different existing geometries; fixed 8+8 particle COM restraint. Not a convergence/scientific scaling comparison.','rows':results},indent=2)+'\n')
                    print(json.dumps(row),flush=True)
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['source','binary','duplex-inputs','report']:parser.add_argument('--'+name,required=True)
    args=vars(parser.parse_args());benchmark(args['source'],args['binary'],args['duplex_inputs'],args['report'])
