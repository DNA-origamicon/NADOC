"""Standard-library event guardian for the documented v3 handoff repair.

Preserves all native work. A third, already-started process stays parked until
one original worker exits. No worker is restarted and no frozen input is edited.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import time
from datetime import datetime, timezone


def read(p):
    return json.loads(Path(p).read_text())


def source(p):
    p=Path(p).resolve()
    return dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())


def save(p,d):
    p=Path(p);tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(d,indent=2)+'\n');tmp.replace(p)


def identity(pid):
    try:return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]
    except FileNotFoundError:return None


def verify(process):
    if identity(process['pid']) != process['identity']:
        raise RuntimeError('Process identity changed: '+str(process['pid']))


def wait_exit(process, deadline):
    verify(process)
    fd=os.pidfd_open(process['pid'])
    try:
        if not select.select([fd],[],[],max(0,deadline-time.time()))[0]:
            raise TimeoutError('Original deadline reached')
    finally:os.close(fd)


def run(root):
    plan=read(root/'plan.json')
    for pin in plan['sources']:
        if source(pin['path']) != pin:raise RuntimeError('Pinned source changed')
    if not hasattr(os,'pidfd_open'):raise RuntimeError('pidfd runtime unavailable')
    wake=read(Path(plan['service_root'])/'completion_wake.json')
    assert wake['state']=='armed' and wake['thread']==plan['thread']
    for name in ['original_worker','paused_worker','parallel_coordinator']:
        verify(plan[name])
    assert Path(f"/proc/{plan['paused_worker']['pid']}/status").read_text().split('State:',1)[1].lstrip().startswith('T')
    # The guardian's external watcher now owns the final batch notification.
    subprocess.run(['systemctl','--user','stop',plan['superseded_watcher']],check=True)
    save(root/'armed.json',dict(at=time.time(),mechanism='pidfd/select, no polling',
        paused_worker=plan['paused_worker'],original_worker=plan['original_worker'],wake_token=wake['token']))
    try:
        wait_exit(plan['original_worker'],min(plan['deadline_epoch'],plan['original_case_deadline']))
    except TimeoutError:
        verify(plan['original_worker'])
        os.kill(plan['original_worker']['pid'],signal.SIGKILL)
        wait_exit(plan['original_worker'],time.time()+10)
    stat=Path(f"/proc/{plan['original_worker']['pid']}/stat").read_text().rsplit(')',1)[1].split()
    assert stat[0]=='Z'
    code=os.waitstatus_to_exitcode(int(stat[49]))
    native=Path(plan['native_root']); original=native/'plus30-mm-trial1'
    save(root/'original_native_exit.json',dict(at=time.time(),returncode=code,
        assessment=source(original/'assessment.json') if (original/'assessment.json').exists() else None))
    verify(plan['paused_worker'])
    os.kill(plan['paused_worker']['pid'],signal.SIGCONT)
    save(root/'resumed.json',dict(at=time.time(),pid=plan['paused_worker']['pid'],
        original_native_returncode=code,no_restarts=True))
    # The original parallel coordinator waits for its two subprocesses and saves
    # an assessment. Its exit also releases the superseded serial dispatcher.
    wait_exit(plan['parallel_supervisor'],plan['deadline_epoch']+30)
    upstream=read(Path(plan['parallel_root'])/'assessment.json')
    rows=[row for row in upstream['records'] if row.get('case')]
    assert len(rows)==3 and {r['case'] for r in rows}=={'plus30-qm-reference','plus30-mm-trial7','minus22p5-mm-model61'}
    a=read(original/'assessment.json') if (original/'assessment.json').exists() else {}
    review=read(original/'independent_review.json') if (original/'independent_review.json').exists() else {}
    rows.append(dict(case='plus30-mm-trial1',returncode=code,
        passed=bool(code==0 and a.get('joint_optimizer_converged') and review.get('independent_stationarity_passed')),
        assessment=source(original/'assessment.json') if a else None,
        independent_review=source(original/'independent_review.json') if review else None))
    passed=all(row['passed'] for row in rows)
    save(root/'assessment.json',dict(at=datetime.now(timezone.utc).isoformat(),records=rows,
        all_four_constrained_stationarity_passed=passed,
        scheduling_error_preserved=source(Path(plan['parallel_root'])/'assessment.json'),
        correction='Replace only failed pidfd observation with verified original native exit and result; no scientific result overridden.',
        requires_native_evidence_and_basin_review=True,simulation_ready=False,minimum_certified=False))
    if not passed:raise RuntimeError('Native case failed; preserve and review')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    run(parser.parse_args().root.resolve())
