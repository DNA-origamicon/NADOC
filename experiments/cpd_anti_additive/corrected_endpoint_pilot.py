"""One corrected sugar endpoint gradient; completion-triggered audit before Sella."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

import numpy as np

REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import checked,now,pin,read,save,native_audit
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint
from experiments.cpd_anti_additive.audit_corrected_core_stage1 import parse_native_table
from experiments.cpd_anti_additive.endpoint_native import require_fitting_condition

CAMPAIGN=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
PYTHON=Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')


def prepare(seed_root):
    import psi4
    seed=read(seed_root/'assessment.json')
    assert seed['passed']
    auth=read(CAMPAIGN/'campaign_authorization_20261010.json')
    assert auth['user_authorized'] and auth['compute_policy']['cloud_spending_usd']==0
    model_ref=seed['models'][0];model=read(checked(model_ref))
    assert model['endpoint']==1 and read(checked(model['audit']))['passed']
    base=read(CAMPAIGN/'optimization/plan.json')
    root=CAMPAIGN/'endpoint-1-pilot-v1';root.mkdir(exist_ok=False)
    for name in ['scratch','tmp']: (root/name).mkdir()
    shutil.copy2(Path(__file__),root/'executed_source.py')
    x=np.load(checked(model['geometry']))/.529177210903
    np.save(root/'geometry_bohr.npy',x)
    save(root/'input.json',dict(elements=model['elements'],geometry_bohr=x.tolist(),
                              options=base['options'],method='mp2',charge=0,multiplicity=1))
    psi4.set_output_file(str(root/'basis_preflight.dat'),False)
    psi4.set_options(base['options'])
    text='\n'.join(el+' '+' '.join(f'{v:.17g}' for v in pos) for el,pos in zip(model['elements'],x))
    molecule=psi4.geometry('0 1\n'+text+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
    bases={}
    for key,role in [('BASIS','ORBITAL'),('DF_BASIS_SCF','JKFIT'),('DF_BASIS_MP2','RIFIT')]:
        kwargs={'puream':False} if key=='DF_BASIS_SCF' else {}
        b=psi4.core.BasisSet.build(molecule,key,'6-31G(d)' if key=='BASIS' else '',role,'6-31G(d)',**kwargs)
        bases[key]=dict(name=b.name(),nbf=b.nbf());b.print_detail_out()
    psi4.core.flush_outfile();psi4.core.close_outfile()
    save(root/'plan.json',dict(at=now(),worker=pin(root/'executed_source.py'),model=model_ref,
        seed_assessment=pin(seed_root/'assessment.json'),authorization=pin(CAMPAIGN/'campaign_authorization_20261010.json'),
        core_minimum=pin(CAMPAIGN/'core_local_minimum_assessment.json'),
        reference_design=pin(CAMPAIGN/'endpoint_reference_design_v1.json'),
        input=pin(root/'input.json'),geometry=pin(root/'geometry_bohr.npy'),options=base['options'],
        psi4_version=psi4.__version__,basis=bases,basis_preflight=pin(root/'basis_preflight.dat'),
        sources=[*seed['sources'],pin(REPO/'experiments/cpd_anti_additive/prepare_corrected_endpoints.py'),
            pin(REPO/'experiments/cpd_anti_additive/corrected_core_stage1.py'),
            pin(REPO/'experiments/cpd_anti_additive/endpoint_native.py'),
            pin(REPO/'experiments/cpd_anti_additive/audit_corrected_core_stage1.py')],
        maximum_gradients=1,hard_seconds=900,expected_seconds=240,threads=4,memory_gib=4,
        purpose='Measure endpoint-1 analytic gradient cost and electronic/geometry integrity; reuse exact gradient in subsequent Sella optimization if admitted.',
        completion_semantics='One gradient acquired, not optimized or minimum certified; audit before another native job.',
        minimum_certified=False,simulation_ready=False))
    save(root/'preflight.json',dict(at=now(),passed=audit_endpoint(x,model)['passed'],
        geometry=audit_endpoint(x,model),basis=bases,new_qm_evaluations=0))
    print(root)


def context(root):
    plan=read(root/'plan.json')
    assert checked(plan['worker'])==Path(__file__).resolve()
    for ref in plan['sources']:checked(ref)
    for key in ['authorization','core_minimum','reference_design','seed_assessment','basis_preflight']:checked(plan[key])
    assert read(checked(plan['authorization']))['user_authorized']
    assert plan['maximum_gradients']==1 and plan['hard_seconds']==900
    pause=CAMPAIGN/'pause.json'
    if pause.exists() and read(pause).get('paused'):raise RuntimeError('Campaign paused')
    if (root/'launch_receipt.json').exists():
        execution=read(checked(read(root/'launch_receipt.json')['execution_plan']))
        assert checked(execution['plan'])==root/'plan.json'
    return plan,read(checked(plan['model']))


def run(root):
    plan,model=context(root)
    with (root/'started.json').open('x') as f:f.write(now()+'\n')
    error=None;done=False;start=time.monotonic()
    try:
        import psi4
        assert psi4.__version__==plan['psi4_version']
        inp=read(checked(plan['input']));x=np.load(checked(plan['geometry']))
        assert np.array_equal(x,np.array(inp['geometry_bohr'])) and inp['options']==plan['options']
        assert audit_endpoint(x,model)['passed']
        os.chdir(root)
        psi4.set_output_file(str(root/'output.dat'),False)
        psi4.set_memory('4 GiB');psi4.set_num_threads(4)
        psi4.core.IOManager.shared_object().set_default_path(str(root/'scratch'))
        psi4.set_options(plan['options'])
        text='\n'.join(el+' '+' '.join(f'{v:.17g}' for v in pos) for el,pos in zip(inp['elements'],x))
        molecule=psi4.geometry('0 1\n'+text+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
        stamp=time.monotonic();grad,wfn=psi4.gradient('mp2',molecule=molecule,return_wfn=True)
        elapsed=time.monotonic()-stamp;g=np.asarray(grad).copy();e=float(wfn.energy())
        actual=np.asarray(wfn.molecule().geometry()).copy()
        save(root/'raw_result.json',dict(energy_hartree=e,gradient_hartree_bohr=g.tolist(),
            returned_geometry_bohr=actual.tolist(),wall_seconds=elapsed,
            input=plan['input'],geometry=plan['geometry'],audit_pending=True))
        assert np.max(abs(actual-x))<1e-14 and audit_endpoint(actual,model)['passed']
        psi4.core.clean();psi4.core.flush_outfile();psi4.core.close_outfile()
        native=(root/'output.dat').read_text();audit=native_audit(native,e,g)
        en,gn=parse_native_table(native,len(x))
        assert abs(en-e)<1e-9 and np.max(abs(gn-g))<1e-11
        require_fitting_condition(native)
        save(root/'result.json',dict(at=now(),input=plan['input'],geometry=plan['geometry'],native=pin(root/'output.dat'),
            returned_geometry_bohr=actual.tolist(),energy_hartree=e,gradient_hartree_bohr=g.tolist(),
            wall_seconds=elapsed,native_audit=audit,minimum_certified=False))
        done=True
    except Exception as exc:
        error=repr(exc);(root/'failure_traceback.txt').write_text(traceback.format_exc())
    save(root/'assessment.json',dict(at=now(),error=error,native_completed=done,new_gradients=1 if done else 0,
        wall_seconds=time.monotonic()-start,minimum_certified=False,simulation_ready=False))
    return 1 if error else 0


def launch(root):
    # Verify using frozen module; then one bounded service and its event watcher.
    import importlib.util
    spec=importlib.util.spec_from_file_location('frozen_endpoint_pilot',root/'executed_source.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    plan,_=module.context(root)
    assert read(root/'preflight.json')['passed']
    units=subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'],text=True)
    if any('cpd-' in row and '-watch' not in row for row in units.splitlines()):raise RuntimeError('Other CPD job active')
    processes=subprocess.check_output(['ps','-eo','args='],text=True).splitlines()
    if any(row.strip().split(' ')[0].split('/')[-1] in ('namd2','namd3','psi4') for row in processes):raise RuntimeError('Other native job active')
    mem={row.split(':')[0]:int(row.split()[1])*1024 for row in Path('/proc/meminfo').read_text().splitlines()
         if row.startswith(('MemAvailable:','SwapFree:'))}
    if mem['MemAvailable']<12*1024**3 or shutil.disk_usage(root).free<30*1024**3:raise RuntimeError('Resource headroom insufficient')
    service=CAMPAIGN/(root.name+'-service');service.mkdir(exist_ok=False)
    for old,new in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:shutil.copy2(REPO/'experiments/cpd_anti_additive'/old,service/new)
    stamp=time.time();unit='cpd-corrected-anti1-endpoint1-pilot-v1'
    save(service/'watcher_config.json',dict(codex_executable=str(Path(shutil.which('codex')).resolve()),
        expected_seconds=plan['expected_seconds'],review_deadline_epoch=stamp+720,review_deadline_id='endpoint1-pilot-audit',self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=os.environ['CODEX_THREAD_ID'],
        command=[str(PYTHON),str(root/'executed_source.py'),'run',str(root)],cwd=str(root),
        runtime_hours=.25,memory_gib=8,omp_threads=4,plan=pin(root/'plan.json'),completion_semantics=plan['completion_semantics']))
    save(root/'launch_receipt.json',dict(at=now(),unit=unit,deadline_epoch=stamp+900,prelaunch_memory=mem,
        execution_plan=pin(service/'execution_plan.json'),supervisor=pin(service/'supervisor.py'),watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=8G','--property=MemorySwapMax=0',
        '--property=RuntimeMaxSec=885s','--property=TimeoutStopSec=15s','--property=KillMode=control-group','--property=CPUQuota=400%',
        f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=PYTHONDONTWRITEBYTECODE=1',
        '--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4',
        f'--setenv=PSI_SCRATCH={root}/tmp',f'--setenv=TMPDIR={root}/tmp',
        '/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)],check=True)
    print(service)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','run','launch'));p.add_argument('root',type=Path)
    args=p.parse_args();result=globals()[args.action](args.root.resolve())
    if args.action=='run':sys.exit(result)
