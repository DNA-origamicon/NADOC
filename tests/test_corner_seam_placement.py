"""Production Corner geometry must reproduce the user-approved frozen atoms."""

from dataclasses import asdict
import gzip
import json
from pathlib import Path
from time import monotonic

import numpy as np
import pytest

from backend.core.atomistic import build_atomistic_model
from backend.core.models import Design


@pytest.fixture(scope='module')
def approved():
    path = Path(__file__).parents[1] / 'frontend/src/ui/geometry_review_data/corner-closure.json.gz'
    with gzip.open(path, 'rt') as stream:
        primary = json.load(stream)
    return {'six': primary, **primary['controls']}


@pytest.mark.slow
@pytest.mark.parametrize('case', ['hc2', 'sq2', 'six', 'square'])
def test_production_matches_approved_same_topology_atoms(approved, case):
    fixture = approved[case]
    source = Design.model_validate(fixture['candidate_design'])
    before = source.model_dump_json()
    started = monotonic()
    model = build_atomistic_model(source)
    print(f'Corner {case} approved atom construction: {monotonic()-started:.3f} s')
    expected = fixture['candidate']
    assert len(model.atoms) == len(expected['atoms'])
    assert sorted(tuple(sorted(edge)) for edge in model.bonds) == sorted(
        tuple(sorted(edge)) for edge in expected['bonds'])
    for atom, record in zip(model.atoms, expected['atoms']):
        actual = asdict(atom)
        assert {k: v for k, v in actual.items() if k not in ('x', 'y', 'z')} == {
            k: v for k, v in record.items() if k not in ('x', 'y', 'z')}
    np.testing.assert_allclose([[a.x, a.y, a.z] for a in model.atoms],
        [[a['x'], a['y'], a['z']] for a in expected['atoms']], atol=1e-8, rtol=0)
    assert source.model_dump_json() == before


def test_physical_coordinate_overrides_do_not_enter_corner_placement(approved, monkeypatch):
    source = Design.model_validate(approved['hc2']['candidate_design'])
    def forbidden(*args, **kwargs):
        raise AssertionError('Physical override entered authored Corner placement')
    monkeypatch.setattr('backend.core.corner_seam_placement.place_corner_seams', forbidden)
    legacy = build_atomistic_model(source, nuc_pos_override={}, _corner_seam_placement=False)
    actual = build_atomistic_model(source, nuc_pos_override={})
    assert actual == legacy


@pytest.mark.slow
def test_corner_placement_preserves_other_junction_atoms():
    from backend.api import crud, headless_build as hb, state
    from backend.api.part_proof_commands import dependencies, execute
    from backend.api.routes_corner import CreateCornerRequest, create_corner
    from backend.core.corner_seam_placement import corner_insert_links
    from backend.core.models import LatticeType, StrandType
    from backend.core.part_history_contract import assess_part_history

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle([[0, 0], [0, 1]], 84, lattice=LatticeType.HONEYCOMB,
                         separate_fresh_extrusions=False)
        hb.add_cluster('Mixed Corner', [h.id for h in state.get_or_404().helices], log=True)
        source, revision = state.copy_for_persist()
        owner = next(c for c in source.cluster_transforms if c.name == 'Mixed Corner')
        create_corner(CreateCornerRequest(cluster_id=owner.id, position_bp=42, angle_deg=90,
            direction_deg=15, expected_design_id=source.id, expected_revision=revision))
        source = state.get_or_404()
        a, b = [s for s in source.strands if s.strand_type == StrandType.SCAFFOLD]
        hb.force_ligate(a.id, b.id)
        other = state.get_or_404().forced_ligations[-1]
        crud.patch_forced_ligation_extra_bases(other.id, crud.CrossoverExtraBasesRequest(sequence='AC'))
        source = Design.model_validate_json(state.get_or_404().model_dump_json())
        assert assess_part_history(source, execute=execute, dependencies=dependencies)['status'] == 'verified'
        links = corner_insert_links(source)
        owned = {link.id for link in links}
        assert other.id not in owned
        flexible = set()
        for link in links:
            flexible.add((link.three_prime_helix_id, link.three_prime_bp, link.three_prime_direction.value, "O3'"))
            flexible.update((link.five_prime_helix_id, link.five_prime_bp, link.five_prime_direction.value, name)
                            for name in ('P', 'OP1', 'OP2', "O5'"))
        def unchanged(model):
            result = {}
            for atom in model.atoms:
                if atom.crossover_id in owned:
                    continue
                if not atom.crossover_id and (atom.helix_id, atom.bp_index, atom.direction, atom.name) in flexible:
                    continue
                row = asdict(atom)
                for key in ('serial', 'x', 'y', 'z'):
                    row.pop(key)
                identity = tuple(row.items())
                assert identity not in result
                result[identity] = (atom.x, atom.y, atom.z)
            return result
        original = unchanged(build_atomistic_model(source, _corner_seam_placement=False))
        current = unchanged(build_atomistic_model(source))
        assert original.keys() == current.keys()
        np.testing.assert_array_equal(list(original.values()), [current[key] for key in original])
