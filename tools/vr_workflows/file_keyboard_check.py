"""Seeded filename-key selection stress test using the production native hit test.

Offline selection at 0.6 m ray distance; not headset delivery or human accuracy.
No structures, workspace mutations, retries or endpoint correction.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

from tools.vr_motion.model import reach
from tools.vr_motion.presets import PRESETS

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate', action='store_true')
    parser.add_argument('--output', type=Path, default=ROOT / '.development-artifacts/vr-file-keyboard')
    args = parser.parse_args()
    binary = ROOT / 'native/vr_viewer/build/nadoc-vr-file-keyboard-test'
    subprocess.run([str(ROOT / 'scripts/validation_guard.sh'), 'cmake', '--build',
                    str(binary.parent), '--target', binary.name, '-j1'], check=True,
                   env={**os.environ, 'PATH': '/usr/bin:/bin:' + os.environ.get('PATH', '')})
    targets = [line.split() for line in subprocess.check_output([str(binary), '--targets'], text=True).splitlines()]
    result = {'scope': 'offline production ray hit test; 0.6 m distance; final uncorrected reach sample', 'profiles': {}}
    for name in PRESETS if args.validate else ['steady_fast']:
        duration, profile = PRESETS[name]
        with tempfile.TemporaryDirectory(prefix='nadoc-file-keys-') as scratch:
            samples = Path(scratch) / 'samples.txt'
            with samples.open('w') as out:
                for index, (key, x, y) in enumerate(targets):
                    for seed in range(50):
                        trace = reach([0, 0, .6], [float(x), float(y), .6], duration_s=duration, profile=profile, seed=seed * len(targets) + index)
                        pose = trace['samples'][-1]['hands']['right']
                        out.write(' '.join(map(str, [key, *pose['position'], *pose['orientation']])) + '\n')
            checked = subprocess.run([str(binary), str(samples)], capture_output=True, text=True)
            hits, trials = map(int, checked.stdout.split())
            result['profiles'][name] = dict(hits=hits, trials=trials, misses=trials-hits, rate=hits/trials, passed=checked.returncode == 0)
    result['passed'] = all(p['passed'] for p in result['profiles'].values())
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
