"""Bounded, resumable NAMD flex statistics, shared by all representations.

Only the last preview chunk and a single current frame are read. The final pass
retains chronological alignment semantics and O(DNA atoms) sufficient statistics.
Preview statistics are separate: no frame is double weighted in the final map.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

import numpy as np

from backend.core.trajectory_cache import persistent_analysis, _signature

CHUNK_FRAMES = 32
PUBLISH_SECONDS = 5.0


def _render(ctx, state, reference_frame, include_reference_frame=True):
    from backend.core.md_trajectory import _add_mean_axis_tangents
    p_order = ctx['p_order']
    n_keys = len(p_order)
    term_specs = ctx.get('term_specs') or []
    n_term = len(term_specs)
    used = int(state['used'])
    have_norm = bool(state['have_norm'])
    sum_pos = state['sum_pos']
    sum_sq = state['sum_sq']
    sum_norm = state['sum_norm']
    sum_base = state['sum_base']
    count_base = state['count_base']
    sum_tpos = state['sum_tpos']
    sum_tsq = state['sum_tsq']
    sum_tnorm = state['sum_tnorm']
    mean_pos = sum_pos / used
    msd = sum_sq / used - np.einsum("ij,ij->i", mean_pos, mean_pos)
    rmsf = np.sqrt(np.maximum(msd, 0.0))

    if have_norm:
        nrm = np.linalg.norm(sum_norm, axis=1, keepdims=True)
        mean_norm = sum_norm / np.where(nrm > 1e-6, nrm, 1.0)
    else:
        mean_norm = np.tile([0.0, 0.0, 1.0], (n_keys, 1))

    positions = []
    for i, key in enumerate(p_order):
        hid, bp, direction = key[0], key[1], key[2]
        copy = key[3] if len(key) > 3 else 0  # loop-insertion copy index (0 = base)
        position = {
            "helix_id": hid,
            "bp_index": bp,
            "direction": direction,
            "copy": copy,
            "backbone_position": [
                float(mean_pos[i, 0]),
                float(mean_pos[i, 1]),
                float(mean_pos[i, 2]),
            ],
            "nx": float(mean_norm[i, 0]),
            "ny": float(mean_norm[i, 1]),
            "nz": float(mean_norm[i, 2]),
            "rmsf": float(rmsf[i]),
        }
        if count_base[i] > 0:
            position["base_position"] = (sum_base[i] / count_base[i]).tolist()
        positions.append(position)

    # Append the recovered 5'-terminal nucleotides (same payload shape, real keys).
    rmsf_all = rmsf
    if n_term:
        mean_t = sum_tpos / used
        rmsf_t = np.sqrt(
            np.maximum(sum_tsq / used - np.einsum("ij,ij->i", mean_t, mean_t), 0.0)
        )
        tn = np.linalg.norm(sum_tnorm, axis=1, keepdims=True)
        mean_tnorm = sum_tnorm / np.where(tn > 1e-6, tn, 1.0)
        for j, (key, *_rest) in enumerate(term_specs):
            positions.append(
                {
                    "helix_id": key[0],
                    "bp_index": key[1],
                    "direction": key[2],
                    "copy": key[3]
                    if len(key) > 3
                    else 0,  # 5'-termini are base copies (0)
                    "backbone_position": [
                        float(mean_t[j, 0]),
                        float(mean_t[j, 1]),
                        float(mean_t[j, 2]),
                    ],
                    "nx": float(mean_tnorm[j, 0]),
                    "ny": float(mean_tnorm[j, 1]),
                    "nz": float(mean_tnorm[j, 2]),
                    "rmsf": float(rmsf_t[j]),
                }
            )
        rmsf_all = np.concatenate([rmsf, rmsf_t]) if len(rmsf_t) else rmsf

    context = {}
    if include_reference_frame:
        # Actual PSF strand/residue order, including recovered 5' termini. Do not
        # connect spatially close nucleotides belonging to different strands.
        strands = {}
        for row, (segid, resid) in enumerate(ctx['backbone_residues']):
            strands.setdefault(segid, []).append((resid, row))
        edges = []
        for strand in strands.values():
            strand.sort()
            edges.extend([a[1], b[1]] for a, b in zip(strand, strand[1:]) if b[0] == a[0] + 1)
        context = {"reference_frame": {k: v.tolist() for k, v in reference_frame.items()},
                   "backbone_edges": edges}

    _add_mean_axis_tangents(positions)
    return {
        "ready": True,
        "n_frames": used,
        "positions": positions,
        "min_rmsf": float(rmsf_all.min()),
        "max_rmsf": float(rmsf_all.max()),
        "mean_rmsf": float(rmsf_all.mean()),
        **context,
    }


def _empty(ctx):
    n, t = len(ctx['p_order']), len(ctx.get('term_specs') or [])
    return dict(sum_pos=np.zeros((n, 3)), sum_sq=np.zeros(n), sum_norm=np.zeros((n, 3)),
                sum_base=np.zeros((n, 3)), count_base=np.zeros(n, dtype=np.int64),
                sum_tpos=np.zeros((t, 3)), sum_tsq=np.zeros(t), sum_tnorm=np.zeros((t, 3)),
                atom_sum=np.zeros((len(ctx['atom_meta']), 3)), used=np.array(0),
                have_norm=np.array(False), next_sample=np.array(0))


def _add(ctx, state, index, reference):
    from backend.core.md_trajectory import _extract_md_nadoc_frame, _extract_md_atoms_frame
    previous = ctx.get('R_prev'), ctx.get('prev_frame_idx', -999)
    p, normals, bases, terms, tnorm = _extract_md_nadoc_frame(
        ctx, index, with_termini=True, with_base_centers=True,
        **({'frame_out': reference} if index == 0 else {}))
    coarse_state = ctx.get('R_prev'), ctx.get('prev_frame_idx', -999)
    ctx['R_prev'], ctx['prev_frame_idx'] = previous
    atoms = _extract_md_atoms_frame(ctx, index, positions_only=True)
    ctx['R_prev'], ctx['prev_frame_idx'] = coarse_state
    if p is None or len(p) != len(state['sum_pos']) or len(atoms) != len(state['atom_sum']):
        raise ValueError(f'Incomplete DNA coordinates in frame {index}')
    state['sum_pos'] += p
    state['sum_sq'] += np.einsum('ij,ij->i', p, p)
    if normals is not None:
        state['sum_norm'] += normals
        state['have_norm'][...] = True
    if bases is not None:
        valid = np.isfinite(bases).all(axis=1)
        state['sum_base'][valid] += bases[valid]
        state['count_base'][valid] += 1
    if len(state['sum_tpos']):
        if terms is None or len(terms) != len(state['sum_tpos']):
            raise ValueError(f'Missing terminal coordinates in frame {index}')
        state['sum_tpos'] += terms
        state['sum_tsq'] += np.einsum('ij,ij->i', terms, terms)
        state['sum_tnorm'] += tnorm
    state['atom_sum'] += atoms
    state['used'] += 1


def _average(ctx, state, include_model=True):
    meta = ctx['atom_meta']
    means = state['atom_sum'] / int(state['used'])
    serials = np.asarray([m['serial'] for m in meta], dtype=np.int64)
    flat = np.zeros((int(serials.max()) + 1, 3), dtype=np.float32)
    flat[serials] = means
    result = dict(ready=True, n_frames=int(state['used']), atomistic=flat.ravel().tolist())
    if not include_model:
        return result
    atoms = [{**m, 'x': float(p[0]), 'y': float(p[1]), 'z': float(p[2]),
              'scalar_key': m.get('scalar_key') or
                  f"{m.get('helix_id', '')}:{m.get('bp_index', 0)}:{m.get('direction', '')}:{m.get('copy_k', 0)}"}
             for m, p in zip(meta, means)]
    bonds = ctx['heavy_bonds'].tolist()
    return dict(ready=True, n_frames=int(state['used']), atomistic=flat.ravel().tolist(),
                model=dict(atoms=atoms, bonds=bonds, bonds_available=bool(bonds), n_serials=len(flat)))


def _checkpoint_path(inputs):
    paths = []
    signature = _signature(inputs, paths)
    root = next((p for path in paths for p in path.parents if (p / 'job.json').is_file()), None)
    if root is None:
        return None
    directory = root / 'analysis_cache'
    directory.mkdir(exist_ok=True)
    digest = hashlib.sha256(json.dumps([1, signature], sort_keys=True).encode()).hexdigest()
    return directory / f'flex-checkpoint-{digest}.npz'


def _save(path, state, ctx, reference):
    if path is None:
        return
    # SIGKILL cannot execute finally. Serialize checkpoint writes per job so a
    # following writer can safely remove the one interrupted temporary file.
    import fcntl
    with (path.parent / '.flex-checkpoints.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for orphan in path.parent.glob('.flex-write-*'):
            orphan.unlink(missing_ok=True)
        fd, name = tempfile.mkstemp(prefix='.flex-write-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as output:
                np.savez(output, **state, rotation=ctx['R_prev'] if ctx.get('R_prev') is not None else np.empty(0),
                         previous=np.array(ctx.get('prev_frame_idx', -999)),
                         reference=np.array(json.dumps({k: v.tolist() for k, v in reference.items()})))
            os.replace(name, path)
            # Bounded resumable state per job. Completed shared results live in the
            # existing analysis cache; old interrupted input revisions are disposable.
            for old in sorted(path.parent.glob('flex-checkpoint-*.npz'), key=lambda p: p.stat().st_mtime, reverse=True)[2:]:
                old.unlink(missing_ok=True)
        finally:
            Path(name).unlink(missing_ok=True)


@persistent_analysis
def calculate_flex(topology_path, segments, coordinate_path, design, max_frames=0, frame_range=None, progress=None):
    from backend.core.md_trajectory import _build_playback_ctx, _stride_pick

    report = progress or (lambda *args: None)
    publish = getattr(progress, 'publish', lambda *args: None)
    report('rmsf_setup', 0, 1)
    ctx = _build_playback_ctx(topology_path, [s[2] for s in segments], coordinate_path, design)
    try:
        n = ctx['n_frames']
        if not n or not ctx['p_order']:
            empty = dict(ready=False, n_frames=0, positions=[], reason='no trajectory frames or mapped bases')
            return dict(ready=False, rmsf=empty, average=dict(ready=False, atomistic=[], n_frames=0))
        from backend.core.md_flex_range import flex_frame_indices
        indices = flex_frame_indices(n, frame_range)
        if max_frames > 0 and len(indices) > max_frames:
            indices = _stride_pick(indices, max_frames)
        total = len(indices)
        # Coarse and heavy extraction share one read, never a trajectory-sized array.
        reader = ctx['dcd_prefix']
        read = reader.frame
        last_index, last_frame = None, None
        def frame(index):
            nonlocal last_index, last_frame
            if index != last_index:
                last_frame = read(index)
                last_index = index
            return last_frame
        reader.frame = frame
        state, reference = _empty(ctx), {}
        budget = getattr(progress, 'slice_seconds', None)
        slice_started = time.monotonic()
        path = _checkpoint_path((topology_path, segments, coordinate_path, design, max_frames, frame_range))
        if path is not None and path.exists():
            try:
                with np.load(path, allow_pickle=False) as saved:
                    restored = {k: saved[k] for k in state}
                    if any(restored[k].shape != state[k].shape for k in state):
                        raise ValueError('checkpoint shape mismatch')
                    if not 0 <= int(restored['next_sample']) <= total or int(restored['used']) != int(restored['next_sample']):
                        raise ValueError('checkpoint coverage mismatch')
                    state = restored
                    ctx['R_prev'] = saved['rotation'] if saved['rotation'].size else None
                    ctx['prev_frame_idx'] = int(saved['previous'])
                    reference = {k: np.array(v) for k, v in json.loads(str(saved['reference'])).items()}
            except (OSError, ValueError, KeyError, EOFError):
                state, reference = _empty(ctx), {}
                ctx['R_prev'], ctx['prev_frame_idx'] = None, -999
        start = int(state['next_sample'])
        if start:
            publish(_render(ctx, state, reference), 'backfill', start, total, _average(ctx, state))
        elif callable(getattr(progress, 'publish', None)):
            preview = _empty(ctx)
            tail = indices[max(0, total - CHUNK_FRAMES):]
            report('tail_preview', 0, len(tail))
            for i, index in enumerate(tail):
                _add(ctx, preview, index, {})
                report('tail_preview', i + 1, len(tail))
            publish(_render(ctx, preview, {}, False), 'tail_preview', len(tail), total, _average(ctx, preview))
            # The chronological pass preserves the original sequential alignment
            # convention. Preview is separate, so its frames never get extra weight.
            ctx['R_prev'], ctx['prev_frame_idx'] = None, -999
        last_publish = time.monotonic()
        for sample in range(start, total):
            _add(ctx, state, indices[sample], reference)
            state['next_sample'][...] = sample + 1
            boundary = (sample + 1) % CHUNK_FRAMES == 0 or sample + 1 == total
            if boundary:
                _save(path, state, ctx, reference)
                report('backfill', sample + 1, total)
                now = time.monotonic()
                if now - last_publish >= PUBLISH_SECONDS or sample + 1 == total:
                    publish(_render(ctx, state, reference), 'backfill', sample + 1, total, _average(ctx, state, include_model=False))
                    last_publish = now
                if path is not None and budget and now - slice_started >= budget and sample + 1 < total:
                    pending = dict(ready=False, continue_calculation=True)
                    return dict(pending, rmsf=dict(pending), average=dict(pending))
                time.sleep(0.01)  # yield disk/CPU between bounded chunks
        result = dict(ready=True, rmsf=_render(ctx, state, reference), average=_average(ctx, state))
        return result
    finally:
        ctx['dcd_prefix'].close()
