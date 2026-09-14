"""Bound biotin + 5′ biotin-TEG heavy-atom display geometry (not a force field).

Connectivity follows IDT /5BiotinTEG/, structure image 2100: BTN-C(O)-NH-
CH2-CH2-O-CH2-CH2-O-CH2-CH2-O-CH2-CH2-O-P(DNA).
The 1STP bicyclic ring stays crystallographic. Flexible tail/spacer coordinates
are fitted to the existing 5′ phosphate with bond/angle constraints; DNA is never
moved and an unreachable endpoint is never joined with a stretched bond.
"""
from functools import lru_cache
from contextlib import closing
from itertools import combinations
import json
import hashlib
import sqlite3
import threading
from appdirs import user_cache_dir
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

CATALOG = json.loads((Path(__file__).resolve().parents[1] / 'data/proteins/biotin_pockets.json').read_text())
RING = {'C2', 'S1', 'C6', 'C5', 'N1', 'C3', 'O3', 'N2', 'C4'}
SPACER = [('NT', 'N'), ('C1T', 'C'), ('C2T', 'C'), ('O1T', 'O'),
          ('C3T', 'C'), ('C4T', 'C'), ('O2T', 'O'), ('C5T', 'C'),
          ('C6T', 'C'), ('O3T', 'O'), ('C7T', 'C'), ('C8T', 'C'), ('O4T', 'O')]


def pocket_transform(particle, record):
    """Canonical pocket A → world, same C-alpha alignment as pocket_geometry."""
    site = CATALOG['pockets'][record.chain]
    local = np.eye(4)
    local[:3, :3], local[:3, 3] = site['rotation'], site['translation']
    return particle.pose.to_array() @ particle.coating.poses[record.tetramer_index].to_array() @ local


# Bump the version when the objective, geometry or acceptance criteria change.
_FIT_VERSION = 'teg-lm-vector-v1-' + hashlib.sha256(json.dumps(CATALOG, sort_keys=True).encode()).hexdigest()[:16]
# Covers all 6,000 attachments allowed on a single 1,500-tetramer coating.
_FIT_CAPACITY = 8192
_FIT_LOCKS = [threading.Lock() for _ in range(32)]


def _fit_cache_path():
    return Path(user_cache_dir('NADOC')) / 'biotin-display.sqlite3'


def _disk_fit(key, value=None, *, write=False):
    """Disposable bounded geometry cache, independent of documents and job hashes."""
    try:
        path = _fit_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=2)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS fits (key TEXT PRIMARY KEY, xyz TEXT)')
            if write:
                db.execute('INSERT OR REPLACE INTO fits VALUES (?, ?)', (key, json.dumps(value)))
                db.execute('DELETE FROM fits WHERE rowid NOT IN (SELECT rowid FROM fits ORDER BY rowid DESC LIMIT ?)', (_FIT_CAPACITY,))
                return None
            row = db.execute('SELECT xyz FROM fits WHERE key=?', (key,)).fetchone()
            if row is not None:
                xyz = json.loads(row[0])
                if xyz is None:
                    return (True, None)
                xyz = np.asarray(xyz, dtype=float)
                if xyz.shape == (28, 3) and np.isfinite(xyz).all():
                    names, elements, _, pairs = _unconnected_teg()
                    xyz.flags.writeable = False
                    return (True, (names, elements, xyz, [*pairs, (27, 28)]))
    except (OSError, sqlite3.Error, ValueError, TypeError):
        pass  # A missing/read-only/corrupt cache cannot prevent display.
    return (False, None)


@lru_cache(maxsize=_FIT_CAPACITY)
def _fit_teg(endpoint, phosphate_oxygen):
    key = hashlib.sha256(json.dumps([_FIT_VERSION, endpoint, phosphate_oxygen]).encode()).hexdigest()
    # Collapse simultaneous surface/atomistic requests, including negative fits.
    with _FIT_LOCKS[int(key[:4], 16) % len(_FIT_LOCKS)]:
        found, fit = _disk_fit(key)
        if found:
            return fit
        fit = _solve_teg(endpoint, phosphate_oxygen)
        if fit is not None:
            fit[2].flags.writeable = False
        _disk_fit(key, None if fit is None else fit[2].tolist(), write=True)
        return fit


def _solve_teg(endpoint, phosphate_oxygen):
    """Deterministic, rigid-motion invariant fit in canonical protein coordinates."""
    ligand = [a for a in CATALOG['pockets']['A']['atoms'] if a['name'] != 'O12']
    names = [a['name'] for a in ligand] + [a[0] for a in SPACER] + ['P']
    elements = [a['element'] for a in ligand] + [a[1] for a in SPACER] + ['P']
    idx = {name: i for i, name in enumerate(names)}
    fixed = np.array([a['position'] for a in ligand] + [[0., 0., 0.]] * len(SPACER) + [endpoint])
    target = np.asarray(endpoint)
    start = fixed[idx['C11']]
    direction = target - start
    distance = np.linalg.norm(direction)
    if distance > 2.65 or distance < .15:
        return None
    direction /= distance
    side = np.cross(direction, fixed[idx['C10']] - start)
    if np.linalg.norm(side) < 1e-8:
        side = np.cross(direction, [1., 0., 0.] if abs(direction[0]) < .8 else [0., 1., 0.])
    side /= np.linalg.norm(side)
    n = len(SPACER)
    for k in range(n):
        t = (k + 1) / (n + 1)
        fixed[len(ligand) + k] = start + t * (target - start) + .12 * (-1)**k * side
    # Complete the existing tetrahedral phosphate, rather than approaching its
    # occupied O5′/OP1/OP2 face. Both DNA and the new P-O bond stay fixed.
    fixed[idx['O4T']] = phosphate_oxygen
    pairs = [(idx[a], idx[b]) for a, b in CATALOG['bonds'] if a != 'O12' and b != 'O12']
    chain = ['C11'] + [a[0] for a in SPACER] + ['P']
    pairs += [(idx[a], idx[b]) for a, b in zip(chain, chain[1:])]
    lengths = []
    for i, j in pairs:
        if i < len(ligand) and j < len(ligand):
            lengths.append(np.linalg.norm(fixed[i] - fixed[j]))
        elif names[i] == 'C11':
            lengths.append(.134)  # amide C-N
        else:
            lengths.append({('C', 'C'): .153, ('C', 'N'): .147, ('C', 'O'): .143, ('O', 'P'): .160}[tuple(sorted((elements[i], elements[j])))])
    lengths = np.array(lengths)
    adjacent = {i: [] for i in range(len(names))}
    for i, j in pairs:
        adjacent[i].append(j); adjacent[j].append(i)
    angles, cosines = [], []
    for j, neighbors in adjacent.items():
        for i, k in combinations(neighbors, 2):
            angles.append((i, j, k))
            if max(i, j, k) < len(ligand):
                u, v = fixed[i] - fixed[j], fixed[k] - fixed[j]
                cosines.append(np.dot(u, v) / np.linalg.norm(u) / np.linalg.norm(v))
            else:
                cosines.append(np.cos(np.deg2rad(120 if names[j] in ('C11', 'NT') else 112)))
    edges = np.asarray(pairs); triples = np.asarray(angles); cosines = np.array(cosines)
    mobile = np.array([i for i, name in enumerate(names) if name not in RING and name not in ('P', 'O4T')])
    # Prevent folded spacer self-intersections (exclude 1-2 and 1-3 neighbors).
    excluded = {tuple(sorted(p)) for p in pairs} | {tuple(sorted((i, k))) for i, _, k in angles}
    contacts = np.array([(i, j) for i, j in combinations(range(len(names)), 2)
                         if (i, j) not in excluded and (i in mobile or j in mobile)])
    def measures(x):
        xyz = fixed.copy(); xyz[mobile] = x.reshape(-1, 3)
        lengths_now = np.linalg.norm(xyz[edges[:, 0]] - xyz[edges[:, 1]], axis=1)
        u, v = xyz[triples[:, 0]] - xyz[triples[:, 1]], xyz[triples[:, 2]] - xyz[triples[:, 1]]
        cos_now = np.sum(u * v, axis=1) / np.maximum(np.linalg.norm(u, axis=1) * np.linalg.norm(v, axis=1), 1e-12)
        return xyz, lengths_now, cos_now
    def residual(x):
        xyz, lens, cos = measures(x)
        separation = np.linalg.norm(xyz[contacts[:, 0]] - xyz[contacts[:, 1]], axis=1)
        # Coplanar amide: the three substituents of carbonyl C already constrain
        # that center; additionally keep the N substituent in its carbonyl plane.
        c, o, nitrogen, nc = (xyz[idx[z]] for z in ('C11', 'O11', 'NT', 'C1T'))
        plane = np.dot(np.cross(o - c, nitrogen - c), nc - nitrogen) / .003
        return np.r_[100 * (lens - lengths), 2 * (cos - cosines),
                     15 * np.minimum(separation - .23, 0), plane]
    def jacobian(x):
        xyz, lens, cos = measures(x)
        jac = np.zeros((len(edges) + len(triples) + len(contacts) + 1, len(names), 3))
        rows = np.arange(len(edges))
        g = 100 * (xyz[edges[:, 0]] - xyz[edges[:, 1]]) / np.maximum(lens[:, None], 1e-12)
        jac[rows, edges[:, 0]] = g
        jac[rows, edges[:, 1]] = -g
        rows = np.arange(len(triples)) + len(edges)
        u = xyz[triples[:, 0]] - xyz[triples[:, 1]]
        v = xyz[triples[:, 2]] - xyz[triples[:, 1]]
        lu = np.maximum(np.linalg.norm(u, axis=1)[:, None], 1e-12)
        lv = np.maximum(np.linalg.norm(v, axis=1)[:, None], 1e-12)
        gi = 2 * (v / (lu * lv) - cos[:, None] * u / lu**2)
        gk = 2 * (u / (lu * lv) - cos[:, None] * v / lv**2)
        jac[rows, triples[:, 0]] = gi
        jac[rows, triples[:, 2]] = gk
        jac[rows, triples[:, 1]] = -gi - gk
        rows = np.arange(len(contacts)) + len(edges) + len(triples)
        v = xyz[contacts[:, 0]] - xyz[contacts[:, 1]]
        length = np.linalg.norm(v, axis=1)[:, None]
        g = 15 * v / np.maximum(length, 1e-12) * (length < .23)
        jac[rows, contacts[:, 0]] = g
        jac[rows, contacts[:, 1]] = -g
        row = len(jac) - 1
        c, o, nitrogen, nc = (xyz[idx[z]] for z in ('C11', 'O11', 'NT', 'C1T'))
        u, v, w = o - c, nitrogen - c, nc - nitrogen
        gu, gv, gw = np.cross(v, w) / .003, np.cross(w, u) / .003, np.cross(u, v) / .003
        for name, g in [('O11', gu), ('C11', -gu-gv), ('NT', gv-gw), ('C1T', gw)]:
            jac[row, idx[name]] = g
        return jac[:, mobile].reshape(len(jac), -1)
    for attempt in range(3):
        seed = fixed[mobile].copy()
        if attempt:
            for row, i in enumerate(mobile):
                if i >= len(ligand):
                    t = (i - len(ligand) + 1) / (n + 1)
                    seed[row] += (-1)**attempt * .35 * np.sin(np.pi * t) * np.cross(direction, side)
        result = least_squares(residual, seed.ravel(), jac=jacobian, max_nfev=160, ftol=1e-6, method='lm')
        xyz, lens, cos = measures(result.x)
        if np.max(np.abs(lens - lengths)) <= .006 and np.max(np.abs(cos - cosines)) <= .22:
            return tuple(names[:-1]), tuple(elements[:-1]), xyz[:-1], tuple(pairs)
    return None


def _unconnected_teg():
    """Same heavy-atom serial layout, chemically sized free spacer, no DNA bond."""
    ligand = [a for a in CATALOG['pockets']['A']['atoms'] if a['name'] != 'O12']
    names = [a['name'] for a in ligand] + [a[0] for a in SPACER]
    elements = [a['element'] for a in ligand] + [a[1] for a in SPACER]
    xyz = [np.array(a['position']) for a in ligand]
    by_name = {a['name']: np.array(a['position']) for a in CATALOG['pockets']['A']['atoms']}
    direction = by_name['O12'] - by_name['C11']; direction /= np.linalg.norm(direction)
    normal = np.cross(by_name['O11'] - by_name['C11'], direction); normal /= np.linalg.norm(normal)
    previous = by_name['C11']
    for k, (_, element) in enumerate(SPACER):
        if k:
            angle = np.deg2rad((60 if k == 1 else 68) * (-1)**k)
            direction = direction * np.cos(angle) + np.cross(normal, direction) * np.sin(angle)
        length = .134 if k == 0 else (.147 if k == 1 else .143 if element == 'O' or SPACER[k-1][1] == 'O' else .153)
        previous = previous + length * direction
        xyz.append(previous)
    pairs = [(names.index(a), names.index(b)) for a, b in CATALOG['bonds'] if 'O12' not in (a, b)]
    chain = ['C11'] + [a[0] for a in SPACER]
    pairs += [(names.index(a), names.index(b)) for a, b in zip(chain, chain[1:])]
    return names, elements, np.array(xyz), pairs


def append_biotin_linkers(model, design):
    from dataclasses import replace
    from backend.core.atomistic import Atom, AtomisticModel
    atoms, bonds, warnings = list(model.atoms), list(model.bonds), list(model.warnings)
    owned = {r.strand_id for p in design.nanoparticles for r in p.biotin_dna}
    # Cached all-atom references may already contain a prior display fit. Refit
    # after nucleotide transforms rather than translating the bound ring with DNA.
    keep = [a for a in atoms if not (a.residue == 'BTE' and a.strand_id in owned)]
    if len(keep) != len(atoms):
        remap = {a.serial: i for i, a in enumerate(keep)}
        atoms = [replace(a, serial=i) for i, a in enumerate(keep)]
        bonds = [(remap[i], remap[j]) for i, j in bonds if i in remap and j in remap]
    terminals = {}
    for atom in atoms:
        if atom.seq_num == 1 and atom.name in ('P', "O5'", 'OP1', 'OP2'):
            terminals.setdefault(atom.strand_id, {})[atom.name] = atom
    for particle in design.nanoparticles:
        if not particle.visible or not particle.coating:
            continue
        for record in particle.biotin_dna:
            terminal = terminals.get(record.strand_id, {})
            target = terminal.get('P')
            if target is None:
                continue
            transform = pocket_transform(particle, record)
            local = transform[:3, :3].T @ (np.array([target.x, target.y, target.z]) - transform[:3, 3])
            oxygen_neighbors = [terminal[name] for name in ("O5'", 'OP1', 'OP2') if name in terminal]
            vectors = np.array([[a.x-target.x, a.y-target.y, a.z-target.z] for a in oxygen_neighbors])
            exit_axis = -np.sum(vectors / np.linalg.norm(vectors, axis=1)[:, None], axis=0) if len(vectors) else np.zeros(3)
            if np.linalg.norm(exit_axis) > 1e-8:
                oxygen = local + .160 * (transform[:3, :3].T @ (exit_axis / np.linalg.norm(exit_axis)))
                fit = _fit_teg(tuple(np.round(local, 7)), tuple(np.round(oxygen, 7)))
            else:
                fit = None
            if fit is None:
                # Preserve real ligand/spacer geometry and stable atom serials. No long chemical
                # bonds or prevent all the other DNA atoms from being displayed.
                names, elements, xyz, pairs = _unconnected_teg()
                warnings.append(f'Biotin-TEG at strep {record.tetramer_index + 1}, pocket {record.chain}: no valid linker fit to the current DNA position; the spacer is shown unconnected. Adjust linker reach or DNA placement.')
            else:
                names, elements, xyz, pairs = fit
            xyz = xyz @ transform[:3, :3].T + transform[:3, 3]
            offset = len(atoms)
            for name, element, pos in zip(names, elements, xyz):
                atoms.append(Atom(serial=len(atoms), name=name, element=element, residue='BTE',
                                  chain_id=target.chain_id, seq_num=0, x=float(pos[0]), y=float(pos[1]), z=float(pos[2]),
                                  strand_id=target.strand_id, helix_id=target.helix_id, bp_index=target.bp_index,
                                  direction=target.direction, is_modified=True))
            for i, j in pairs:
                bonds.append((offset + i, target.serial if j == len(names) else offset + j))
    return AtomisticModel(atoms, bonds, warnings)


def prepare_biotin_display(design):
    """Prepare chemistry when DNA is attached/loaded; view switches only place atoms."""
    owned = {r.helix_id for p in design.nanoparticles for r in p.biotin_dna}
    if not owned:
        return
    from backend.core.atomistic import build_atomistic_model
    build_atomistic_model(design, exclude_helix_ids={h.id for h in design.helices} - owned, fast_bridges=True)
