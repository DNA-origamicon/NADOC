"""Production native reach-back lifecycle checks; keeps the physical viewer running."""
import argparse
import os
import subprocess
import uuid
from tools.vr_workflows.tour_catalog import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate', action='store_true')
    parser.parse_args()
    output = ROOT / '.development-artifacts/vr-quiver-reactivation' / uuid.uuid4().hex[:10]
    output.mkdir(parents=True)
    build = ROOT / 'native/vr_viewer/build'
    env = {**os.environ, 'PATH': '/usr/bin:/bin:' + os.environ.get('PATH', '')}
    guard = str(ROOT / 'scripts/validation_guard.sh')
    with (output / 'native.log').open('w') as log:
        for command in [
            ['cmake', '--build', str(build), '--target', 'nadoc-vr-scrywrite-live-test', 'nadoc-vr-ligation-test', '-j1'],
            [str(build / 'nadoc-vr-scrywrite-live-test'), '--quiver'],
            [str(build / 'nadoc-vr-scrywrite-live-test'), '--tablet-lighting'],
            [str(build / 'nadoc-vr-ligation-test')],
        ]:
            subprocess.run([guard, *command], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    print(output, flush=True)


if __name__ == '__main__':
    main()
