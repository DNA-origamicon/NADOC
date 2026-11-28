"""Approved Corner-owned molecular placement in the final wedge frames.

Only derived atoms change. Topology, sequence, native feature inputs, other
junction providers and simulation overrides retain their existing authority.
"""

from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
import re
import threading
from types import SimpleNamespace

import numpy as np

from backend.core.models import Direction
from backend.core.part_history_proof import command_rows


_observer = ContextVar('corner_seam_observer', default=None)
_numerical_lock = threading.RLock()


@contextmanager
def observe_corner_placement(callback):
    token = _observer.set(callback)
    try:
        yield
    finally:
        _observer.reset(token)


def corner_insert_links(design, *, exclude_helix_ids=None, strand_ids=None):
    if not any(link.extra_bases and ':seam:' in link.id for link in design.forced_ligations):
        return ()
    limit = sum(1 + len(getattr(entry, 'children', [])) for entry in design.feature_log)
    operations = {params.get('operation_id') for _, kind, params in command_rows(design, limit)
                  if kind == 'corner' and type(params.get('_proof_version')) is int
                  and params['_proof_version'] in (1, 2, 3)}
    if not operations:
        return ()
    endpoints = None if strand_ids is None else {
        (d.helix_id, d.end_bp, d.direction) for s in design.strands if s.id in strand_ids for d in s.domains}
    result = []
    for link in design.forced_ligations:
        operation, separator, digest = link.id.rpartition(':seam:')
        if not link.extra_bases or not separator or operation not in operations or re.fullmatch('[0-9a-f]{24}', digest) is None:
            continue
        if exclude_helix_ids and {link.three_prime_helix_id, link.five_prime_helix_id} & exclude_helix_ids:
            continue
        if endpoints is not None and (link.three_prime_helix_id, link.three_prime_bp, link.three_prime_direction) not in endpoints:
            continue
        result.append(link)
    return tuple(result)


def _endpoints(link):
    return tuple((getattr(link, end + '_helix_id'), getattr(link, end + '_bp'),
                  getattr(link, end + '_direction').value) for end in ('three_prime', 'five_prime'))


def place_corner_seams(design, model, links):
    """Complete deferred Corner inserts, then fit exactly the approved two passes."""
    from threadpoolctl import threadpool_limits
    from importlib import import_module

    # Load the SciPy numerical runtimes before inspecting their thread pools.
    for module in ('scipy.linalg', 'scipy.linalg.cython_blas', 'scipy.linalg.cython_lapack'):
        import_module(module)

    # These tiny local fits slow dramatically with a workstation-wide BLAS
    # pool. Serialize this scope so overlapping Corner callers cannot restore
    # each other's process-level thread setting mid-fit.
    with _numerical_lock, threadpool_limits(limits=1, user_api='blas'):
        _place_corner_seams(design, model, links)


def _place_corner_seams(design, model, links):
    from backend.core import atomistic
    from backend.core.corner_seam_clashes import find_clashes
    from backend.core.corner_seam_closure import close_component
    from backend.core.corner_seam_bridge_math import minimize_bridge
    from backend.core.design_geometry import _geometry_for_design
    from backend.core.geometry import NucleotidePosition

    sugar, chains = defaultdict(dict), {}
    for atom in model.atoms:
        chains[atom.strand_id] = atom.chain_id
        if not atom.crossover_id and not atom.extension_id and not atom.copy_k:
            sugar[(atom.helix_id, atom.bp_index, atom.direction)][atom.name] = atom.serial
    links = tuple(link for link in links if all(key in sugar for key in _endpoints(link)))
    if not links:
        return
    keys = {key for link in links for key in _endpoints(link)}
    cache = defaultdict(dict)
    # Authored residue poses are applied once by the caller, after this fit.
    # Only duplex endpoints are inputs here. Extension slabs themselves consume
    # completed atoms and must not recursively re-enter this construction.
    for row in _geometry_for_design(design.model_copy(update={'nucleotide_transforms': []}),
                                    _corner_seams=False, extension_slabs=False):
        if (row['helix_id'], row['bp_index'], row['direction']) not in keys or row.get('copy_k', 0):
            continue
        direction = Direction(row['direction'])
        cache[row['helix_id']][(row['bp_index'], direction, 0)] = NucleotidePosition(
            helix_id=row['helix_id'], bp_index=row['bp_index'], direction=direction,
            position=np.asarray(row['backbone_position']), base_position=np.asarray(row['base_position']),
            base_normal=np.asarray(row['base_normal']), axis_tangent=np.asarray(row['axis_tangent']))
    # A read-only adapter into the shared insert builder, never a changed Design.
    inputs = SimpleNamespace(crossovers=[], forced_ligations=links, strands=design.strands)
    atomistic._build_extra_base_atoms(design=inputs, atoms=model.atoms, bonds=model.bonds,
        serial=len(model.atoms), strand_to_chain=chains, nuc_pos_cache=cache, helix_map={},
        bp_to_sugar_serials=sugar, exclude_helix_ids=None, bridge_fn=minimize_bridge)
    angle = -np.deg2rad(atomistic._EXTRA_BASE_3PRIME_GAMMA_CW_DEG)
    for link in links:
        atomistic._rotate_built_gamma_branch(model.atoms, sugar[_endpoints(link)[1]], angle)
    atomistic._thread_inserts_inline(model.atoms, design)
    link_ids = {link.id for link in links}
    flexible = {a.serial for a in model.atoms if a.crossover_id in link_ids}
    for link in links:
        first, second = _endpoints(link)
        flexible.add(sugar[first]["O3'"])
        flexible.update(sugar[second][name] for name in ('P', 'OP1', 'OP2', "O5'"))
    if any(len(link.extra_bases) == 2 for link in links):
        def traced_clashes(positions, finite, bonds, threshold, cap):
            from backend.core.corner_seam_dependencies import trace_clearance
            rows = find_clashes(positions, finite, bonds, threshold, cap)
            trace_clearance(positions, flexible, rows, cap, threshold)
            return rows
        atomistic._apply_reciprocal_phosphate_clearance(model, allowed_atom_serials=flexible,
                                                       clash_finder=traced_clashes)
    observer = _observer.get()
    completed, total = 0, 2*len(links)
    if observer:
        observer(completed, total)
    # Membership is immutable during fitting. Reuse it and a dense coordinate
    # buffer instead of rebuilding all atom dictionaries/lists for each seam.
    positions = np.array([[a.x, a.y, a.z] for a in model.atoms])
    components = _closure_components(model, links)
    for _ in range(2):
        for ids, bonds, mask in components:
            local = atomistic.AtomisticModel(
                atoms=[replace(model.atoms[serial], serial=i) for i, serial in enumerate(ids)],
                bonds=bonds)
            close_component(local, environment=positions[mask])
            for serial, atom in zip(ids, local.atoms):
                model.atoms[serial].x, model.atoms[serial].y, model.atoms[serial].z = atom.x, atom.y, atom.z
                positions[serial] = atom.x, atom.y, atom.z
            completed += 1
            if observer:
                observer(completed, total)
    if not np.isfinite([[model.atoms[i].x, model.atoms[i].y, model.atoms[i].z] for i in flexible]).all():
        raise ValueError('Corner seam placement produced nonfinite coordinates.')


def _closure_components(model, links):
    """Index once; preserve the original atom and bond traversal of every seam."""
    residues, inserts = defaultdict(list), defaultdict(list)
    for atom in model.atoms:
        if atom.crossover_id:
            inserts[atom.crossover_id].append(atom.serial)
        elif not atom.extension_id and not atom.copy_k:
            residues[(atom.helix_id, atom.bp_index, atom.direction)].append(atom.serial)
    edges = np.asarray(model.bonds, dtype=np.int64).reshape(-1, 2)
    components = []
    for link in links:
        ids = sorted(set(inserts[link.id]).union(*(residues[key] for key in _endpoints(link))))
        mapping = np.full(len(model.atoms), -1, dtype=np.int64)
        mapping[ids] = np.arange(len(ids))
        local = mapping[edges]
        bonds = [tuple(edge) for edge in local[np.all(local >= 0, axis=1)].tolist()]
        mask = np.ones(len(model.atoms), dtype=bool)
        mask[ids] = False
        components.append((ids, bonds, mask))
    return components
