"""Isolated Join regression, with optional physical controller/stereo validation.

All persistent evidence and temporary browser/backend/native data are created on
the mounted Archive filesystem. The browser check intercepts VR transport; only
the physical tour owns a viewer. Both use the real desktop Join routing backend.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import uuid

from tools.vr_workflows.tour_catalog import ROOT

PROFILES = ('steady_fast', 'steady_deliberate', 'variable_fast', 'variable_deliberate')


def archive_output(requested):
    archive = Path('/media/jojo/Archive')
    if not archive.is_mount():
        raise RuntimeError('The Archive drive must be mounted before generating Join evidence.')
    output = requested.resolve()
    if not output.is_relative_to(archive.resolve()):
        raise ValueError('Join output and scratch must be on the mounted Archive drive.')
    output.mkdir(parents=True, exist_ok=True)
    if output.stat().st_dev != archive.stat().st_dev:
        raise RuntimeError('Join output resolves to a different filesystem than Archive.')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate', action='store_true')
    parser.add_argument('--browser', action='store_true', help='No headset; exercise real browser dispatch and desktop routing.')
    parser.add_argument('--profile', choices=PROFILES)
    parser.add_argument('--capture-final', type=Path, nargs='?', const=Path('configured'),
                        help='Record gestures with the configured live compositor, or an explicit capture directory.')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    from tools.native_placement_audit import check_review_gate
    pending_reviews = check_review_gate()
    if pending_reviews:
        raise RuntimeError('Complete the native placement review before starting Join: ' +
                           ', '.join(item['incident_id'] for item in pending_reviews))
    if args.profile and (args.validate or args.browser):
        parser.error('--profile is only available for a single physical run')
    if args.capture_final:
        if args.browser:
            parser.error('--capture-final requires the physical runtime')
        if args.capture_final == Path('configured'):
            from backend.api.vr_capture_launch import load_config, readiness
            config = load_config()
            if config is None:
                parser.error('Final-output capture is not configured')
            status = readiness(config)
            if not status.get('available'):
                parser.error('Final-output recorder is unavailable: ' + str(status.get('reason')))
            args.capture_final = Path(status['directory'])
    if not args.browser:
        from backend.api.routes_vr_tours import _viewer_active
        if _viewer_active():
            raise RuntimeError('Close the active viewer before starting an isolated Join tour.')
    output = archive_output(args.output or ROOT / '.development-artifacts/vr-join-20261011' / uuid.uuid4().hex[:10])
    profiles = ('browser',) if args.browser else PROFILES if args.validate else (args.profile or PROFILES[0],)
    results = []
    for profile in profiles:
        case = output / profile
        case.mkdir(exist_ok=True)
        # Inventory before Playwright: __e2e__ documents/.nadoc-projects are removed
        # by global-teardown; this context also removes the entire private
        # workspace and browser profile on every exit. The isolated Vite bridge
        # credential is removed by global-teardown. Physical native sidecars
        # and the read-only compositor sampler are owned and closed by the
        # spec's finally block. Its dependency cache shares this temporary
        # Archive directory and is removed on success or failure; evidence persists.
        # A short real Archive path keeps native Unix-domain sockets below the
        # 108-byte sockaddr_un limit; a symlink to a long path is insufficient.
        # This context owns and removes exactly its newly created directory.
        with tempfile.TemporaryDirectory(prefix='j11-', dir='/media/jojo/Archive') as temporary:
            if Path(temporary).stat().st_dev != output.stat().st_dev:
                raise RuntimeError('Join scratch resolves to a different filesystem than evidence.')
            workspace = Path(temporary) / 'w'
            workspace.mkdir()
            browser_tmp = Path(temporary) / 't'
            browser_tmp.mkdir()
            with socket.socket() as backend, socket.socket() as frontend:
                backend.bind(('127.0.0.1', 0))
                frontend.bind(('127.0.0.1', 0))
                backend_port, frontend_port = str(backend.getsockname()[1]), str(frontend.getsockname()[1])
            env = {**os.environ, 'TMPDIR': str(browser_tmp), 'NADOC_WORKSPACE': str(workspace),
                   'UV_CACHE_DIR': str(Path(temporary) / 'uv-cache'),
                   'SCRYWRITE_TEST_WORKSPACE': str(workspace), 'SCRYWRITE_BACKEND_PORT': backend_port,
                   'SCRYWRITE_FRONTEND_PORT': frontend_port, 'NADOC_SMOKE_BACKEND_PORT': backend_port,
                   'NADOC_SMOKE_FRONTEND_PORT': frontend_port, 'NADOC_E2E_API_BASE': 'http://127.0.0.1:' + backend_port,
                   'NADOC_DISABLE_SESSION_CACHE': '1', 'NADOC_VR_PROFILE': profile,
                   'NADOC_VR_DEMO': '0' if args.validate or args.browser else '1'}
            if not args.browser:
                # Keep configured native scratch, sockets and journals inside
                # this owned context too. Reuse only the live compositor/layer.
                from backend.api.vr_capture_launch import load_config, capture_directory
                config = load_config()
                if config:
                    private_config = Path(temporary) / 'capture.json'
                    data = dict(schema=1, archive_mount=str(config.archive_mount),
                        storage_root=str(Path(temporary) / 'c'), socket_root=str(Path(temporary) / 's'),
                        layer_directory=str(config.layer_directory), layer_library_sha256=config.layer_library_sha256,
                        active_capture_directory=str(capture_directory(config)))
                    if config.viewer_build_directory:
                        data['viewer_build_directory'] = str(config.viewer_build_directory)
                    private_config.write_text(json.dumps(data))
                    private_config.chmod(0o600)
                    env['NADOC_VR_CAPTURE_CONFIG'] = str(private_config)
            if args.capture_final:
                env['NADOC_JOIN_FINAL_CAPTURE'] = str(args.capture_final.resolve(strict=True))
            config = 'playwright.vr-join.config.js' if args.browser else 'playwright.vr-bend.config.js'
            command = [str(ROOT / 'scripts/validation_guard.sh'), 'node',
                       'node_modules/@playwright/test/cli.js', 'test', '--config', config,
                       '--workers=1', '--output', str(case / 'playwright')]
            if args.browser:
                command.extend(['--grep', 'Join'])
            else:
                command.append('vr_join_physical.spec.js')
                env['NADOC_PHYSICAL_VR_TEST'] = '1'
                env['NADOC_VR_FRAME_AUDIT'] = '1'
                command.append('--headed')
            print(f'Join {profile}: isolated workspace {workspace}; evidence {case}', flush=True)
            with (case / 'browser.log').open('w') as log:
                result = subprocess.run(command, cwd=ROOT / 'frontend', env=env,
                                        stdout=log, stderr=subprocess.STDOUT)
            leftovers = list(workspace.rglob('*.nadoc')) + list(workspace.rglob('*.nass'))
            projects = list((workspace / '.nadoc-projects').glob('*/snapshots/*'))
            if not args.browser:
                from tools.vr_workflows.frame_audit import report
                from tools.vr_workflows.frame_audit_tour import compositor_report
                for viewer_log in (case / 'playwright').rglob('viewer.log'):
                    intervals = [json.loads(line) for source in viewer_log.parent.rglob('intervals.jsonl')
                                 for line in source.read_text().splitlines() if line.strip()]
                    audit = report(viewer_log.read_text(errors='replace'), intervals, target_budget_ms=1000 / 90)
                    (viewer_log.parent / 'frame-audit.json').write_text(json.dumps(audit, indent=2))
                    compositor = compositor_report(viewer_log.parent / 'compositor.jsonl', intervals)
                    (viewer_log.parent / 'compositor-summary.json').write_text(json.dumps(compositor, indent=2))
            result_row = {'profile': profile, 'passed': result.returncode == 0,
                          'workspace_artifacts_remaining': [str(p.relative_to(workspace)) for p in leftovers + projects]}
            results.append(result_row)
            (output / 'result.json').write_text(json.dumps({'results': results,
                'physical_headset': not args.browser, 'temporary_workspace_removed_on_exit': True}, indent=2))
            if leftovers or projects:
                raise RuntimeError(f'Join artifact cleanup failed: {result_row}; evidence: {case}')
    print(output, flush=True)
    if any(not result['passed'] for result in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
