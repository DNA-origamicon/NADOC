"""Reference-derived routing oracle and independent PDF-evidence tests.

No authored molecular structures are created. Pointer routing is read-only;
these tests do not claim to recover it from a published Pointer image.
"""
import base64
import gzip
import json
from pathlib import Path

import pymupdf

from backend.core.article_design_detection import detect_designs, read_lists, route_hypotheses
from backend.core.article_sequence_inference import rank_directions, sequence_variants
from backend.core.sequences import M13MP18_SEQUENCE

FIXTURES = Path(__file__).parent / 'fixtures'


def pointer_templates():
    source = json.loads(gzip.decompress((FIXTURES / 'cadnano_dietz_pointer.json.gz').read_bytes()))
    helices = {h['num']: h for h in source['vstrands']}
    def paths(kind):
        starts = [(h['num'], i) for h in helices.values() for i, p in enumerate(h[kind]) if p[:2] == [-1, -1] and p[2:] != [-1, -1]]
        result = []
        for start in starts:
            path, seen, current = [], set(), start
            while current != (-1, -1):
                assert current not in seen
                seen.add(current)
                h, bp = current
                if helices[h]['skip'][bp] != -1:
                    path.append(current)
                current = tuple(helices[h][kind][bp][2:])
            result.append(path)
        return result
    scaffold, = paths('scaf')
    index = {site: i for i, site in enumerate(scaffold)}
    return [[index.get(site) for site in path] for path in paths('stap')]


def test_pointer_direction_register_inference_from_published_staples():
    templates = pointer_templates()
    staples = json.loads((FIXTURES / 'dietz_pointer_2017_staples.json').read_text())['sequences']
    result = rank_directions(templates, staples, M13MP18_SEQUENCE)
    best = result['hypotheses'][0]
    assert result['direction_resolved']
    assert best['matched_staples'] == 161
    assert best['scaffold_offset'] == 0
    assert best['scaffold_direction'] == best['staple_direction'] == 'drawn'
    assert best['paired_bases_verified'] == 7249
    assert best['unknown_bases'] == 740
    assert all(m['variant'].startswith('uppercase core') for m in best['matches'])
    # Reverse the observation order, not the reference topology; recover its sense.
    reversed_result = rank_directions([list(reversed(t)) for t in templates], staples, M13MP18_SEQUENCE)
    assert reversed_result['direction_resolved']
    assert reversed_result['hypotheses'][0]['staple_direction'] == 'reversed'
    assert reversed_result['hypotheses'][0]['matched_staples'] == 161


def test_unrelated_sequences_and_repeated_templates_do_not_resolve_direction():
    assert not rank_directions([[0, 1, 2] * 6], ['A' * 18], M13MP18_SEQUENCE)['direction_resolved']
    assert sequence_variants('agACGTACGTACGTacgttga')[1] == ('ACGTACGTACGT', 'uppercase core; lowercase flanks excluded')
    assert sequence_variants('ACGT-invalid') == []


def test_route_calibration_recovers_only_continuous_observed_paths():
    runs = [[0, 15, 10], [15, 0, 20], [0, 15, 30], [15, 0, 40], [0, 15, 50], [15, 0, 60]]
    paths = [{'path_id': 1, 'continuous': True, 'length': 90, 'runs': runs},
             {'path_id': 2, 'continuous': True, 'length': 15, 'runs': [[15, 0, 10]]},
             {'path_id': 3, 'continuous': False, 'length': 15, 'runs': [[0, 15, 20]]}]
    result = route_hypotheses(paths, 96)
    assert len(result) == 1
    assert result[0]['templates'] == [list(range(15, -1, -1))]
    assert result[0]['source_paths'] == [2]
    assert result[0]['calibration']['points_per_base'] == 1


def routing_pdf():
    # Existing diagram-evidence fixture, labelled with two different designs.
    from tests.test_image_evaluation import drawing_pdf
    with pymupdf.open(stream=drawing_pdf(), filetype='pdf') as doc:
        doc[0].insert_text((25, 215), 'Pointer caDNAno diagram')
        second = pymupdf.open(stream=drawing_pdf(), filetype='pdf')
        doc.insert_pdf(second)
        second.close()
        doc[1].insert_text((25, 215), 'Barrel caDNAno diagram')
        return doc.tobytes()


def upload(data, name):
    return {'name': name, 'data': base64.b64encode(data).decode()}


def test_multiple_images_pair_only_with_likely_labelled_lists():
    report = detect_designs({'paper': upload(routing_pdf(), 'paper.pdf'), 'staple_lists': [
        upload(b'ACGTCAGTACGTACGA\nTGACGTCAGTACGTAC', 'Pointer.csv'),
        upload(b'ATGCTGACGTCAGTCA\nGTCAGTCAGTACGTCA', 'Barrel.csv'),
        upload(b'ACGTCAGTCAGTCAGT', 'Unrelated.csv')]})
    assert len(report['designs']) == 2
    for figure, name in zip(report['designs'], ('Pointer.csv', 'Barrel.csv')):
        assert len(figure['pairings']) == 1
        assert name in figure['pairings'][0]['label']
        assert figure['pairings'][0]['basis'] == 'caption/context only'
        assert not figure['pairings'][0]['direction_resolved']
        assert figure['observed_paths']
    assert not report['can_reconstruct']


def test_workbook_sheets_stay_separate_and_keep_raw_case():
    import io
    from openpyxl import Workbook
    book = Workbook(); book.active.title = 'Pointer'
    book.active.append(['agACGTACGTACGTacgttga'])
    book.create_sheet('Barrel').append(['GTCAGTCAGTCAGTCA'])
    stream = io.BytesIO(); book.save(stream); book.close()
    lists = read_lists(upload(stream.getvalue(), 'lists.xlsx'))
    assert len(lists) == 2
    assert lists[0]['sequences'] == ['agACGTACGTACGTacgttga']
    assert lists[0]['id'] != lists[1]['id']


def test_analysis_route_validates_upload_envelope():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api.routes_image_evaluation import router
    app = FastAPI(); app.include_router(router, prefix='/api')
    with TestClient(app) as client:
        for payload in ([], {'paper': 2}, {'staple_lists': 3}, {'scaffold_sequence': 4}):
            assert client.post('/api/article-reconstruction/analyze', json=payload).status_code == 422
        malformed = client.post('/api/article-reconstruction/analyze', json={'paper': upload(routing_pdf(), 'paper.pdf'), 'staple_lists': [upload(b'not a workbook', 'staples.xlsx')]})
        assert malformed.status_code == 422
        result = client.post('/api/article-reconstruction/analyze', json={'paper': upload(routing_pdf(), 'paper.pdf')})
        assert result.status_code == 200
        assert len(result.json()['designs']) == 2


def calibrated_pdf():
    """Independent schematic with 384 known scaffold bases and 12 staple paths."""
    import random
    rng = random.Random(431)
    sequence = ''.join(rng.choice('ACGT') for _ in range(384))
    with pymupdf.open() as doc:
        page = doc.new_page(width=300, height=230)
        shape = page.new_shape()
        previous = None
        for row in range(6):
            start, end = ((25, 151) if row % 2 == 0 else (151, 25))
            y = 40+row*20
            if previous:
                shape.draw_line(previous, (start, y))
            shape.draw_line((start, y), (end, y)); previous = (end, y)
        shape.finish(color=(0, .4, .8), closePath=False); shape.commit()
        staples = []
        for row in (0, 2, 4):
            for a in (0, 16, 32, 48):
                b = a+7; x0, x1 = 25+a*2, 25+b*2; y = 40+row*20
                shape = page.new_shape()
                shape.draw_line((x0, y), (x1, y))
                shape.draw_bezier((x1, y), (x1-1, y+6), (x1-1, y+14), (x1, y+20))
                shape.draw_line((x1, y+20), (x0, y+20))
                shape.finish(color=(.5, .5, .5), closePath=False); shape.commit()
                indices = list(range(row*64+a, row*64+b+1)) + [((row+1)*64+63-x) for x in range(b, a-1, -1)]
                staples.append(''.join(sequence[i] for i in indices).translate(str.maketrans('ACGT', 'TGCA')))
        page.insert_text((25, 200), 'Fig. S1. Pointer test caDNAno diagram')
        return doc.tobytes(), sequence, staples


def test_image_to_sequence_pairing_preserves_symmetric_direction_alternatives():
    data, scaffold, staples = calibrated_pdf()
    report = detect_designs({'paper': upload(data, 'diagram.pdf'), 'scaffold_sequence': scaffold,
                            'staple_lists': [upload('\n'.join(staples).encode(), 'anonymous.csv')]})
    assert report['designs']
    pairing = report['designs'][0]['pairings'][0]
    assert pairing['basis'] == 'sequence agreement'
    assert not pairing['direction_resolved']  # Repeated hairpins allow six equally supported mappings.
    assert pairing['best_ties'] == 6
    best = pairing['alternatives'][0]
    assert best['matched_staples'] == 12
    assert best['paired_bases_verified'] == 192
    assert len(best['observed_partner_indices']) == 12
    assert len(best['source_paths']) == 12
    assert best['scaffold_offset'] == 0
