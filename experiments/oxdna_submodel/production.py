"""Audited, isolated MD continuations from local and pre-existing relaxations.

Only --attach-box writes to the existing job, via its public submodel operation.
Parent molecular inputs and relaxation outputs are never changed. Production
outputs remain experimental artifacts, not ordinary managed Run-button jobs.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from scipy.optimize import linprog
from scipy.spatial.transform import Rotation

from backend.api.headless_oxdna_build import _use_workspace
from backend.api.routes_oxdna import get_oxdna_display, put_oxdna_submodel, get_oxdna_submodel
from backend.api.simulation_submodel import SubmodelSelection
from backend.core.models import Design
from backend.physics.oxdna_interface import _strand_nucleotide_order
from scripts.agent_structure_guard import audit


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inside_box(points, box):
    lo,hi=np.asarray(box['min_corner']),np.asarray(box['max_corner'])
    local=(points-(lo+hi)/2) @ Rotation.from_quat(box['rotation']).as_matrix()
    return np.all(np.abs(local) <= (hi-lo)/2+1e-10,axis=1)


def duplex_box(positions,bp):
    """Fit parallel boundary planes separating bp 14..27 in the aligned display.

    The upstream selection is explicit, and membership is then independently
    checked against the resulting oriented box. Refuse a bent frame that cannot
    express this selection as a single box rather than silently change the mask.
    """
    mobile=(bp>=14)&(bp<=27);middle=positions[mobile]
    differences=np.concatenate([(positions[bp<14,None,:]-middle).reshape(-1,3),
                                (middle[:,None,:]-positions[bp>27]).reshape(-1,3)])
    fit=linprog([0,0,-1],A_ub=np.column_stack([differences[:,:2],np.ones(len(differences))]),
                b_ub=-differences[:,2],bounds=[(-3,3),(-3,3),(None,None)],method='highs')
    if not fit.success or fit.x[2] <= 1e-5:
        raise ValueError('Central 14 bp cannot be separated by this single-box fit')
    z=np.array([*fit.x[:2],1.]);z/=np.linalg.norm(z)
    x=np.cross([0,1,0],z);x/=np.linalg.norm(x);y=np.cross(z,x)
    axes=np.column_stack([x,y,z]);local=middle@axes
    margin=min(.005,fit.x[2]/np.linalg.norm([*fit.x[:2],1.])/4)
    lo=local.min(axis=0)-[.4,.4,margin];hi=local.max(axis=0)+[.4,.4,margin]
    center=axes@((lo+hi)/2);half=(hi-lo)/2
    selection=SubmodelSelection(box={'min_corner':(center-half).tolist(),
                                    'max_corner':(center+half).tolist(),
                                    'rotation':Rotation.from_matrix(axes).as_quat().tolist()})
    box=selection.model_dump(mode='json')['box']
    if not np.array_equal(inside_box(positions,box),mobile):
        raise ValueError('Oriented box membership differs from the requested base indices')
    return selection


def settings(folder, temperature, steps, parameters=None, caps=False):
    return f'''backend = CPU
sim_type = MD
seed = 314159
steps = {steps}
restart_step_counter = true
T = {temperature}
dt = 0.003
thermostat = brownian
newtonian_steps = 53
diff_coeff = 2.5
refresh_vel = true
fix_diffusion = false
reset_initial_com_momentum = false
reset_com_momentum = false
use_barostat = false
list_type = verlet
verlet_skin = 0.20
interaction_type = DNA2
salt_concentration = 0.5
use_average_seq = {'false' if parameters else 'true'}
''' + (f'seq_dep_file = {parameters}\n' if parameters else '') + (
        'max_backbone_force = 50.0\nmax_backbone_force_far = 100.0\n' if caps else '') + f'''
topology = topology.top
conf_file = conf.dat
submodel_mobile_file = mobile.txt
trajectory_file = trajectory.dat
lastconf_file = last_conf.dat
energy_file = energy.dat
print_energy_every = 1000
print_conf_interval = 10000
time_scale = linear
no_stdout_energy = true
max_io = 20
'''


def prepare(root, workspace, parent_id, pilot, steps, attach_box):
    root,workspace,pilot=map(lambda p:Path(p).resolve(),(root,workspace,pilot))
    parent=workspace/'oxdna_jobs'/parent_id
    metadata=json.loads((parent/'job.json').read_text())
    if metadata['status']!='completed' or metadata['n_nucleotides']!=84:
        raise ValueError('Pilot requires the completed 84-nucleotide duplex')
    frozen=parent/'3_equil/last_conf.dat'
    design=Design.model_validate_json((parent/'design.json').read_text());audit(design)
    if len(design.helices)!=1 or design.helices[0].length_bp!=42:
        raise ValueError('This pilot requires one 42-bp helix')
    before={str(p.relative_to(parent)):sha(p) for p in parent.rglob('*') if p.is_file()}
    with _use_workspace(workspace):
        display=asyncio.run(get_oxdna_display(parent_id,align=True))
    if display['stage_name']!='3_equil':raise ValueError('Parent acquired a later stage; inspect before continuing')
    lookup={(r['helix_id'],r['bp_index'],r['direction']):r for r in display['positions']}
    order=_strand_nucleotide_order(design)
    positions=np.array([lookup[key]['backbone_position'] for key in order]);bp=np.array([key[1] for key in order])
    selection=duplex_box(positions,bp)
    mobile=inside_box(positions,selection.model_dump(mode='json')['box'])
    assert mobile.sum()==28
    (root/'parent-display.json').write_text(json.dumps(display,indent=2))
    (root/'parent-files-before.json').write_text(json.dumps(before,indent=2))
    pilot_manifest=json.loads((pilot/'manifest.json').read_text())
    for name,conf,source_design,topology,temperature,params,caps in [
        ('local_relaxation',pilot/'quench/last_conf.dat',Path(pilot_manifest['upstream_history']),pilot/'quench/topology.top','20C',None,False),
        ('existing_relaxation',frozen,parent/'design.json',parent/'topology.top','296K',parent/'oxDNA2_average_sequence_parameters.txt',True)]:
        folder=root/name;folder.mkdir()
        source=Design.model_validate_json(source_design.read_text());source_proof=audit(source)
        if _strand_nucleotide_order(source)!=order:raise ValueError('Particle order mismatch')
        for src,dest in [(conf,'conf.dat'),(source_design,'source_design.json'),(topology,'topology.top')]:
            (folder/dest).write_bytes(src.read_bytes())
        if params:
            (folder/params.name).write_bytes(params.read_bytes());params=folder/params.name
        (folder/'mobile.txt').write_text('\n'.join(map(str,np.flatnonzero(mobile)))+'\n')
        (folder/'input').write_text(settings(folder,temperature,steps,params,caps))
        (folder/'lineage.json').write_text(json.dumps({'source_configuration':str(conf),'source_configuration_sha256':sha(conf),
             'source_design':str(source_design),'source_design_sha256':sha(source_design),
             'source_job_id':parent_id if name=='existing_relaxation' else pilot_manifest['job_id'],
             'audit':source_proof,'temperature':temperature,'steps':steps,'dt':.003,
             'initial_velocities':'Fresh Maxwell draw; zero velocities and angular momenta for fixed particles',
             'boundary':'Fixed poses at this relaxation endpoint; all full-duplex interactions retained'},indent=2))
    mapping=[{'particle':i,'key':list(key),'mobile':bool(mobile[i]),'aligned_selection_position_nm':positions[i].tolist()} for i,key in enumerate(order)]
    (root/'mapping.json').write_text(json.dumps(mapping,indent=2))
    (root/'selection.json').write_text(selection.model_dump_json(indent=2))
    if attach_box:
        with _use_workspace(workspace):
            asyncio.run(put_oxdna_submodel(parent_id,selection))
            restored=asyncio.run(get_oxdna_submodel(parent_id))
        assert restored==selection.model_dump(mode='json')
    (root/'manifest.json').write_text(json.dumps({'parent_job_id':parent_id,'parent_directory':str(parent),
        'box_attached':attach_box,'selection':selection.model_dump(mode='json'),
        'selection_frame':'Relaxed backbone sites, NADOC align-to-design display frame; membership frozen before production',
        'local_selection':'Same explicit bp 14..27 IDs as the earlier local relaxation',
        'mobile_bp':[14,27],'mobile_nucleotides':28,'fixed_nucleotides':56,'steps':steps},indent=2))
    for name,digest in before.items():
        if name!='submodel_selection.json':assert sha(parent/name)==digest,name
    return root


def execute(folder,binary):
    folder,binary=Path(folder).resolve(),Path(binary).resolve()
    if (folder/'run.log').exists():raise FileExistsError('Preserve the existing run')
    original=(folder/'input').read_text()
    reference='\n'.join('steps = 0' if line.startswith('steps =') else line for line in original.splitlines())+'\n'
    reference=reference.replace('last_conf.dat','initial_normalized.dat').replace('trajectory.dat','initial_trajectory.dat').replace('energy.dat','initial_energy.dat')
    (folder/'initial.input').write_text(reference)
    record={'executable':str(binary),'binary_sha256':sha(binary),'input_sha256':sha(folder/'input'),
            'configuration_sha256':sha(folder/'conf.dat'),'mask_sha256':sha(folder/'mobile.txt')}
    for input_name,log_name in [('initial.input','initial.log'),('input','run.log')]:
        started=time.monotonic()
        with (folder/log_name).open('w') as log:
            result=subprocess.run([str(binary),input_name],cwd=folder,stdout=log,stderr=subprocess.STDOUT,timeout=180)
        record[input_name]={'exit_code':result.returncode,'seconds':time.monotonic()-started}
        (folder/'execution.json').write_text(json.dumps(record,indent=2))
        result.check_returncode()
        if 'SUBMODEL_MD_V1: 28 mobile / 84 total' not in (folder/log_name).read_text():
            raise RuntimeError('Executable did not activate the submodel mask')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);subs=p.add_subparsers(dest='action',required=True)
    prep=subs.add_parser('prepare')
    for name in ('output','workspace','parent_id','pilot'):prep.add_argument(name)
    prep.add_argument('--steps',type=int,default=1000000);prep.add_argument('--attach-box',action='store_true')
    run=subs.add_parser('run');run.add_argument('folder');run.add_argument('binary')
    a=p.parse_args()
    if a.action=='prepare':prepare(a.output,a.workspace,a.parent_id,a.pilot,a.steps,a.attach_box)
    else:execute(a.folder,a.binary)
