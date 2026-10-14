"""Bounded HF electrostatics/calibration on the exact certified corrected core."""
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
ROOT=CAMPAIGN/'electrostatic-core-pilot-v1'
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
    if (p['hard_seconds'],p['task_timeout_seconds'],len(p['tasks']))!=(1800,150,10):raise ValueError('Allocation changed')
    if (CAMPAIGN/'pause.json').exists() and read(CAMPAIGN/'pause.json').get('paused'):raise RuntimeError('Campaign paused')
    if (root/'launch_receipt.json').exists():
        execution=read(checked(read(root/'launch_receipt.json')['execution_plan']))
        if checked(execution['plan'])!=root/'plan.json':raise ValueError('Launched plan changed')
    return p,read(checked(p['core_plan']))


def prepare():
    require_archive(CAMPAIGN)
    cert_path=CAMPAIGN/'core_local_minimum_assessment.json';cert=read(cert_path)
    stage=read(checked(cert['stationarity_audit']));base=read(checked(stage['plan']))
    ring=CAMPAIGN/'coupled-ring-training-v1/completion_audit.json'
    if not read(ring)['passed'] or not cert['minimum_certified']:raise ValueError('Preceding evidence missing')
    import psi4
    assert psi4.constants.bohr2angstroms==HF_BOHR_ANGSTROM
    x=np.load(checked(cert['geometry']));assert geometry_audit(x,base)['passed'];xa=x*HF_BOHR_ANGSTROM;keys=base['atom_keys']
    ROOT.mkdir();(ROOT/'tmp').mkdir();shutil.copy2(Path(__file__),ROOT/'executed_source.py')
    scope=REPO/'backend/data/forcefield/tt_cpd_patch_charge_scope_v2.json';scope_data=read(scope)
    assert scope_data['chemical_definitions']['tt-cpd-cis-anti-i']==base['definition']['sha256']
    variable=[k for k in scope_data['atoms_with_charges_replaced'] if k.split(':')[1] not in ['H6','H51','H52','H53']]
    assert len(variable)==20 and set(variable)<=set(keys)
    policy=dict(at=now(),schema='nadoc.corrected-anti-electrostatic-method-choice.v1',
        primary_sources=[dict(title='Xu et al. 2016, modified ribonucleotides',doi='10.1002/jcc.24307',url='https://pmc.ncbi.nlm.nih.gov/articles/PMC4801715/',pdf='https://rcastoragev2.blob.core.windows.net/dc8e1053af18c252983be5e4260408da/PMC4801715.pdf',location='Charge optimization, p. 898; Model compounds, p. 899',finding='Unscaled HF dipoles and scaled neutral water interactions; neutral methyl caps for base charge models.'),dict(title='Vanommeslaeghe et al. 2010, CGenFF',url='https://pmc.ncbi.nlm.nih.gov/articles/PMC2888302/',finding='General small-molecule dipole overpolarization guidance; neutral water energy/distance corrections.')],
        method='HF/6-31G(d), RHF, neutral singlet',qm_dipole_scale=1.0,
        bohr_to_angstrom=HF_BOHR_ANGSTROM,unit_convention='Use Psi4 conversion for input/output/grid Angstrom values to preserve exact certified Bohr geometry. The campaign display conversion differs by 0.44 parts per billion.',
        choice='Use the modified-nucleotide precedent for this base patch, rather than imposing the generic workflow 1.3 multiplier. This is an explicit local modeling choice supported by close chemical precedent, not a universal requirement or CPD validation.',
        water_energy_scale=1.16,water_distance_offset_angstrom=-.2,counterpoise_corrected=False,
        primary_charge_model='Exact certified 36-atom N1-methyl capped corrected core. Both caps neutral and excluded from DNA patch; avoids sugar-OH intramolecular contacts controlling primary base charges.',
        boundary_followup='At most two existing sugar-bearing endpoint conformers may later test transfer if justified. They remain uncertified as full minima and are not claimed as primary minimum-based charge references. No boundary electrostatic acquisition in this pilot.',
        charge_scope=pin(scope),variable_base_charge_keys=variable,
        fixed='Methyl-cap charges, aliphatic H6/methyl-H charges, sugar/phosphate charges, Lennard-Jones and bonded terms. Preserve total paired-base charge zero; freeze exact baseline charge vectors before fitting.',
        maximum_absolute_base_charge_shift_e=.15,charge_fit_rounds_max=2,
        prospective_objective='Water minimum energies/distances plus unscaled HF dipole vector and restrained base-charge shifts. ESP retained as diagnostic. Freeze numerical weights and baseline before fitting; none fitted in this acquisition.',
        df_admission='Three identical-geometry DF/DIRECT water contacts must agree within 0.02 kcal/mol raw interaction energy; report scaled errors too. This inherited numerical tolerance is a local implementation criterion, not a literature accuracy law.',
        orientation_scope='One screened fixed orientation per site; not a global orientation optimization. Full curves must bracket minima, retain mixed-site contacts and use matched QM/MM geometry.',
        thresholds_not_minimum_certification=True,minimum_certified=False,simulation_ready=False)
    save(ROOT/'method_choice.json',policy)
    radii={'H':.31,'C':.76,'N':.71,'O':.66};sites=[]
    for residue in (1,2):
        for atom,anchor,plane,role in [('O2','C2','N3','acceptor'),('O4','C4','C5','acceptor'),('H3','N3','C2','donor')]:
            target=f'{residue}:{atom}';ti=keys.index(target);candidates=[]
            for az in (0,120,240):
                points=[]
                for dist in [1.5,1.7,1.9,2.1,2.3,2.5,2.7]:
                    water,probe=place_tip3p_probe(target=xa[ti],axis_anchor=xa[keys.index(f'{residue}:{anchor}')],plane_point=xa[keys.index(f'{residue}:{plane}')],role=role,distance_angstrom=dist,azimuth_degrees=az)
                    pairs=sorted((float(np.linalg.norm(np.asarray(w[1:])-pos)/(radii[w[0]]+radii[el])),keys[i],wi) for wi,w in enumerate(water) for i,(el,pos) in enumerate(zip(base['elements'],xa)) if i!=ti)
                    points.append(dict(distance_angstrom=dist,water_angstrom=[list(w) for w in water],probe_atom=probe,minimum_nontarget_radius_ratio=pairs[0][0],closest_nontarget_atom=pairs[0][1],closest_water_index=pairs[0][2]))
                candidates.append(dict(azimuth=az,minimum_ratio=min(p['minimum_nontarget_radius_ratio'] for p in points),points=points))
            selected=max(candidates,key=lambda c:c['minimum_ratio'])
            sites.append(dict(id=target.replace(':','-'),target_atom=target,role=role,candidates=candidates,selected=selected,screen_passed=bool(selected['minimum_ratio']>=1.1)))
    save(ROOT/'water_inventory.json',dict(at=now(),source_geometry=cert['geometry'],atom_keys=keys,sites=sites,
        screen='Choose least crowded of three frozen azimuths across seven distances. Minimum non-target covalent-radius ratio >=1.1 is a local steric screen, not proof of a unique hydrogen bond.',
        maximum_full_curves=6,maximum_full_points=42,full_curve_acquisition_admitted=False,
        excluded_sites=[s['id'] for s in sites if not s['screen_passed']],heldout_acquisition=False))
    selected_sites=[next(s for s in sites if s['id']==label) for label in ['1-O2','2-O4','1-H3']]
    if not all(s['screen_passed'] for s in selected_sites):raise ValueError('Pilot contact screen failed; preserve review')
    grid=np.array(build_esp_grid([(el,*pos) for el,pos in zip(base['elements'],xa)],radius_scales=[1.4,1.6,1.8,2.0],directions_per_atom=50))
    canonical=np.array([[0.,0.,0.],[.9572,0.,0.],[.9572*np.cos(np.radians(104.52)),.9572*np.sin(np.radians(104.52)),0.]])
    tasks=[]
    def task(label,elements,coords,algorithm,kind,site=None):
        folder=ROOT/label;folder.mkdir();(folder/'scratch').mkdir()
        if kind=='core':np.savetxt(folder/'grid.dat',grid,fmt='%.10f')
        inp=dict(elements=elements,geometry_angstrom=np.asarray(coords).tolist(),charge=0,multiplicity=1,
            method='hf',options=dict(basis='6-31G(d)',reference='rhf',scf_type=algorithm,e_convergence=1e-12,d_convergence=1e-12,maxiter=300),
            kind=kind,site=site,grid=pin(folder/'grid.dat') if kind=='core' else None)
        save(folder/'input.json',inp);tasks.append(dict(label=label,input=pin(folder/'input.json'),kind=kind,site=site,scf_type=algorithm))
    for alg in ('df','direct'):
        task('core-'+alg,base['elements'],xa,alg,'core')
        task('water-'+alg,['O','H','H'],canonical,alg,'water')
        for site in selected_sites:
            point=next(p for p in site['selected']['points'] if p['distance_angstrom']==1.9)
            water=np.array([w[1:] for w in point['water_angstrom']]);task(site['id']+'-'+alg,base['elements']+['O','H','H'],np.vstack([xa,water]),alg,'complex',site['id'])
    sources=[*base['sources'],pin(cert_path),cert['stationarity_audit'],cert['geometry'],pin(ring),pin(ROOT/'method_choice.json'),pin(ROOT/'water_inventory.json'),
        pin(scope),pin(REPO/'backend/parameterization/photoproduct_water.py'),pin(REPO/'backend/parameterization/photoproduct_esp.py'),
        pin(REPO/'experiments/cpd_anti_additive/corrected_core_stage1.py'),pin(REPO/'experiments/cpd_anti_additive/endpoint_native.py'),pin(REPO/'experiments/cpd_anti_additive/corrected_coupled_ring.py')]
    save(ROOT/'plan.json',dict(at=now(),worker=pin(ROOT/'executed_source.py'),sources=sources,authorization=pin(CAMPAIGN/'campaign_authorization_20261010.json'),
        core_certification=pin(cert_path),core_plan=stage['plan'],method_choice=pin(ROOT/'method_choice.json'),inventory=pin(ROOT/'water_inventory.json'),
        tasks=tasks,calibration_sites=[s['id'] for s in selected_sites],maximum_new_scf=10,hard_seconds=1800,task_timeout_seconds=150,
        expected_seconds=600,expected_time_basis='Conservative ten-minute scheduling estimate; this bounded pilot measures DIRECT/DF timing before curve admission.',
        threads=4,psi4_memory_gib=4,service_memory_gib=8,psi4_version=base['psi4_version'],
        completion_semantics='Ten fixed-geometry HF calculations; audit native evidence, ESP/dipoles and DF/DIRECT interaction errors before admitting distance curves. No optimizer, fit or minimum promotion.',
        water_reference='Same rigid TIP3P geometry; isolated HF water energy reused across rigid translations/rotations. No ghost atoms or counterpoise. Record each complex orientation.',
        heldout_acquisition=False,minimum_certified=False,fit_target_accepted=False,simulation_ready=False,cloud_spending_usd=0))
    import importlib.util
    spec=importlib.util.spec_from_file_location('hf_preflight',ROOT/'executed_source.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.context(ROOT)
    save(ROOT/'preflight.json',dict(at=now(),passed=True,core_identity=geometry_audit(x,base),source_pins_verified=True,
        screened_pilot_sites=[s['id'] for s in selected_sites],esp_grid_points=len(grid),fresh_calculations=10,archive_mount_verified=True,
        output=str(ROOT),scratch=str(ROOT/'tmp'),system_disk_fallback=False,new_qm_evaluations=0))
    print(ROOT)


def worker(root,label):
    p,base=context(root);task=next(t for t in p['tasks'] if t['label']==label);inp=read(checked(task['input']));folder=root/label
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


def review(root):
    p,base=context(root);records={};rows=[]
    for t in p['tasks']:
        v=read(root/t['label']/'result.json');inp=read(checked(t['input']));x=np.array(inp['geometry_angstrom'])
        if v['input']!=t['input']:raise ValueError('Input/result mismatch')
        audit_hf_native(checked(v['native']).read_text(),inp['elements'],x,inp['options']['scf_type'],v['energy_hartree'],v['dipole_au'])
        if np.max(abs(np.load(checked(v['returned_geometry']))-x))>1e-12:raise ValueError('Returned geometry changed')
        if inp['kind']!='water' and not geometry_audit(x[:36]/HF_BOHR_ANGSTROM,base)['passed']:raise ValueError('Identity changed')
        if inp['grid']:
            if v['grid']!=inp['grid']:raise ValueError('ESP grid changed')
            grid=np.loadtxt(checked(v['grid']));values=np.loadtxt(checked(v['potentials']))
            if values.shape!=(len(grid),) or not np.isfinite(values).all():raise ValueError('ESP shape invalid')
        records[t['label']]=v;rows.append(dict(label=t['label'],result=pin(root/t['label']/'result.json'),wall_seconds=v['wall_seconds']))
    comparisons=[]
    for site in p['calibration_sites']:
        values={alg:627.509474*(records[site+'-'+alg]['energy_hartree']-records['core-'+alg]['energy_hartree']-records['water-'+alg]['energy_hartree']) for alg in ['df','direct']}
        error=abs(values['df']-values['direct']);comparisons.append(dict(site=site,raw_interaction_kcal_mol=values,raw_absolute_error_kcal_mol=error,scaled_absolute_error_kcal_mol=1.16*error,passed=error<=.02))
    dif=np.array(records['core-df']['dipole_au'])-records['core-direct']['dipole_au']
    data=dict(at=now(),plan=pin(root/'plan.json'),native_evidence_passed=True,records=rows,calibration=comparisons,
        df_direct_calibration_passed=all(c['passed'] for c in comparisons),core_dipole_vectors_au={a:records['core-'+a]['dipole_au'] for a in ['df','direct']},
        core_dipole_df_direct_difference_debye=float(np.linalg.norm(dif)*2.541746473),
        esp_df_direct_rms_difference_au=float(np.sqrt(np.mean((np.loadtxt(checked(records['core-df']['potentials']))-np.loadtxt(checked(records['core-direct']['potentials'])))**2))),
        measured_scf_seconds=sum(v['wall_seconds'] for v in records.values()),requires_completion_audit=True,
        full_curves_admitted=False,fit_target_accepted=False,minimum_certified=False,simulation_ready=False)
    out=root/'independent_review.json'
    if out.exists():
        old=read(out)
        if old['records']!=rows:raise ValueError('Previously reviewed evidence changed')
        return old
    save(out,data);return data


def run(root):
    p,_=context(root)
    with (root/'started.json').open('x') as f:f.write(now()+'\n')
    deadline=read(root/'launch_receipt.json')['deadline_epoch'];completed=[];error=None
    try:
        for t in p['tasks']:
            context(root)
            if deadline-time.time()<p['task_timeout_seconds']+30:raise RuntimeError('Insufficient boundary time')
            folder=root/t['label'];env={**os.environ,'TMPDIR':str(folder/'scratch'),'PSI_SCRATCH':str(folder/'scratch')}
            with (folder/'runner.log').open('x') as log:
                c=subprocess.run([str(PYTHON),str(checked(p['worker'])),'worker',str(root),'--label',t['label']],env=env,cwd=folder,stdout=log,stderr=subprocess.STDOUT,timeout=p['task_timeout_seconds'])
            if c.returncode:raise RuntimeError(f"Native task {t['label']} failed: {c.returncode}")
            completed.append(pin(folder/'result.json'));save(root/'progress.json',dict(at=now(),completed=completed))
        review(root)
    except Exception as exc:
        error=repr(exc);(root/'failure_traceback.txt').write_text(traceback.format_exc())
    save(root/'assessment.json',dict(at=now(),completed=len(completed),native_completed=len(completed)==10,error=error,requires_completion_audit=True,minimum_certified=False,simulation_ready=False))
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
    start=time.time();unit='cpd-corrected-anti1-electrostatic-core-pilot-v1'
    save(service/'watcher_config.json',dict(codex_executable=str(Path(shutil.which('codex')).resolve()),expected_seconds=p['expected_seconds'],review_deadline_epoch=start+1500,review_deadline_id='electrostatic-pilot-audit',self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=os.environ['CODEX_THREAD_ID'],command=[str(PYTHON),str(checked(p['worker'])),'run',str(root)],cwd=str(root),runtime_hours=.5,memory_gib=8,omp_threads=4,plan=pin(root/'plan.json'),completion_semantics=p['completion_semantics']))
    save(root/'launch_receipt.json',dict(at=now(),deadline_epoch=start+1800,unit=unit,prelaunch_memory=mem,execution_plan=pin(service/'execution_plan.json'),supervisor=pin(service/'supervisor.py'),watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=8G','--property=MemorySwapMax=0','--property=RuntimeMaxSec=1785s','--property=TimeoutStopSec=15s','--property=KillMode=control-group','--property=CPUQuota=400%',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4',f'--setenv=PSI_SCRATCH={root}/tmp',f'--setenv=TMPDIR={root}/tmp','/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)],check=True)
    print(service)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','launch','run','worker','review'));p.add_argument('root',nargs='?',type=Path,default=ROOT);p.add_argument('--label');args=p.parse_args();root=args.root.resolve()
    if args.action=='prepare':prepare()
    elif args.action=='worker':worker(root,args.label)
    elif args.action=='run':sys.exit(run(root))
    elif args.action=='review':print(review(root))
    else:launch(root)
