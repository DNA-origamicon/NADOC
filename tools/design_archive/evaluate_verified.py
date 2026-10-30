"""Serial, provenance-preserving evaluation of the verified Nanobase figure cohort."""
import argparse
import hashlib
import json
from pathlib import Path

import pymupdf

from backend.core.image_evaluation import evaluate_pdf


def run(source, output):
    output.mkdir(parents=True, exist_ok=True)
    reviews = json.loads(Path('tools/design_archive/nanobase_figure_reviews.json').read_text())
    supplements = json.loads((source / 'supplements.json').read_text())
    pdfs = {p['sha256']: p for s in supplements for p in s['pdfs']}
    records = []
    for record_id, review in reviews.items():
        if review['kind'] != 'cadnano':
            continue
        result = {'id': int(record_id), 'review': review}
        try:
            pdf = pdfs[review['pdf_sha256']]
            data = Path(pdf['path']).read_bytes()
            assert hashlib.sha256(data).hexdigest() == review['pdf_sha256']
            with pymupdf.open(stream=data, filetype='pdf') as original, pymupdf.open() as page:
                page.insert_pdf(original, from_page=review['page'] - 1, to_page=review['page'] - 1)
                evaluation = evaluate_pdf(page.tobytes())
            result.update(source_pdf=pdf['path'], source_url=pdf['url'], evaluation=evaluation)
            result['status'] = 'candidates detected' if evaluation['figures'] else 'no candidates'
        except Exception as exc:
            result.update(status='error', error=str(exc))
        (output / f'{record_id}.json').write_text(json.dumps(result, indent=2))
        summary = {k: v for k, v in result.items() if k != 'evaluation'}
        summary['candidates'] = [{k: v for k, v in f.items() if k in ('id', 'path_count', 'bounds', 'source_bounds')} | {'rows': len(f['rows']), 'columns': len(f['columns']), 'crossovers': len(f['crossovers']), 'flags': len(f['flags'])} for f in result.get('evaluation', {}).get('figures', [])]
        records.append(summary)
        print(record_id, result['status'], len(summary['candidates']), flush=True)
    (output / 'summary.json').write_text(json.dumps(records, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    run(args.source, args.output)
