from backend.core.models import Design, Strand, Domain, StrandType, Direction
from backend.core.scaffold_gap_overhangs import scaffold_intervals, reconcile_scaffold_gaps
from backend.core.lattice import autodetect_all_overhangs, migrate_split_staple_domains


def fixture(reverse=False):
    def domain(a,b):return Domain(helix_id='h',start_bp=a,end_bp=b,direction=Direction.REVERSE if a>b else Direction.FORWARD)
    scaf=Strand(id='s',strand_type=StrandType.SCAFFOLD,domains=[domain(a,b) for a,b in [(0,3),(8,11),(16,19),(24,27)]])
    stap=Strand(id='t',strand_type=StrandType.STAPLE,domains=[domain(27,0) if reverse else domain(0,27)])
    return Design(name='gaps',strands=[scaf,stap])


def test_arbitrary_gap_count_both_directions_and_idempotence():
    for reverse in (False,True):
        d=fixture(reverse);assert scaffold_intervals(d)=={'h':[(0,3),(8,11),(16,19),(24,27)]}
        result=autodetect_all_overhangs(d)
        staple=result.find_strand('t')
        sites={b for dom in staple.domains if dom.overhang_id for b in range(min(dom.start_bp,dom.end_bp),max(dom.start_bp,dom.end_bp)+1)}
        assert sites==set(range(4,8))|set(range(12,16))|set(range(20,24))
        assert len(result.overhangs)==3
        assert autodetect_all_overhangs(result).model_dump()==result.model_dump()
        assert migrate_split_staple_domains(result).model_dump()==result.model_dump()
        assert sum(abs(x.end_bp-x.start_bp)+1 for x in staple.domains)==28
        assert not result.extensions


def test_scaffold_filling_one_gap_removes_only_that_tag():
    d=reconcile_scaffold_gaps(fixture())
    s=d.find_strand('s');s.domains.append(Domain(helix_id='h',start_bp=4,end_bp=7,direction=Direction.FORWARD))
    result=reconcile_scaffold_gaps(d)
    assert len(result.overhangs)==2
    assert all(not dom.overhang_id for dom in result.find_strand('t').domains if dom.start_bp==4)


def test_gap_spec_tracks_changed_strand_ownership():
    d=reconcile_scaffold_gaps(fixture())
    staple=d.find_strand('t');staple.id='joined'
    result=reconcile_scaffold_gaps(d)
    specs={o.id:o for o in result.overhangs}
    for dom in result.find_strand('joined').domains:
        if dom.overhang_id:
            assert specs[dom.overhang_id].strand_id=='joined'
    assert len(specs)==3
