"""Compare packed Move/Rotate previews with the original renderer.

The Debug entry runs generated-geometry parity checks without a headset. Supply
--scene-dir containing full.nadocvr, stick.nadocvr and ballstick.nadocvr to also
measure a saved real model. This measures isolated GL work, not compositor FPS.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time
from tools.vr_workflows.tour_catalog import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scene-dir', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--validate', action='store_true', help='Run the same deterministic renderer parity checks.')
    args = parser.parse_args()
    output = args.output or ROOT / '.development-artifacts/vr-move-preview' / time.strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True, exist_ok=False)
    build = ROOT / 'native/vr_viewer/build'
    # Avoid Conda's unrelated linker when building against system GL/OpenXR.
    env = {**os.environ, 'PATH': '/usr/bin:/bin:' + os.environ.get('PATH', '')}
    with (output / 'build.log').open('w') as log:
        subprocess.run(['cmake', '-S', str(ROOT / 'native/vr_viewer'), '-B', str(build)], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['cmake', '--build', str(build), '--target', 'nadoc-vr-rigid-preview-test', '-j2'], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    binary = build / 'nadoc-vr-rigid-preview-test'
    with (output / 'parity.log').open('w') as log:
        subprocess.run([str(binary)], stdout=log, stderr=subprocess.STDOUT, check=True)
    results = []
    if args.scene_dir:
        for rep in ('full', 'stick', 'ballstick', 'vdw'):
            scene = args.scene_dir / f'{"ballstick" if rep == "vdw" else rep}.nadocvr'
            for owner in ('base', 'cluster'):
                key = f'{rep}-{owner}'
                path = output / f'{key}.log'
                with path.open('w') as log:
                    subprocess.run([str(binary), str(scene), rep, owner, str(output / key)], stdout=log, stderr=subprocess.STDOUT, check=True)
                for line in path.read_text().splitlines():
                    if line.startswith('RESULT '):
                        row = dict(item.split('=', 1) for item in line.split()[1:])
                        for name in row:
                            if name.endswith('_ms'):
                                row[name] = float(row[name])
                        results.append(row)
                (output / 'timing.json').write_text(json.dumps(results, indent=2) + '\n')
    (output / 'result.json').write_text(json.dumps(dict(
        parity_passed=True, timing_cases=len(results), physical_headset_test=False,
        scope='Production preview update and isolated shadow/two-eye-sized draws; no XR/UI/transport timing.'), indent=2) + '\n')
    print(output, flush=True)


if __name__ == '__main__':
    main()
