"""Static, DNA-only playback tables; no geometry reconstruction or solvent topology.

The cache contains derived display metadata only. File identities and the complete
active design key it; trajectories are reopened and counted on every request.
"""
from __future__ import annotations

from collections import OrderedDict
import fcntl
import hashlib
import os
from pathlib import Path
import pickle
import tempfile

import numpy as np


_TABLES = OrderedDict()


def _identity(path):
    path = Path(path).resolve()
    stat = path.stat()
    return str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def playback_context(topology, paths, coordinate, design):
    from backend.core.md_trajectory import _DcdPrefixChain

    root = Path(os.environ.get('NADOC_MD_PLAYBACK_CACHE_DIR',
                str(Path(tempfile.gettempdir()) / f'nadoc-md-playback-{os.getuid()}')))
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.stat().st_uid != os.getuid() or root.stat().st_mode & 0o077:
        raise ValueError('playback cache directory must be private')
    key = hashlib.sha256(repr((
        3, _identity(topology), _identity(coordinate),
        tuple(_identity(p) if p.exists() else (str(p.resolve()), None)
              for p in (Path(topology).parent / 'charge_audit.json',
                        Path(topology).parent / 'manifest.json')),
        design.model_dump(mode='json'),
    )).encode()).hexdigest()
    target = root / (key + '.pickle')
    ctx = _TABLES.get(key)
    if ctx is None:
        with (root / (key + '.lock')).open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                with target.open('rb') as fh:
                    ctx = pickle.load(fh)
            except (OSError, EOFError, pickle.UnpicklingError):
                ctx = _build_tables(topology, coordinate, design)
                fd, tmp = tempfile.mkstemp(dir=root)
                try:
                    with os.fdopen(fd, 'wb') as fh:
                        pickle.dump(ctx, fh, protocol=pickle.HIGHEST_PROTOCOL)
                    os.replace(tmp, target)
                finally:
                    Path(tmp).unlink(missing_ok=True)
                # Bounded, rebuildable metadata cache. Do not retain arbitrary job histories.
                entries = sorted(root.glob('*.pickle'), key=lambda p: p.stat().st_mtime, reverse=True)
                size = 0
                for entry in entries:
                    size += entry.stat().st_size
                    if size > 256 * 1024**2 and entry != target:
                        entry.unlink(missing_ok=True)
        _TABLES[key] = ctx
        while len(_TABLES) > 2:
            _TABLES.popitem(last=False)
    else:
        _TABLES.move_to_end(key)
    ctx = dict(ctx)  # only static tables are shared; readers/alignment state are private
    prefix = _DcdPrefixChain(paths, ctx.pop('prefix_atoms'))
    ctx.update(dcd_prefix=prefix, n_frames=int(prefix.ends[-1]), universe=None,
               R_prev=None, prev_frame_idx=-999, playback_only=True)
    return ctx


def _build_tables(topology, coordinate, design):
    from backend.core.atomistic_to_nadoc import (
        _GRO_DNA_RESNAMES, atom_design_ident, build_active_design_reference,
        build_namd_coarse_reference, load_segid_chain_map,
        md_rigid_reference_from_map, md_snap_mask,
    )
    from backend.core.md_base_frames import _RING_NAMES

    if design.extensions or any(getattr(x, 'extra_bases', None) for x in design.crossovers):
        raise ValueError('synthetic residues require the full mapping')
    segmap = load_segid_chain_map(Path(topology).parent)
    if not segmap:
        raise ValueError('no package residue mapping')
    cm, _ = build_namd_coarse_reference(design, coordinate, segmap, mapping_only=True)
    reference = build_active_design_reference(design)
    letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    strand_by_chain = {
        (letters[i] if i < 26 else letters[i // 26 - 1] + letters[i % 26]): s.id
        for i, s in enumerate(design.strands)
    }
    residues = {}
    heavy, meta, heavy_res = [], [], []
    with Path(topology).open() as fh:
        for line in fh:
            if '!NATOM' in line:
                natoms = int(line.split()[0])
                break
        else:
            raise ValueError('PSF has no atoms')
        for expected in range(natoms):
            fields = next(fh).split()
            if int(fields[0]) != expected + 1:
                raise ValueError('nonsequential PSF atom numbering')
            if fields[3] not in _GRO_DNA_RESNAMES:
                continue
            segid, resid, name = fields[1], int(fields[2]), fields[4]
            rk = (segid, resid)
            if rk not in residues:
                chain = segmap.get(segid)
                key = cm.get((chain, resid))
                if key is None or tuple(key) not in reference:
                    raise ValueError('incomplete lightweight residue mapping')
                residues[rk] = dict(row=len(residues), key=key, atoms={},
                                    ident=atom_design_ident(key, strand_by_chain[chain]))
            res = residues[rk]
            res['atoms'][name] = expected
            element = name.lstrip('0123456789')[0].upper()
            if element != 'H':
                heavy.append(expected)
                heavy_res.append(res['row'])
                meta.append(dict(serial=expected, element=element, name=name, **res['ident']))
        bonds = np.empty((0, 2), dtype=np.int32)
        for line in fh:
            if '!NBOND' in line:
                count = int(line.split()[0]) * 2
                numbers = []
                while count > 0:
                    line = next(fh)
                    numbers.append(line)
                    count -= len(line.split())
                bonds = np.fromstring(' '.join(numbers), sep=' ', dtype=np.int32).reshape(-1, 2) - 1
                break
    if not heavy or len(residues) != len(cm):
        raise ValueError('DNA topology does not exactly cover the design residue map')
    heavy = np.asarray(heavy, dtype=np.int64)
    mask = np.zeros(natoms, dtype=bool)
    mask[heavy] = True
    bonds = bonds[mask[bonds].all(axis=1)]
    # MDAnalysis normalizes pair direction but preserves PSF record order.
    bonds = np.sort(bonds, axis=1)
    rows = list(residues.values())
    prows = [r for r in rows if 'P' in r['atoms']]
    order = [r['key'] for r in prows]
    pidx = np.asarray([r['atoms']['P'] for r in prows], dtype=np.int64)
    c1 = np.asarray([r['atoms']["C1'"] for r in prows], dtype=np.int64)
    p_at = {tuple(k): i for i, k in enumerate(order)}
    terms, trows = [], []
    for (segid, resid), res in residues.items():
        a = res['atoms']
        neighbor = cm.get((segmap[segid], resid + 1))
        ni = p_at.get(tuple(neighbor)) if neighbor is not None else None
        if 'P' not in a and "O5'" in a and "C1'" in a and ni is not None:
            terms.append((res['key'], a["O5'"], a["C1'"], ni))
            trows.append(res)
    rings = [np.asarray([i for name, i in r['atoms'].items() if name in _RING_NAMES], dtype=np.int64)
             for r in prows + trows]
    groups = []
    for size in sorted({len(r) for r in rings if len(r) >= 5}):
        indices = np.asarray([i for i, r in enumerate(rings) if len(r) == size])
        groups.append((indices, np.stack([rings[i] for i in indices])))
    anchors = np.asarray(list(pidx) + [s[1] for s in terms], dtype=np.int64)
    global_to_heavy = {int(v): i for i, v in enumerate(heavy)}
    res_anchor = [global_to_heavy[r['atoms'].get('P', next(i for i in r['atoms'].values() if i in global_to_heavy))] for r in rows]
    segids = [key[0] for key in residues]
    segments = {s: i for i, s in enumerate(dict.fromkeys(segids))}
    heavy_res = np.asarray(heavy_res, dtype=np.int64)
    heavy_segment = np.asarray([segments[s] for s in segids])[heavy_res]
    p_heavy = np.asarray([global_to_heavy[int(i)] for i in pidx])
    p_segment = heavy_segment[p_heavy]
    for i, m in enumerate(meta):
        m['segment_group'] = int(heavy_segment[i])
    layout = dict(heavy_res_group=heavy_res, residue_anchor_rows=np.asarray(res_anchor),
                  residue_segment_ids=np.asarray(segids, dtype=object),
                  heavy_segment_group=heavy_segment, p_heavy_rows=p_heavy,
                  p_segment_group=p_segment, n_segments=len(segments),
                  segment_p_rows=[np.flatnonzero(p_segment == s) for s in range(len(segments))],
                  segment_heavy_rows=[np.flatnonzero(heavy_segment == s) for s in range(len(segments))])
    eq, valid, rigid = md_rigid_reference_from_map(reference, order)
    if rigid.sum() < 3:
        raise ValueError('no rigid display reference')
    centroid = eq[rigid].mean(axis=0)
    centered = eq - centroid
    centered[~rigid] = 0
    return dict(p_order=order, dna_p_idx=pidx, c1p_idx=c1,
                centroid_T=np.zeros(3), eq_positions=eq, eq_valid=valid,
                rigid_mask=rigid, snap_mask=md_snap_mask(order, valid, rigid),
                eq_centroid=centroid, eq_centered=centered,
                base_ring_idx=rings[:len(prows)], full_base_layout=(anchors, groups),
                term_specs=terms, heavy_idx=heavy, atom_meta=meta,
                direct_heavy_layout=layout, heavy_bonds=bonds,
                prefix_atoms=max(int(heavy.max()), int(anchors.max())) + 1,
                n_dna_p=len(order), p_order_source='psf-stream')
