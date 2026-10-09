"""Production VR list layouts and history scrub/action checks, with a pixel atlas."""
import argparse
import os
import subprocess
import uuid
from tools.vr_workflows.tour_catalog import ROOT
from tools.vr_workflows.menu_render_audit import report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    output = ROOT / '.development-artifacts/vr-list-review' / uuid.uuid4().hex[:10]
    output.mkdir(parents=True)
    build = ROOT / 'native/vr_viewer/build'
    env = {**os.environ, 'PATH': '/usr/bin:/bin:' + os.environ.get('PATH', '')}
    targets = ['nadoc-vr-' + name for name in ('feature-log-panel-test', 'sweep-panel-test', 'dimensions-test', 'simulation-panel-test', 'menu-render-audit')]
    guard = str(ROOT / 'scripts/validation_guard.sh')
    with (output / 'checks.log').open('w') as log:
        for command in [['cmake', '--build', str(build), '--target', *targets, '-j1'],
                        *[[str(build / target)] for target in targets[:-1]],
                        [str(build / targets[-1]), str(output)]]:
            subprocess.run([guard, *command], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    report(output)
    print(output / 'index.html', flush=True)
    if args.validate:
        print('Native list layout, bounds, scrub cancellation and row actions passed.', flush=True)


if __name__ == '__main__':
    main()
