"""Prepare the diagnostic Hessian after the original-method curvature pilot."""
from pathlib import Path
import argparse
import os
import shutil
import sys

import numpy as np

REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import checked,now,pin,read,save,geometry_audit
from experiments.cpd_anti_additive.corrected_core_hessian import dump_task,analytic_gradient_input
from experiments.cpd_anti_additive.prepare_corrected_core_hessian import launch

CAMPAIGN=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
ROOT=CAMPAIGN/'hessian-stage2-v3'


def prepare():
    decision_path=CAMPAIGN/'curvature_to_hessian_admission.json'
    decision=read(decision_path)
    if not decision['proceed_with_diagnostic_hessian']:
        raise ValueError('No numerical admission')
    stage=read(CAMPAIGN/'stage1_completion_audit.json')
    plan=read(checked(stage['plan']))
    if not stage['passed']:
        raise ValueError('No stationary candidate')
    for ref in plan['sources']:checked(ref)
    ROOT.mkdir(exist_ok=False)
    for name in ['tmp','planning-scratch']:(ROOT/name).mkdir()
    os.environ['PSI_SCRATCH']=str(ROOT/'planning-scratch')
    import psi4,qcengine,qcelemental
    os.chdir(ROOT)
    psi4.core.IOManager.shared_object().set_default_path(str(ROOT/'planning-scratch'))
    psi4.set_output_file(str(ROOT/'planning.dat'),False)
    psi4.set_memory('4 GiB');psi4.set_num_threads(4)
    psi4.set_options(plan['options'])
    psi4.set_options({'findif__disp_size':decision['displacement_size']})
    x=np.load(checked(stage['final_binary_geometry']))
    text='\n'.join(el+' '+' '.join(f'{v:.17g}' for v in xyz) for el,xyz in zip(plan['elements'],x))
    molecule=psi4.geometry('0 1\n'+text+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
    fd=psi4.hessian('mp2',molecule=molecule,return_plan=True)
    if len(fd.task_list)!=211 or fd.findifrec['step']['size']!=decision['displacement_size']:
        raise ValueError('Unexpected displacement allocation')
    records=[];coordinates=[]
    for i,(label,computer) in enumerate(fd.task_list.items()):
        data=computer.plan().model_dump(mode='json')
        data=analytic_gradient_input(data,decision['displacement_size'])
        folder=ROOT/'tasks'/f'{i:03d}';folder.mkdir(parents=True)
        (folder/'input.json').write_bytes(dump_task(data))
        q=np.array(data['molecule']['geometry']).reshape(-1,3)
        if not geometry_audit(q,plan)['passed']:
            raise ValueError('Displaced geometry failed corrected identity')
        coordinates.append(q)
        records.append(dict(id=f'gradient-{i:03d}',index=i,label=label,
            input=dict(path=str((folder/'input.json').relative_to(ROOT)),sha256=pin(folder/'input.json')['sha256']),
            result=dict(path=str((folder/'result.json').relative_to(ROOT))),
            run_record=dict(path=str((folder/'run_record.json').relative_to(ROOT)))))
    original=CAMPAIGN/'hessian-stage2-v1'
    old_input=original/'tasks/000/input.json'
    if old_input.read_bytes()!=(ROOT/'tasks/000/input.json').read_bytes():
        raise ValueError('Reference cannot be reused: planned input bytes differ')
    midpoint=max(float(np.max(abs(.5*(coordinates[i]+coordinates[i+1])-x))) for i in range(1,211,2))
    if midpoint>1e-12:
        raise ValueError('Displaced pairs have changed reference')
    engine=dict(name='Psi4',version=psi4.__version__,qcengine_version=qcengine.__version__,qcelemental_version=qcelemental.__version__)
    finite_difference={key:fd.findifrec[key] for key in ['step','stencil_size']}
    finite_difference.update(mode=fd.metameta['mode'],point_group='c1')
    save(ROOT/'distributed_hessian_plan.json',dict(schema='nadoc.photoproduct-distributed-hessian-plan.v1',
        status='prepared_not_run',gate_effect='none',product_id='tt-cpd-cis-anti-i',
        model_id='corrected-n1-methyl-cis-anti-i-v1',task_count=211,tasks=records,engine=engine,
        method='mp2',basis='6-31g(d)',default_resources_per_task=dict(threads=4,memory_gib=4),
        finite_difference=finite_difference,assembly_scope='Diagnostic only; raw numerical and low-mode review required.'))
    save(ROOT/'reference_reuse.json',dict(at=now(),source_run_record=pin(original/'tasks/000/run_record.json'),
        source_input=pin(old_input),source_plan=pin(original/'distributed_hessian_plan.json'),
        admission=pin(decision_path),byte_identical_input=True,new_qm_evaluations=0,
        scope='Reuse a successfully completed native gradient. Preserve the failed old reference-equality verdict; no claim that the old batch passed.'))
    for name in ['corrected_core_hessian.py','prepare_corrected_core_hessian_v2.py']:
        shutil.copy2(REPO/'experiments/cpd_anti_additive'/name,ROOT/name)
    sources=[pin(REPO/name) for name in [
        'experiments/cpd_anti_additive/corrected_core_stage1.py',
        'experiments/cpd_anti_additive/audit_corrected_core_stage1.py',
        'experiments/cpd_anti_additive/prepare_corrected_core_hessian.py',
        'backend/parameterization/photoproduct_distributed_hessian.py',
        'backend/parameterization/photoproduct_qm.py']]
    import psi4.driver.driver_findif as findif_source
    sources += [pin(Path(findif_source.__file__)),pin(ROOT/'prepare_corrected_core_hessian_v2.py'),
                pin(CAMPAIGN/'original-method-curvature-pilot-v1/completion_audit.json')]
    audit=read(CAMPAIGN/'original-method-curvature-pilot-v1/completion_audit.json')
    mean=audit['native_seconds']/4
    batches=[dict(id='batch-1',task_indices=list(range(105)),expected_gradient_hours=104*mean/3600,
                  new_gradients=104,reused_gradients=1,wall_cap_hours=3),
             dict(id='batch-2',task_indices=list(range(105,211)),expected_gradient_hours=106*mean/3600,
                  new_gradients=106,reused_gradients=0,wall_cap_hours=3)]
    save(ROOT/'manifest.json',dict(at=now(),campaign_root=str(CAMPAIGN),
        campaign_authorization=pin(CAMPAIGN/'campaign_authorization_20261010.json'),
        stage1_audit=pin(CAMPAIGN/'stage1_completion_audit.json'),
        worker=pin(ROOT/'corrected_core_hessian.py'),distributed_plan=pin(ROOT/'distributed_hessian_plan.json'),
        numerical_admission=pin(decision_path),diagnostic_only=True,displacement_size=decision['displacement_size'],
        strip_findif_displacement_keyword=True,
        gradient_input_normalization='Remove only FINDIF__DISP_SIZE from fixed-geometry analytic MP2 gradient tasks. Retain the size in the finite-difference plan and exact displaced geometries; replay verifies every normalized input byte.',
        reused_reference=pin(ROOT/'reference_reuse.json'),sources=sources,engine=engine,
        allowed_batches=['batch-1','batch-2'],batches=batches,expected_gradient_seconds=mean,
        minimum_certified=False,gate_effect='none',
        next_audit='Batch one completion audit before batch two admission. Final assembly does not certify; assess raw antisymmetry and resolved/unresolved low modes first.'))
    psi4.core.flush_outfile();psi4.core.close_outfile()
    save(ROOT/'preparation_audit.json',dict(at=now(),task_count=211,displaced_pairs=105,
        new_qm_evaluations=0,reference_byte_identical=True,all_geometries_passed=True,
        paired_midpoint_error_bohr=midpoint,finite_difference=finite_difference,
        maximum_cartesian_displacement_bohr=max(float(np.max(abs(q-x))) for q in coordinates),
        planning_log=pin(ROOT/'planning.dat'),
        step_caveat='Psi4 displaces mass-weighted symmetry-adapted Cartesian coordinates. This is not identical to the pilot normalized Cartesian direction; that pilot motivates diagnostic acquisition, not all-direction error qualification.'))
    print(ROOT)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','launch'))
    parser.add_argument('--batch',choices=('batch-1','batch-2'),default='batch-1')
    args=parser.parse_args()
    if args.action=='prepare':prepare()
    else:launch(args.batch,root=ROOT,unit_version='v3',proposal=read(ROOT/'manifest.json'))
