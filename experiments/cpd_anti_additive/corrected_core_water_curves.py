"""Six fixed-orientation HF water curves after audited DF/DIRECT calibration."""
from pathlib import Path
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import numpy as np

REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import BOHR,checked,geometry_audit,now,pin,read,save
from experiments.cpd_anti_additive.endpoint_native import NUMBER
from experiments.cpd_anti_additive.corrected_coupled_ring import require_archive
from backend.parameterization.photoproduct_water import place_tip3p_probe
from backend.parameterization.photoproduct_esp import build_esp_grid

CAMPAIGN=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
ROOT=CAMPAIGN/'water-core-curves-v1'
PYTHON=Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')
# Psi4 1.11 uses this conversion. Preserve the certified Bohr coordinates
# exactly; mixing the campaign display conversion with this engine shifts them.
HF_BOHR_ANGSTROM=0.52917721067


def audit_hf_native(text,elements,x_angstrom,algorithm,energy,dipole):
    x_angstrom=np.asarray(x_angstrom,float);dipole=np.asarray(dipole,float)
    if (algorithm not in ('df','direct') or x_angstrom.shape!=(len(elements),3)
            or dipole.shape!=(3,) or not np.isfinite(energy)
            or not np.isfinite(x_angstrom).all() or not np.isfinite(dipole).all()):
        raise ValueError('Invalid HF audit inputs')
    for phrase in ['RHF Reference',f'SCF Algorithm Type is {algorithm.upper()}.',
                   'Energy and wave function converged.','Energy threshold   = 1.00e-12',
                   'Density threshold  = 1.00e-12','Basis Set: 6-31G(D)']:
        if phrase not in text:raise ValueError(f'Missing HF evidence: {phrase}')
    energies=re.findall(r'@(?:DF-)?RHF Final Energy:\s*('+NUMBER+r')',text)
    if len(energies)!=1 or abs(float(energies[0])-energy)>1e-9:raise ValueError('Native HF energy mismatch')
    rows=re.findall(r'^\s*([CHNO])\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')\s*$',text,re.M)
    if len(rows)!=len(elements) or [v[0] for v in rows]!=elements or text.count('Geometry (in Angstrom), charge = 0, multiplicity = 1:')!=1:
        raise ValueError('Native geometry units/order/charge changed')
    x=np.array([[float(v) for v in row[1:4]] for row in rows]);delta=float(np.max(abs(x-x_angstrom)))
    if delta>5.1e-13:raise ValueError('Native geometry mismatch')
    vectors=re.findall(r'^NADOC_DIPOLE_AU\s+('+NUMBER+r')\s+('+NUMBER+r')\s+('+NUMBER+r')',text,re.M)
    if len(vectors)!=1 or np.max(abs(np.array(vectors[0],float)-dipole))>5.1e-13:raise ValueError('Native dipole mismatch')
    return dict(passed=True,geometry_max_rounding_error_angstrom=delta,geometry_tables=1,dipole_units='atomic_unit_e_bohr')


def context(root):
    require_archive(root);p=read(root/'plan.json')
    if checked(p['worker'])!=Path(__file__).resolve():raise ValueError('Frozen worker changed')
    for ref in p['sources']:checked(ref)
    cert=read(checked(p['core_certification']));auth=read(checked(p['authorization']))
    if not cert['minimum_certified'] or not auth['user_authorized'] or auth['compute_policy']['cloud_spending_usd']!=0:raise ValueError('Missing core reference/local authority')
    if (p['hard_seconds'],p['task_timeout_seconds'],len(p['tasks']))!=(3600,180,44):raise ValueError('Allocation changed')
    if (CAMPAIGN/'pause.json').exists() and read(CAMPAIGN/'pause.json').get('paused'):raise RuntimeError('Campaign paused')
    if (root/'launch_receipt.json').exists():
        execution=read(checked(read(root/'launch_receipt.json')['execution_plan']))
        if checked(execution['plan'])!=root/'plan.json':raise ValueError('Launched plan changed')
    if p['maximum_new_scf']!=39 or len(p['reused_results'])!=5:raise ValueError('Recovery allocation changed')
    return p,read(checked(p['core_plan']))


def reused_result(root,task,plan):
    ref=plan['reused_results'].get(task['label'])
    if ref is None:return None
    original=checked(ref);local=root/task['label']/'result.json'
    if pin(local)['sha256']!=ref['sha256']:raise ValueError('Reused result changed')
    result=read(original)
    if result['input']!=task['input']:raise ValueError('Reused input changed')
    inp=read(checked(task['input']))
    audit_hf_native(checked(result['native']).read_text(),inp['elements'],inp['geometry_angstrom'],inp['options']['scf_type'],result['energy_hartree'],result['dipole_au'])
    checked(result['returned_geometry'])
    if result['grid']:checked(result['grid']);checked(result['potentials'])
    return pin(local)


def prepare():
    require_archive(CAMPAIGN)
    previous=CAMPAIGN/'electrostatic-core-pilot-v2';old=read(previous/'plan.json')
    audit=read(previous/'completion_audit.json')
    if not audit['passed'] or not audit['df_direct_calibration_passed'] or not audit['full_curve_preparation_admitted']:
        raise ValueError('Calibration admission missing')
    for ref in old['sources']:checked(ref)
    checked(old['worker']);inventory=read(checked(old['inventory']))
    core_task=next(t for t in old['tasks'] if t['label']=='core-df');core=read(checked(core_task['input']))
    ROOT.mkdir();(ROOT/'tmp').mkdir();shutil.copy2(Path(__file__),ROOT/'executed_source.py')
    tasks=[];reuse={}
    for label in ('core-df','water-df'):
        task=dict(next(t for t in old['tasks'] if t['label']==label));folder=ROOT/label;folder.mkdir()
        ref=pin(previous/label/'result.json');shutil.copy2(checked(ref),folder/'result.json');reuse[label]=ref;tasks.append(task)
    curves=[]
    for site in inventory['sites']:
        if not site['screen_passed']:raise ValueError('Unscreened site')
        labels=[]
        for point in site['selected']['points']:
            dist=point['distance_angstrom'];label=site['id']+f'-r{round(dist*100):03d}-df';folder=ROOT/label;folder.mkdir()
            water=[w[1:] for w in point['water_angstrom']]
            inp={**core,'elements':core['elements']+['O','H','H'],'geometry_angstrom':core['geometry_angstrom']+water,'kind':'complex','site':site['id'],'grid':None}
            task=dict(label=label,kind='complex',site=site['id'],scf_type='df',distance_angstrom=dist)
            original=next((t for t in old['tasks'] if t['label']==site['id']+'-df'),None)
            if dist==1.9 and original is not None:
                if inp!=read(checked(original['input'])):raise ValueError('Pilot geometry/options mismatch')
                task['input']=original['input'];ref=pin(previous/original['label']/'result.json');reuse[label]=ref
                shutil.copy2(checked(ref),folder/'result.json')
            else:
                (folder/'scratch').mkdir();save(folder/'input.json',inp);task['input']=pin(folder/'input.json')
            labels.append(label);tasks.append(task)
        curves.append(dict(site=site['id'],target_atom=site['target_atom'],role=site['role'],azimuth=site['selected']['azimuth'],labels=labels))
    assert len(tasks)==44 and len(reuse)==5 and len(curves)==6
    expected=39*max(c['df_seconds'] for c in audit['calibration'])*1.25
    p={**old,'at':now(),'worker':pin(ROOT/'executed_source.py'),'tasks':tasks,
        'sources':[*old['sources'],pin(previous/'plan.json'),old['worker'],pin(previous/'completion_audit.json'),*reuse.values()],
        'previous_plan':pin(previous/'plan.json'),'calibration_audit':pin(previous/'completion_audit.json'),'reused_results':reuse,'curves':curves,
        'maximum_new_scf':39,'hard_seconds':3600,'task_timeout_seconds':180,'expected_seconds':expected,
        'expected_time_basis':'39 fresh complexes times slowest measured pilot DF time, times1.25 scheduling margin; 180s individual timeout (7.2x observed maximum), 1h allocation.',
        'maximum_curves':6,'water_distances_angstrom':[1.5,1.7,1.9,2.1,2.3,2.5,2.7],
        'completion_semantics':'42 frozen fixed-orientation contact energies (3 reused) and2 reused isolated references. Review native data, curve bracketing and mixed contacts before fitting. No new stationary point or fitted parameter acceptance.'}
    save(ROOT/'plan.json',p)
    import importlib.util
    spec=importlib.util.spec_from_file_location('curves_preflight',ROOT/'executed_source.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.context(ROOT)
    for task in tasks:
        result=m.reused_result(ROOT,task,p)
        if task['label'] in reuse and result is None:raise ValueError('Missed completed calculation')
    save(ROOT/'preflight.json',dict(at=now(),passed=True,source_pins_verified=True,calibration=pin(previous/'completion_audit.json'),
        inventory=old['inventory'],reused_results=5,new_df_calculations=39,strict_method_unchanged=True,archive_mount_verified=True,new_qm_evaluations=0,
        failed_attempts_preserved=True,system_disk_fallback=False,expected_seconds=expected))
    print(ROOT)


def worker(root,label):
    p,base=context(root);task=next(t for t in p['tasks'] if t['label']==label);inp=read(checked(task['input']));folder=root/label
    if label in p['reused_results']:raise ValueError('Completed calculation cannot be re-executed')
    x=np.array(inp['geometry_angstrom']);require_archive(folder/'scratch')
    if inp['kind']!='water' and not geometry_audit(x[:36]/HF_BOHR_ANGSTROM,base)['passed']:raise ValueError('Core identity failed')
    if inp['grid']:checked(inp['grid'])
    with (folder/'started.json').open('x') as f:f.write(now()+'\n')
    import psi4
    if psi4.__version__!=p['psi4_version']:raise ValueError('Engine changed')
    if psi4.constants.bohr2angstroms!=HF_BOHR_ANGSTROM:raise ValueError('Engine length conversion changed')
    os.chdir(folder);psi4.set_output_file(str(folder/'output.dat'),False);psi4.set_memory('4 GiB');psi4.set_num_threads(4)
    psi4.core.IOManager.shared_object().set_default_path(str(folder/'scratch'));psi4.set_options(inp['options'])
    text='\n'.join(el+' '+' '.join(f'{v:.17g}' for v in pos) for el,pos in zip(inp['elements'],x))
    molecule=psi4.geometry('0 1\n'+text+'\nunits angstrom\nsymmetry c1\nno_com\nno_reorient')
    start=time.monotonic();energy,wfn=psi4.energy('hf',molecule=molecule,return_wfn=True)
    properties=['DIPOLE','GRID_ESP'] if inp['grid'] else ['DIPOLE'];psi4.oeprop(wfn,*properties)
    dipole=np.asarray(wfn.variable('DIPOLE'));actual=np.asarray(wfn.molecule().geometry())*HF_BOHR_ANGSTROM
    psi4.core.print_out('NADOC_DIPOLE_AU %.12f %.12f %.12f\n'%tuple(dipole))
    np.save(folder/'returned_geometry_angstrom.npy',actual)
    psi4.core.clean();psi4.core.flush_outfile();psi4.core.close_outfile()
    native=(folder/'output.dat').read_text();audit=audit_hf_native(native,inp['elements'],x,inp['options']['scf_type'],energy,dipole)
    if np.max(abs(actual-x))>1e-12:raise ValueError('Returned geometry changed')
    potential=None
    if inp['grid']:
        values=np.loadtxt(folder/'grid_esp.dat');grid=np.loadtxt(checked(inp['grid']))
        if values.shape!=(len(grid),) or not np.isfinite(values).all():raise ValueError('ESP shape/values invalid')
        potential=pin(folder/'grid_esp.dat')
    save(folder/'result.json',dict(at=now(),input=task['input'],native=pin(folder/'output.dat'),energy_hartree=float(energy),
        dipole_au=dipole.tolist(),grid=inp['grid'],potentials=potential,returned_geometry=pin(folder/'returned_geometry_angstrom.npy'),
        native_audit=audit,wall_seconds=time.monotonic()-start,minimum_certified=False,simulation_ready=False))


def curve_diagnostics(distances,energies):
    r=np.asarray(distances,float);e=np.asarray(energies,float)
    if r.ndim!=1 or r.shape!=e.shape or len(r)<3 or not np.isfinite(r).all() or not np.isfinite(e).all() or np.any(np.diff(r)<=0):
        raise ValueError('Invalid water curve')
    i=int(np.argmin(e));interior=0<i<len(e)-1
    bracketed=bool(interior and e[i]<e[i-1] and e[i]<e[i+1])
    attractive=bool(e[i]<0)
    monotone=bool(np.all(np.diff(e[:i+1])<0) and np.all(np.diff(e[i:])>0))
    quadratic=None
    if bracketed:
        q=np.polyfit(r[i-1:i+2]-r[i],e[i-1:i+2],2)
        vertex=-q[1]/(2*q[0])+r[i]
        quadratic=dict(raw_distance_angstrom=float(vertex),raw_energy_kcal_mol=float(np.polyval(q,vertex-r[i])),curvature_kcal_mol_angstrom2=float(2*q[0]),inside_neighbor_interval=bool(r[i-1]<vertex<r[i+1]),interpretation='Local three-point interpolation diagnostic; not a newly evaluated minimum or a charge fit.')
    return dict(sampled_minimum_index=i,sampled_distance_angstrom=float(r[i]),sampled_raw_energy_kcal_mol=float(e[i]),bracketed=bracketed,attractive=attractive,monotone_flanks=monotone,quadratic_diagnostic=quadratic,needs_shape_review=not(bracketed and attractive and monotone))


def review(root):
    p,base=context(root);records={};rows=[]
    for t in p['tasks']:
        v=read(root/t['label']/'result.json');inp=read(checked(t['input']));x=np.array(inp['geometry_angstrom'])
        if v['input']!=t['input']:raise ValueError('Input/result mismatch')
        audit_hf_native(checked(v['native']).read_text(),inp['elements'],x,inp['options']['scf_type'],v['energy_hartree'],v['dipole_au'])
        actual=np.load(checked(v['returned_geometry']))
        if not np.isfinite(actual).all() or np.max(abs(actual-x))>1e-12:raise ValueError('Returned geometry changed')
        if inp['kind']!='water' and not geometry_audit(x[:36]/HF_BOHR_ANGSTROM,base)['passed']:raise ValueError('Identity changed')
        if inp['grid']:
            if v['grid']!=inp['grid']:raise ValueError('ESP grid changed')
            grid=np.loadtxt(checked(v['grid']));values=np.loadtxt(checked(v['potentials']))
            if values.shape!=(len(grid),) or not np.isfinite(values).all():raise ValueError('ESP shape invalid')
        if t['label'] in p['reused_results']:reused_result(root,t,p)
        records[t['label']]=v;rows.append(dict(label=t['label'],result=pin(root/t['label']/'result.json'),wall_seconds=v['wall_seconds'],reused=t['label'] in p['reused_results']))
    taskmap={t['label']:t for t in p['tasks']};curves=[];policy=read(checked(p['method_choice']))
    for curve in p['curves']:
        points=[]
        for label in curve['labels']:
            raw=627.509474*(records[label]['energy_hartree']-records['core-df']['energy_hartree']-records['water-df']['energy_hartree'])
            distance=taskmap[label]['distance_angstrom']
            points.append(dict(label=label,distance_angstrom=distance,raw_interaction_kcal_mol=raw,scaled_interaction_kcal_mol=raw*policy['water_energy_scale'],corrected_distance_angstrom=distance+policy['water_distance_offset_angstrom'],result=pin(root/label/'result.json')))
        diagnostic=curve_diagnostics([v['distance_angstrom'] for v in points],[v['raw_interaction_kcal_mol'] for v in points])
        curves.append(dict(**curve,points=points,diagnostic=diagnostic))
    data=dict(at=now(),plan=pin(root/'plan.json'),native_evidence_passed=True,records=rows,curves=curves,
        all_curves_bracketed=all(v['diagnostic']['bracketed'] for v in curves),all_sampled_minima_attractive=all(v['diagnostic']['attractive'] for v in curves),
        curves_needing_shape_review=[v['site'] for v in curves if v['diagnostic']['needs_shape_review']],
        new_scf_seconds=sum(v['wall_seconds'] for k,v in records.items() if k not in p['reused_results']),
        reused_count=5,new_count=39,requires_completion_audit=True,fit_target_accepted=False,minimum_certified=False,simulation_ready=False)
    out=root/'independent_review.json'
    if out.exists():
        old=read(out)
        if old['records']!=rows:raise ValueError('Previously reviewed evidence changed')
        return old
    save(out,data);return data


def run(root):
    p,_=context(root)
    with (root/'started.json').open('x') as f:f.write(now()+'\n')
    deadline=read(root/'launch_receipt.json')['deadline_epoch'];completed=[];reused_count=0;new_count=0;error=None
    try:
        for t in p['tasks']:
            context(root)
            reused=reused_result(root,t,p)
            if reused is not None:
                completed.append(reused);reused_count+=1;save(root/'progress.json',dict(at=now(),completed=completed,reused_count=reused_count,new_count=new_count));continue
            if deadline-time.time()<p['task_timeout_seconds']+30:raise RuntimeError('Insufficient boundary time')
            folder=root/t['label'];env={**os.environ,'TMPDIR':str(folder/'scratch'),'PSI_SCRATCH':str(folder/'scratch')}
            with (folder/'runner.log').open('x') as log:
                c=subprocess.run([str(PYTHON),str(checked(p['worker'])),'worker',str(root),'--label',t['label']],env=env,cwd=folder,stdout=log,stderr=subprocess.STDOUT,timeout=p['task_timeout_seconds'])
            if c.returncode:raise RuntimeError(f"Native task {t['label']} failed: {c.returncode}")
            completed.append(pin(folder/'result.json'));new_count+=1;save(root/'progress.json',dict(at=now(),completed=completed,reused_count=reused_count,new_count=new_count))
        review(root)
    except Exception as exc:
        error=repr(exc);(root/'failure_traceback.txt').write_text(traceback.format_exc())
    save(root/'assessment.json',dict(at=now(),completed=len(completed),reused_count=reused_count,new_completed=new_count,native_completed=len(completed)==44,error=error,requires_completion_audit=True,minimum_certified=False,simulation_ready=False))
    return 1 if error else 0


def launch(root):
    p,_=context(root)
    if not read(root/'preflight.json')['passed']:raise ValueError('Preflight missing')
    units=subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'],text=True)
    if any('cpd-' in line and '-watch' not in line for line in units.splitlines()):raise RuntimeError('Other CPD native job active')
    processes=subprocess.check_output(['ps','-eo','args='],text=True).splitlines()
    if any(line.strip().split(' ')[0].split('/')[-1] in ('namd2','namd3','psi4') for line in processes):raise RuntimeError('Other native job active')
    mem={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemAvailable:','SwapFree:'))}
    if mem['MemAvailable']<12*1024**3 or shutil.disk_usage(root).free<30*1024**3:raise RuntimeError('Insufficient resource headroom')
    service=CAMPAIGN/(root.name+'-service');service.mkdir()
    for old,new in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:shutil.copy2(REPO/'experiments/cpd_anti_additive'/old,service/new)
    start=time.time();unit='cpd-corrected-anti1-water-core-curves-v1'
    save(service/'watcher_config.json',dict(codex_executable=str(Path(shutil.which('codex')).resolve()),expected_seconds=p['expected_seconds'],review_deadline_epoch=start+3000,review_deadline_id='water-curves-audit',self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=os.environ['CODEX_THREAD_ID'],command=[str(PYTHON),str(checked(p['worker'])),'run',str(root)],cwd=str(root),runtime_hours=1,memory_gib=8,omp_threads=4,plan=pin(root/'plan.json'),completion_semantics=p['completion_semantics']))
    save(root/'launch_receipt.json',dict(at=now(),deadline_epoch=start+3600,unit=unit,prelaunch_memory=mem,execution_plan=pin(service/'execution_plan.json'),supervisor=pin(service/'supervisor.py'),watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=8G','--property=MemorySwapMax=0','--property=RuntimeMaxSec=3585s','--property=TimeoutStopSec=15s','--property=KillMode=control-group','--property=CPUQuota=400%',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4',f'--setenv=PSI_SCRATCH={root}/tmp',f'--setenv=TMPDIR={root}/tmp','/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)],check=True)
    print(service)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','launch','run','worker','review'));p.add_argument('root',nargs='?',type=Path,default=ROOT);p.add_argument('--label');args=p.parse_args();root=args.root.resolve()
    if args.action=='prepare':prepare()
    elif args.action=='worker':worker(root,args.label)
    elif args.action=='run':sys.exit(run(root))
    elif args.action=='review':print(review(root))
    else:launch(root)
