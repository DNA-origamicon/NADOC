"""Optional final-output evidence around a production Join gesture.

The recorder owns journal commands before/after the callback; controller commands
run synchronously inside it. This avoids competing ScryWrite sequence owners.
"""
import json
import os
from pathlib import Path
import shutil


def record_join_operation(live, output, label, operation):
    directory = os.environ.get('NADOC_JOIN_FINAL_CAPTURE')
    if not directory:
        return operation()
    from tools.vr_capture.viewer_record import record

    pid = int(live.session.split('-')[0])
    argv = Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\0')
    journal_directory = argv[argv.index('--pose-journal') + 1]
    context = dict(session=live.session, diagnostics_required=True,
        submitted_frame_marker=live.state['frame_identity'],
        pose_journal=dict(enabled=True, socket=str(live.bridge.socket_path),
                          session=live.session, directory=journal_directory))
    called = False

    def emit(status):
        nonlocal called
        # The recorder emits progress updates with the same phase. Only the
        # first acknowledged recording update should start controller input.
        if status['phase'] == 'recording' and not called:
            called = True
            live.state = live.bridge.call('scrywrite_observe', {})
            if live.state.get('session') != live.session:
                raise RuntimeError('Join recording viewer changed')
            operation()

    try:
        # Apply includes browser routing and the native scene refresh. Its
        # measured 3–4 second latency outlasts the short gesture recording.
        report = record(Path(directory), emit, context=context, viewer_pid=pid,
                        seconds=5 if label == 'apply' else 2, delay=0)
        (output / f'{label}-final-output.json').write_text(json.dumps(report, indent=2))
        journal = report.get('pose_journal', {}).get('native', {}).get('path')
        if journal:
            shutil.copy2(journal, output / f'{label}-pose-journal.jsonl')
        if report['status'] != 'saved' or not called:
            raise RuntimeError(f'Join final-output recording failed: {report["status"]}: {report.get("message")}')
    finally:
        live.state = live.bridge.call('scrywrite_observe', {})
