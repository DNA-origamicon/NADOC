"""Event-driven handoff of a live diagnostic to two four-core lanes.

Only dispatch changes. The live optimization and all frozen scientific inputs
remain untouched. A replacement external watcher is armed before handoff.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

REPO = Path(os.environ.get('NADOC_REPO_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.validation_gate import checked, read, source
from experiments.cpd_anti_additive.sella_pilot import save, now
from experiments.cpd_anti_additive.watch import process_identity


def require_identity(pid, identity):
    if process_identity(pid) != identity:
        raise RuntimeError(f'Process identity changed: {pid}')


def assess(folder, returncode):
    result = read(folder/'assessment.json') if (folder/'assessment.json').exists() else {}
    audit = read(folder/'independent_review.json') if (folder/'independent_review.json').exists() else {}
    return dict(case=folder.name, returncode=returncode,
        passed=bool(returncode == 0 and result.get('joint_optimizer_converged') and audit.get('independent_stationarity_passed')),
        assessment=source(folder/'assessment.json') if result else None,
        independent_review=source(folder/'independent_review.json') if audit else None)


def await_existing(plan):
    live = plan['live_worker']
    require_identity(live['pid'], live['identity'])
    fd = os.pidfd_open(live['pid'])
    try:
        timeout = max(0, min(plan['deadline_epoch'], live['deadline_epoch'])-time.time())
        ready, _, _ = select.select([fd], [], [], timeout)
        if not ready:
            require_identity(live['pid'], live['identity'])
            os.kill(live['pid'], signal.SIGTERM)
            if not select.select([fd], [], [], 10)[0]:
                os.kill(live['pid'], signal.SIGKILL)
            return dict(case=live['case'],passed=False,error='Original case or batch deadline reached')
        # Its original parent is stopped, so the unreaped native exit status is
        # available even though this coordinator cannot waitpid a non-child.
        stat = Path(f"/proc/{live['pid']}/stat").read_text().rsplit(')',1)[1].split()
        if stat[0] != 'Z':
            raise RuntimeError('Expected original parent to retain native exit status')
        returncode = os.waitstatus_to_exitcode(int(stat[49]))
        return assess(Path(plan['native_root'])/live['case'], returncode)
    finally:
        os.close(fd)


def run_case(plan, task, cores):
    folder = Path(task['folder'])
    if (folder/'started.json').exists():
        raise RuntimeError('Refusing duplicate case: '+folder.name)
    remaining = min(21600, plan['deadline_epoch']-time.time())
    if remaining <= 0:
        return dict(case=folder.name,passed=False,error='Original batch deadline reached')
    command = ['/usr/bin/taskset','-c',cores,plan['runtime_python'],plan['worker'],'case',str(folder)]
    with (folder/'parallel_worker.log').open('x') as log:
        try:
            p = subprocess.run(command, cwd=REPO,stdout=log,stderr=subprocess.STDOUT,timeout=remaining)
            return assess(folder,p.returncode)
        except subprocess.TimeoutExpired:
            save(folder/'timeout.json',dict(at=now(),error='Original case/batch cap reached'))
            return dict(case=folder.name,passed=False,error='Original case/batch cap reached')


def run(root):
    # Check before freezing the original dispatcher or starting any new case.
    # The separate Sella runtime lacks this API; use system Python for dispatch.
    if not hasattr(os, 'pidfd_open'):
        raise RuntimeError('Dispatcher requires system Python with os.pidfd_open')
    plan = read(root/'plan.json')
    for item in plan['sources']:
        checked(item)
    # The launch supervisor will not call us until the new external watcher is armed.
    wake = read(Path(plan['service_root'])/'completion_wake.json')
    assert wake['state']=='armed' and wake['thread']==plan['thread']
    require_identity(wake['watcher_pid'], plan_identity := process_identity(wake['watcher_pid']))
    assert plan_identity is not None
    dispatcher=plan['old_dispatcher']; live=plan['live_worker']
    require_identity(dispatcher['pid'],dispatcher['identity'])
    require_identity(live['pid'],live['identity'])
    for task in plan['pending']:
        if (Path(task['folder'])/'started.json').exists():
            raise RuntimeError('Pending inventory changed before handoff')
    with (root/'started.json').open('x') as f:
        json.dump(dict(at=now(),plan=source(root/'plan.json')),f)
    os.kill(dispatcher['pid'],signal.SIGSTOP)
    # Bounded startup synchronization, not long-job polling.
    for _ in range(100):
        if Path(f"/proc/{dispatcher['pid']}/status").read_text().split('State:',1)[1].lstrip().startswith('T'):
            break
        time.sleep(.01)
    else:
        os.kill(dispatcher['pid'],signal.SIGCONT)
        raise RuntimeError('Original dispatcher did not stop')
    try:
        require_identity(live['pid'],live['identity'])
        children=Path(f"/proc/{dispatcher['pid']}/task/{dispatcher['pid']}/children").read_text().split()
        assert children == [str(live['pid'])]
        assert all(not (Path(t['folder'])/'started.json').exists() for t in plan['pending'])
    except BaseException:
        os.kill(dispatcher['pid'],signal.SIGCONT)
        raise
    save(root/'handoff.json',dict(at=now(),old_dispatcher_stopped=True,
        live_worker_unmodified=True,new_watcher=wake['token'],plan=source(root/'plan.json')))
    # The replacement watcher now owns completion/failure delivery. Suppress an
    # extra wake for the deliberately superseded orchestration service.
    subprocess.run(['systemctl','--user','stop',plan['old_watcher_unit']],check=True)
    rows = list(plan['completed'])
    pending = list(plan['pending'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(await_existing,plan):'4-7'}
        task=pending.pop(0)
        futures[pool.submit(run_case,plan,task,'0-3')]='0-3'
        save(root/'dispatch.json',dict(at=now(),existing=live['case'],launched=task['case_id'],queued=[t['case_id'] for t in pending],max_live_workers=2))
        while futures:
            done,_=wait(futures,return_when=FIRST_COMPLETED)
            for future in done:
                cores=futures.pop(future)
                try:
                    row=future.result()
                except Exception as exc:
                    row=dict(passed=False,error=repr(exc),cores=cores)
                rows.append(row)
                save(root/'progress.json',dict(at=now(),records=rows,total=4))
                if pending:
                    futures[pool.submit(run_case,plan,pending.pop(0),cores)]=cores
    # All native calculations have terminated; release the old stopped
    # dispatcher without letting it redispatch already completed cases.
    require_identity(dispatcher['pid'],dispatcher['identity'])
    os.kill(dispatcher['pid'],signal.SIGTERM)
    os.kill(dispatcher['pid'],signal.SIGCONT)
    passed=len(rows)==4 and all(r['passed'] for r in rows)
    save(root/'assessment.json',dict(at=now(),records=rows,
        all_four_constrained_stationarity_passed=passed,original_dispatcher_superseded=True,
        original_scientific_inputs_unchanged=True,requires_native_evidence_review=True,
        simulation_ready=False,minimum_certified=False))
    if not passed:
        raise RuntimeError('One or more native cases failed; review preserved evidence')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    run(parser.parse_args().root.resolve())
