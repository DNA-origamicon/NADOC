"""Evidence regression: a changed PDF must invalidate its previous visual review."""
import json
from pathlib import Path

from tools.design_archive.build_inventory import build
from tools.design_archive.inventory_nanobase import doi_for


def test_doi_normalization_keeps_preprint_versions_out_of_identifiers():
    assert doi_for({'paperLink': 'https://www.biorxiv.org/content/10.1101/2023.09.14.557688v1.abstract'}) == '10.1101/2023.09.14.557688'
    assert doi_for({'paperLink': 'https://www.nature.com/articles/s41565-024-01676-4'}) == '10.1038/s41565-024-01676-4'
    assert doi_for({'paperLink': 'http://', 'citation': ''}) is None


def test_changed_pdf_loses_verified_label(tmp_path):
    reviews = json.loads((Path(__file__).parents[1] / 'tools/design_archive/nanobase_figure_reviews.json').read_text())
    review = reviews['51']
    (tmp_path / 'snapshot.json').write_text(json.dumps({
        'retrieved_at': '2026-10-27', 'source': 'https://nanobase.org/',
        'records': [{'id': 51, 'title': 'Dumbbell', 'paperLink': 'https://doi.org/' + review['doi']}],
        'inspection': [{'id': 51, 'doi': review['doi'], 'files': []}], 'publications': [],
    }))
    supplement = [{'doi': review['doi'], 'pdfs': [{'url': 'https://example.org/supplement.pdf', 'pages': 29, 'sha256': review['pdf_sha256'], 'hits': []}]}]
    source = tmp_path / 'supplements.json'; output = tmp_path / 'output.json'
    source.write_text(json.dumps(supplement)); build(tmp_path, output)
    assert json.loads(output.read_text())['records'][0]['supplement']['status'].startswith('Verified')
    supplement[0]['pdfs'][0]['sha256'] = '0' * 64
    source.write_text(json.dumps(supplement)); build(tmp_path, output)
    result = json.loads(output.read_text())['records'][0]
    assert result['supplement']['status'] == 'Accessible PDF — figure review pending'
    assert result['comparison'].startswith('Not compared')
