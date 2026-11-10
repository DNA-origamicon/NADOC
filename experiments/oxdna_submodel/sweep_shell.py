"""Bounded shell sweep and same-frame force comparison; explicitly requested science."""
import argparse
import json
from pathlib import Path
import subprocess
import time

import numpy as np
from backend.core.models import Design
from scripts.agent_structure_guard import audit
from experiments.oxdna_submodel.production import sha
from experiments.oxdna_submodel.shell import crop
from experiments.oxdna_submodel.analyze import frames


def native(folder,binary,input_name='input',timeout=90):
    started=time.monotonic()
    with (folder/(input_name+'.log')).open('w') as log:
        process=subprocess.run([str(binary),input_name],cwd=folder,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
    elapsed=time.monotonic()-started
    process.check_returncode()
    return elapsed


def run(source,output,binary,analysis):
    source,output,binary,analysis=map(lambda p:Path(p).resolve(),(source,output,binary,analysis))
    output.mkdir(parents=True,exist_ok=False)
    parent=source/'existing_relaxation'
    proof=audit(Design.model_validate_json((parent/'source_design.json').read_text()))
    (output/'source_design.json').write_bytes((parent/'source_design.json').read_bytes())
    mapping=json.loads((source/'mapping.json').read_text())
    points=np.array([row['aligned_selection_position_nm'] for row in mapping])
    box=json.loads((source/'selection.json').read_text())['box']
    top=(parent/'topology.top').read_text();conf=(parent/'conf.dat').read_text()
    native_frames=(parent/'initial_normalized.dat').read_text().splitlines()
    trajectory=(parent/'trajectory.dat').read_text().splitlines()
    # Initial state plus ten snapshots throughout the previous full-model run.
    probe_frames=['\n'.join(native_frames)+'\n']+['\n'.join(trajectory[i*87:(i+1)*87])+'\n' for i in range(9,100,10)]
    provenance={'source_directory':str(parent),'source_audit':proof,'source_files':{f:sha(parent/f) for f in ['source_design.json','topology.top','conf.dat','trajectory.dat','input']},
                'binary':str(binary),'binary_sha256':sha(binary),'radii_nm':[0,.5,1,2,3,None],
                'steps_per_run':100000,'seeds':[314159,271828],
                'warning':'Scientific pilot; shell sufficiency is specimen/pose/parameter dependent.'}
    (output/'manifest.json').write_text(json.dumps(provenance,indent=2))
    summary=[]
    for radius in provenance['radii_nm']:
        name='full' if radius is None else f'shell_{radius:g}'
        case=output/name;case.mkdir()
        cropped_top,cropped_conf,recipe=crop(top,conf,points,box,radius)
        (case/'topology.top').write_text(cropped_top);(case/'conf.dat').write_text(cropped_conf)
        (case/'extraction.json').write_text(json.dumps(recipe,indent=2))
        (case/'mobile.txt').write_text('\n'.join(map(str,recipe['mobile_output_indices']))+'\n')
        ids=recipe['retained_source_indices'];mobile_ids=recipe['mobile_output_indices'];n=len(ids)
        base=(parent/'input').read_text().replace('steps = 1000000','steps = 100000').replace('print_conf_interval = 10000','print_conf_interval = 1000')
        base=base.replace('topology = topology.top',f'topology = {case/"topology.top"}').replace('conf_file = conf.dat',f'conf_file = {case/"conf.dat"}').replace('submodel_mobile_file = mobile.txt',f'submodel_mobile_file = {case/"mobile.txt"}')
        # Native initialization computes all forces before printing step-zero observables.
        probe=case/'probes';probe.mkdir();force_samples=[]
        for i,full_conf in enumerate(probe_frames):
            _,small,_=crop(top,full_conf,points,box,radius)
            (probe/'conf.dat').write_text(small)
            probe_input=base.replace('steps = 100000','steps = 0').replace(str(case/'conf.dat'),str(probe/'conf.dat'))
            probe_input+='\ndata_output_1 = {\n name = force.dat\n print_every = 1\n col_1 = {\n type = force_and_torque\n particle = '+','.join(map(str,mobile_ids))+'\n lab_frame = true\n }\n}\n'
            (probe/'input').write_text(probe_input);native(probe,binary)
            rows=np.loadtxt(probe/'force.dat');rows=rows[np.argsort(rows[:,0])]
            force_samples.append(rows[:,1:].tolist())
        (case/'mobile_forces.json').write_text(json.dumps(force_samples))
        pair_targets={}
        for new,old in enumerate(ids):pair_targets.setdefault(mapping[old]['key'][1],[]).append(new)
        mobile_set=set(mobile_ids)
        expected={tuple(sorted(v)) for v in pair_targets.values() if len(v)==2 and all(i in mobile_set for i in v)}
        trials=[]
        for seed in provenance['seeds']:
            trial=case/f'seed_{seed}';trial.mkdir();(trial/'input').write_text(base.replace('seed = 314159',f'seed = {seed}'))
            seconds=native(trial,binary)
            initial=frames(case/'conf.dat',n)[0];output_frames=frames(trial/'trajectory.dat',n)
            frozen=np.array([i not in mobile_set for i in range(n)])
            # Input axes may normalize at load; compare frozen poses across saved frames.
            drift=max(float(abs(frame[frozen,:9]-output_frames[0][frozen,:9]).max()) for frame in output_frames)
            assert drift==0 and all(np.isfinite(frame).all() for frame in output_frames)
            assert all(np.max(np.abs(frame[frozen,9:15]))==0 for frame in output_frames)
            assert all(np.max(np.abs(frame[frozen,:3]-initial[frozen,:3]))==0 for frame in output_frames)
            text=(trial/'input').read_text().replace('trajectory_file = trajectory.dat',f'trajectory_file = {trial/"trajectory.dat"}')
            text+='\nanalysis_data_output_1 = {\n name = hb.dat\n print_every = 1\n col_1 = {\n type = hb_list\n }\n}\n'
            (trial/'analysis.input').write_text(text)
            with (trial/'analysis.log').open('w') as log:subprocess.run([str(analysis),'analysis.input'],cwd=trial,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=30)
            pairs=[]
            for line in (trial/'hb.dat').read_text().splitlines():
                if line.startswith('# step'):pairs.append(set())
                elif line.strip():pairs[-1].add(tuple(sorted(map(int,line.split()))))
            retained=[len(p&expected) for p in pairs]
            rms=[float(np.sqrt(np.mean(np.sum((f[mobile_ids,:3]-initial[mobile_ids,:3])**2,axis=1)))*.8518) for f in output_frames]
            trials.append({'seed':seed,'seconds':seconds,'mobile_pairs_min':min(retained),'mobile_pairs_mean':float(np.mean(retained)),
                           'mobile_pairs_final':retained[-1],'rms_final_nm':rms[-1],'fixed_drift':drift})
            (trial/'results.json').write_text(json.dumps(trials[-1],indent=2))
        summary.append({'case':name,'radius_nm':radius,'particles':n,'fixed':n-28,'cuts':recipe['cut_bonds_source_indices'],'trials':trials})
        (output/'summary.json').write_text(json.dumps(summary,indent=2))
        print(name,n,[(r['mobile_pairs_min'],round(r['seconds'],2)) for r in trials],flush=True)
    reference=np.array(json.loads((output/'full/mobile_forces.json').read_text()))
    for row in summary:
        differences=np.array(json.loads((output/row['case']/'mobile_forces.json').read_text()))-reference
        row['max_force_vector_difference']=float(np.max(np.linalg.norm(differences[:,:,:3],axis=2)))
        row['max_torque_vector_difference']=float(np.max(np.linalg.norm(differences[:,:,3:],axis=2)))
        row['relative_force_rms_difference']=float(np.sqrt(np.mean(differences[:,:,:3]**2)/np.mean(reference[:,:,:3]**2)))
    (output/'summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps([{k:v for k,v in r.items() if k!='trials'} for r in summary],indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for key in ['source','output','binary','analysis']:p.add_argument(key)
    a=p.parse_args();run(a.source,a.output,a.binary,a.analysis)
