"""One admission retry for the two-hour alternate-sugar core release."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import json
import os
import subprocess
import sys
import time
import traceback

REPO = Path(os.environ.get('NADOC_REPO_ROOT', '/home/jojo/Work/NADOC'))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read, save, pin, checked, now
from experiments.cpd_anti_additive.launch import wait_for_watcher
from experiments.cpd_anti_additive.watch import deliver
from experiments.cpd_published_comparator.completion_events import CompletionEvents


def main(root):
    cfg = read(root / 'plan.json')
    checked(cfg['source']); plan_path = checked(cfg['native_plan']); plan = read(plan_path)
    worker = checked(plan['worker']); job = plan_path.parent
    state = dict(at=now(), state='admission_running', pid=os.getpid(), native_job=str(job),
                 no_periodic_retry=True, simulation_ready=False)
    save(root / 'status.json', state)
    # A separately authorized/manual launch or an intervening pause cancels this attempt.
    # Match this campaign's worker. The legacy MD ensemble hold is separate;
    # it explicitly does not revoke corrected-refinement research authorization.
    pause = job.parent/'pause.json'
    if pause.exists() and read(pause).get('paused'):
        state.update(state='cancelled_paused', pause_record=pin(pause), finished_at=now()); save(root/'status.json', state)
        wake = read(root/'completion_wake.json')
        wake.update(state='cancelled_paused', pause_record=pin(pause), finished_at=now())
        save(root/'completion_wake.json', wake)
        return
    if (job/'launch_receipt.json').exists():
        state.update(state='skipped_already_launched', finished_at=now()); save(root/'status.json', state)
        wake = read(root/'completion_wake.json')
        wake.update(state='skipped_already_launched', finished_at=now())
        save(root/'completion_wake.json', wake)
        return
    try:
        assert (plan['max_new_gradients'], plan['hard_seconds']) == (30, 7200)
        assert cfg['attempts_allowed'] == 1 and not cfg['periodic_retry']
        # The admission helper is not a CPD calculation; avoid tripping the native exclusive-job guard.
        assert 'cpd-' not in cfg['timer_unit']
        # Native launcher rechecks exclusive admission, unchanged headroom and every source pin.
        command = [cfg['python'], str(worker), 'launch', str(job)]
        # User systemd does not inherit the interactive extension's executable path.
        child_env = {**os.environ, 'CODEX_THREAD_ID': cfg['thread'],
                     'PATH': str(Path(cfg['codex_executable']).parent)+os.pathsep+os.environ.get('PATH', os.defpath)}
        result = subprocess.run(command, text=True, capture_output=True, timeout=30,
                                env=child_env)
        (root/'launch_stdout.txt').write_text(result.stdout)
        (root/'launch_stderr.txt').write_text(result.stderr)
        state['launcher_returncode'] = result.returncode
        if result.returncode:
            raise RuntimeError('One deferred admission attempt failed; inspect launch_stderr.txt')
        service = job.parent/(job.name+'-service')
        wake = wait_for_watcher(service)
        events = CompletionEvents(job); deadline = time.monotonic()+15
        try:
            while not (job/'constraint_configuration.json').exists():
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise RuntimeError('Missing configured-target startup receipt')
                events.wait(remaining)
        finally:
            events.close()
        configuration = read(job/'constraint_configuration.json')
        assert abs(configuration['installed_target_degrees']-plan['constraint']['target_degrees']) < 1e-8
        assert abs(configuration['initial_residual_radians']) < 1e-8
        assert configuration['torsion_error_degrees'] < 1e-6
        assert configuration['fixed_atom_count'] == 0 and configuration['rank'] == 1
        assert configuration['free_dimensions'] == 146 and configuration['internal_free_dimensions'] == 140
        status = read(service/'status.json'); assert status['state'] == 'running'
        receipt = read(job/'launch_receipt.json')
        raw = subprocess.check_output(['systemctl', '--user', 'show', receipt['unit']+'.service',
            '-p', 'ActiveState', '-p', 'MemoryMax', '-p', 'MemorySwapMax', '-p', 'RuntimeMaxUSec',
            '-p', 'CPUQuotaPerSecUSec', '-p', 'TimeoutStopUSec'], text=True)
        props = dict(line.split('=', 1) for line in raw.strip().splitlines())
        assert props['ActiveState'] == 'active' and props['MemoryMax'] == str(8*1024**3)
        assert props['MemorySwapMax'] == '0' and props['CPUQuotaPerSecUSec'] == '4s'
        assert props['RuntimeMaxUSec'] == '1h 59min 45s' and props['TimeoutStopUSec'] == '15s'
        assert abs(wake['active_deadline_epoch']-(receipt['deadline_epoch']-300)) < 1e-6
        local = lambda epoch: datetime.fromtimestamp(epoch, ZoneInfo('America/Denver')).isoformat()
        verification = dict(at=now(), startup_verified=True, service_status=status, systemd=props,
             wake=wake, constraint_configuration=configuration, constraint_receipt=pin(job/'constraint_configuration.json'),
             audit_deadline_local=local(wake['active_deadline_epoch']), deadline_local=local(receipt['deadline_epoch']),
             expected_allocation_finish_local=local(receipt['deadline_epoch']-7200+plan['expected_seconds']),
             policy='One deferred admission and startup check; native completion/failure plus one deadline. No periodic polling.')
        save(job/'launch_verification.json', verification)
        h = read(checked(cfg['preparation_handoff']))
        h.update(at=now(), stage='alternate-sugar-core-release-continuation-active', native_job_started=True,
                 admission_timer_consumed=True, preparation_handoff=cfg['preparation_handoff'],
                 launch_verification=pin(job/'launch_verification.json'), service=str(service), wake_token=wake['token'],
                 audit_deadline_local=verification['audit_deadline_local'], hard_deadline_local=verification['deadline_local'])
        save(job/'active_handoff.json', h)
        save(job.parent/'current_handoff.json', dict(at=now(), handoff=pin(job/'active_handoff.json')))
        state.update(state='complete', native_started=True, native_service=str(service),
                     launch_verification=pin(job/'launch_verification.json'), finished_at=now())
        save(root/'status.json', state)
        receipt_wake = read(root/'completion_wake.json')
        receipt_wake.update(state='native_watcher_armed_no_admission_wake_needed', native_wake_token=wake['token'])
        save(root/'completion_wake.json', receipt_wake)
    except Exception as exc:
        state.update(state='failed', error=repr(exc), finished_at=now())
        (root/'failure_traceback.txt').write_text(traceback.format_exc())
        save(root/'status.json', state)
        wake = read(root/'completion_wake.json')
        message = (f"CPD_ANTI_QM_WAKE token={wake['token']} event=failed. "
                   f"Review {root}/status.json and launch_stderr.txt; this was one deferred resource-admission attempt. "
                   f"Write {root}/completion_wake_ack.json with token, event, received_at. "
                   "Review the current handoff before further action; no periodic polling, no duplicate jobs, no cloud spending.")
        delivery = deliver(cfg['codex_executable'], cfg['thread'], message, 30)
        wake['deliveries'].append({**delivery, 'event': 'failed'})
        wake['state'] = 'queued' if delivery['returncode'] == 0 else 'delivery_failed'
        save(root/'completion_wake.json', wake)
        if delivery['returncode']:
            raise RuntimeError('Deferred failure wake delivery failed; receipt preserved')


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
