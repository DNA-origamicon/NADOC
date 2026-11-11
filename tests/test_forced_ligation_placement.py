"""Equivalent user-authored junctions must share atomistic placement policy."""
import numpy as np
import pytest

from backend.api import state as design_state
from backend.api.routes import _demo_design
from backend.core.atomistic import build_atomistic_model
from backend.core.models import Design
from backend.core.sequences import domain_bp_range
from tests.test_forced_ligation import (
    client, _make_bundle, _hid_at, _nick,
    _find_strand_with_3prime, _find_strand_with_5prime,
)


@pytest.fixture(autouse=True)
def isolated_design():
    design_state.set_design(_demo_design())
    yield
    design_state.set_design(_demo_design())


def equivalent_junctions(sequence, direction, *, source_half_first=True, bp=7):
    """Create both branches through real editor routes, preserving their logs."""
    base = Design.model_validate(_make_bundle([[0, 0], [0, 1]], 28))
    ha, hb = _hid_at(base.model_dump(mode="json"), 0, 0), _hid_at(base.model_dump(mode="json"), 0, 1)
    other = "FORWARD" if direction == "REVERSE" else "REVERSE"
    source_nick, target_nick = bp, (bp - 1 if other == "FORWARD" else bp + 1)
    request = {
        'half_a': {'helix_id': ha, 'index': bp, 'strand': direction},
        'half_b': {'helix_id': hb, 'index': bp, 'strand': other},
        'nick_bp_a': source_nick, 'nick_bp_b': target_nick,
    }
    if not source_half_first:
        request['half_a'], request['half_b'] = request['half_b'], request['half_a']
        request['nick_bp_a'], request['nick_bp_b'] = request['nick_bp_b'], request['nick_bp_a']
    response = client.post('/api/design/crossovers/place', json=request)
    assert response.status_code == 201, response.text
    xo = response.json()['design']['crossovers'][-1]['id']
    response = client.patch(f'/api/design/crossovers/{xo}/extra-bases', json={'sequence': sequence})
    assert response.status_code == 200, response.text
    standard = Design.model_validate(response.json()['design'])

    design_state.load_design(base.model_copy(deep=True))
    _nick(ha, source_nick, direction)
    split = _nick(hb, target_nick, other)
    src = _find_strand_with_3prime(split, ha, bp, direction)
    dst = _find_strand_with_5prime(split, hb, bp, other)
    response = client.post('/api/design/forced-ligation', json={
        'three_prime_strand_id': src['id'], 'five_prime_strand_id': dst['id'],
    })
    assert response.status_code == 201, response.text
    fl = response.json()['design']['forced_ligations'][-1]['id']
    response = client.patch(f'/api/design/forced-ligations/{fl}/extra-bases', json={'sequence': sequence})
    assert response.status_code == 200, response.text
    forced = Design.model_validate(response.json()['design'])
    return standard, forced


def atom_map(model):
    return {(a.helix_id, a.bp_index, a.direction, a.copy_k, a.extra_base_k, a.name):
            np.array([a.x, a.y, a.z]) for a in model.atoms}


@pytest.mark.parametrize('fast_bridges', [False, True])
@pytest.mark.parametrize('direction', ['FORWARD', 'REVERSE'])
@pytest.mark.parametrize('sequence', ['T', 'TT'])
def test_forced_and_standard_insert_atoms_match(fast_bridges, direction, sequence):
    standard, forced = equivalent_junctions(sequence, direction)
    first = atom_map(build_atomistic_model(standard, fast_bridges=fast_bridges))
    second = atom_map(build_atomistic_model(forced, fast_bridges=fast_bridges))
    assert first.keys() == second.keys()
    for key in first:
        np.testing.assert_allclose(first[key], second[key], atol=1e-12, rtol=0, err_msg=str(key))


def test_forced_only_tt_runs_native_phosphate_clearance(monkeypatch):
    import backend.core.atomistic as aa
    _, forced = equivalent_junctions('TT', 'REVERSE')
    assert not forced.crossovers
    calls = []
    original = aa._apply_reciprocal_phosphate_clearance

    def record(model):
        calls.append(True)
        return original(model)

    monkeypatch.setattr(aa, '_apply_reciprocal_phosphate_clearance', record)
    build_atomistic_model(forced)
    assert calls == [True]


def assign_paired_sequence(design, forward_base):
    """Use the sequence editor so parity also covers the non-T duplex templates."""
    design_state.load_design(design.model_copy(deep=True))
    complement = {'A': 'T', 'T': 'A', 'G': 'C', 'C': 'G'}
    for strand in design.strands:
        sequence = ''.join(
            (forward_base if domain.direction.value == 'FORWARD'
             else complement[forward_base])
            for domain in strand.domains for _ in domain_bp_range(domain)
        )
        response = client.patch(f'/api/design/strand/{strand.id}', json={'sequence': sequence})
        assert response.status_code == 200, response.text
    return design_state.get_or_404().model_copy(deep=True)


@pytest.mark.parametrize('direction', ['FORWARD', 'REVERSE'])
@pytest.mark.parametrize('forward_base', ['A', 'C', 'G', 'T'])
def test_forced_standard_parity_includes_sequenced_flanking_duplex(direction, forward_base):
    # Unsequenced fixtures use the DT template everywhere. They miss the
    # sequence-dependent phosphate positions implicated in the Gerling audit.
    standard, forced = equivalent_junctions('TT', direction)
    standard = assign_paired_sequence(standard, forward_base)
    forced = assign_paired_sequence(forced, forward_base)
    first = atom_map(build_atomistic_model(standard, fast_bridges=True))
    second = atom_map(build_atomistic_model(forced, fast_bridges=True))
    assert first.keys() == second.keys()
    for key in first:
        np.testing.assert_allclose(first[key], second[key], atol=1e-12, rtol=0,
                                   err_msg=str(key))
