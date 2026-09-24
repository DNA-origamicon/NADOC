"""Ring paths must retain proper torsions without repeated atoms or duplicates."""
from experiments.cpd_drude_recovery.nucleotide_term_coverage import interactions


def test_four_member_ring_has_four_unique_paths_of_each_length():
    result=interactions({('a','b'),('b','c'),('c','d'),('d','a')})
    assert {k:len(v) for k,v in result.items()}=={'bond':4,'angle':4,'proper_torsion':4}
    assert all(len(set(t))==4 for t in result['proper_torsion'])
    assert ('a','b','c','d') in result['proper_torsion']


def test_three_leaf_branch_has_angles_but_no_proper_torsions():
    result=interactions({('a','b'),('a','c'),('a','d')})
    assert len(result['angle'])==3
    assert not result['proper_torsion']


def test_reversing_edges_does_not_change_coverage():
    edges={('a','b'),('b','c'),('c','d'),('c','e')}
    assert interactions(edges)==interactions({(b,a) for a,b in edges})
