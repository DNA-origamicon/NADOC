"""The approved atoms, Full view and bond review share Corner landmarks."""

import gzip
import json
from pathlib import Path

import numpy as np
import pytest

from backend.core.models import Design, NucleotideTransform
from backend.core.design_geometry import _geometry_for_design, _compact_geometry_from_nucleotides
from backend.core.bond_review_insert_positions import insert_positions


@pytest.mark.slow
def test_full_and_compact_corner_landmarks_match_atoms_with_one_saved_pose():
    from backend.core.atomistic_cache import build_atomistic_model_cached
    from backend.core.corner_seam_placement import corner_insert_links
    with gzip.open(Path(__file__).parents[1] / 'frontend/src/ui/geometry_review_data/corner-closure.json.gz', 'rt') as stream:
        fixture = json.load(stream)['controls']['hc2']
    design = Design.model_validate(fixture['candidate_design'])
    original = design.model_dump_json()
    atoms = build_atomistic_model_cached(design).atoms
    full = _geometry_for_design(design)
    from backend.physics.native_oxdna import native_full_to_oxdna_geometry
    from backend.physics.oxdna_interface import resolved_nuc_map
    physical = native_full_to_oxdna_geometry(design, full)
    assert all(n["placement_source"] == "oxdna-particle-frame-v1" for n in physical)
    resolved = resolved_nuc_map(design, full)
    assert all(np.isfinite(n["backbone_position"]).all() for n in resolved.values())
    positions = insert_positions(design, full)
    compact = _compact_geometry_from_nucleotides(full)
    for link in corner_insert_links(design):
        for k in range(len(link.extra_bases)):
            group = [a for a in atoms if a.crossover_id == link.id and a.extra_base_k == k]
            bead = next(a for a in group if a.name == "O5'")
            np.testing.assert_allclose(positions[('__xb__', link.id, k)], [bead.x, bead.y, bead.z], atol=1e-12)
            row = next(n for n in full if link.id in n.get('corner_inserts', {}))
            landmark = row['corner_inserts'][link.id][str(k)]
            base = [[a.x, a.y, a.z] for a in group if "'" not in a.name and a.name not in ('P', 'OP1', 'OP2')]
            np.testing.assert_allclose(landmark['base_position'], np.mean(base, axis=0), atol=1e-12)
            bucket = compact[row['helix_id']][row['direction']]
            assert bucket['corner'][bucket['bp'].index(row['bp_index'])] == row['corner_inserts']
        endpoint = next(a for a in atoms if a.helix_id == link.five_prime_helix_id
                        and a.bp_index == link.five_prime_bp and a.direction == link.five_prime_direction.value
                        and a.name == "O5'" and not a.crossover_id)
        row = next(n for n in full if (n['helix_id'], n['bp_index'], n['direction']) ==
                   (endpoint.helix_id, endpoint.bp_index, endpoint.direction))
        np.testing.assert_allclose(row['backbone_position'], [endpoint.x, endpoint.y, endpoint.z], atol=1e-12)
    link = corner_insert_links(design)[0]
    posed = design.model_copy(deep=True)
    posed.nucleotide_transforms.append(NucleotideTransform(kind='extra_base', crossover_id=link.id,
        extra_base_k=0, translation=[3, -2, 1], rotation=[0, 0, 0, 1], pivot=[0, 0, 0]))
    posed_positions = insert_positions(posed, _geometry_for_design(posed))
    key = ('__xb__', link.id, 0)
    np.testing.assert_allclose(posed_positions[key], np.array(positions[key]) + [3, -2, 1])
    assert design.model_dump_json() == original
