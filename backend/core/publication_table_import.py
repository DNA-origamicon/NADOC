"""Layout-aware sequence tables. Evidence only; never infer strand placement.

Slash-delimited vendor chemistry is not DNA. Unlabelled physical rows retain
possible continuation links instead of silently joining independent oligos.
"""
import re
from collections import Counter

from backend.core.models import VALID_MODIFICATIONS

_SEQUENCE = re.compile(r'(?:[ACGTacgt\s]|/[^/\n]+/)+')
_TOKEN = re.compile(r'/([^/]+)/|([ACGTacgt]+)')


def annotate_sequence(raw, notes='', module='', spans=()):
    sequence, modifications = '', []
    for match in _TOKEN.finditer(raw):
        token, bases = match.groups()
        if bases:
            sequence += bases.upper()
        else:
            modifications.append({'token': match.group(), 'name': token, 'offset': len(sequence)})
    for item in modifications:
        name = item['name'].lower()
        canonical = re.sub(r'^(?:5|3|i)', '', name)
        end = 'five_prime' if name.startswith('5') and item['offset'] == 0 else (
            'three_prime' if name.startswith('3') and item['offset'] == len(sequence) else None)
        lipid = bool(re.search(r'chol|lipid|palmit', name))
        item.update(kind='lipid' if lipid else 'modification', native_key=canonical if canonical in VALID_MODIFICATIONS else None,
                    end=end, status='unsupported_lipid' if lipid else (
                        'supported_terminal_label_pending_route' if canonical in VALID_MODIFICATIONS and end else
                        'unsupported_internal_modification' if canonical in VALID_MODIFICATIONS else 'unsupported_modification'))
    context = f'{module} {notes}'
    for name in re.findall(r'(?i)\b(?:Chol|Pal|cholesterol|palmitoyl|lipid)\b', context):
        modifications.append({'name': name, 'kind': 'lipid', 'status': 'unsupported_lipid', 'offset': None, 'end': None})
    labels = []
    if re.search(r'(?i)toehold|locktoe', context):labels.append('toehold')
    if re.search(r'(?i)handle|_ha\b', context):labels.append('handle')
    # Parse tokens across span boundaries before translating bold glyphs to bases.
    joined = ''.join(span['text'] for span in spans)
    bold = [bool(span.get('bold')) for span in spans for _ in span['text']]
    functional, offset = [], 0
    for match in _TOKEN.finditer(joined):
        if match.group(1) is not None:continue
        for index in range(match.start(), match.end()):
            if bold[index]:
                if functional and functional[-1]['end'] == offset:functional[-1]['end'] += 1
                else:functional.append({'start':offset, 'end':offset+1})
            offset += 1
    return {'sequence': sequence, 'modifications': modifications,
            'functional_spans': functional,
            'overhang_annotations': [{'label': label, 'representation': 'native_overhang',
                'status': 'pending_route_and_unpaired_interval', 'candidate_intervals': functional}
                for label in labels]}


def import_pdf_tables(doc):
    """Recognize Module / Notes / DNA Sequence tables and consecutive continuations.

    Header locations determine columns; no publication-specific page coordinates.
    Empty module cells are deliberately not forward-filled (replacement oligos
    and line wraps are indistinguishable without additional evidence).
    """
    tables, current, columns = [], None, None
    for page_no, page in enumerate(doc, 1):
        lines = [line for block in page.get_text('dict')['blocks'] for line in block.get('lines', [])]
        text = lambda line: ''.join(s['text'] for s in line['spans']).strip()
        headers = {text(line).lower(): line for line in lines if text(line).lower() in ('module', 'notes', 'dna sequence', 'sequence')}
        seq_header = headers.get('dna sequence') or headers.get('sequence')
        if seq_header and 'module' in headers and 'notes' in headers:
            columns = {key: headers[key]['bbox'][0] for key in ('module', 'notes')}
            columns['sequence'] = seq_header['bbox'][0]
            # Repeated headers continue an adjacent table with the same columns.
            if current is None or current['pages'][-1] != page_no-1 or current['columns'] != columns:
                current = {'page': page_no, 'pages': [], 'columns': columns, 'rows': [], 'context': ''}
                tables.append(current)
            top = max(line['bbox'][3] for line in headers.values())
        elif current and current['pages'][-1] == page_no-1:
            top = page.rect.y0
        else:
            continue
        found = []
        for line in sorted(lines, key=lambda l: (l['bbox'][1], l['bbox'][0])):
            x, y, _, _ = line['bbox']; raw = text(line)
            if y <= top or abs(x-columns['sequence']) > 3 or not _SEQUENCE.fullmatch(raw):continue
            spans = [{'text': s['text'], 'bold': bool(s['flags'] & 16)} for s in line['spans']]
            parsed = annotate_sequence(raw)
            if len(parsed['sequence']) < 4:continue
            adjacent = [l for l in lines if abs(l['bbox'][1]-y) < 1.5]
            cells = {key: ' '.join(text(l) for l in adjacent if abs(l['bbox'][0]-columns[key]) < 3) for key in ('module', 'notes')}
            row = {'id': f'p{page_no}-r{len(current["rows"])+len(found)+1}', 'page': page_no,
                   'bbox': list(line['bbox']), **cells, 'raw_sequence': raw, 'spans': spans,
                   **annotate_sequence(raw, cells['notes'], cells['module'], spans)}
            if not row['module']:
                previous = (found or current['rows'])
                row['row_status'] = 'unlabelled_or_continuation'
                row['possible_continuation_of'] = previous[-1]['id'] if previous else None
            else:row['row_status'] = 'labelled'
            found.append(row)
        if found:
            current['pages'].append(page_no); current['rows'].extend(found)
            current['context'] += '\n' + '\n'.join(text(l) for l in lines if not _SEQUENCE.fullmatch(text(l)))
        else:
            current = columns = None
    for table in tables:
        table['module_counts'] = dict(Counter(r['module'] or 'unlabelled' for r in table['rows']))
        table['notices'] = ['Modules may be alternatives or accessory oligos. Do not combine every row into one design.',
                            'Unlabelled rows retain possible continuation links; they are not automatically concatenated.',
                            'Bold sequence spans indicate function, not proof of an unpaired overhang.']
        table['context'] = table['context'][:6000]
    return tables
