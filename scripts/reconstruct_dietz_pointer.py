"""Reproduce the pinned mrDNA Pointer reference using the recorded import operation.

Run with ``uv run python -m scripts.reconstruct_dietz_pointer OUTPUT.nadoc``.
No relaxation or sequence assignment is performed. Publication always audits
the actual serialized process, including independent replay and bond geometry.
"""

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path

from backend.api.routes_part_cadnano_import import _prepare
from backend.core.models import Design
from scripts.agent_structure_guard import audit, publish

FIXTURE = Path(__file__).resolve().parents[1] / 'tests/fixtures/cadnano_dietz_pointer.json.gz'
SOURCE_SHA256 = 'b2be312ef90f945cd0f6b5f134946019e7b1b52a763175820af72029342139f0'


def compare_reference(design, raw):
    """Compare every ordered source site, both pointers, cells and loop/skip.

    Uses the saved domain paths, not export/reimport or the importer's tracer.
    caDNAno slots include deleted bases; separately count realized nucleotides.
    """
    source = json.loads(raw)
    cells = {(h['row'], h['col']): h for h in source['vstrands']}
    assert len(design.helices) == len(cells)
    by_id = {h.id: cells[tuple(h.grid_pos)] for h in design.helices}
    expected, actual = {}, {}
    for h in source['vstrands']:
        for kind in ('scaf', 'stap'):
            for bp, pointer in enumerate(h[kind]):
                if pointer != [-1] * 4:
                    expected[kind, h['num'], bp] = tuple(pointer)
    for h in design.helices:
        ref = by_id[h.id]
        expected_ls = Counter((bp, value) for key in ('loop', 'skip')
                              for bp, value in enumerate(ref[key]) if value)
        assert Counter((x.bp_index, x.delta) for x in h.loop_skips) == expected_ls
    lengths = Counter()
    for strand in design.strands:
        kind = 'scaf' if strand.is_scaffold else 'stap'
        path = []
        for domain in strand.domains:
            step = 1 if domain.direction.value == 'FORWARD' else -1
            path.extend((by_id[domain.helix_id]['num'], bp)
                        for bp in range(domain.start_bp, domain.end_bp + step, step))
        for index, (num, bp) in enumerate(path):
            key = kind, num, bp
            assert key not in actual, f'Duplicate source site {key}'
            previous = path[index - 1] if index else (-1, -1)
            following = path[index + 1] if index + 1 < len(path) else (-1, -1)
            actual[key] = (*previous, *following)
        lengths[kind] += 1
        ref = by_id[strand.domains[0].helix_id]
        color = dict(ref.get('stap_colors', [])).get(path[0][1])
        if kind == 'stap' and color:
            assert strand.color.upper() == f'#{color:06X}'
    assert actual == expected, 'Source routing differs from reconstructed strand paths'
    assert not design.extensions, 'Reference was converted into terminal extensions'
    return {'source_sha256': hashlib.sha256(raw).hexdigest(),
            'helices': len(cells), 'routed_sites': len(actual),
            'strand_counts': dict(lengths), 'all_source_pointers_match': True,
            'all_loop_skip_declarations_match': True, 'staple_colors_match': True,
            'sequences': 'not supplied by the caDNAno reference; left unassigned',
            'reference_scope': 'Exact pinned mrDNA pointer_v1_12_from_dietz.json; '
                               '162 strands versus 164 described in the 2012 paper.'}


def reconstruct():
    raw = gzip.decompress(FIXTURE.read_bytes())
    assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA256
    design, response = _prepare(raw, 'Dietz Pointer v1.12 (mrDNA reference)')
    assert not response.get('import_warnings'), response.get('import_warnings')
    return design, raw, compare_reference(design, raw)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    design, raw, comparison = reconstruct()
    result = publish(design, args.output)
    reopened = Design.model_validate_json(args.output.read_text())
    comparison = compare_reference(reopened, raw)
    result['reopened_audit'] = audit(reopened)
    result['reference_comparison'] = comparison
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'path': str(args.output), 'report': str(args.report),
                      'status': result['status'], **comparison}, indent=2))


if __name__ == '__main__':
    main()
