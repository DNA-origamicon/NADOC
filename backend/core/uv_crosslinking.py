"""Read-only, resumable pyrimidine geometry screening for a saved NAMD job.

One SQLite transaction commits each frame's statistics and its cursor together.
Killing the worker can lose the in-flight frame, never completed progress. Display
filters are deliberately absent from the cache key: every pair class is measured.
"""
from __future__ import annotations

from contextlib import closing
from functools import lru_cache

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np

SCHEMA = 1
SCREEN_ANG = 6.0
NOTE = ('Geometric opportunity: fraction of production frames with C5=C6 midpoint '
        'distance <4.5 Å and circular angular deviation <45° from 16.74°. '
        'Exploratory common screen for TT/TC/CT/CC; not a calibrated formation '
        'probability, yield, or isomer-resolved prediction.')
PYRIMIDINES = {'THY': 'T', 'DT': 'T', 'T': 'T', 'CYT': 'C', 'DC': 'C', 'C': 'C'}


@lru_cache(maxsize=64)
def _design_digest(path, size, mtime_ns):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cache_spec(job_dir, topology, trajectories, design):
    """Cheap cache lookup; never opens a trajectory or builds molecular geometry."""
    paths = [Path(topology), *map(Path, trajectories)]
    if isinstance(design, (str,Path)):
        path = Path(design)
        stat = path.stat()
        digest = _design_digest(str(path),stat.st_size,stat.st_mtime_ns)
    else:
        digest = hashlib.sha256(design.model_dump_json().encode()).hexdigest()
    source = dict(schema=SCHEMA, files=[dict(name=p.name, size=p.stat().st_size,
                  mtime_ns=p.stat().st_mtime_ns) for p in paths],
                  design_sha256=digest)
    key = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
    folder = Path(job_dir) / 'analysis' / 'uv_crosslinking' / key
    return folder, source


def _connect(folder):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / 'analysis.sqlite', timeout=30)
    db.execute('PRAGMA journal_mode=WAL')
    # Completed transactions survive worker cancellation/application crashes.
    # NORMAL avoids a disk flush for every frame of this reproducible cache;
    # power loss can roll back recent frames, never split cursor/pair updates.
    db.execute('PRAGMA synchronous=NORMAL')
    db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT)')
    db.execute('''CREATE TABLE IF NOT EXISTS pairs (
        a INTEGER, b INTEGER, contacts INTEGER, reactive INTEGER,
        min_d REAL, tt_score_sum REAL, PRIMARY KEY(a,b))''')
    db.commit()
    return db


def _put(db, key, value):
    db.execute('INSERT OR REPLACE INTO state VALUES (?,?)', (key, json.dumps(value)))


def read_result(folder):
    path = Path(folder) / 'analysis.sqlite'
    if not path.exists():
        return None
    with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=5)) as db:
        if not db.execute("SELECT name FROM sqlite_master WHERE name='state'").fetchone():
            return None
        db.execute('BEGIN')  # cursor and pair sums must come from one snapshot
        state = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM state')}
        if 'sites' not in state:
            return None
        sites = state['sites']
        done, total = state.get('done', 0), state['total']
        pairs = []
        for a, b, contacts, reactive, min_d, score in db.execute('SELECT * FROM pairs ORDER BY a,b'):
            sa, sb = sites[a], sites[b]
            pairs.append(dict(id=f'{sa["id"]}~{sb["id"]}', a=a, b=b,
                              chemistry=sa['base']+sb['base'], same_strand=sa['segid']==sb['segid'],
                              contact_frames=contacts, reactive_frames=reactive,
                              opportunity=reactive/done if done else 0, min_distance_ang=min_d,
                              tt_contact_mean=score/contacts if sa['base']==sb['base']=='T' else None))
    return dict(ready=done > 0, complete=done == total and total > 0,
                preliminary=done < total, n_sampled_frames=done, n_total_frames=total,
                n_candidates=len(pairs), sites=sites, pairs=pairs, note=NOTE,
                source=state.get('source'), schema=SCHEMA)


def progress(folder):
    # Polling reads two scalar rows, never the full pair/site payload.
    state = {}
    path = Path(folder) / 'analysis.sqlite'
    if path.exists():
        with closing(sqlite3.connect(f'file:{path}?mode=ro',uri=True,timeout=5)) as db:
            if db.execute("SELECT name FROM sqlite_master WHERE name='state'").fetchone():
                state = {k:json.loads(v) for k,v in db.execute("SELECT key,value FROM state WHERE key IN ('done','total')")}
    if 'total' not in state:
        return dict(active=True, phase='preparing', fraction=0, done=0, total=0,
                    message='Preparing UV crosslinking analysis')
    done, total = state.get('done',0), state['total']
    complete = done==total and total>0
    return dict(active=not complete, phase='complete' if complete else 'measuring',
                fraction=done/max(1,total), done=done, total=total,
                message='Analysis saved' if complete else 'Screening pyrimidine pairs · progress saved')


def pyrimidine_sites(universe, design, package):
    from backend.core.atomistic_to_nadoc import build_namd_coarse_reference, load_segid_chain_map
    from backend.core.chain_ids import alphabetic_chain_id
    segmap = load_segid_chain_map(Path(package))
    if not segmap:
        raise ValueError('Package residue mapping is unavailable; cannot safely color this design')
    mapping, _ = build_namd_coarse_reference(design, None, segmap, mapping_only=True)
    strands = {alphabetic_chain_id(i): s for i,s in enumerate(design.strands)}
    helix_labels = {h.id: str(h.label) if h.label not in (None,'') else str(i)
                    for i,h in enumerate(design.helices)}
    sites = []
    for residue in universe.residues:
        base = PYRIMIDINES.get(str(residue.resname).upper())
        if not base or residue.segid not in segmap:
            continue
        c5, c6 = (residue.atoms.select_atoms('name '+n) for n in ('C5','C6'))
        if len(c5)!=1 or len(c6)!=1:
            raise ValueError(f'Missing C5/C6 atoms at {residue.segid}:{residue.resid}')
        # Saturated CPD carbons bonded to another residue are not reactants.
        formed = False
        if hasattr(universe, 'bonds'):
            for atom in (c5[0],c6[0]):
                formed |= any(a.resindex != atom.resindex and a.name in ('C5','C6')
                              for a in atom.bonded_atoms)
        if formed:
            continue
        chain = segmap[residue.segid]
        key = mapping.get((chain,int(residue.resid)))
        if key is None:
            raise ValueError(f'Unmapped pyrimidine {residue.segid}:{residue.resid}')
        display_key = ':'.join(map(str,key))
        label = display_key
        if key[0] == '__xb__':
            crossover = next((x for x in design.crossovers if x.id==key[1]),None)
            if crossover:
                hid, anchor = crossover.half_a.helix_id, crossover.half_a.index
            else:
                junction = next(x for x in design.forced_ligations if x.id==key[1])
                hid, anchor = junction.three_prime_helix_id, junction.three_prime_bp
            label = f'Extra base - {helix_labels[hid]}[{anchor}+{key[2]+1}]'
        elif key[0].startswith('__ext_'):
            ext = next(e for e in design.extensions if '__ext_'+e.id == key[0])
            strand = strands[chain]
            dom = strand.domains[0] if ext.end=='five_prime' else strand.domains[-1]
            hi = helix_labels[dom.helix_id]
            anchor = dom.start_bp if ext.end=='five_prime' else dom.end_bp
            label = f'Extension - {hi}[{anchor}›{key[1]+1}]'
        else:
            hi = helix_labels[key[0]]
            strand = strands[chain]
            dom = next(d for d in strand.domains if d.helix_id==key[0] and d.direction.value==key[2]
                       and min(d.start_bp,d.end_bp)<=key[1]<=max(d.start_bp,d.end_bp))
            kind = 'OH' if dom.overhang_id else ('Scaffold' if strand.strand_type.value=='scaffold' else 'Staple')
            token = f'{key[1]}+loop{key[3]}' if len(key)>3 and key[3] else str(key[1])
            label = f'{kind} - {hi}[{token}]'
        sites.append(dict(id=f'{residue.segid}:{residue.resid}', segid=str(residue.segid),
                          resid=int(residue.resid), base=base, label=label, display_key=display_key,
                          c5_serial=int(c5[0].index), c6_serial=int(c6[0].index)))
    return sites


def accumulate_frame(db, positions, box, sites, frame):
    """PBC-aware spatial screen and atomic per-frame checkpoint."""
    from MDAnalysis.lib.distances import self_capped_distance
    from backend.core.kimmdy_analysis import _site_midpoints_ang, _geometry_for_candidates, _valid_box
    from backend.core.cpd_metrics import angular_separation_deg, kimmdy_rate
    box = _valid_box(box)
    if not np.isfinite(positions[[s[k] for s in sites for k in ('c5_serial','c6_serial')]]).all():
        raise ValueError(f'Nonfinite reactive atoms in frame {frame}')
    hits = self_capped_distance(_site_midpoints_ang(positions, sites, box),
                               max_cutoff=SCREEN_ANG, box=box, return_distances=False) if sites else []
    candidates = [dict(site_a=sites[int(a)],site_b=sites[int(b)]) for a,b in hits]
    d, eta = _geometry_for_candidates(positions,candidates,box)
    reactive = (d<.45)&(angular_separation_deg(eta)<45)
    scores = kimmdy_rate(d,eta)
    if not np.isfinite(d).all() or not np.isfinite(eta).all():
        raise ValueError(f'Degenerate pyrimidine geometry in frame {frame}')
    with db:
        for i,(a,b) in enumerate(hits):
            a,b = sorted((int(a),int(b)))
            db.execute('''INSERT INTO pairs VALUES (?,?,1,?,?,?) ON CONFLICT(a,b)
                DO UPDATE SET contacts=contacts+1,reactive=reactive+excluded.reactive,
                min_d=min(min_d,excluded.min_d),tt_score_sum=tt_score_sum+excluded.tt_score_sum''',
                (a,b,int(reactive[i]),float(10*d[i]),float(scores[i]) if sites[a]['base']==sites[b]['base']=='T' else 0))
        _put(db,'done',frame+1)


def analyze(topology, trajectories, design, folder, source, *, frame_limit=None):
    """Resume from the first uncommitted frame; the limit supports bounded workers/tests."""
    import fcntl
    import MDAnalysis as mda
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'writer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        cached = read_result(folder)
        if cached and cached['complete']:
            return cached
        if isinstance(design,(str,Path)):
            from backend.core.models import Design
            design = Design.model_validate_json(Path(design).read_text())
        u = mda.Universe(str(topology),list(map(str,trajectories)))
        sites = pyrimidine_sites(u,design,Path(topology).parent)
        db = _connect(folder)
        try:
            with db:
                _put(db,'sites',sites)
                _put(db,'total',len(u.trajectory))
                _put(db,'source',source)
            done = cached['n_sampled_frames'] if cached else 0
            stop = len(u.trajectory) if frame_limit is None else min(len(u.trajectory),done+frame_limit)
            for frame in range(done,stop):
                ts = u.trajectory[frame]
                accumulate_frame(db,ts.positions,ts.dimensions,sites,frame)
        finally:
            db.close()
            u.trajectory.close()
    return read_result(folder)


def md_uv_crosslinking(topology, trajectories, design, folder, source):
    return analyze(topology,trajectories,design,folder,source)
