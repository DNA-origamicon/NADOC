"""Nanopore aperture crossings and continuous, pore-centred ion paths (nm).

Read only ion coordinates from memory-mapped DCD records. Cache one immutable
trajectory snapshot; changing the path window never rereads the solvent/DNA.
"""
from __future__ import annotations

import json
import hashlib
import mmap
import struct
import threading
from pathlib import Path

import numpy as np

from backend.core.md_solvent import ion_rows, SPECIES
from backend.core.md_trajectory import _DcdPrefixFile

_lock = threading.Lock()
_cache = None


def crossing_events(xyz, cells, center, normal, radius, breaks=(), progress=None):
    """Return (later frame, ion row, direction), rejecting periodic-face crossings."""
    events = []
    breaks = set(breaks)
    for frame in range(1, len(xyz)):
        if progress and frame % 32 == 0:
            progress('crossings', frame, len(xyz))
        if frame in breaks:
            continue
        cell = cells[frame]
        delta = xyz[frame] - xyz[frame - 1]
        delta -= cell * np.round(delta / cell)
        rel = xyz[frame - 1] - center
        rel -= cell * np.round(rel / cell)
        before = np.einsum('ij,j->i', rel, normal)
        after = before + np.einsum('ij,j->i', delta, normal)
        rows = np.flatnonzero(((before < 0) & (after >= 0)) | ((before > 0) & (after <= 0)))
        if not len(rows):
            continue
        frac = before[rows] / (before[rows] - after[rows])
        hit = rel[rows] + frac[:, None] * delta[rows]
        hit -= cell * np.round(hit / cell)
        radial = hit - np.outer(np.einsum('ij,j->i', hit, normal), normal)
        for row in rows[np.linalg.norm(radial, axis=1) <= radius]:
            events.append((frame, int(row), 1 if after[row] > before[row] else -1))
    return events


def path_window(xyz, cells, frame, row, before, after, center, start=0, end=None):
    lo, hi = max(start, frame - before), min(len(xyz) if end is None else end, frame + after + 1)
    raw = xyz[lo:hi, row].astype(float)
    steps = np.diff(raw, axis=0)
    cell = cells[lo + 1:hi]
    steps -= cell * np.round(steps / cell)
    points = np.vstack([np.zeros(3), np.cumsum(steps, axis=0)])
    anchor = xyz[frame, row] - center
    anchor -= cells[frame] * np.round(anchor / cells[frame])
    points += anchor - points[frame - lo]
    return lo, points


def _read_snapshot(package, dcds, progress=None):
    report = progress or (lambda *args: None)
    report("topology", 0, 1)
    manifest = json.loads((package / 'manifest.json').read_text())
    pore = manifest.get('graphene_nanopore')
    if not isinstance(pore, dict) or not pore.get('pore_diameter_nm'):
        raise ValueError('Ion paths require a NAMD nanopore simulation.')
    center = np.asarray(pore['pore_center_nm'], float)
    normal = np.asarray(pore['dir'], float)
    if center.shape != (3,) or normal.shape != (3,) or not np.all(np.isfinite(center)) or not np.all(np.isfinite(normal)) or np.linalg.norm(normal) == 0:
        raise ValueError('Nanopore geometry is invalid.')
    normal /= np.linalg.norm(normal)
    radius = float(pore['pore_diameter_nm']) / 2
    if not np.isfinite(radius) or radius <= 0:
        raise ValueError('Nanopore diameter must be positive.')
    # Stream the PSF atom section: avoid constructing millions of topology objects.
    names, resnames, serials = [], [], []
    graphene_rows = []
    from backend.core.md_solvent import ION_ISH_RESNAMES
    with (package / f"{manifest['name_stem']}.psf").open() as fh:
        for line in fh:
            if '!NATOM' in line:
                count = int(line.split()[0])
                for atom_index in range(count):
                    if atom_index % 50000 == 0:
                        report("topology", atom_index, count)
                    fields = next(fh).split()
                    if fields[3] == "GRP":
                        graphene_rows.append(int(fields[0]) - 1)
                    if fields[3] in ION_ISH_RESNAMES:
                        serials.append(int(fields[0]))
                        resnames.append(fields[3])
                        names.append(fields[4])
                break
    report("topology", 1, 1)
    frame_count = 0
    for path in dcds:
        reader = _DcdPrefixFile(path, 0)
        try:
            frame_count += reader.n_frames
        finally:
            reader.close()
    report("coordinates", 0, frame_count)
    selected, codes = ion_rows(names, resnames)
    serials = np.asarray(serials, dtype=int)[selected]
    rows = serials - 1
    chunks, cell_chunks, breaks = [], [], []
    total = 0
    graphene = np.empty((len(graphene_rows), 3), dtype=np.float32)
    for path in dcds:
        reader = _DcdPrefixFile(path, 0)
        try:
            if not reader.cell_record_bytes:
                raise ValueError('Ion paths require a periodic cell in the trajectory.')
            # A bounded ion-only cache; never map/copy every solvent atom.
            if (total + reader.n_frames) * max(1, len(rows)) * 12 > 768 * 1024**2:
                raise ValueError('Ion trajectory exceeds the 768 MiB path-analysis limit.')
            with mmap.mmap(reader.fd, 0, access=mmap.ACCESS_READ) as mapped:
                # Random atom slices must not trigger whole-solvent OS readahead.
                if hasattr(mapped, 'madvise'):
                    mapped.madvise(mmap.MADV_RANDOM)
                xyz = np.empty((reader.n_frames, len(rows), 3), dtype=np.float32)
                cells = np.empty((reader.n_frames, 3), dtype=np.float32)
                for f in range(reader.n_frames):
                    if f % 16 == 0:
                        report("coordinates", total + f, frame_count)
                    base = reader.frame_start + f * reader.frame_bytes
                    cell = np.frombuffer(mapped, '<f8', 6, base + 4).copy()
                    if not np.allclose(cell[[1, 3, 4]], 0) and not np.allclose(cell[[1, 3, 4]], 90):
                        raise ValueError('Ion paths currently require an orthogonal periodic cell.')
                    cells[f] = cell[[0, 2, 5]] / 10
                    for axis in range(3):
                        offset = base + reader.cell_record_bytes + axis * reader.coord_record_bytes + 4
                        coord = np.frombuffer(mapped, '<f4', reader.n_atoms, offset)
                        xyz[f, :, axis] = coord[rows] / 10
                        if total == 0 and f == 0:
                            graphene[:, axis] = coord[graphene_rows] / 10
                        del coord
                if not np.all(cells > 0):
                    raise ValueError('Trajectory contains an invalid periodic cell.')
                if total:
                    breaks.append(total)  # never infer a crossing across a segment boundary
                chunks.append(xyz)
                cell_chunks.append(cells)
                total += len(xyz)
        finally:
            reader.close()
    if not chunks:
        raise ValueError('No trajectory is available yet.')
    xyz = chunks[0] if len(chunks) == 1 else np.concatenate(chunks)
    cells = cell_chunks[0] if len(chunks) == 1 else np.concatenate(cell_chunks)
    report("coordinates", 1, 1)
    report("crossings", 0, len(xyz))
    events = crossing_events(xyz, cells, center, normal, radius, breaks, progress=report)
    report("crossings", 1, 1)
    if len(graphene):
        graphene -= center
        graphene -= cells[0] * np.round(graphene / cells[0])
    return xyz, cells, serials, codes, center, normal, radius, events, breaks, graphene


def average_in_pore_frame(positions, reference, center):
    """Invert the first saved frame's actual RMSF affine, retaining its pore image."""
    box = np.asarray(reference['box_nm'])
    pore_image = center + box * np.round((np.asarray(reference['c_box']) - center) / box)
    return ((np.asarray(positions) - reference['eq_centroid']) @ np.asarray(reference['R_align'])
            + reference['mob_c'] - np.asarray(reference['T_dyn']) - pore_image)


def _origami_average(package, dcds, design, center, progress=None):
    if design is None or not design.strands:
        return None
    from backend.core.md_trajectory import md_rmsf, md_rmsf_atomistic, md_rmsf_surface

    manifest = json.loads((package / 'manifest.json').read_text())
    stem = manifest['name_stem']
    result = md_rmsf(package / f'{stem}.psf', [(str(p), '', p) for p in dcds],
                     package / f'{stem}.pdb', design, include_reference_frame=True,
                     **({"progress": progress} if progress else {}))
    if not result.get('ready') or not result.get('reference_frame'):
        raise ValueError(result.get('reason', 'Could not compute the origami RMSF average.'))
    # Prepare each representation once during the reported load. Switching views
    # then consumes cached geometry rather than spawning another trajectory scan.
    segments = [(str(p), '', p) for p in dcds]
    atoms = md_rmsf_atomistic(package / f'{stem}.psf', segments, package / f'{stem}.pdb',
                              design, include_model=True, progress=progress)
    surface = md_rmsf_surface(package / f'{stem}.psf', segments, package / f'{stem}.pdb',
                              design, average=atoms, rmsf=result, model=atoms.get('model'), progress=progress)
    positions = result['positions']
    mean = average_in_pore_frame([p['backbone_position'] for p in positions], result['reference_frame'], center)
    bases = average_in_pore_frame([p.get('base_position', p['backbone_position']) for p in positions], result['reference_frame'], center)
    reference = result['reference_frame']
    rotation = np.asarray(reference['R_align'])
    # One rigid transform puts all pore-centred companions into the shared display frame.
    translation = -average_in_pore_frame([reference['eq_centroid']], reference, center)[0] @ rotation.T + reference['eq_centroid']
    transform = np.eye(4)
    transform[:3, :3] = rotation
    transform[:3, 3] = translation
    return {'display_rmsf': result, 'atomistic_model': atoms.pop('model'),
            'atomistic_average': atoms, 'surface_average': surface, 'display_transform': transform.T.ravel().tolist(),
            'positions': np.round(mean, 5).ravel().tolist(),
            'base_positions': np.round(bases, 5).ravel().tolist(),
            'backbone_edges': result['backbone_edges'],
            'rmsf': [p['rmsf'] for p in positions], 'n_frames': result['n_frames'],
            'placement': 'RMSF average aligned into the first saved frame relative to the pore'}


MAX_PATH_WINDOW = 1_000_000


def shared_path_tracks(xyz, cells, serials, codes, center, events, bounds, before, after):
    """Store overlapping windows of the same ion once, with an image offset per crossing."""
    groups = {}
    paths = [None] * len(events)
    for index, (frame, row, direction) in enumerate(events):
        segment = int(np.searchsorted(bounds, frame, side='right')) - 1
        lo = max(bounds[segment], frame - before)
        hi = min(bounds[segment + 1], frame + after + 1)
        groups.setdefault((row, segment), []).append((lo, hi, index, frame, direction))
    tracks = []
    expanded = 0
    for (row, _segment), windows in groups.items():
        windows.sort()
        merged = []
        for window in windows:
            lo, hi = window[:2]
            if merged and lo <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], hi)
                merged[-1][2].append(window)
            else:
                merged.append([lo, hi, [window]])
        for lo, hi, members in merged:
            _, points = path_window(xyz, cells, lo, row, 0, hi - lo - 1, center, lo, hi)
            track = len(tracks)
            tracks.append(points.astype(np.float32).ravel())
            for start, end, index, frame, direction in members:
                anchor = xyz[frame, row].astype(float) - center
                anchor -= cells[frame] * np.round(anchor / cells[frame])
                offset = np.round(anchor - points[frame - lo], 5)
                paths[index] = {'ion_serial': int(serials[row]), 'species': SPECIES[int(codes[row])],
                                'crossing_frame': frame, 'direction': direction, 'start_frame': start,
                                'track': track, 'point_start': start - lo, 'point_count': end - start,
                                'offset': offset.tolist()}
                expanded += end - start
    return paths, tracks, expanded


def pack_ion_paths(data):
    """NIPT v1: 12-byte prefix, padded JSON metadata, then shared float32 xyz tracks."""
    header = {k: v for k, v in data.items() if k != 'tracks'}
    header['tracks'] = []
    offset = 0
    for track in data['tracks']:
        header['tracks'].append({'offset': offset, 'count': len(track) // 3})
        offset += len(track)
    raw = json.dumps(header, separators=(',', ':')).encode()
    padding = b'\0' * (-len(raw) % 4)
    return b''.join([struct.pack('<III', 0x4e495054, 1, len(raw)), raw, padding,
                     *(np.asarray(track, dtype='<f4').tobytes() for track in data['tracks'])])


def ion_paths(package, dcds, before=10, after=10, design=None, *, compact=False, progress=None):
    global _cache
    report = progress or (lambda *args: None)
    report("waiting", 0, 1)
    package = Path(package)
    files = [package / 'manifest.json', *package.glob('*.psf'), *map(Path, dcds)]
    files.extend(package.glob('*.pdb'))
    key = (hashlib.sha256(design.to_json().encode()).hexdigest() if design is not None else None,
           tuple((str(p.resolve()), p.stat().st_size, p.stat().st_mtime_ns) for p in files))
    with _lock:
        report("waiting", 1, 1)
        if _cache is None or _cache[0] != key:
            _cache = None
            snapshot = _read_snapshot(package, dcds, progress=report)
            origami = _origami_average(package, dcds, design, snapshot[4], progress=report)
            _cache = (key, snapshot, origami)
        for stage in ("topology", "coordinates", "crossings", "rmsf_setup", "rmsf", "atomistic_setup", "atomistic_average", "atomistic_topology", "surface"):
            report(stage, 1, 1)
        xyz, cells, serials, codes, center, normal, radius, events, breaks, graphene = _cache[1]
        bounds = [0, *breaks, len(xyz)]
        if compact:
            report("windows", 0, 1)
            paths, tracks, expanded = shared_path_tracks(
                xyz, cells, serials, codes, center, events, bounds, before, after)
            report('windows', 1, 1)
            return {'frames': len(xyz), 'ion_count': len(serials), 'crossings': len(events),
                    'before': before, 'after': after, 'paths': paths, 'tracks': tracks,
                    'expanded_points': expanded, 'stored_points': sum(len(t) // 3 for t in tracks),
                    'origami': _cache[2], 'graphene': np.round(graphene, 5).ravel().tolist(),
                    'pore': {'center_nm': [0, 0, 0], 'normal': normal.tolist(), 'radius_nm': radius},
                    'frame_basis': 'saved DCD frames, zero-based; windows clip at segment boundaries'}
        paths = []
        vertices = 0
        for frame, row, direction in events:
            segment = int(np.searchsorted(bounds, frame, side='right')) - 1
            lo, points = path_window(xyz, cells, frame, row, before, after, center, bounds[segment], bounds[segment + 1])
            vertices += len(points)
            if vertices > 1_000_000:
                raise ValueError('Too many path points. Reduce the frames before/after crossing.')
            paths.append({'ion_serial': int(serials[row]), 'species': SPECIES[int(codes[row])],
                          'crossing_frame': frame, 'direction': direction, 'start_frame': lo,
                          'positions': np.round(points, 5).ravel().tolist()})
        return {'frames': len(xyz), 'ion_count': len(serials), 'crossings': len(events),
                'before': before, 'after': after, 'paths': paths,
                'origami': _cache[2], 'graphene': np.round(graphene, 5).ravel().tolist(),
                'pore': {'center_nm': [0, 0, 0], 'normal': normal.tolist(), 'radius_nm': radius},
                'frame_basis': 'saved DCD frames, zero-based; windows clip at segment boundaries'}
