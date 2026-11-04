"""Numerical oracle, circular-origin invariance and transactional routing tests."""
import math
import numpy as np
import pytest
from backend.core.models import Domain, Direction, Strand, StrandType, LoopSkip
from backend.core.scaffold_register import (
    Conditions, NN, R, score_registers, loop_energy, prepare_design,
    evaluate_design, apply_nick,
)
from backend.core.sequences import assign_staple_sequences
from tests.conftest import make_minimal_design


def circle_design(length=64):
    d = make_minimal_design(n_helices=2, helix_length_bp=length, with_staple=False)
    def dom(h, a, b):
        return Domain(helix_id=h, start_bp=a, end_bp=b,
                      direction=Direction.FORWARD if b >= a else Direction.REVERSE)
    rng = np.random.default_rng(319)
    seq = ''.join(rng.choice(list('ACGT'), 2*length))
    sc = d.strands[0].model_copy(update={'domains': [dom('h0', 9, length-1), dom('h1', length-1, 0), dom('h0', 0, 8)], 'sequence': seq})
    staples = [Strand(id=f's{i}', strand_type=StrandType.STAPLE,
                     domains=[dom('h0', i+15, i), dom('h1', i, i+15)]) for i in range(0, length, 16)]
    return assign_staple_sequences(d.model_copy(update={'strands': [sc] + staples}))


def scalar_scores(sequence, staples, conditions):
    """Slow enumeration: literal duplex sequences, scalar sums, no prefix sums."""
    t = conditions.temperature
    n = len(sequence)
    result = []
    for offset in range(n):
        total_log = 0
        paired = 0
        for domains in staples:
            dg = -R*t*math.log((conditions.staple_nM-conditions.scaffold_nM/2)*1e-9)
            centers = []
            for domain in domains:
                inds = list(domain)
                if len(inds)>1 and (inds[1]-inds[0]) % n == n-1:
                    inds.reverse()
                seq = ''.join(sequence[(i+offset) % n] for i in inds)
                h, s = .2, -5.7
                for j in range(len(seq)-1):
                    dh, ds = NN[seq[j:j+2]]; h += dh; s += ds
                ends = int(seq[0] in 'AT') + (int(seq[-1] in 'AT') if len(seq)>1 else 0)
                h += 2.2*ends
                s += 6.9*ends + .368*(len(seq)-1)*math.log(conditions.salt)
                dg += h-t*s/1000
                centers.append((inds[0]+(len(inds)-1)/2) % n)
                paired += len(inds)
            for a,b in zip(centers,centers[1:]):
                distance=min(abs(a-b), n-abs(a-b))
                dg += loop_energy(distance,t)
            total_log -= np.logaddexp(0,dg/(R*t))
        result.append(total_log/paired)
    return np.array(result)


@pytest.mark.parametrize('temperature', [20, 50, 90])
def test_vectorized_matches_literal_sequence_enumeration(temperature):
    _, seq, staples, *_ = prepare_design(circle_design())
    c = Conditions(temperature_c=temperature)
    np.testing.assert_allclose(score_registers(seq, staples, c), scalar_scores(seq, staples, c), atol=2e-12, rtol=2e-12)


def test_origin_does_not_split_duplex_or_change_loop_lengths():
    d = circle_design()
    original = d.model_dump()
    before = prepare_design(d)
    assert len(before[2][0]) == 2  # h0 duplex crosses old symbolic start
    r = evaluate_design(d)
    for cut in (1, 5, 42, 76, 120):
        if cut not in before[3]:
            continue
        after = apply_nick(d, cut)
        assert after.strands[0].sequence == d.strands[0].sequence
        assert after.strands[1].domains == d.strands[1].domains
        assert after.crossovers == d.crossovers
        assert after.forced_ligations == d.forced_ligations
        assert sorted(prepare_design(after)[4]) == sorted(before[4])
        expected = next(row['q'] for row in r['scores'] if row['cut_index'] == cut)
        assert evaluate_design(after)['current']['q'] == pytest.approx(expected, abs=2e-12)
        assert [len(s) for s in prepare_design(after)[2]] == [len(s) for s in before[2]]
    assert d.model_dump() == original


def test_unsupported_inputs_fail_without_changing_design():
    d = circle_design(); before = d.model_dump()
    with pytest.raises(ValueError, match='eligible'):
        apply_nick(d, 55)  # crossover between h0 and h1
    assert d.model_dump() == before
    with pytest.raises(ValueError, match='ends must'):
        prepare_design(assign_staple_sequences(make_minimal_design().model_copy(update={
            'strands': [s.model_copy(update={'sequence': 'A'*42}) for s in make_minimal_design().strands]})))
    sc = d.strands[0].model_copy(update={'custom_scaffold_length': 1000})
    with pytest.raises(ValueError, match='full physical scaffold'):
        prepare_design(d.model_copy(update={'strands': [sc] + d.strands[1:]}))
    sc = d.strands[0].model_copy(update={'sequence': 'N'*128})
    with pytest.raises(ValueError, match='complete'):
        prepare_design(d.model_copy(update={'strands': [sc] + d.strands[1:]}))


def test_uniform_sequence_ties_preserve_current_start_and_finite_scores():
    d = circle_design(); sc = d.strands[0].model_copy(update={'sequence': 'A'*128})
    result = evaluate_design(d.model_copy(update={'strands': [sc] + d.strands[1:]}))
    assert result['best']['cut_index'] == 0
    assert all(math.isfinite(row['q']) for row in result['scores'])


@pytest.mark.parametrize('kwargs', [{'staple_nM': 5}, {'temperature_c': float('nan')}, {'magnesium_mM': 0, 'tris_mM': 0}])
def test_invalid_conditions(kwargs):
    with pytest.raises(ValueError): Conditions(**kwargs)


def test_unpaired_terminal_sequence_is_preserved():
    d = circle_design()
    s = d.strands[1]
    tail = Domain(helix_id='h0', start_bp=65, end_bp=64, direction=Direction.REVERSE)
    modified = s.model_copy(update={'domains': [tail] + s.domains, 'sequence': 'GA' + s.sequence})
    d = d.model_copy(update={'strands': [d.strands[0], modified] + d.strands[2:]})
    assert evaluate_design(d)['ignored_terminal_staple_nt'] == 2
    assert apply_nick(d, 5).strands[1].sequence.startswith('GA')


def test_skip_is_counted_and_paired_insertion_is_rejected():
    d = circle_design()
    h = d.helices[0].model_copy(update={'loop_skips': [LoopSkip(bp_index=20, delta=-1)]})
    sc = d.strands[0].model_copy(update={'sequence': d.strands[0].sequence[:-1]})
    skipped = d.model_copy(update={'helices': [h, d.helices[1]], 'strands': [sc]+d.strands[1:]})
    assert evaluate_design(skipped)['scaffold_nt'] == 127
    r = evaluate_design(skipped)
    assert evaluate_design(apply_nick(skipped, r['best']['cut_index']))['current']['q'] == pytest.approx(r['best']['q'], abs=2e-12)
    h = h.model_copy(update={'loop_skips': [LoopSkip(bp_index=20, delta=1)]})
    sc = sc.model_copy(update={'sequence': d.strands[0].sequence + 'A'})
    with pytest.raises(ValueError, match='Paired insertion'):
        prepare_design(d.model_copy(update={'helices': [h, d.helices[1]], 'strands': [sc]+d.strands[1:]}))
