"""Isolated evaluation order candidate; NEVER imported by production code.

The input is a complete natively recorded Design. This returns only a derived
atom model for A/B inspection, never another authored Design or export seed.
It postpones native seam construction until the duplex frames have reached
their final positions. No phase, template, insertion count or route changes.
"""

from collections import defaultdict
from unittest.mock import patch

import numpy as np

from backend.core import atomistic
from backend.core.design_geometry import _geometry_for_design
from backend.core.geometry import NucleotidePosition
from backend.core.models import Direction
from experiments.corner_seam_scope import require_corner_only_inserts

PROVIDER = 'corner-final-frame-seams-diagnostic-v1'
PROCESS = [
    'Replay the complete native source recipe, including Corner and its seam sequences.',
    'Construct the same native duplex atoms with seam insert construction deferred.',
    'Apply the recorded deformation and cluster transforms to the duplex atoms.',
    'Construct native seam inserts and phosphate bridges between the final endpoints.',
    'Apply the existing terminal gamma torsion and native reciprocal phosphate clearance.',
    'Rebuild atom sequence numbering from the unchanged strand paths.',
]


def deferred_duplex_atoms(design):
    """Private diagnostic intermediate, retaining the complete input Design."""
    def defer(*args, **kwargs):
        return kwargs['serial']

    # This module runs in a standalone diagnostic process. The native builder is
    # restored before constructing the comparison; no application path sees it.
    with patch.object(atomistic, '_build_extra_base_atoms', defer), \
            patch.object(atomistic, '_rotate_built_gamma_branch', lambda *args: None):
        model = atomistic.build_atomistic_model(design, _two_base_phosphate_clearance=False,
                                               _corner_seam_placement=False)
    return model


def candidate_atoms(design):
    # Deferral currently covers all inserts in a standalone diagnostic process.
    # Refuse mixed sources before that patch can touch unrelated junctions.
    require_corner_only_inserts(design)
    native_inserts = atomistic._build_extra_base_atoms
    model = deferred_duplex_atoms(design)
    sugar, chains = defaultdict(dict), {}
    for atom in model.atoms:
        if atom.crossover_id or atom.extension_id:
            raise ValueError('Unexpected non-duplex residues in the deferred diagnostic build.')
        chains[atom.strand_id] = atom.chain_id
        if not atom.copy_k:
            sugar[(atom.helix_id, atom.bp_index, atom.direction)][atom.name] = atom.serial
    cache = defaultdict(dict)
    for row in _geometry_for_design(design):
        direction = Direction(row['direction'])
        key = (row['bp_index'], direction, row.get('copy_k', 0))
        cache[row['helix_id']][key] = NucleotidePosition(
            helix_id=row['helix_id'], bp_index=row['bp_index'], direction=direction,
            position=np.asarray(row['backbone_position']), base_position=np.asarray(row['base_position']),
            base_normal=np.asarray(row['base_normal']), axis_tangent=np.asarray(row['axis_tangent']))
    native_inserts(design=design, atoms=model.atoms, bonds=model.bonds, serial=len(model.atoms),
        strand_to_chain=chains, nuc_pos_cache=cache, helix_map={h.id: h for h in design.helices},
        bp_to_sugar_serials=sugar, exclude_helix_ids=None)
    angle = -np.deg2rad(atomistic._EXTRA_BASE_3PRIME_GAMMA_CW_DEG)
    for link in design.forced_ligations:
        if link.extra_bases:
            dst = sugar[(link.five_prime_helix_id, link.five_prime_bp, link.five_prime_direction.value)]
            atomistic._rotate_built_gamma_branch(model.atoms, dst, angle)
    atomistic._thread_inserts_inline(model.atoms, design)
    if any(len(link.extra_bases or ()) == 2 for link in design.forced_ligations):
        atomistic._apply_reciprocal_phosphate_clearance(model)
    return model
