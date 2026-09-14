"""Guarded execution and measured qualification of a prepared PEG wall package."""
import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import time

import numpy as np

from backend.core.dcd_fast import read_frame, read_layout
from backend.core.hardware import heavy_sim_running
from backend.core.namd_metrics import parse_namd_log_frames
from backend.core.namd_peg_wall import RepulsiveSlit
from experiments.peg_namd.structure import read_pair
from experiments.peg_wall.build import sha256

ROOT = Path(__file__).resolve().parents[2]


def verify_inputs(package):
    manifest = json.loads((package/'manifest.json').read_text())
    if manifest.get('schema') != 'nadoc.peg_wall_qualification.v1':
        raise ValueError('not a PEG wall qualification package')
    for name, digest in manifest['input_hashes'].items():
        if Path(name).name != name or sha256(package/name) != digest:
            raise ValueError(f'input changed since preparation: {name}')
    return manifest


def trajectory_metrics(package, manifest, energy_rows=()):
    slit = RepulsiveSlit(**manifest['slit'])
    pair = read_pair(package/'system.psf', package/'grafts.pdb')
    anchors, peg = manifest['audit']['anchor_indices_0'], manifest['audit']['peg_indices_0']
    path = package/'output/resident.dcd'
    layout = read_layout(path)
    if layout.n_atoms != len(pair['atoms']) or layout.n_frames < 1:
        raise ValueError('trajectory atom count or saved frames invalid')
    max_penetration, peg_penetration, max_anchor, sum_anchor_sq = 0., 0., 0., 0.
    first = None
    max_motion = 0.
    energy_by_step = {int(row['TS']): row for row in energy_rows}
    energy_errors = []
    for i in range(layout.n_frames):
        xyz, _ = read_frame(path, layout, i)
        if not np.isfinite(xyz).all():
            raise ValueError('nonfinite trajectory coordinates')
        wrapped = np.mod(xyz/10, slit.box_nm)
        distances = np.minimum(*(frame.signed_distance(wrapped)*10 for frame in slit.frames))
        max_penetration = max(max_penetration, float(max(0., -distances.min())))
        peg_penetration = max(peg_penetration, float(max(0., -distances[peg].min())))
        delta = xyz[anchors] - pair['xyz'][anchors]
        # Tethers use NAMD's periodic nearest-image displacement to consref.
        box = np.array(slit.box_nm)*10
        delta -= box*np.rint(delta/box)
        squared = np.sum(delta**2, axis=1)
        if energy_by_step:
            row = energy_by_step.get(layout.istart+i*layout.nsavc)
            if row is not None and 'BOUNDARY' in row and 'MISC' in row:
                tether_energy = manifest['graft_k_kcal_mol_A2']*float(squared.sum())
                wall_energy = slit.energy_forces(xyz)[0]
                energy_errors.append(max(abs(row['BOUNDARY']-tether_energy), abs(row['MISC']-wall_energy)))
        max_anchor = max(max_anchor, float(np.sqrt(squared.max())))
        sum_anchor_sq += squared.sum()
        if first is None:
            first = xyz[peg].copy()
        else:
            motion = xyz[peg]-first
            motion -= box*np.rint(motion/box)
            max_motion = max(max_motion, float(np.sqrt(np.mean(np.sum(motion**2, axis=1)))))
    return dict(saved_frames=layout.n_frames, sampled_max_penetration_A=max_penetration,
                sampled_PEG_max_penetration_A=peg_penetration,
                sampled_max_anchor_displacement_A=max_anchor,
                sampled_anchor_rms_displacement_A=float(np.sqrt(sum_anchor_sq/(len(anchors)*layout.n_frames))),
                sampled_PEG_motion_rms_A=max_motion,
                energy_comparison_frames=len(energy_errors),
                max_force_energy_error_kcal_mol=max(energy_errors) if energy_errors else None)


def analyze(package):
    package = Path(package)
    manifest = verify_inputs(package)
    log = (package/'resident.log').read_text(errors='replace')
    rows = parse_namd_log_frames(package/'resident.log')
    resident = 'Running with GPU-resident mode' in log
    finite = bool(rows) and all({'TS', 'TOTAL', 'TEMP', 'BOUNDARY', 'MISC'} <= row.keys()
                               and all(math.isfinite(v) for v in row.values()) for row in rows)
    complete = bool(rows) and rows[-1].get('TS') == manifest['steps'] and 'End of program' in log
    fatal = bool(re.search(r'FATAL ERROR|CUDA error|Constraint failure|Atoms moving too fast', log, re.I))
    receipt = json.loads((package/'resident_execution.json').read_text())
    metrics = trajectory_metrics(package, manifest, rows)
    checks = dict(gpu_resident_confirmed=resident, finite_energy_records=finite,
                  requested_steps_completed=complete, no_engine_errors=not fatal,
                  process_exited_zero=receipt['returncode'] == 0,
                  emitted_forces_match_analytic_energies=(metrics['energy_comparison_frames'] == metrics['saved_frames']
                      and metrics['max_force_energy_error_kcal_mol'] is not None
                      and metrics['max_force_energy_error_kcal_mol'] < .1),
                  frames_cover_run=metrics['saved_frames'] >= manifest['steps']//100,
                  wall_penetration_below_1A=metrics['sampled_max_penetration_A'] < 1.,
                  graft_excursion_below_1p5A=metrics['sampled_max_anchor_displacement_A'] < 1.5,
                  PEG_is_mobile=metrics['sampled_PEG_motion_rms_A'] > 1e-4)
    result = dict(status='short_qualification_passed' if all(checks.values()) else 'failed',
                  checks=checks, metrics=metrics, completed_steps=rows[-1].get('TS') if rows else None,
                  duration_ps=manifest['steps']*manifest['timestep_fs']/1000,
                  limitations=['Coordinates sampled every 100 steps, energies every 10 steps.',
                               'Finite-stiffness wall; thresholds are smoke criteria, not physical validation.',
                               'No equilibrium, brush thermodynamics, production/HMR or throughput qualification.'])
    (package/'validation.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def run_stage(package, stage, namd, threads=2, device=0):
    package = Path(package).resolve()
    verify_inputs(package)
    if stage not in ('minimize', 'resident') or not 1 <= threads <= 8 or not 0 <= device <= 15:
        raise ValueError('invalid stage, threads or GPU device')
    # Friendly preflight; the binding guard still independently checks its session/lock.
    marker = ROOT/'.nadoc-test-session'
    if not marker.exists() or int(marker.read_text().splitlines()[0]) <= time.time():
        raise RuntimeError('Run `just test-session` in your terminal first (CLAUDE.md verification rule).')
    occupied, reason = heavy_sim_running()
    if occupied:
        raise RuntimeError(f'Existing simulation owns the machine: {reason}')
    namd = str(Path(shutil.which(str(namd)) or namd).resolve())
    if not Path(namd).is_file():
        raise ValueError('NAMD executable not found')
    if (package/f'{stage}.log').exists() or any((package/'output').glob(f'{stage}.*')):
        raise ValueError('stage outputs already exist; preserve evidence and prepare a new package')
    if stage == 'resident':
        prior = json.loads((package/'minimize_execution.json').read_text())
        if prior['returncode'] or prior['binary_sha256'] != sha256(namd):
            raise ValueError('successful minimization with the same NAMD binary is required')
        if prior['coordinate_sha256'] != sha256(package/'output/minimize.coor'):
            raise ValueError('minimized coordinates changed')
    command = [namd, f'+p{threads}', '+devices', str(device), str(package/f'{stage}.conf')]
    # NAMD paths are relative to the package. Run guard from repository root and use
    # a shell with positional arguments, not interpolated executable/path text.
    guarded = ['bash', str(ROOT/'scripts/test_guard.sh'), f'PEG-wall-{stage}', '0', '1', '--',
               'bash', '-c', 'cd -- "$1" && shift && exec timeout 180 "$@"', 'peg-wall', str(package), *command]
    start = time.time()
    with (package/f'{stage}.log').open('x') as log:
        proc = subprocess.run(guarded, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    result = dict(command=command, binary=namd, binary_sha256=sha256(namd),
                  returncode=proc.returncode, elapsed_seconds=time.time()-start,
                  input_hashes=verify_inputs(package)['input_hashes'])
    coor = package/f'output/{stage}.coor'
    if coor.exists():
        result['coordinate_sha256'] = sha256(coor)
    (package/f'{stage}_execution.json').write_text(json.dumps(result, indent=2)+'\n')
    if proc.returncode:
        raise RuntimeError(f'{stage} failed; inspect {package}/{stage}.log')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--stage', choices=['minimize', 'resident', 'analyze'], required=True)
    parser.add_argument('--namd', type=Path)
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--device', type=int, default=0)
    args = parser.parse_args()
    if args.stage == 'analyze':
        result = analyze(args.package)
    else:
        if not args.namd:
            parser.error('--namd is required for execution; choose the pinned GPU-resident build')
        result = run_stage(args.package, args.stage, args.namd, args.threads, args.device)
        if args.stage == 'resident':
            result = analyze(args.package)
    print(json.dumps(result, indent=2))
    if result.get('status') == 'failed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
