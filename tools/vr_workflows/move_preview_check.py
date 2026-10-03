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
    parser.add_argument('--compare-setup', action='store_true', help='Compare prepared and legacy first-grab setup on the same saved scenes, including exact rendered pixels.')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--validate', action='store_true', help='Run the same deterministic renderer parity checks.')
    args = parser.parse_args()
    if args.compare_setup and not args.scene_dir:
        parser.error('--compare-setup requires --scene-dir')
    output = args.output or ROOT / '.development-artifacts/vr-move-preview' / time.strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True, exist_ok=False)
    build = ROOT / 'native/vr_viewer/build'
    # Avoid Conda's unrelated linker when building against system GL/OpenXR.
    env = {**os.environ, 'PATH': '/usr/bin:/bin:' + os.environ.get('PATH', ''),
           'NADOC_VR_MOTION_DETAIL': '0'}
    with (output / 'build.log').open('w') as log:
        subprocess.run(['cmake', '-S', str(ROOT / 'native/vr_viewer'), '-B', str(build)], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(['nice', '-n', '10', 'cmake', '--build', str(build), '--target', 'nadoc-vr-rigid-preview-test', '-j1'], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    binary = build / 'nadoc-vr-rigid-preview-test'
    with (output / 'parity.log').open('w') as log:
        subprocess.run([str(binary)], env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    results = []
    first_previews = []
    pixel_parity = []
    if args.scene_dir:
        for rep in ('full', 'stick', 'ballstick', 'vdw'):
            scene = args.scene_dir / f'{"ballstick" if rep == "vdw" else rep}.nadocvr'
            for owner in ('base', 'cluster'):
                for setup in (('legacy', 'prepared') if args.compare_setup else ('prepared',)):
                    key = f'{rep}-{owner}-{setup}' if args.compare_setup else f'{rep}-{owner}'
                    path = output / f'{key}.log'
                    case_env = {**os.environ, 'NADOC_VR_MOTION_DETAIL': '0'}
                    case_env.pop('NADOC_TEST_LEGACY_PREVIEW_SETUP', None)
                    if setup == 'legacy':
                        case_env['NADOC_TEST_LEGACY_PREVIEW_SETUP'] = '1'
                    with path.open('w') as log:
                        subprocess.run([str(binary), str(scene), rep, owner, str(output / key)], env=case_env, stdout=log, stderr=subprocess.STDOUT, check=True)
                    for line in path.read_text().splitlines():
                        if line.startswith(('RESULT ', 'FIRST_PREVIEW ')):
                            row = dict(item.split('=', 1) for item in line.split()[1:])
                            row['setup'] = setup
                            for name in row:
                                if name.endswith('_ms'):
                                    row[name] = float(row[name])
                            (results if line.startswith('RESULT ') else first_previews).append(row)
                if args.compare_setup:
                    for mode in ('idle', 'selected_idle', 'translate', 'rotate'):
                        legacy = output / f'{rep}-{owner}-legacy-{mode}.ppm'
                        prepared = output / f'{rep}-{owner}-prepared-{mode}.ppm'
                        equal = legacy.read_bytes() == prepared.read_bytes()
                        pixel_parity.append(dict(rep=rep, owner=owner, mode=mode, equal=equal))
                (output / 'timing.json').write_text(json.dumps(results, indent=2) + '\n')
                (output / 'first-preview.json').write_text(json.dumps(first_previews, indent=2) + '\n')
                (output / 'pixel-parity.json').write_text(json.dumps(pixel_parity, indent=2) + '\n')
    if any(not row['equal'] for row in pixel_parity):
        raise RuntimeError('Prepared first-grab pixels differ from legacy; see pixel-parity.json')
    (output / 'result.json').write_text(json.dumps(dict(
        parity_passed=True, timing_cases=len(results), first_preview_cases=len(first_previews),
        exact_pixel_comparisons=len(pixel_parity), physical_headset_test=False,
        scope='Production preview update and isolated shadow/two-eye-sized draws; no XR/UI/transport timing.'), indent=2) + '\n')
    print(output, flush=True)


if __name__ == '__main__':
    main()
