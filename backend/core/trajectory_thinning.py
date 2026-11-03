"""Preview and transactionally thin fixed-record NAMD DCDs without re-encoding frames.

Stride starts at frame zero in EACH physical DCD, so segment boundaries and first
frame timestamps survive. A durable journal + hard links allow an interrupted
multi-file replacement to be rolled back on the next operation.
"""
from __future__ import annotations

import hashlib
import json
import mmap
import os
import shutil
import struct
import uuid
from collections import OrderedDict
from pathlib import Path

import numpy as np

from backend.core.dcd_fast import read_layout, UnsupportedDCD, cell_to_dimensions

STRIDES = (1, 2, 4, 5, 10, 20, 50)


def layout(path):
    d = read_layout(path)
    if d.n_frames < 1 or d.nsavc < 1 or d.delta_ps <= 0:
        raise ValueError('Trajectory has no frames or valid timing information.')
    if Path(path).stat().st_size != d.header_bytes + d.n_frames * d.frame_bytes:
        raise ValueError('Trajectory contains an incomplete frame; thinning is unavailable.')
    with open(path, 'rb') as f:
        header = f.read(d.header_bytes)
    if struct.unpack_from(d.endian+'i', header, 8)[0] != d.n_frames:
        raise ValueError('Trajectory frame count is not finalized; thinning is unavailable.')
    if struct.unpack_from(d.endian+'i', header, 88)[0] != 84:
        raise ValueError('Invalid DCD header record.')
    return d


def fingerprint(sources):
    values = []
    for src in sources:
        for key in ('path', 'topology'):
            p = Path(src[key]); s = p.stat()
            values.append((str(p.resolve()), s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns))
        values.append(src.get('wrapped', False))
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def _frame(buf, d):
    """Validate every record marker, including trailers; return coordinate offsets."""
    pos = 0
    offsets = []
    for size in ([48] if d.has_cell else []) + [4*d.n_atoms]*3:
        if (struct.unpack_from(d.endian+'i', buf, pos)[0] != size or
                struct.unpack_from(d.endian+'i', buf, pos+4+size)[0] != size):
            raise ValueError('Invalid DCD frame record; original files have been preserved.')
        offsets.append(pos+4)
        pos += size+8
    return offsets[-3:]


def _rmsd_estimates(sources, layouts, strides, max_pairs=128):
    import MDAnalysis as mda
    from MDAnalysis.analysis.rms import rmsd
    from backend.core.cpd_metrics import make_whole_dna

    values = {k: [] for k in strides}
    totals = {k: sum(max(0, d.n_frames-k) for d in layouts) for k in strides}
    for src, d in zip(sources, layouts):
        u = mda.Universe(str(src['topology']))
        if len(u.atoms) != d.n_atoms:
            raise ValueError('Topology atom count does not match trajectory.')
        solute = u.select_atoms('segid D*')
        if not len(solute):
            solute = u.select_atoms('nucleic or protein')
        heavy = solute.select_atoms('not name H*')
        heavy = heavy[heavy.masses > 2]
        if len(heavy) < 3:
            raise ValueError('No DNA/protein heavy-atom selection available for RMSD.')
        wrapped = src.get('wrapped', False)
        fragments = solute.fragments if wrapped else None
        if wrapped:
            u.load_new(np.zeros((1, d.n_atoms, 3), dtype=np.float32))
        # Keep only the small solute coordinates in the cache, not solvent frames.
        cache = OrderedDict()
        with open(src['path'], 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as mm:
            def coordinates(i):
                if i in cache:
                    return cache[i]
                start = d.header_bytes+i*d.frame_bytes
                # Marker validation doesn't require copying the full frame.
                view = memoryview(mm)[start:start+d.frame_bytes]
                try:
                    offsets = _frame(view, d)
                    ids = solute.indices if wrapped else heavy.indices
                    xyz = np.column_stack([np.frombuffer(view, dtype=d.endian+'f4', count=d.n_atoms, offset=o)[ids] for o in offsets])
                    if wrapped:
                        cell = np.frombuffer(view, dtype=d.endian+'f8', count=6, offset=4).copy() if d.has_cell else None
                finally:
                    view.release()
                if wrapped:
                    dims = cell_to_dimensions(cell)
                    if dims is None or not np.allclose(dims[3:], 90):
                        raise ValueError('RMSD reconstruction requires an orthorhombic periodic cell.')
                    u.dimensions = dims
                    solute.positions = xyz
                    make_whole_dna(solute, fragments, dims[:3])
                    xyz = heavy.positions.copy()
                if not np.isfinite(xyz).all():
                    raise ValueError('Non-finite coordinates in RMSD sample.')
                cache[i] = xyz.astype(np.float64)
                if len(cache) > max(2, min(128, (64*1024*1024)//(len(heavy)*3*8))):
                    cache.popitem(last=False)
                return cache[i]
            for k in strides:
                count = d.n_frames-k
                if count <= 0:
                    continue
                n = min(count, max(1, round(max_pairs*count/totals[k])))
                for i in np.unique(np.linspace(0, count-1, n, dtype=int)):
                    values[k].append(float(rmsd(coordinates(int(i)), coordinates(int(i+k)), superposition=True)))
    return {k: {'median_rmsd_A': float(np.median(v)) if v else None, 'sample_pairs': len(v)} for k, v in values.items()}


def preview(sources):
    before = fingerprint(sources)
    layouts = [layout(s['path']) for s in sources]
    total = sum(Path(s['path']).stat().st_size for s in sources)
    strides = [k for k in STRIDES if any(d.n_frames > k for d in layouts) or k == 1]
    error = None
    try:
        rms = _rmsd_estimates(sources, layouts, strides)
    except (ValueError, KeyError, AttributeError, UnsupportedDCD) as exc:
        rms = {}; error = str(exc)
    if fingerprint(sources) != before:
        raise ValueError('Job files changed during assessment. Open Thin job again.')
    options = []
    for k in strides:
        kept = sum((d.n_frames+k-1)//k for d in layouts)
        size = sum(d.header_bytes+((d.n_frames+k-1)//k)*d.frame_bytes for d in layouts)
        options.append({'stride': k, 'spacing_ps': sorted({round(d.delta_ps*k, 6) for d in layouts}),
                        'frames_kept': kept, 'saved_bytes': total-size, 'saved_percent': 100*(total-size)/total,
                        **rms.get(k, {'median_rmsd_A': None, 'sample_pairs': 0})})
    return {'fingerprint': before, 'source_frames': sum(d.n_frames for d in layouts),
            'source_bytes': total, 'file_count': len(sources), 'options': options,
            'rmsd_note': error or 'Estimated from sampled frame pairs across this job; aligned DNA/protein heavy atoms. This does not test missed events.',
            'boundary_note': 'Keeps the first frame and then every selected frame interval in each trajectory segment. Frame spacing may differ between segments.'}


def _sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _save_journal(path, data):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(data, f); f.flush(); os.fsync(f.fileno())
    os.replace(tmp, path); _sync_dir(path.parent)


def recover(job_dir):
    journal = Path(job_dir)/'.trajectory-thinning.json'
    if not journal.exists():
        return
    data = json.loads(journal.read_text())
    for item in data['files']:
        source, backup, temp = (Path(item[k]) for k in ('source', 'backup', 'temp'))
        # Only paths recorded under this job can ever be restored/deleted.
        for p in (source, backup, temp):
            if not p.resolve().is_relative_to(Path(job_dir).resolve()):
                raise ValueError('Invalid thinning recovery path.')
        if data['state'] != 'committed' and backup.exists():
            os.replace(backup, source)
        backup.unlink(missing_ok=True); temp.unlink(missing_ok=True)
        _sync_dir(source.parent)
    journal.unlink(); _sync_dir(journal.parent)


def apply(sources, stride, expected_fingerprint, job_dir, check_ready=lambda: None):
    if type(stride) is not int or stride not in STRIDES or stride == 1:
        raise ValueError('Choose a thinning interval greater than one.')
    if fingerprint(sources) != expected_fingerprint:
        raise ValueError('Job files changed since the preview. Open Thin job again.')
    layouts = [layout(s['path']) for s in sources]
    for s, d in zip(sources, layouts):
        p = Path(s['path'])
        if p.is_symlink() or not p.resolve().is_relative_to(Path(job_dir).resolve()):
            raise ValueError('Trajectory must be a regular file inside this job.')
        if d.nsavc*stride > 2**31-1:
            raise ValueError('Selected frame spacing exceeds the DCD format limit.')
    required = {}
    for s, d in zip(sources, layouts):
        parent = Path(s['path']).parent
        required[parent] = required.get(parent, 0)+d.header_bytes+((d.n_frames+stride-1)//stride)*d.frame_bytes
    # Validate free space per filesystem, not per folder.
    devices = {}
    for parent, size in required.items():
        dev = parent.stat().st_dev
        old = devices.get(dev, (parent, 0)); devices[dev] = (parent, old[1]+size)
    for parent, size in devices.values():
        if shutil.disk_usage(parent).free < size + 1024*1024:
            raise ValueError('Insufficient free space to safely prepare the thinned trajectory.')
    token = uuid.uuid4().hex
    files = [{'source': str(Path(s['path']).resolve()),
              'temp': str(Path(s['path']).resolve().with_name('.'+Path(s['path']).name+'.thin-'+token)),
              'backup': str(Path(s['path']).resolve().with_name('.'+Path(s['path']).name+'.original-'+token))} for s in sources]
    journal = Path(job_dir)/'.trajectory-thinning.json'
    data = {'state': 'preparing', 'files': files}
    _save_journal(journal, data)
    old_bytes = sum(Path(s['path']).stat().st_size for s in sources)
    try:
        for item, d in zip(files, layouts):
            source, temp = Path(item['source']), Path(item['temp'])
            count = (d.n_frames+stride-1)//stride
            with source.open('rb') as inp, temp.open('xb') as out:
                header = bytearray(inp.read(d.header_bytes))
                struct.pack_into(d.endian+'i', header, 8, count)
                struct.pack_into(d.endian+'i', header, 16, d.nsavc*stride)
                # NSTEP is the last saved integrator step (ISTART stays unchanged).
                last_step = d.istart+(count-1)*stride*d.nsavc
                if last_step > 2**31-1:
                    raise ValueError('Trajectory step count exceeds DCD format limit.')
                struct.pack_into(d.endian+'i', header, 20, last_step)
                out.write(header); digest = hashlib.sha256()
                for i in range(0, d.n_frames, stride):
                    inp.seek(d.header_bytes+i*d.frame_bytes); block = inp.read(d.frame_bytes)
                    if len(block) != d.frame_bytes:
                        raise ValueError('Trajectory changed during thinning.')
                    _frame(block, d); digest.update(block); out.write(block)
                out.flush(); os.fsync(out.fileno())
            os.chmod(temp, source.stat().st_mode & 0o777)
            new = layout(temp)
            if new.n_frames != count or not np.isclose(new.delta_ps, d.delta_ps*stride):
                raise ValueError('Thinned trajectory timing or frame count did not verify.')
            actual = hashlib.sha256()
            with temp.open('rb') as f:
                f.seek(new.header_bytes)
                while block := f.read(8*1024*1024):
                    actual.update(block)
            if actual.digest() != digest.digest():
                raise ValueError('Retained-frame verification failed; originals preserved.')
        check_ready()
        if fingerprint(sources) != expected_fingerprint:
            raise ValueError('Job files changed during thinning; originals preserved.')
        for item in files:
            os.link(item['source'], item['backup']); _sync_dir(Path(item['source']).parent)
        data['state'] = 'prepared'; _save_journal(journal, data)
        for item in files:
            os.replace(item['temp'], item['source']); _sync_dir(Path(item['source']).parent)
        data['state'] = 'committed'; _save_journal(journal, data)
    except BaseException:
        recover(job_dir)
        raise
    new_bytes = sum(Path(s['path']).stat().st_size for s in sources)
    recover(job_dir)
    return {'ok': True, 'stride': stride, 'saved_bytes': old_bytes-new_bytes,
            'frames_kept': sum((d.n_frames+stride-1)//stride for d in layouts),
            'source_frames': sum(d.n_frames for d in layouts)}
