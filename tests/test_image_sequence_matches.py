from backend.core.image_sequence_matches import brick_reference, exact_spans, match_design_domains
from backend.core.models import Domain, Direction, Strand, StrandType, LoopSkip
from tests.conftest import make_minimal_design


def test_maximal_exact_spans_preserve_orientation_and_report_repeated_targets():
    refs = [{'index': 1, 'sequence': 'TTACGTCAGG'}, {'index': 2, 'sequence': 'ACGTCA'}]
    hits = list(exact_spans('NACGTCAN', refs, 6))
    assert [(h['offset'], h['length'], h['published_index']) for h in hits] == [(1, 6, 1), (1, 6, 2)]
    assert list(exact_spans('TGACGT', refs, 6)) == []  # reverse complement is not a match
    assert list(exact_spans('ACNTCA', refs, 6)) == []


def test_domain_boundary_overhang_indel_and_reverse_coordinates_are_respected():
    d = make_minimal_design()
    h = d.helices[0].id
    d.helices[0].loop_skips = [LoopSkip(bp_index=18, delta=-1), LoopSkip(bp_index=17, delta=1)]
    d.strands = [Strand(id='s', strand_type=StrandType.STAPLE, sequence='TTTTTTACGTCAAAAAAA', domains=[
        Domain(helix_id=h, start_bp=26, end_bp=21, direction=Direction.REVERSE, overhang_id='tail'),
        Domain(helix_id=h, start_bp=20, end_bp=15, direction=Direction.REVERSE),
        Domain(helix_id=h, start_bp=14, end_bp=9, direction=Direction.REVERSE)])]
    before = d.model_dump_json()
    ref = {'title': 'test', 'sequences': [{'index': 1, 'sequence': 'TTTTTTACGTCA'}, {'index': 2, 'sequence': 'CAAAAA'}]}
    r = match_design_domains(d, 6, ref)
    assert len(r['matches']) == 1
    m = r['matches'][0]
    assert (m['start_bp'], m['end_bp'], m['domain_index'], m['full_domain']) == (20, 15, 1, True)
    assert d.model_dump_json() == before
    d.strands[0].sequence = 'A'
    assert match_design_domains(d, 6, ref)['skipped_strands'] == ['s']


def test_reference_pins_brick_sheet_and_exact_published_example():
    r = brick_reference()
    assert r['sheet'] == 'Brick' and len(r['sequences']) == r['count'] == 211
    assert r['workbook_sha256'] == 'f2b31457717417ec2fcaeed65a2074f048ae6fb5c3f9f123127e14fc9fcffcf6'
    assert any(h['published_index'] == 175 for h in exact_spans('CGGTGCCCCCTGCATCAGACGATCCA', r['sequences'], 26))


def test_endpoint_no_active_design_and_threshold_validation(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import state
    from backend.api.routes_image_evaluation import router
    monkeypatch.setattr(state, 'get_design_with_revision', lambda: (None, 0))
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        assert client.get('/image-evaluation/brick-matches').status_code == 404
        assert client.get('/image-evaluation/brick-matches?minimum=2').status_code == 422


def test_offset_preview_uses_reference_and_never_mutates_document():
    from backend.core.image_sequence_matches import preview_matches, sequence_reference
    from backend.core.sequences import P7560_SEQUENCE
    d = make_minimal_design()
    h = d.helices[0].id
    d.strands = [Strand(id='sc', strand_type=StrandType.SCAFFOLD, domains=[Domain(helix_id=h, start_bp=0, end_bp=25, direction=Direction.FORWARD)]),
                 Strand(id='st', domains=[Domain(helix_id=h, start_bp=25, end_bp=0, direction=Direction.REVERSE)])]
    before = d.model_dump_json()
    r = preview_matches(d, 6, '42hb13', 17)
    assert d.model_dump_json() == before
    assert r['preview']['register'] == 17 and r['reference']['count'] == 213
    assert r['helices'][0]['label'] == str(d.helices[0].label if d.helices[0].label is not None else 0)
    expected = P7560_SEQUENCE[17:43].translate(str.maketrans('ACGT', 'TGCA'))[::-1]
    for hit in r['matches']:
        assert hit['sequence'] == expected[hit['offset']:hit['offset'] + hit['length']]
    assert sequence_reference('42hb14')['count'] == 176
    assert sequence_reference('42hb13')['sequences'][177]['sequence'] == 'TTTTTTTTTTGTTGTTCCAGTTTGGAACAT'


def test_preview_endpoint_rejects_invalid_parameters_and_preserves_active_design(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import state
    from backend.api.routes_image_evaluation import router
    d = make_minimal_design()
    before = d.model_dump_json()
    monkeypatch.setattr(state, 'get_design_with_revision', lambda: (d, 7))
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        assert client.get('/image-evaluation/brick-matches?register=7560').status_code == 422
        assert client.get('/image-evaluation/brick-matches?reference=unknown').status_code == 422
        r = client.get('/image-evaluation/brick-matches?reference=42hb13&register=17')
        assert r.status_code == 200, r.text
        assert r.json()['design_revision'] == 7 and r.json()['preview']['register'] == 17
    assert d.model_dump_json() == before
