"""One original-method gradient at the observed alternate sugar conformation."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys
import time
import traceback
import numpy as np

REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now
from experiments.cpd_anti_additive.corrected_coupled_ring import require_archive
from experiments.cpd_anti_additive.corrected_bonded_baseline import BOHR,EH
from experiments.cpd_anti_additive.corrected_fixed_core_boundary import free_projection
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint
from experiments.cpd_anti_additive.endpoint_native import audit_native
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion,wrapped

CAMPAIGN=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
ROOT=CAMPAIGN/'alternate-sugar-qm-pilot-v1'
PYTHON=Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')


def context(root):
    require_archive(root);p=read(root/'plan.json')
    if checked(p['worker'])!=Path(__file__).resolve():raise ValueError('Use frozen worker')
    for ref in p['sources']:checked(ref)
    for key in ['model','input','geometry','authorization','reference_result']:checked(p[key])
    auth=read(checked(p['authorization']))
    assert auth['user_authorized'] and auth['compute_policy']['cloud_spending_usd']==0
    assert p['maximum_gradients']==1 and p['hard_seconds']==900 and p['native_timeout_seconds']==600
    if (CAMPAIGN/'pause.json').exists() and read(CAMPAIGN/'pause.json').get('paused'):raise RuntimeError('Campaign paused')
    if (root/'launch_receipt.json').exists():
        assert checked(read(checked(read(root/'launch_receipt.json')['execution_plan']))['plan'])==root/'plan.json'
    return p,read(checked(p['model']))


def prepare():
    import psi4
    require_archive(CAMPAIGN)
    auditpath=CAMPAIGN/'fixed-core-boundary-v1/completion_audit.json';audit=read(auditpath)
    assert audit['passed'] and audit['alternate_qm_gradient_pilot_admitted']
    old=read(checked(audit['plan']));record=next(v for v in audit['records'] if v['offset_degrees']==0)
    mm=read(checked(record['assessment']));point=mm['point'];reference=read(checked(point['qm_result']))
    inp=read(checked(reference['input']));model=read(checked(old['model']));refx=np.load(checked(reference['geometry']))
    en,gn,reference_native=audit_native(checked(reference['native']).read_text(),model['elements'],refx)
    assert abs(en-reference['energy_hartree'])<1e-9 and np.max(abs(gn-np.array(reference['gradient_hartree_bohr'])))<1e-11
    x=np.load(checked(mm['final_geometry']))/BOHR
    drift=float(np.max(abs(x[old['fixed_indices']]-refx[old['fixed_indices']])))
    assert drift<1e-10
    x[old['fixed_indices']]=refx[old['fixed_indices']]
    assert audit_endpoint(x,model)['passed']
    chi_error=abs(wrapped(torsion(x,point['constraint']['indices'])-point['constraint']['target_degrees']))
    assert chi_error<.01
    ROOT.mkdir();(ROOT/'tmp').mkdir();(ROOT/'scratch').mkdir();shutil.copy2(Path(__file__),ROOT/'executed_source.py')
    np.save(ROOT/'geometry_bohr.npy',x)
    save(ROOT/'input.json',dict(at=now(),elements=model['elements'],geometry_bohr=x.tolist(),options=inp['options'],method='mp2',charge=0,multiplicity=1))
    psi4.set_output_file(str(ROOT/'basis_preflight.dat'),False);psi4.set_options(inp['options'])
    text='\n'.join(e+' '+' '.join(f'{v:.17g}' for v in q) for e,q in zip(model['elements'],x))
    molecule=psi4.geometry('0 1\n'+text+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
    bases={}
    for key,role in [('BASIS','ORBITAL'),('DF_BASIS_SCF','JKFIT'),('DF_BASIS_MP2','RIFIT')]:
        kwargs={'puream':False} if key=='DF_BASIS_SCF' else {}
        b=psi4.core.BasisSet.build(molecule,key,'6-31G(d)' if key=='BASIS' else '',role,'6-31G(d)',**kwargs)
        bases[key]=dict(name=b.name(),nbf=b.nbf());b.print_detail_out()
    psi4.core.flush_outfile();psi4.core.close_outfile()
    assert [bases[k]['nbf'] for k in ['BASIS','DF_BASIS_SCF','DF_BASIS_MP2']]==[449,2737,1820]
    sources=[pin(auditpath),audit['plan'],record['assessment'],mm['final_geometry'],point['qm_result'],reference['geometry'],reference['native'],reference['input'],
             old['model'],model['sdf'],model['graph'],model['definition'],pin(CAMPAIGN/'endpoint_reference_design_v1.json'),pin(ROOT/'basis_preflight.dat')]
    for name in ['corrected_core_stage1.py','corrected_coupled_ring.py','corrected_bonded_baseline.py','corrected_fixed_core_boundary.py',
                 'corrected_mm_endpoint_profile.py','prepare_corrected_endpoints.py','endpoint_native.py','audit_corrected_core_stage1.py','endpoint_scan_geometry.py']:
        sources.append(pin(REPO/'experiments/cpd_anti_additive'/name))
    plan=dict(at=now(),worker=pin(ROOT/'executed_source.py'),sources=sources,authorization=old['authorization'],model=old['model'],
        input=pin(ROOT/'input.json'),geometry=pin(ROOT/'geometry_bohr.npy'),reference_result=point['qm_result'],reference_geometry=reference['geometry'],
        mm_alternative=mm['final_geometry'],fixed_indices=old['fixed_indices'],free_indices=old['free_indices'],constraint=point['constraint'],
        options=inp['options'],psi4_version=psi4.__version__,basis=bases,
        coordinate_conversion=dict(mm_angstrom_per_bohr=BOHR,maximum_roundoff_fixed_coordinate_restoration_bohr=drift,
            rule='Convert audited MM coordinates using the same Bohr factor used to construct its QM seed; restore32fixed atoms exactly from original native QM reference. This removes solver roundoff, not a geometry optimization.'),
        maximum_gradients=1,hard_seconds=900,native_timeout_seconds=600,expected_seconds=300,threads=4,psi4_memory_gib=4,service_memory_gib=8,
        purpose='One MP2/6-31G(d) original-method gradient at the offset0 alternate MM sugar conformation. Compare vertical QM energy and50-dimensional tangent forces with the existing QM conformer. Resolve whether a QM basin-closure attempt is necessary before refitting standard sugar or CPD-boundary terms.',
        decision_boundary='A lower single-point energy can show the old conformer is not globally lowest within this conditioned domain; higher energy or large force does not exclude a lower nearby alternate minimum. No basin preference, barrier, minimum or rate inferred from this one point. Audit native method, energy, force direction and cost before any separately bounded optimization.',
        completion_semantics='One native gradient, not an optimization or minimum certification; raw results saved before validation. Original SCF/response tolerances and fitting condition unchanged.',
        new_fit=False,heldout_accessed=False,minimum_certified=False,basin_closure_certified=False,simulation_ready=False,cloud_spending_usd=0)
    save(ROOT/'plan.json',plan);save(ROOT/'preflight.json',dict(at=now(),passed=True,plan=pin(ROOT/'plan.json'),geometry=audit_endpoint(x,model),basis=bases,
        reference_native_audit=reference_native,exact_fixed_reference_coordinates=True,chi_error_degrees=chi_error,new_qm_evaluations=0))
    print(dict(root=str(ROOT),basis=bases,chi_error_degrees=chi_error,fixed_roundoff_bohr=drift,prior_gradient_seconds=reference['wall_seconds']))


def gradient(root):
    p,model=context(root)
    with (root/'native_started.json').open('x') as f:f.write(now()+'\n')
    import psi4
    assert psi4.__version__==p['psi4_version']
    inp=read(checked(p['input']));x=np.load(checked(p['geometry']))
    assert inp['options']==p['options'] and np.array_equal(x,np.array(inp['geometry_bohr'])) and audit_endpoint(x,model)['passed']
    os.chdir(root);psi4.set_output_file(str(root/'output.dat'),False);psi4.set_memory('4 GiB');psi4.set_num_threads(4)
    psi4.core.IOManager.shared_object().set_default_path(str(root/'scratch'));psi4.set_options(p['options'])
    text='\n'.join(e+' '+' '.join(f'{v:.17g}' for v in q) for e,q in zip(model['elements'],x))
    molecule=psi4.geometry('0 1\n'+text+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
    stamp=time.monotonic();grad,wfn=psi4.gradient('mp2',molecule=molecule,return_wfn=True)
    elapsed=time.monotonic()-stamp;e=float(wfn.energy());g=np.asarray(grad).copy();actual=np.asarray(wfn.molecule().geometry()).copy()
    np.save(root/'gradient_hartree_bohr.npy',g);np.save(root/'returned_geometry_bohr.npy',actual)
    raw=dict(at=now(),input=p['input'],geometry=p['geometry'],energy_hartree=e,gradient_hartree_bohr=g.tolist(),
        returned_geometry=pin(root/'returned_geometry_bohr.npy'),gradient_binary=pin(root/'gradient_hartree_bohr.npy'),wall_seconds=elapsed)
    save(root/'raw_result.json',raw);psi4.core.flush_outfile();psi4.core.close_outfile()
    assert np.max(abs(actual-x))<1e-14 and audit_endpoint(actual,model)['passed']
    en,gn,native=audit_native((root/'output.dat').read_text(),model['elements'],x)
    assert abs(en-e)<1e-9 and np.max(abs(gn-g))<5.1e-13
    reference=read(checked(p['reference_result']));projected=free_projection(x*BOHR,g*EH/BOHR,p['fixed_indices'],p['constraint']['indices'])
    save(root/'result.json',dict(**raw,native=pin(root/'output.dat'),native_audit=native,
        energy_relative_to_reference_kcal_mol=(e-reference['energy_hartree'])*EH,
        free_projected_max_atom_gradient_kcal_mol_A=float(np.linalg.norm(projected,axis=1).max()),
        minimum_certified=False,basin_closure_certified=False,simulation_ready=False))


def run(root):
    p,_=context(root);assert read(root/'admission.json')['passed'];start=time.monotonic();error=None
    with (root/'started.json').open('x') as f:f.write(now()+'\n')
    try:
        with (root/'native_runner.log').open('x') as log:
            child=subprocess.run([str(PYTHON),str(checked(p['worker'])),'gradient',str(root)],cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=600)
        if child.returncode:raise RuntimeError(f'Native gradient failed:{child.returncode}')
        checked(pin(root/'result.json'))
    except Exception as exc:
        error=repr(exc);(root/'failure_traceback.txt').write_text(traceback.format_exc())
    save(root/'assessment.json',dict(at=now(),error=error,wall_seconds=time.monotonic()-start,attempted_gradients=1,
        completed_gradients=1 if error is None else 0,requires_completion_audit=True,minimum_certified=False,simulation_ready=False))
    return 1 if error else 0


def launch(root):
    p,_=context(root);assert read(root/'preflight.json')['passed'] and read(root/'admission.json')['passed']
    units=subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'],text=True)
    if any('cpd-' in line and '-watch' not in line for line in units.splitlines()):raise RuntimeError('Another CPD calculation active')
    processes=subprocess.check_output(['ps','-eo','args='],text=True).splitlines()
    if any(row.strip().split(' ')[0].split('/')[-1] in ('namd2','namd3','psi4') for row in processes):raise RuntimeError('Another native job active')
    available=int(next(v.split()[1] for v in Path('/proc/meminfo').read_text().splitlines() if v.startswith('MemAvailable:')))*1024
    if available<12*1024**3 or shutil.disk_usage(root).free<30*1024**3:raise RuntimeError('Insufficient headroom')
    service=CAMPAIGN/(root.name+'-service');service.mkdir()
    for old,new in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:shutil.copy2(REPO/'experiments/cpd_anti_additive'/old,service/new)
    start=time.time();unit='cpd-corrected-anti1-alternate-sugar-qm-pilot-v1'
    save(service/'watcher_config.json',dict(codex_executable=str(Path(shutil.which('codex')).resolve()),expected_seconds=300,review_deadline_epoch=start+720,review_deadline_id='alternate-sugar-qm-pilot-audit',self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=os.environ['CODEX_THREAD_ID'],command=[str(PYTHON),str(checked(p['worker'])),'run',str(root)],cwd=str(root),runtime_hours=.25,memory_gib=8,omp_threads=4,plan=pin(root/'plan.json'),completion_semantics=p['completion_semantics']))
    save(root/'launch_receipt.json',dict(at=now(),deadline_epoch=start+900,unit=unit,available_memory_gib=available/1024**3,execution_plan=pin(service/'execution_plan.json'),supervisor=pin(service/'supervisor.py'),watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=8G','--property=MemorySwapMax=0','--property=RuntimeMaxSec=885s','--property=TimeoutStopSec=15s','--property=KillMode=control-group','--property=CPUQuota=400%',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4',f'--setenv=TMPDIR={root}/tmp',f'--setenv=PSI_SCRATCH={root}/scratch','/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)],check=True)
    print(service)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','gradient','run','launch'])
    parser.add_argument('root',nargs='?',type=Path,default=ROOT);args=parser.parse_args();root=args.root.resolve()
    if args.action=='prepare':prepare()
    elif args.action=='gradient':gradient(root)
    elif args.action=='run':sys.exit(run(root))
    else:launch(root)
