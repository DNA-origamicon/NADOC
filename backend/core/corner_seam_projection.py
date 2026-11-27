"""Full-view landmarks projected from the approved Corner atom placement.

These records are derived display data, never persisted construction inputs.
Residue poses are applied by the existing consumers after this projection.
"""

from collections import defaultdict
from collections import OrderedDict
from copy import deepcopy
import threading
import hashlib
import orjson

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.corner_seam_placement import corner_insert_links

_projection_lock = threading.Lock()
_projections = OrderedDict()
_MAX_PROJECTIONS = 16
_MAX_PROJECTION_BYTES = 16 * 1024**2


def _projection_key(design):
    from backend.core.atomistic_cache import atomistic_fingerprint
    from backend.core.part_history_contract import FIELD_ROLES
    if design.atomistic_reference is not None:
        return atomistic_fingerprint(design)
    # Native placement reads authored topology/poses and Corner ownership, not
    # representation choices, recovery journals or embedded replay source bytes.
    # Unknown/new fields remain included. Physical references use the full key above.
    excluded = {name for name, role in FIELD_ROLES.items() if role in {
        'presentation', 'history', 'physical', 'input_source', 'repair_draft'}}
    data = design.model_dump(mode='json', exclude=excluded | {'metadata', 'id'})
    data['corner_links'] = [link.id for link in corner_insert_links(design)]
    return hashlib.sha256(orjson.dumps(data, option=orjson.OPT_SORT_KEYS)).hexdigest()


def clear_projection_cache():
    from backend.core.corner_projection_reuse import clear_reuse_cache
    from backend.core.bevel_geometry_cache import clear
    with _projection_lock:
        _projections.clear()
    clear_reuse_cache()
    clear()


def export_projection(design):
    key = _projection_key(design.model_copy(update={'nucleotide_transforms': []}))
    with _projection_lock:
        cached = _projections.get(key)
        if cached is None:
            return None
        endpoints, inserts = cached[0]
        return [key, [[list(site), list(point)] for site, point in endpoints.items()], deepcopy(inserts)]


def prepare_cached_projection(design):
    """No atom construction: existing projection or a certified deletion only."""
    from backend.core.corner_projection_reuse import reuse_projection
    source = design.model_copy(update={'nucleotide_transforms': []})
    if not corner_insert_links(source) or export_projection(source) is not None:
        return True
    result = reuse_projection(source)
    if result is None:
        return False
    _remember(_projection_key(source), result)
    return True


def import_projection(row):
    if row is None:
        return
    key, endpoints, inserts = row
    _remember(key, ({tuple(site): list(point) for site, point in endpoints}, deepcopy(inserts)))


def _remember(key, result):
    from backend.core.memory_sizes import retained_bytes
    charge = retained_bytes(result)
    if charge <= _MAX_PROJECTION_BYTES:
        with _projection_lock:
            _projections[key] = deepcopy(result), charge
            _projections.move_to_end(key)
            while (len(_projections) > _MAX_PROJECTIONS or
                   sum(row[1] for row in _projections.values()) > _MAX_PROJECTION_BYTES):
                _projections.popitem(last=False)


def _projection(design, links):
    from backend.core.atomistic_cache import build_atomistic_model_cached
    from backend.core.corner_seam_dependencies import model_dependencies
    from backend.core.corner_projection_reuse import reuse_projection, remember_reuse

    source = design.model_copy(update={'nucleotide_transforms': []})
    key = _projection_key(source)
    with _projection_lock:
        cached = _projections.get(key)
        if cached is not None:
            _projections.move_to_end(key)
            return deepcopy(cached[0])
    result = reuse_projection(source)
    if result is not None:
        _remember(key, result)
        return result
    model = build_atomistic_model_cached(source, retain=False)
    result = _project_model(model, links)
    _remember(key, result)
    remember_reuse(source, model, result, model_dependencies(model))
    return result


def attach_corner_projection(design, nucleotides):
    links = corner_insert_links(design)
    if not links:
        return
    endpoints, by_link = _projection(design, links)
    sites = {(n['helix_id'], n['bp_index'], n['direction']): n for n in nucleotides
             if not n.get('copy_k') and not n.get('is_modification')}
    for link in links:
        for end in ('three_prime', 'five_prime'):
            key = (getattr(link, end+'_helix_id'), getattr(link, end+'_bp'),
                   getattr(link, end+'_direction').value)
            if key not in sites:
                continue
            sites[key]['corner_native_backbone'] = sites[key]['backbone_position']
            sites[key]['backbone_position'] = endpoints[key]
            sites[key]['placement_source'] = 'corner-seam-o5-v1'
            # Carry on both endpoints so partial helix updates retain the seam.
            sites[key].setdefault('corner_inserts', {})[link.id] = by_link[link.id]


def _project_model(model, links):
    owned = {link.id for link in links}
    wanted = {(getattr(link, end+'_helix_id'), getattr(link, end+'_bp'),
               getattr(link, end+'_direction').value) for link in links for end in ('three_prime', 'five_prime')}
    inserts, endpoints = defaultdict(list), {}
    for atom in model.atoms:
        if atom.crossover_id in owned:
            inserts[(atom.crossover_id, atom.extra_base_k)].append(atom)
        elif (atom.name == "O5'" and not atom.crossover_id and not atom.extension_id and not atom.copy_k
              and (atom.helix_id, atom.bp_index, atom.direction) in wanted):
            endpoints[(atom.helix_id, atom.bp_index, atom.direction)] = [atom.x, atom.y, atom.z]
    by_link = defaultdict(dict)
    for (link_id, k), atoms in inserts.items():
        points = {a.name: np.array([a.x, a.y, a.z]) for a in atoms}
        base = np.array([p for name, p in points.items()
                         if "'" not in name and name not in ('P', 'OP1', 'OP2')])
        center = base.mean(axis=0)
        _, _, axes = np.linalg.svd(base-center)
        normal = axes[-1]
        nitrogen = points['N9'] if 'N9' in points else points['N1']
        long_axis = nitrogen-points["C1'"]
        long_axis -= normal*np.dot(normal, long_axis)
        long_axis /= np.linalg.norm(long_axis)
        transverse = np.cross(normal, long_axis)
        frame = np.column_stack((long_axis, transverse, normal))
        by_link[link_id][str(k)] = {
            'backbone_position': points["O5'"].tolist(),
            'base_position': center.tolist(),
            'frame_rotation': Rotation.from_matrix(frame).as_quat().tolist(),
        }
    return endpoints, dict(by_link)


from backend.core.memory_budget import register_reclaimer
register_reclaimer('corner_projection', clear_projection_cache)
