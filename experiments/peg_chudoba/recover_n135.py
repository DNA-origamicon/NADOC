"""Recover the interrupted N135 allocation without replacing original evidence."""
import os
import subprocess
import time
from pathlib import Path

from experiments.peg_chudoba.benchmark_scheduling import DEFAULT, BINARY, LIBRARY, HERE, digest, lease, read, write
from experiments.peg_chudoba.serialize_existing import alive, process
from experiments.peg_chudoba.validate_narrow import gpu_assessment


def main():
    out=DEFAULT
    root=out/'recovery_n135_20260911'
    status=root/'driver.json'
    if status.exists():
        raise RuntimeError('Recovery already allocated; inspect recorded state before retrying')
    failed=out/'production/gpu_n135_dt1_round2/r201'
    old=read(failed/'run.json')
    if old['status'] != 'failed' or old['completed_steps'] != 5280000:
        raise RuntimeError('Unexpected failure record')
    if read(out/'lease.json')['status'] != 'restored':
        raise RuntimeError('Another allocation owns the lease')
    if digest(BINARY) != old['binary_sha256'] or digest(LIBRARY) != old['shared_library_sha256']:
        raise RuntimeError('Engine provenance changed')
    directory=root/'r201'
    directory.mkdir(parents=True,exist_ok=False)
    for name in ('last_conf.dat','topology.top'):
        (directory/('conf.dat' if name=='last_conf.dat' else name)).write_bytes((failed/name).read_bytes())
    remaining=old['steps']-old['completed_steps']
    settings=(failed/'input').read_text()
    settings=settings.replace('steps = 80000000\n',f'steps = {remaining}\n')
    settings=settings.replace('refresh_vel = true','refresh_vel = false')
    # The native allocator caps capacity at N+1. With multiplier N and at
    # least one bead in an occupied cell, every particle fits in any cell.
    settings+='\nmax_density_multiplier = 135\n'
    (directory/'input').write_text(settings)
    meta=dict(old,output=str(directory.resolve()),status='prepared',steps=remaining,
              completed_steps=0,physical_duration_ns=remaining/1e6,
              trajectory_frames=remaining//8000,max_density_multiplier=135,
              recovery_source=str(failed.resolve()),recovery_source_sha256=digest(failed/'last_conf.dat'),
              recovery_checkpoint_step=old['completed_steps'],refresh_vel=False,
              initial_run=str(failed.resolve()),
              initial_source=dict(directory=str(failed.resolve()),conf_sha256=digest(failed/'last_conf.dat'),run_sha256=digest(failed/'run.json')),
              purpose='Remaining original allocation; checkpoint velocities retained, Langevin RNG restarts; not a bitwise continuation')
    write(directory/'run.json',meta)
    record=dict(owner=process(os.getpid()),status='prepared',directory=str(directory),
                original_steps=old['steps'],checkpoint_steps=old['completed_steps'],remaining_steps=remaining,
                excluded_failed_tail_steps=5390,source_sha256=digest(failed/'last_conf.dat'),
                script_sha256=digest(Path(__file__)))
    (root/'execution_source.py').write_bytes(Path(__file__).read_bytes())
    write(status,record)
    lease(out,'park',os.getpid())
    try:
        record.update(status='running',started_unix=time.time());write(status,record)
        meta.update(status='running',started_unix=time.time());write(directory/'run.json',meta)
        env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1')
        with (directory/'engine.log').open('w') as log:
            child=subprocess.Popen([str(BINARY),'input'],cwd=directory,stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
            lease(out,'register',child.pid)
            code=child.wait()
        final=directory/'last_conf.dat'
        steps=int(final.open().readline().split('=')[1]) if final.exists() else 0
        meta.update(returncode=code,completed_steps=steps,elapsed_seconds=time.time()-meta['started_unix'],
                    status='completed' if code==0 and steps>=remaining else 'failed')
        write(directory/'run.json',meta)
        if meta['status'] != 'completed':
            raise RuntimeError('Recovery failed; inspect preserved logs')
        refs=[r for r in read(HERE/'campaign_comparison.json')['comparisons'] if r['n']==135 and r['temperature_K']==294 and r['cutoff']=='zero_tail']
        cohort=[directory]+[failed.parent/f'r{i}' for i in (202,203)]
        assessment=gpu_assessment(cohort,refs[0])
        assessment['recovery_note']='First 5.28 ns excluded for r201; resumed 74.72 ns analyzed with normal 10% discard. Other origins retain their 80 ns allocations.'
        write(root/'assessment.json',assessment)
        report=read(out/'validation.json');report['gpu']['n135_dt1']=assessment
        report['status']='N135 recovery completed; validation incomplete'
        write(out/'validation.json',report)
        record.update(status='completed',passed=assessment['passed'],equivalence_status=assessment['equivalence_status'])
    except Exception as error:
        record.update(status='failed',error=str(error))
        raise
    finally:
        record['finished_unix']=time.time();write(status,record)
        lease(out,'restore')


if __name__=='__main__':
    main()
