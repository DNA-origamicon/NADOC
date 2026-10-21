"""Guard the isolated ownership candidate against inferred material ancestry."""
import pytest

from backend.core.models import Direction
from backend.core.sweep import SweepRequest
from tests.test_part_member_motion_order import _source, _owner
from tests.test_part_transform_preview import snapshot
from tools.member_motion_birth_audit import preserved_existing_owner_candidate


def test_unmoved_native_sweep_is_an_exact_negative_control():
    source = _source()
    body = SweepRequest(cells=[(0, 0)], points_nm=[(0, 0, 0), (0, 0, 2.338)],
                        source_helix_id=source.helices[0].id, ligate_adjacent=False)
    after = snapshot(source, 'sweep', body.model_dump(mode='json'), 'birth')
    captured = source.model_dump_json(), after.model_dump_json()
    candidate = preserved_existing_owner_candidate(source, after)
    assert candidate == after
    assert (source.model_dump_json(), after.model_dump_json()) == captured


def test_candidate_refuses_to_guess_ownership_after_a_domain_split():
    source = _source()
    strand = next(s for s in source.strands if s.domains[0].direction == Direction.FORWARD)
    source = _owner(source, strand)
    split = snapshot(source, 'nick', {'helix_id': strand.domains[0].helix_id,
                     'bp_index': 3, 'direction': Direction.FORWARD.value}, 'nick')
    captured = source.model_dump_json(), split.model_dump_json()
    with pytest.raises(AssertionError, match='split/merged ancestry'):
        preserved_existing_owner_candidate(source, split)
    assert (source.model_dump_json(), split.model_dump_json()) == captured


def test_phase_fixture_changes_native_coordinates_without_changing_topology():
    from backend.core.design_geometry import _geometry_for_design
    from backend.core.atomistic import build_atomistic_model
    from tools.member_motion_birth_audit import phase_source
    zero, rolled = phase_source(0), phase_source(170)
    assert zero.helices == rolled.helices
    assert zero.strands == rolled.strands
    assert _geometry_for_design(zero) != _geometry_for_design(rolled)
    first, second = (build_atomistic_model(d, fast_bridges=True) for d in (zero, rolled))
    assert first.bonds == second.bonds
    assert [(a.x, a.y, a.z) for a in first.atoms] != [(a.x, a.y, a.z) for a in second.atoms]
