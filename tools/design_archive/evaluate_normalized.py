"""Benchmark scale/rotation hypotheses without changing the production evaluator."""
import json
from pathlib import Path
import pymupdf
from backend.core.image_evaluation import evaluate_pdf


def run(root):
    results = []
    for entry in json.loads((root / 'evaluation/summary.json').read_text()):
        original = pymupdf.open(entry['source_pdf'])
        page = original[entry['review']['page'] - 1]
        result = {'id': entry['id'], 'source_sha256': entry['review']['pdf_sha256'], 'page': entry['review']['page'], 'embedded_images': len(page.get_images()), 'vector_paths': len(page.get_drawings()), 'hypotheses': []}
        if result['vector_paths'] > 100:
            for rotation in (0, 90):
                with pymupdf.open() as normalized:
                    w, h = (page.rect.height, page.rect.width) if rotation else (page.rect.width, page.rect.height)
                    dest = normalized.new_page(width=w * 4, height=h * 4)
                    dest.show_pdf_page(dest.rect, original, page.number, rotate=rotation)
                    evaluation = evaluate_pdf(normalized.tobytes())
                path = root / 'normalized' / f'{entry["id"]}-{rotation}.json'
                path.parent.mkdir(exist_ok=True)
                path.write_text(json.dumps(evaluation))
                result['hypotheses'].append({'rotation': rotation, 'scale': 4, 'file': str(path), 'candidates': [{'rows': len(f['rows']), 'columns': len(f['columns']), 'crossovers': len(f['crossovers']), 'paths': f['path_count']} for f in evaluation['figures']]})
        original.close()
        results.append(result)
        print(result['id'],result['hypotheses'],flush=True)
        (root / 'normalization-summary.json').write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    import sys
    run(Path(sys.argv[1]))
