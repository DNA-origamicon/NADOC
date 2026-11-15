"""Pin synthetic residue numbering independently of molecular coordinates."""
from types import SimpleNamespace as NS

from backend.core.md_residue_map import thread_synthetic_residues
from backend.core.models import Direction


def test_extensions_and_reversed_junction_ownership_share_export_order():
    f, r = Direction.FORWARD, Direction.REVERSE
    a = NS(helix_id='h0', start_bp=0, end_bp=1, direction=f)
    b = NS(helix_id='h1', start_bp=1, end_bp=0, direction=r)
    design = NS(strands=[NS(id='s', domains=[a, b])],
                crossovers=[NS(id='x', extra_bases='TT',
                    half_a=NS(helix_id='h1', index=1, strand=r),
                    half_b=NS(helix_id='h0', index=1, strand=f))],
                forced_ligations=[], extensions=[
                    NS(id='five', strand_id='s', end='five_prime', sequence='AA'),
                    NS(id='three', strand_id='s', end='three_prime', sequence='T')])
    keys = [('h0', 0, 'FORWARD'), ('h0', 1, 'FORWARD'),
            ('h1', 1, 'REVERSE'), ('h1', 0, 'REVERSE')]
    result = thread_synthetic_residues(design, {('A', i + 1): k for i, k in enumerate(keys)})
    assert [result[('A', i)] for i in range(1, 10)] == [
        ('__ext_five', 1, 'FORWARD'), ('__ext_five', 0, 'FORWARD'),
        *keys[:2], ('__xb__', 'x', 0), ('__xb__', 'x', 1), *keys[2:],
        ('__ext_three', 0, 'REVERSE')]


def test_loop_copies_preserve_exporters_ambiguous_flank_tail_policy():
    f = Direction.FORWARD
    design = NS(strands=[NS(id='s', domains=[NS(helix_id='h', end_bp=3, direction=f)])],
        crossovers=[NS(id='x', extra_bases='T', half_a=NS(helix_id='h', index=3, strand=f),
                       half_b=NS(helix_id='b', index=0, strand=f))], forced_ligations=[], extensions=[])
    keys = [('h', 3, 'FORWARD'), ('h', 3, 'FORWARD', 1), ('h', 4, 'FORWARD')]
    result = thread_synthetic_residues(design, {('A', i+1): k for i,k in enumerate(keys)})
    assert list(result.values()) == keys + [('__xb__', 'x', 0)]
    assert result[('A', 4)] == ('__xb__', 'x', 0)
