"""Read only a DCD's final 20 ns; measure DNA heavy-atom 3-sigma envelopes.

No trajectory frames before the requested window are read. The input PDB provides
the preparation reference. Alignment uses DNA phosphorus atoms, with no scaling.
Both aligned (internal deformation) and translation-only (actual cell orientation)
envelopes are reported. 3 sigma is a marginal coordinate statistic, not a joint
confidence bound or a guarantee against periodic-image artifacts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np
from threadpoolctl import threadpool_limits

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core.resume_transfer import dcd_layout
from backend.core.md_plan import parse_conf_directives


def rotation(moving, reference):
    u, _, vt = np.linalg.svd(moving.T @ reference)
    return u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt


def envelope(mean, m2, count, reference):
    sigma = np.sqrt(np.maximum(m2 / (count - 1), 0))
    lower, upper = (mean - 3 * sigma).min(0), (mean + 3 * sigma).max(0)
    mean_lower, mean_upper = mean.min(0), mean.max(0)
    ref_lower, ref_upper = reference.min(0), reference.max(0)
    fluct = np.maximum(mean_lower - lower, upper - mean_upper) / 10
    expanded = np.maximum(ref_lower - lower, upper - ref_upper) / 10
    return dict(
        mean_span_nm=((mean_upper - mean_lower) / 10).tolist(),
        three_sigma_span_nm=((upper - lower) / 10).tolist(),
        fluctuation_padding_per_axis_nm=fluct.tolist(),
        expansion_from_input_per_axis_nm=expanded.tolist(),
        # Extra 2 nm per face retains a 4 nm envelope-to-image gap.
        padding_from_mean_for_4nm_gap_nm=(fluct + 2).tolist(),
        padding_from_input_for_4nm_gap_nm=(np.maximum(expanded, 0) + 2).tolist(),
        box_for_4nm_gap_nm=((upper - lower) / 10 + 4).tolist(),
    )


def analyze(row, out):
    started = time.monotonic()
    dcd = Path(row['path'])
    pkg = dcd.parent.parent
    stem = dcd.stem.split('.cont')[0]
    conf = parse_conf_directives((pkg / (stem + '.conf')).read_text())
    wrapped = conf.get('wrapall', 'off').lower() not in ('off', 'no', 'false')
    psf, pdb = pkg / conf['structure'], pkg / conf['coordinates']
    ids, phosphorus, segments = [], [], []
    with psf.open() as f:
        for line in f:
            if '!NATOM' in line:
                natoms = int(line.split()[0])
                break
        for i in range(natoms):
            a = next(f).split()
            if a[3] in {'ADE', 'THY', 'GUA', 'CYT', 'DA', 'DT', 'DG', 'DC'} and not a[4].startswith('H'):
                if a[4] == 'P':
                    phosphorus.append(len(ids))
                ids.append(i)
                segments.append(a[1])
    ids, phosphorus = np.array(ids), np.array(phosphorus)
    if not len(phosphorus):
        raise ValueError('No DNA phosphorus atoms')
    reference = []
    selected = set(ids)
    i = 0
    with pdb.open() as f:
        for line in f:
            if line.startswith(('ATOM  ', 'HETATM')):
                if i in selected:
                    reference.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
                i += 1
                if i > ids[-1]:
                    break
    reference = np.array(reference)
    if len(reference) != len(ids):
        raise ValueError('PDB/PSF atom count mismatch')
    reference -= reference[phosphorus].mean(0)
    ref_fit = reference[phosphorus]
    segment_ids = np.array(segments)
    groups = [np.flatnonzero(segment_ids == seg) for seg in sorted(set(segments))]
    scaffold = max(groups, key=len)
    layout = dcd_layout(dcd)
    assert layout and layout.n_atoms == natoms and row['periodic']
    mm = np.memmap(dcd, mode='r', dtype='u1')
    nframes = row['frames']
    start = max(0, int(np.ceil((row['last_ns'] - 20 - row['first_ns']) / row['interval_ns'] - 1e-7)))
    arrays = [np.ndarray((nframes, natoms), dtype='<f4', buffer=mm,
              offset=layout.header_size + 56 + 4 + axis * (8 + 4 * natoms),
              strides=(layout.frame_size, 4)) for axis in range(3)]
    cells = np.ndarray((nframes, 6), dtype='<f8', buffer=mm,
                       offset=layout.header_size + 4, strides=(layout.frame_size, 8))
    cell_samples, span_samples = [], []
    moments = [(np.zeros_like(reference), np.zeros_like(reference)) for _ in range(2)]
    count = 0
    for frame in range(start, nframes):
        raw = np.column_stack([a[frame, ids] for a in arrays]).astype(float)
        cell = cells[frame, [0, 2, 5]].copy()
        angles = cells[frame, [1, 3, 4]]
        if not (np.allclose(angles, 0) or np.allclose(angles, 90)):
            raise ValueError('Nonorthorhombic cell requires a different audit')
        if wrapped:
            # NAMD wraps entire bonded strands. Register each PSF segment to the
            # scaffold's image using the prepared assembly; never wrap atoms
            # independently, which would hide deformations or break a strand.
            displacement = np.median(raw[scaffold] - reference[scaffold], axis=0)
            for group in groups:
                relative = np.median(raw[group] - reference[group], axis=0) - displacement
                raw[group] -= np.rint(relative / cell) * cell
        raw -= raw[phosphorus].mean(0)
        aligned = raw @ rotation(raw[phosphorus], ref_fit)
        count += 1
        for x, (mean, m2) in zip((aligned, raw), moments):
            delta = x - mean
            mean += delta / count
            m2 += delta * (x - mean)
        cell_samples.append(cell / 10)
        span_samples.append(np.ptp(raw, axis=0) / 10)
        if count % 250 == 0:
            print(dcd.name, count, '/', nframes - start, flush=True)
    result = dict(
        source=row, input_pdb=str(pdb), config=str(pkg / (stem + '.conf')),
        n_heavy_atoms=len(ids), n_alignment_atoms=len(phosphorus),
        wrapped_strand_reconstruction=wrapped,
        first_analyzed_frame=start, last_analyzed_frame=nframes-1, frames_analyzed=count,
        analyzed_start_ns=row['first_ns']+start*row['interval_ns'], analyzed_end_ns=row['last_ns'],
        aligned=envelope(*moments[0], count, reference),
        cell_orientation=envelope(*moments[1], count, reference),
        input_span_nm=(np.ptp(reference, axis=0) / 10).tolist(),
        mean_cell_nm=np.mean(cell_samples, axis=0).tolist(),
        minimum_cell_nm=np.min(cell_samples, axis=0).tolist(),
        minimum_envelope_gap_nm=np.min(np.array(cell_samples)-span_samples, axis=0).tolist(),
        elapsed_s=time.monotonic()-started,
    )
    out.write_text(json.dumps(result, indent=2))
    np.savez_compressed(out.with_suffix('.npz'), mean=moments[0][0],
                        sigma=np.sqrt(np.maximum(moments[0][1]/(count-1),0)))
    print('DONE', out.name, result['aligned']['padding_from_input_for_4nm_gap_nm'], flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('inventory', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--match', default='24hb_')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    with threadpool_limits(limits=1):
        for row in json.loads(args.inventory.read_text()):
            if row.get('duration_ns',0) <= 20 or args.match not in row['path']:
                continue
            # Include job folder to distinguish multiple runs of one design.
            dcd = Path(row['path'])
            out = args.out / (dcd.parents[3].name + '_' + dcd.stem + '.json')
            if out.exists():
                continue
            try:
                analyze(row, out)
            except Exception as exc:
                print('ERROR', row['path'], repr(exc), flush=True)
                out.with_suffix('.error.json').write_text(json.dumps({'source':row,'error':repr(exc)},indent=2))


if __name__ == '__main__':
    main()
