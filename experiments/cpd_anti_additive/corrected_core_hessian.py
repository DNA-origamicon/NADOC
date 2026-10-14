"""Sequential, checkpointed Hessian batches for the corrected stationary core.

Reuse the existing QCEngine worker, preserving its native output and exact task
inputs. The two batches are separately admitted; this module never launches one.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback

import numpy as np

REPO = Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import checked, now, pin, read, save
from experiments.cpd_anti_additive.audit_corrected_core_stage1 import parse_native_table


def dump_task(value):
    return (json.dumps(value,indent=2)+'\n').encode()


def analytic_gradient_input(value,step):
    """Remove only displacement-generation metadata from an analytic task.

    DISP_SIZE is retained in the Hessian manifest and exact displaced geometry;
    it does not enter an analytic MP2 gradient at a supplied fixed geometry.
    Work on a copy so the engine plan and original evidence are not mutated.
    """
    from copy import deepcopy
    value=deepcopy(value)
    spec=value['specification']
    if spec['driver']!='gradient' or spec['model']['method']!='mp2':
        raise ValueError('Normalization requires analytic MP2 gradient tasks')
    if spec['keywords'].pop('FINDIF__DISP_SIZE',None)!=step:
        raise ValueError('Unexpected displacement keyword; refuse normalization')
    return value


def load_context(root):
    manifest=read(root/'manifest.json')
    auth=read(checked(manifest['campaign_authorization']))
    if not auth.get('user_authorized') or auth.get('compute_policy',{}).get('cloud_spending_usd')!=0:
        raise ValueError('Campaign authority missing')
    if manifest.get('diagnostic_only'):
        decision=read(checked(manifest['numerical_admission']))
        if not decision['proceed_with_diagnostic_hessian']:
            raise ValueError('Diagnostic Hessian not admitted')
        if manifest['displacement_size']!=decision['displacement_size']:
            raise ValueError('Displacement policy changed')
    if checked(manifest['worker'])!=Path(__file__).resolve():
        raise ValueError('Not executing the frozen worker')
    for ref in manifest['sources']: checked(ref)
    stage=read(checked(manifest['stage1_audit']))
    plan=read(checked(stage['plan']))
    for ref in plan['sources']: checked(ref)
    source=checked(stage['frozen_worker'])
    spec=importlib.util.spec_from_file_location('corrected_identity',source)
    identity=importlib.util.module_from_spec(spec);spec.loader.exec_module(identity)
    return manifest,stage,plan,identity


def rebuild(root):
    """Recreate every planned displacement without an electronic calculation."""
    import psi4
    manifest,stage,plan,identity=load_context(root)
    if psi4.__version__!=manifest['engine']['version']:
        raise ValueError('Psi4 version changed')
    scratch=root/'planning-scratch';scratch.mkdir(exist_ok=True)
    psi4.core.IOManager.shared_object().set_default_path(str(scratch))
    psi4.core.clean_options()
    psi4.set_memory('4 GiB');psi4.set_num_threads(4)
    psi4.set_options(plan['options'])
    if 'displacement_size' in manifest:
        psi4.set_options({'findif__disp_size':manifest['displacement_size']})
    x=np.load(checked(stage['final_binary_geometry']))
    lines='\n'.join(el+' '+' '.join(f'{v:.17g}' for v in pos) for el,pos in zip(plan['elements'],x))
    molecule=psi4.geometry('0 1\n'+lines+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
    fd=psi4.hessian('mp2',molecule=molecule,return_plan=True)
    records=read(checked(manifest['distributed_plan']))['tasks']
    if fd.__class__.__name__!='FiniteDifferenceComputer' or len(fd.task_list)!=211:
        raise ValueError('Unexpected finite-difference plan')
    for (label,task),record in zip(fd.task_list.items(),records,strict=True):
        path=root/record['input']['path']
        generated=task.plan().model_dump(mode='json')
        if manifest.get('strip_findif_displacement_keyword'):
            generated=analytic_gradient_input(generated,manifest['displacement_size'])
        if label!=record['label'] or dump_task(generated)!=path.read_bytes():
            raise ValueError(f'Regenerated task differs from immutable preview: {label}')
        if pin(path)['sha256']!=record['input']['sha256']:
            raise ValueError('Task hash changed')
        data=read(path)
        x=np.array(data['molecule']['geometry']).reshape(-1,3)
        if not identity.geometry_audit(x,plan)['passed']:
            raise ValueError('Displacement failed corrected identity')
    return fd,molecule


def task_audit(root,index):
    from qcelemental.models.v2 import AtomicResult
    manifest,stage,plan,identity=load_context(root)
    distributed=read(checked(manifest['distributed_plan']))
    task=distributed['tasks'][index]
    folder=root/task['result']['path'];folder=folder.parent
    reused=index==0 and bool(manifest.get('reused_reference'))
    if reused:
        reuse=read(checked(manifest['reused_reference']))
        source_record=checked(reuse['source_run_record'])
        record=read(source_record)
        old_plan=checked(reuse['source_plan'])
        if (record['plan_sha256']!=pin(old_plan)['sha256'] or
                checked(reuse['source_input']).read_bytes()!=(root/task['input']['path']).read_bytes()):
            raise ValueError('Reused reference is not byte-identical')
    else:
        source_record=folder/'run_record.json'
        record=read(source_record)
    if (record['status']!='completed_unreviewed' or record['task_id']!=task['id'] or
            (not reused and record['plan_sha256']!=manifest['distributed_plan']['sha256']) or
            record['input_sha256']!=task['input']['sha256']):
        raise ValueError('Incomplete, failed or mismatched result record')
    result_path=checked(record['result'])
    obj=AtomicResult.model_validate_json(result_path.read_text())
    result=obj.model_dump(mode='json')
    source=read(root/task['input']['path'])
    if not obj.success or result['input_data']!=source:
        raise ValueError('Task result does not match the exact input')
    for key in ('version','qcengine_version','qcelemental_version'):
        if record['engine'][key]!=manifest['engine'][key]:
            raise ValueError('QM engine stack changed')
    if str(obj.provenance.version)!=manifest['engine']['version']:
        raise ValueError('Result engine provenance changed')
    x=np.array(source['molecule']['geometry']).reshape(-1,3)
    if source['molecule']['symbols']!=plan['elements'] or not identity.geometry_audit(x,plan)['passed']:
        raise ValueError('Task geometry failed')
    gradient=np.array(obj.return_result).reshape(-1,3)
    energy=float(obj.properties.return_energy)
    native=obj.stdout
    if not isinstance(native,str):
        raise ValueError('Native stdout is absent')
    native_path=folder/'output.dat'
    if native_path.exists():
        if native_path.read_text()!=native:
            raise ValueError('Existing native output differs from QCSchema stdout')
    else:
        with native_path.open('x') as stream:stream.write(native)
    electronic=identity.native_audit(native,energy,gradient)
    table_energy,table_gradient=parse_native_table(native,len(x))
    delta=float(np.max(abs(gradient-table_gradient)))
    if delta>1e-11 or abs(energy-table_energy)>1e-9:
        raise ValueError('QCSchema energy/gradient differs from native table')
    scratch_root=source_record.parents[2] if reused else root
    if not Path(record['execution']['psi4_psio_default_path']).is_relative_to(scratch_root):
        raise ValueError('Psi4 scratch escaped Archive root')
    reference=None
    if index==0:
        old=read(checked(stage['final_result']))
        reference=dict(energy_delta_hartree=abs(energy-old['energy_hartree']),
                       max_gradient_delta_au=float(np.max(abs(gradient-np.array(old['gradient_hartree_bohr'])))))
        if manifest.get('diagnostic_only'):
            if not reused or not stage['passed'] or not identity.stationary(electronic):
                raise ValueError('Diagnostic reference must retain independently verified stationarity')
            reference['scope']='Exact reused original-method reference, independently stationary. Original equality-gate failure preserved; this is diagnostic acquisition admission only.'
        elif reference['energy_delta_hartree']>1e-8 or reference['max_gradient_delta_au']>1e-8:
            raise ValueError('Independent reference disagrees with optimization')
    return dict(index=index,label=task['label'],passed=True,input=pin(root/task['input']['path']),
                result=pin(result_path),run_record=pin(source_record),native=pin(native_path),
                electronic=electronic,native_gradient_max_difference_au=delta,
                reference_agreement=reference,wall_seconds=record['execution']['elapsed_seconds'],reused=reused)


def execution_groups(indices):
    indices=list(indices)
    groups=[]
    if indices and indices[0]==0:
        groups.append([0]);indices=indices[1:]
    if len(indices)%2:
        raise ValueError('Displacement pair is split')
    for a,b in zip(indices[::2],indices[1::2]):
        if a%2!=1 or b!=a+1:
            raise ValueError('Displacement pair is split')
        groups.append([a,b])
    return groups


def admit_group(remaining_seconds,tasks,observed_seconds):
    estimate=max([60.59254043805413,*observed_seconds])*1.5
    if remaining_seconds < tasks*estimate+120:
        raise RuntimeError('Insufficient boundary time for a complete pair and audit')
    return min(600.,max(300.,3*max([60.59254043805413,*observed_seconds])))


def run_batch(root,batch_id):
    manifest,stage,plan,identity=load_context(root)
    batch=root/batch_id
    bp=read(batch/'plan.json')
    expected=list(range(105)) if batch_id=='batch-1' else list(range(105,211))
    if (bp['batch_id']!=batch_id or bp['hard_seconds']!=10800 or
            bp['task_indices']!=expected):
        raise ValueError('Batch allocation changed')
    checked(bp['manifest']);checked(bp['authorization'])
    if batch_id=='batch-2':
        decision=read(checked(bp['preceding_audit_decision']))
        if not decision['proceed'] or not read(checked(decision['batch_review']))['passed']:
            raise ValueError('Batch one has not been admitted for continuation')
    with (batch/'started.json').open('x') as f:
        json.dump(dict(at=now(),pid=os.getpid()),f)
    os.chdir(batch)
    started=time.monotonic()
    deadline=read(batch/'launch_receipt.json')['deadline_epoch']
    completed=[];durations=[];error=None
    save(batch/'progress.json',dict(completed=completed,in_flight=None))
    try:
        import psi4
        psi4.set_output_file(str(batch/'plan_replay.dat'),False)
        rebuild(root)
        psi4.core.flush_outfile()
        tasks=read(checked(manifest['distributed_plan']))['tasks']
        for group in execution_groups(bp['task_indices']):
            pause=Path(manifest['campaign_root'])/'pause.json'
            if pause.exists() and read(pause).get('paused'):
                raise RuntimeError('Campaign paused at task boundary')
            timeout=admit_group(deadline-time.time(),len(group),durations)
            for index in group:
                if pause.exists() and read(pause).get('paused'):
                    raise RuntimeError('Campaign paused; partial pair remains explicitly incomplete')
                task=tasks[index];folder=(root/task['result']['path']).parent
                if index==0 and manifest.get('reused_reference'):
                    audit=task_audit(root,index)
                    save(folder/'task_audit.json',audit)
                    completed.append(dict(index=index,audit=pin(folder/'task_audit.json')))
                    save(batch/'progress.json',dict(completed=completed,in_flight=None,
                         elapsed_seconds=time.monotonic()-started,reused_reference=True))
                    continue
                if any((folder/n).exists() for n in ('result.json','run_record.json','task_started.json')):
                    raise FileExistsError('Refuse automatic overwrite/retry of a prior task')
                scratch=folder/'scratch';scratch.mkdir(exist_ok=False)
                save(folder/'task_started.json',dict(at=now(),task=task['id'],batch=batch_id))
                save(batch/'progress.json',dict(completed=completed,in_flight=index,at=now()))
                command=[sys.executable,'-m','backend.parameterization.photoproduct_distributed_hessian',
                         'run-task','--plan',str(checked(manifest['distributed_plan'])),
                         '--task-id',task['id'],'--scratch-dir',str(scratch),'--threads','4','--memory-gib','4']
                env=os.environ.copy();env['PSI_SCRATCH']=str(scratch);env['TMPDIR']=str(scratch)
                with (folder/'runner.log').open('x') as log:
                    child=subprocess.Popen(command,cwd=scratch,env=env,stdout=log,
                                           stderr=subprocess.STDOUT,start_new_session=True)
                    try:
                        code=child.wait(timeout=min(timeout,max(1.,deadline-time.time()-60)))
                    except subprocess.TimeoutExpired:
                        os.killpg(child.pid,signal.SIGTERM)
                        try:child.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            os.killpg(child.pid,signal.SIGKILL);child.wait()
                        save(folder/'interrupted.json',dict(at=now(),reason='Task exceeded measured stall/boundary allowance',timeout_seconds=timeout))
                        raise RuntimeError(f'Task {index} stalled; native evidence preserved')
                if code!=0:
                    raise RuntimeError(f'Task {index} exited {code}; inspect preserved runner/native result')
                audit=task_audit(root,index)
                save(folder/'task_audit.json',audit)
                completed.append(dict(index=index,audit=pin(folder/'task_audit.json')))
                durations.append(audit['wall_seconds'])
                save(batch/'progress.json',dict(completed=completed,in_flight=None,elapsed_seconds=time.monotonic()-started))
                print(json.dumps(dict(task=index,completed=len(completed),total=len(bp['task_indices']),seconds=audit['wall_seconds'])),flush=True)
                if len(durations)>=3 and np.median(durations[-3:])>2*60.59254043805413:
                    raise RuntimeError('Three successive tasks show >2x baseline slowdown; audit before continuing')
        if batch_id=='batch-2':
            if deadline-time.time()<120:
                raise RuntimeError('Insufficient assembly/audit grace; completed tasks saved')
            assemble(root)
    except Exception as exc:
        error=repr(exc)
        (batch/'failure_traceback.txt').write_text(traceback.format_exc())
    save(batch/'assessment.json',dict(at=now(),error=error,completed=len(completed),
         expected=len(bp['task_indices']),elapsed_seconds=time.monotonic()-started,
         passed=error is None,minimum_certified=False,gate_effect='none'))
    if error is None:
        review_batch(root,batch_id)
    return 1 if error else 0


def review_batch(root,batch_id):
    manifest,stage,plan,identity=load_context(root)
    batch=root/batch_id;bp=read(batch/'plan.json')
    outcome=read(batch/'assessment.json')
    if outcome['error'] or outcome['completed']!=len(bp['task_indices']):
        raise ValueError('Batch incomplete or failed')
    records=[task_audit(root,i) for i in bp['task_indices']]
    new_records=[r for r in records if not r['reused']]
    report=dict(at=now(),passed=True,batch_id=batch_id,task_count=len(records),tasks=records,
                new_gradient_count=len(new_records),reused_gradient_count=len(records)-len(new_records),
                mean_gradient_seconds=float(np.mean([r['wall_seconds'] for r in new_records])),
                maximum_gradient_seconds=max(r['wall_seconds'] for r in new_records),
                assessment=pin(batch/'assessment.json'),minimum_certified=False,gate_effect='none')
    path=batch/'batch_review.json'
    if path.exists():
        old=read(path)
        if old['tasks']!=records:
            raise ValueError('Previously reviewed task evidence changed')
        return old
    save(path,report)
    return report


def reconstruct_raw_hessian(masses,coordinates,gradients,step):
    """Retain the unsymmetrized response in the actual displacement basis.

    Psi4 symmetrizes before returning its Hessian, so symmetry of that returned
    matrix alone cannot measure finite-difference noise. Infer the mass-weighted
    basis from paired exact input geometries rather than relying on SALC ordering.
    """
    mass=np.repeat(np.sqrt(np.asarray(masses,float)),3)
    x=np.asarray(coordinates,float).reshape(len(coordinates),-1)
    g=np.asarray(gradients,float).reshape(len(gradients),-1)
    if (not np.isfinite(x).all() or not np.isfinite(g).all() or
            not np.isfinite(mass).all() or np.any(mass<=0) or
            x.shape!=g.shape or x.shape[1]!=len(mass) or len(x)%2 or
            not np.isfinite(step) or step<=0):
        raise ValueError('Invalid paired Hessian data')
    directions=((x[::2]-x[1::2])*mass/(2*step)).T
    if np.max(abs(directions.T@directions-np.eye(directions.shape[1])))>1e-9:
        raise ValueError('Mass-weighted displacement basis is not orthonormal')
    responses=((g[::2]-g[1::2])/mass/(2*step)).T
    raw=directions.T@responses
    symmetric=.5*(raw+raw.T)
    cartesian=(directions@symmetric@directions.T)*mass[:,None]*mass[None,:]
    return raw,directions,cartesian


def assemble(root):
    import psi4
    from qcelemental.models.v2 import AtomicResult
    from backend.parameterization.photoproduct_distributed_hessian import _restore_qcengine_arrays,_signed_frequency
    from psi4.driver.qcdb.vib import harmonic_analysis
    manifest,stage,plan,identity=load_context(root)
    out=root/'assembly';out.mkdir(exist_ok=False)
    psi4.set_output_file(str(out/'native_assembly.dat'),False)
    fd,molecule=rebuild(root)
    tasks=read(checked(manifest['distributed_plan']))['tasks']
    audits=[];coordinates=[];gradients=[]
    for i,((label,computer),record) in enumerate(zip(fd.task_list.items(),tasks,strict=True)):
        audit=task_audit(root,i);audits.append(audit)
        result=AtomicResult.model_validate_json(checked(audit['result']).read_text())
        if i:
            coordinates.append(read(root/record['input']['path'])['molecule']['geometry'])
            gradients.append(np.asarray(result.return_result).ravel())
        computer.result=_restore_qcengine_arrays(result);computer.computed=True
    result=fd.get_results()
    hessian=np.asarray(result.return_result,float)
    if hessian.shape!=(108,108) or not np.isfinite(hessian).all():
        raise ValueError('Malformed Cartesian Hessian')
    symmetry=float(np.max(abs(hessian-hessian.T)))
    if symmetry>1e-8:raise ValueError('Hessian symmetry failed')
    numerical_diagnostics=None
    if manifest.get('diagnostic_only'):
        raw,directions,reconstructed=reconstruct_raw_hessian(
            [molecule.mass(i) for i in range(36)],coordinates,gradients,manifest['displacement_size'])
        reconstruction_error=float(np.max(abs(reconstructed-hessian)))
        if reconstruction_error>1e-9:
            raise ValueError('Independent Hessian reconstruction differs from Psi4')
        np.save(out/'raw_hessian_displacement_basis.npy',raw)
        np.save(out/'mass_weighted_displacement_basis.npy',directions)
        numerical_diagnostics=dict(raw_hessian=pin(out/'raw_hessian_displacement_basis.npy'),
            basis=pin(out/'mass_weighted_displacement_basis.npy'),
            raw_antisymmetry_max=float(np.max(abs(raw-raw.T))),
            raw_antisymmetry_spectral_norm=float(np.linalg.norm(raw-raw.T,2)),
            raw_symmetry_units='hartree/(bohr^2 atomic_mass_unit)',
            independent_cartesian_reconstruction_max_error=reconstruction_error,
            interpretation='Antisymmetry is a numerical consistency diagnostic, not a rigorous bound on symmetric errors. Returned Psi4 Hessian was symmetrized by construction.')
    basis=psi4.core.BasisSet.build(molecule,'ORBITAL','6-31G(d)',quiet=True)
    vib,text=harmonic_analysis(hessian,np.asarray(molecule.geometry()),
             np.asarray([molecule.mass(i) for i in range(36)]),basis,molecule.irrep_labels(),
             project_trans=True,project_rot=True)
    frequencies=[_signed_frequency(complex(w)) for w,t in zip(vib['omega'].data,vib['TRV'].data,strict=True) if t=='V']
    if len(frequencies)!=102 or not np.isfinite(frequencies).all():
        raise ValueError('Incomplete vibrational mode table')
    np.save(out/'hessian_hartree_bohr2.npy',hessian)
    np.savetxt(out/'hessian_hartree_bohr2.txt',hessian,fmt='%.16e')
    np.save(out/'normal_modes_cartesian.npy',np.asarray(vib['x'].data))
    np.save(out/'normal_modes_mass_weighted.npy',np.asarray(vib['q'].data))
    save(out/'mode_labels.json',dict(TRV=list(vib['TRV'].data),masses=[molecule.mass(i) for i in range(36)]))
    (out/'vibrational_analysis.txt').write_text(text)
    (out/'qcschema_hessian.json').write_bytes(dump_task(result.model_dump(mode='json')))
    psi4.core.flush_outfile();psi4.core.close_outfile()
    imaginary=sum(v<0 for v in frequencies)
    soft=[v for v in frequencies if 0<=v<10.]
    certified=imaginary==0 and not soft and not manifest.get('diagnostic_only',False)
    save(out/'harmonic_audit.json',dict(at=now(),assembled=True,task_count=211,
         all_tasks=audits,source_stationarity_audit=manifest['stage1_audit'],
         hessian=pin(out/'hessian_hartree_bohr2.npy'),native_assembly=pin(out/'native_assembly.dat'),
         vibration_report=pin(out/'vibrational_analysis.txt'),symmetry_error=symmetry,
         frequency_count=102,frequencies_cm_inverse=frequencies,imaginary_mode_count=imaginary,
         numerical_diagnostics=numerical_diagnostics,
         lowest_frequency_cm_inverse=min(frequencies),soft_mode_review_below_10_cm_inverse=soft,
         minimum_certified=certified,gate_effect='none',simulation_ready=False,
         verdict=('diagnostic_hessian_requires_numerical_and_low_mode_review' if manifest.get('diagnostic_only')
                  else 'passed_local_harmonic_minimum' if certified else 'requires_mode_diagnosis'),
         claim='Local capped-core harmonic minimum only if stationarity, identity and all vibrational checks pass. No global-minimum or force-field/MD validation.'))
    return certified


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('preflight','run','review','assemble'))
    parser.add_argument('root',type=Path)
    parser.add_argument('--batch',choices=('batch-1','batch-2'),default='batch-1')
    args=parser.parse_args();root=args.root.resolve()
    if args.action=='preflight':
        import psi4
        os.chdir(root)
        psi4.set_output_file(str(root/'preflight_replay.dat'),False)
        fd,_=rebuild(root);psi4.core.flush_outfile()
        save(root/'preflight.json',dict(at=now(),passed=True,task_count=len(fd.task_list),
             no_qm_evaluations=True,all_task_bytes_match_preview=True,all_geometries_passed=True))
        print('211 exact task inputs and stereochemistries verified; no QM run.')
    elif args.action=='run':sys.exit(run_batch(root,args.batch))
    elif args.action=='review':print(review_batch(root,args.batch)['task_count'])
    else:print(assemble(root))
