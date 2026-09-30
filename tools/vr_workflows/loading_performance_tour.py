"""Real browser loading with native timings and read-only SteamVR frame timing."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from tools.vr_workflows.loading_profile import summarize, acceptance_failures


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--doc', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'inventory.txt').write_text('Evidence stays here. The browser_representation_tour child owns private __e2e__ documents/files/caches and its viewer/IPC cleanup. This wrapper owns and terminates only its read-only compositor sampler. No runtime settings changed.\n')
    timing = args.output/'compositor.jsonl'
    with (args.output/'compositor.log').open('w') as log:
        sampler = subprocess.Popen(['uv', 'run', '--with', 'openvr', 'python', '-m',
                                    'tools.vr_workflows.compositor_timing', '--output', str(timing), '--seconds', '1800'],
                                   stdout=log, stderr=subprocess.STDOUT)
        try:
            command = [sys.executable, '-m', 'tools.vr_workflows.browser_representation_tour',
                       '--doc', args.doc, '--output', str(args.output/'browser')]
            if args.validate:
                command.append('--validate')
            completed = subprocess.run(command, check=False)
        finally:
            sampler.terminate()
            sampler.wait(timeout=15)
    report = summarize(args.output/'browser', timing)
    failures = acceptance_failures(report)
    if completed.returncode:
        failures.insert(0, 'Functional controller/stereo tour failed (see retained browser evidence)')
    report['acceptance_failures'] = failures
    (args.output/'loading-profile.json').write_text(json.dumps(report, indent=2))
    if failures:
        raise RuntimeError('Loading frame-delivery regression: '+ '; '.join(failures))
    print('Loading cadence and compositor regression gates passed; physical comfort remains a headset review.')


if __name__ == '__main__':
    main()
