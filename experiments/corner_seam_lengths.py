"""Isolated per-junction count exploration, not an authored part or export seed.

Each proposal consists of two copied endpoint residues plus the existing native
insert/bridge component. The source Design and its recorded seam count remain
unchanged. This only measures alternatives for the future Corner search.
"""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np

from backend.core import atomistic
from backend.core.atomistic_validation import _find_clashes, CLASH_NM
from backend.core.geometry import NucleotidePosition
from backend.core.models import Direction
from backend.core.ring_piercing import model_piercings


def junction_component(model, link, sites, count, *, gamma=True):
    keys = [(getattr(link, end+'_helix_id'), getattr(link, end+'_bp'),
             getattr(link, end+'_direction').value) for end in ('three_prime', 'five_prime')]
    atoms, serials = [], {}
    for atom in model.atoms:
        key = (atom.helix_id, atom.bp_index, atom.direction)
        if key in keys and not atom.crossover_id and not atom.copy_k:
            serials[atom.serial] = len(atoms)
            atoms.append(replace(atom, serial=len(atoms)))
    if len({(a.helix_id, a.bp_index, a.direction) for a in atoms}) != 2:
        raise ValueError('The junction component needs both complete ordinary endpoint residues.')
    bonds = [(serials[a], serials[b]) for a, b in model.bonds if a in serials and b in serials]
    sugar = {key: {a.name: a.serial for a in atoms
                  if (a.helix_id, a.bp_index, a.direction) == key} for key in keys}
    cache = {}
    for key in keys:
        row = sites[key]
        cache.setdefault(key[0], {})[(key[1], Direction(key[2]), 0)] = NucleotidePosition(
            helix_id=key[0], bp_index=key[1], direction=Direction(key[2]),
            position=np.asarray(row['backbone_position']), base_position=np.asarray(row['base_position']),
            base_normal=np.asarray(row['base_normal']), axis_tangent=np.asarray(row['axis_tangent']))
    strand_id = next(a.strand_id for a in atoms if (a.helix_id, a.bp_index, a.direction) == keys[0])
    # Minimal native component adapter: no Design, no feature rows, no captured
    # output used as authoring input. The only alternative is an explicit count.
    component = SimpleNamespace(crossovers=[], forced_ligations=[link.model_copy(update={'extra_bases': 'N'*count})],
        strands=[SimpleNamespace(id=strand_id, domains=[SimpleNamespace(helix_id=keys[0][0],
            end_bp=keys[0][1], direction=Direction(keys[0][2]))])])
    atomistic._build_extra_base_atoms(design=component, atoms=atoms, bonds=bonds,
        serial=len(atoms), strand_to_chain={strand_id: atoms[0].chain_id},
        nuc_pos_cache=cache, helix_map={}, bp_to_sugar_serials=sugar, exclude_helix_ids=None)
    result = atomistic.AtomisticModel(atoms=atoms, bonds=bonds)
    if gamma:
        apply_terminal_gamma(result, link)
    return result


def apply_terminal_gamma(model, link):
    dst = {a.name: a.serial for a in model.atoms if not a.crossover_id
           and (a.helix_id, a.bp_index, a.direction) ==
           (link.five_prime_helix_id, link.five_prime_bp, link.five_prime_direction.value)}
    atomistic._rotate_built_gamma_branch(model.atoms, dst,
        -np.deg2rad(atomistic._EXTRA_BASE_3PRIME_GAMMA_CW_DEG))


def local_metrics(local):
    xyz = np.asarray([[a.x, a.y, a.z] for a in local.atoms])
    lengths = [float(np.linalg.norm(xyz[i]-xyz[j])) for i, j in local.bonds
               if {local.atoms[i].name, local.atoms[j].name} == {"O3'", 'P'}]
    flexible = {"O3'", 'P', 'OP1', 'OP2', "O5'"}
    flexible_lengths = [float(np.linalg.norm(xyz[i]-xyz[j])) for i, j in local.bonds
                        if {local.atoms[i].name, local.atoms[j].name} & flexible]
    return {'max_seam_covalent_nm': max(lengths, default=0),
            'max_flexible_covalent_nm': max(flexible_lengths, default=0),
            'local_piercings': len(model_piercings(local)),
            'local_clashes': len(_find_clashes(xyz, np.isfinite(xyz).all(axis=1), local.bonds, CLASH_NM, 1000))}


def reclose_final_bridges(local):
    """Diagnostic only: close after rigid poses/gamma; terminal torsion may change.

    Rigid rings remain fixed. This is NOT permission to override the native
    terminal gamma in production; the displacement is explicit evidence only.
    """
    from backend.core.atomistic_minimisers import _minimize_backbone_bridge

    def key(atom):
        return (atom.helix_id, atom.bp_index, atom.direction,
                atom.crossover_id, atom.extra_base_k)

    residues = {}
    for atom in local.atoms:
        residues.setdefault(key(atom), {})[atom.name] = atom.serial
    before = np.asarray([[a.x, a.y, a.z] for a in local.atoms])
    for i, j in local.bonds:
        a, b = local.atoms[i], local.atoms[j]
        if a.name == 'P' and b.name == "O3'":
            a, b = b, a
        if a.name == "O3'" and b.name == 'P':
            _minimize_backbone_bridge(local.atoms, residues[key(a)], residues[key(b)])
    after = np.asarray([[a.x, a.y, a.z] for a in local.atoms])
    return float(np.linalg.norm(after-before, axis=1).max())


def explore_lengths(design):
    from backend.core.design_geometry import _geometry_for_design
    from experiments.corner_seam_candidate import deferred_duplex_atoms
    model = deferred_duplex_atoms(design)
    sites = {(r['helix_id'], r['bp_index'], r['direction']): r for r in _geometry_for_design(design)
             if not r.get('copy_k')}
    labels = {h.id: h.label if h.label is not None else i for i, h in enumerate(design.helices)}
    rows = []
    for link in design.forced_ligations:
        options = []
        for count in range(1, 9):
            local = junction_component(model, link, sites, count, gamma=False)
            before_gamma = local_metrics(local)
            apply_terminal_gamma(local, link)
            after_gamma = local_metrics(local)
            displacement = reclose_final_bridges(local)
            options.append({'bases': count, 'before_terminal_gamma': before_gamma,
                **after_gamma, 'reclosed': {**local_metrics(local),
                    'max_displacement_nm': displacement,
                    'preserves_terminal_gamma': False}})
        rows.append({'connection_id': link.id, 'current_bases': len(link.extra_bases),
            'from_helix_label': labels[link.three_prime_helix_id], 'from_bp': link.three_prime_bp,
            'to_helix_label': labels[link.five_prime_helix_id], 'to_bp': link.five_prime_bp,
            'options': options})
    return {'scope': 'Each seam in isolation; neighboring duplexes and other seams are NOT screened.', 'junctions': rows}
