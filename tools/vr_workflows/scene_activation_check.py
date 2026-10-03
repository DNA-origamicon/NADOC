"""Check atomic scene activation without a headset; optionally time a saved origami."""
import argparse
import os
from pathlib import Path
import subprocess
import time

from tools.vr_workflows.tour_catalog import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    output = args.output or ROOT / '.development-artifacts/scene-activation' / time.strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True, exist_ok=False)
    build = ROOT / 'native/vr_viewer/build'
    env = {**os.environ, 'PATH': '/usr/bin:/bin:' + os.environ.get('PATH', '')}
    with (output / 'build.log').open('w') as log:
        subprocess.run(['cmake', '-S', str(ROOT / 'native/vr_viewer'), '-B', str(build)], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['cmake', '--build', str(build), '--target', 'nadoc-vr-scene-activation-test', 'nadoc-vr-scene-refresh-test', '-j2'], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    with (output / 'parity.log').open('w') as log:
        subprocess.run(['ctest', '--test-dir', str(build), '-R', '^nadoc-vr-scene-(activation|refresh)$', '--output-on-failure'], stdout=log, stderr=subprocess.STDOUT, check=True)
    if args.scene:
        with (output / 'timing.log').open('w') as log:
            subprocess.run([str(build / 'nadoc-vr-scene-activation-test'), str(args.scene.resolve())], stdout=log, stderr=subprocess.STDOUT, check=True)
    print(output, flush=True)


if __name__ == '__main__':
    main()
