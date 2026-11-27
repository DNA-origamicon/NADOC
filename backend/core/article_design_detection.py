"""Agent-less image/list discovery and conservative vector-route hypotheses.

Results are transient evidence, not authored NADOC models. All proposed
calibrations and direction alternatives retain their source drawing path IDs.
"""
import base64
import csv
import hashlib
import io
import json
import re
from zipfile import BadZipFile
from pathlib import PurePath
from statistics import median

import pymupdf

from backend.core.publication_table_import import import_pdf_tables
from backend.core.publication_raster_tracing import register_and_trace
from backend.core.article_reconstruction import decode_pdf
from backend.core.article_sequence_inference import rank_directions
from backend.core.image_evaluation import evaluate_pdf, clusters
from backend.core.sequences import M13MP18_SEQUENCE
from backend.core.diagram_route_extraction import recover_vector_graph, orient_with_sequences
from backend.core.publication_routing import extract_publication_paths, staple_tables, publication_evidence
from backend.core.publication_vector_panels import calibrate_panels, extract_panel_hypotheses, select_panel_graph


def sequence_rows(text):
    """Read complete contiguous oligo tokens; never silently join table columns."""
    return [m.group() for m in re.finditer(r'(?<![A-Za-z])[ACGTacgt]{12,}(?![A-Za-z])', text)]


def read_lists(item):
    from openpyxl.utils.exceptions import InvalidFileException
    from xlrd.biffh import XLRDError
    try:
        return _read_lists(item)
    except (BadZipFile, InvalidFileException, XLRDError, OSError) as exc:
        raise ValueError('Could not read the staple workbook. Supply a valid XLS, XLSX, CSV or sequence JSON file.') from exc


def _read_lists(item):
    data = base64.b64decode(item['data'], validate=True)
    name = item.get('name', 'staples.txt')
    suffix = PurePath(name).suffix.lower()
    groups = []
    if suffix in ('.xlsx', '.xls'):
        if suffix == '.xlsx':
            from openpyxl import load_workbook
            book = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            try:
                groups = [(sheet.title, '\n'.join(str(cell) for row in sheet.iter_rows(values_only=True)
                                                 for cell in row if cell is not None)) for sheet in book]
            finally:
                book.close()
        else:
            try:
                import xlrd
            except ImportError as exc:
                raise ValueError('Legacy .xls requires xlrd; export the workbook as .xlsx or CSV.') from exc
            book = xlrd.open_workbook(file_contents=data)
            groups = [(sheet.name, '\n'.join(str(cell.value) for row in sheet.get_rows() for cell in row))
                      for sheet in book.sheets()]
    elif suffix == '.json':
        value = json.loads(data)
        seqs = value.get('sequences', []) if isinstance(value, dict) else value
        if not isinstance(seqs, list) or not all(isinstance(s, str) for s in seqs):
            raise ValueError('Sequence JSON must be a string array or an object with sequences.')
        groups = [(value.get('sheet', name) if isinstance(value, dict) else name, '\n'.join(seqs))]
    else:
        text = data.decode('utf-8-sig')
        if suffix == '.csv':
            text = '\n'.join(cell for row in csv.reader(io.StringIO(text)) for cell in row)
        groups = [(name, text)]
    digest = hashlib.sha256(data).hexdigest()
    return [{'id': f'{digest[:12]}-list-{i}', 'label': f'{name} · {label}', 'source_sha256': digest,
             'sequences': sequence_rows(text), 'context': label, 'page': None}
            for i, (label, text) in enumerate(groups) if sequence_rows(text)]


def observed_paths(page, bounds):
    """Recover continuous PDF subpaths with their drawn, untrusted ordering."""
    clip = pymupdf.Rect(bounds) + (-1, -1, 1, 1)
    output = []
    for index, path in enumerate(page.get_drawings()):
        if path.get('color') is None or path.get('fill') is not None:
            continue
        runs, previous, continuous = [], None, not path.get('closePath', False)
        for item in path['items']:
            if item[0] not in ('l', 'c'):
                continuous = False
                continue
            a, b = item[1], item[-1]
            if previous is not None and abs(a-previous) > .5:
                continuous = False
            previous = b
            if item[0] == 'l' and abs(a.y-b.y) < .35 and abs(a.x-b.x) > 1:
                if clip.contains(a) and clip.contains(b):
                    runs.append([float(a.x), float(b.x), float((a.y+b.y)/2)])
                else:
                    continuous = False  # A cropped scaffold must not masquerade as a whole walk.
        if runs:
            output.append({'path_id': index, 'runs': runs, 'continuous': continuous,
                           'color': list(path['color']), 'length': sum(abs(b-a) for a, b, _ in runs)})
    return output


def route_hypotheses(paths, scaffold_length):
    """Test whole-scaffold scale and 7/8-base junction-grid scale hypotheses.

    Horizontal spans count both endpoints. Noninteger calibrations, overlapping
    scaffold walks and broken paths are rejected, not rounded into topology.
    """
    usable = [p for p in paths if p['continuous']]
    if not usable:
        return []
    ys = clusters([y for p in usable for _, _, y in p['runs']], .7)
    origin = min(min(a, b) for p in usable for a, b, _ in p['runs'])
    hypotheses = []
    for scaffold_path in sorted(usable, key=lambda p: -p['length'])[:2]:
        runs = scaffold_path['runs']
        if len(runs) < 2 or scaffold_length <= len(runs):
            continue
        xs = sorted(set(round(x, 2) for a, b, _ in runs for x in (a, b)))
        gaps = [b-a for a, b in zip(xs, xs[1:]) if b-a > 1]
        scales = [(scaffold_path['length']/(scaffold_length-len(runs)), 'whole scaffold length')]
        if gaps:
            scales += [(median(gaps)/step, f'{step}-base interval hypothesis') for step in (7, 8)]
        seen = set()
        for scale, method in scales:
            if scale <= .01 or round(scale, 4) in seen:
                continue
            seen.add(round(scale, 4))
            def walk(path):
                points = []
                for a, b, y in path['runs']:
                    values = [(x-origin)/scale for x in (a, b)]
                    if any(abs(v-round(v)) > .15 for v in values):
                        return None
                    lo, hi = map(round, values)
                    row = min(range(len(ys)), key=lambda i: abs(ys[i]-y))
                    if abs(hi-lo) > scaffold_length:
                        return None
                    points.extend((row, bp) for bp in range(lo, hi+(1 if hi >= lo else -1), 1 if hi >= lo else -1))
                return points
            scaffold = walk(scaffold_path)
            if not scaffold or len(scaffold) != scaffold_length or len(set(scaffold)) != len(scaffold):
                continue
            lookup = {point: i for i, point in enumerate(scaffold)}
            templates, source_paths = [], []
            for path in usable:
                if path is scaffold_path:
                    continue
                points = walk(path)
                if points and 12 <= len(points) <= 300 and len(set(points)) == len(points):
                    templates.append([lookup.get(p) for p in points])
                    source_paths.append(path['path_id'])
            if templates:
                hypotheses.append({'calibration': {'points_per_base': scale, 'method': method, 'x_origin': origin,
                                                   'scaffold_path_id': scaffold_path['path_id'], 'image_rows': ys},
                                   'templates': templates, 'source_paths': source_paths})
    return hypotheses


def figure_context(page, bounds):
    """Use nearby caption blocks, avoiding labels belonging to distant panels."""
    rect = pymupdf.Rect(bounds)
    nearby = []
    for block in page.get_text('blocks'):
        if len(block) < 7 or block[6] != 0:
            continue
        box, text = pymupdf.Rect(block[:4]), block[4]
        if sequence_rows(text):
            continue
        dx = max(rect.x0-box.x1, box.x0-rect.x1, 0)
        dy = max(rect.y0-box.y1, box.y0-rect.y1, 0)
        if dx < 30 and dy < 100:
            nearby.append((dx+dy, text.strip()))
    return ' '.join(text for _, text in sorted(nearby)[:3])[:1500]


def context_score(figure, staple_list):
    ignored = {'figure', 'diagram', 'cadnano', 'staples', 'staple', 'supplementary', 'supplement', 'page', 'table', 'pdf', 'design', 'dna', 'origami', 'routing', 'sequence', 'sequences', 'csv', 'xlsx', 'xls', 'supplemental', 'schematic', 'schematics'}
    tokens = lambda text: {w for w in re.findall(r'[a-z][a-z0-9-]{2,}', text.lower()) if w not in ignored}
    shared = sorted(tokens(figure['context']) & tokens(staple_list['context']))
    same_source = figure['source_sha256'] == staple_list['source_sha256']
    proximity = same_source and staple_list['page'] is not None and abs(figure['page']-staple_list['page']) <= 2
    return min(60, len(shared)*20 + (15 if proximity else 0)), shared


def detect_designs(payload):
    scaffold = re.sub(r'\s+', '', payload.get('scaffold_sequence') or M13MP18_SEQUENCE).upper()
    if set(scaffold) - set('ACGT') or len(scaffold) < 12:
        raise ValueError('Scaffold sequence must contain at least 12 A/C/G/T bases.')
    files = [item for item in [payload.get('paper'), *payload.get('supplements', [])] if item]
    if not files:
        raise ValueError('Upload paper or supplement PDFs to analyze actual diagrams.')
    lists, figures, notes = [], [], []
    for item in payload.get('staple_lists', []):
        lists.extend(read_lists(item))
    for file in files:
        data = decode_pdf(file)
        name = file.get('name', 'PDF')
        report = evaluate_pdf(data)
        digest = report['source_sha256']
        notes.extend(f'{name}: {note}' for note in report['notes'])
        with pymupdf.open(stream=data, filetype='pdf') as doc:
            imported_tables = import_pdf_tables(doc)
            imported_pages = {p for t in imported_tables for p in t['pages']}
            for table in imported_tables:
                lists.append({'id': f'{digest[:12]}-p{table["page"]}-structured',
                              'label': f'{name} · table pages {table["pages"]}',
                              'source_sha256': digest, 'page': table['page'], 'pages': table['pages'],
                              'sequences': [r['sequence'] for r in table['rows']],
                              'context': table['context'], 'table_import': table})
            for index, page in enumerate(doc):
                text = page.get_text()
                seqs = [] if index+1 in imported_pages else sequence_rows(text)
                if len(seqs) >= 2:
                    lists.append({'id': f'{digest[:12]}-p{index+1}-list', 'label': f'{name} · page {index+1}',
                                  'source_sha256': digest, 'page': index+1, 'sequences': seqs,
                                  'context': re.sub(r'[ACGTacgt]{12,}', '', text)[:1500]})
            publication_graphs = {}
            endpoint_tables = staple_tables(doc)
            if endpoint_tables:
                for index, page in enumerate(doc):
                    custom = scaffold if payload.get('scaffold_sequence') else None
                    try:
                        observed = extract_publication_paths(page)
                    except ValueError:
                        try:
                            hypotheses = list(extract_panel_hypotheses(page, calibrate_panels(page)))
                        except ValueError:
                            continue
                        evidence = []
                        observed = None
                        for table in endpoint_tables:
                            try:
                                candidate = select_panel_graph(page, table, hypotheses=hypotheses)
                                if not candidate or candidate['panel_selection']['matching_rows'] < len(table['rows']) / 2:
                                    continue
                                rows = publication_evidence(candidate, [table], custom)
                            except ValueError:
                                continue
                            if rows:
                                rows[0]['vector_panel_registration'] = candidate['panel_selection']
                                evidence.extend(rows)
                                if observed is None:
                                    observed = candidate
                    else:
                        try:
                            evidence = publication_evidence(observed, endpoint_tables, custom)
                        except ValueError:
                            continue
                    if not evidence:
                        continue
                    publication_graphs[index+1] = evidence
                    report['figures'] = [f for f in report['figures'] if f['page'] != index+1]
                    scale = min(2, 1800/max(page.rect.width,page.rect.height))
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False)
                    report['figures'].append({'id':f'p{index+1}-publication', 'page':index+1,
                        'label':f'Page {index+1} · publication routing diagram',
                        'source_bounds':list(page.rect), 'rows':list(observed['calibration']['row_centers']),
                        'crossovers':[], 'flags':[],
                        'image':'data:image/png;base64,'+base64.b64encode(pix.tobytes('png')).decode()})
            calibrated_graphs = {}
            for index, page in enumerate(doc):
                try:
                    graph = recover_vector_graph(data, index)
                except ValueError:
                    continue
                calibrated_graphs[index+1] = graph
                # This graph detector also handles fragmented strokes missed by
                # the original whole-path candidate detector. It must not depend
                # on that detector nominating the page first.
                report['figures'] = [f for f in report['figures'] if f['page'] != index+1]
                scale = min(2, 1800/max(page.rect.width,page.rect.height))
                pix = page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False)
                branches = [p for values in graph['observations'].values() for p in values['primitives'] if p['start'][0] != p['end'][0]]
                report['figures'].append({'id': f'p{index+1}-calibrated', 'page': index+1,
                                         'label': f'Page {index+1} · calibrated routing diagram',
                                         'source_bounds': list(page.rect), 'rows': list(graph['calibration']['row_centers']),
                                         'crossovers': branches, 'flags': [],
                                         'image': 'data:image/png;base64,'+base64.b64encode(pix.tobytes('png')).decode()})
            for figure in report['figures']:
                page = doc[figure['page']-1]
                context = figure_context(page, figure['source_bounds'])
                paths = observed_paths(page, figure['source_bounds'])
                graph, graph_note = calibrated_graphs.get(figure['page']), ''
                figures.append({'id': f'{digest[:12]}-{figure["id"]}', 'label': f'{name} · {figure["label"]}',
                                'source_sha256': digest, 'page': figure['page'], 'context': context,
                                'image': figure['image'], 'rows': len(figure['rows']), 'branches': len(figure['crossovers']),
                                'observed_paths': paths, 'flags': figure['flags'], 'pairings': [],
                                '_routes': [] if figure['page'] in publication_graphs else route_hypotheses(paths, len(scaffold)),
                                '_publication': publication_graphs.get(figure['page'], []), '_graph': graph, 'graph_note': graph_note})
            # Captioned raster pages remain selectable even without vector tracing.
            vector_pages = {f['page'] for f in report['figures']}
            for index, page in enumerate(doc):
                text = page.get_text()
                if index+1 in vector_pages or not page.get_images() or not re.search(r'ca[\s-]*dna[\s-]*no', text, re.I):
                    continue
                pix = page.get_pixmap(matrix=pymupdf.Matrix(min(1, 1000/page.rect.width), min(1, 1000/page.rect.width)), alpha=False)
                figures.append({'id': f'{digest[:12]}-p{index+1}-raster', 'label': f'{name} · page {index+1} · raster candidate',
                                'source_sha256': digest, 'page': index+1, 'context': text[:1500],
                                'image': 'data:image/png;base64,' + base64.b64encode(pix.tobytes('png')).decode(),
                                'rows': 0, 'branches': 0, 'observed_paths': [], 'flags': [], 'pairings': [], '_routes': [],
                                'raster_evidence': register_and_trace(page)})
    # Repeated files are one source of evidence, not independent corroboration.
    lists = list({item['id']: item for item in lists}.values())
    figures = list({item['id']: item for item in figures}.values())
    for figure in figures:
        for staple_list in lists:
            endpoint_evidence = next((e for e in figure.get('_publication', [])
                                      if e['table_page']==staple_list['page'] and
                                      figure['source_sha256']==staple_list['source_sha256']), None)
            if endpoint_evidence:
                figure['pairings'].append({'list_id':staple_list['id'], 'label':staple_list['label'],
                    'list_rows':len(staple_list['sequences']), 'context_score':0, 'shared_labels':[],
                    'basis':'published endpoints and image paths', 'direction_resolved':False,
                    'alternatives':[], 'best_ties':0, 'routing_recovered':False, 'routing':None,
                    'publication_evidence':endpoint_evidence})
                continue
            score, shared = context_score(figure, staple_list)
            if staple_list.get('table_import') and figure['source_sha256'] == staple_list['source_sha256'] and 0 < staple_list['page']-figure['page'] <= 2:
                score = max(score, 20)
            alternatives = []
            graph_result = None
            if figure.get('_graph'):
                try:
                    graph_result = orient_with_sequences(figure['_graph'], scaffold, staple_list['sequences'])
                except ValueError as exc:
                    figure['graph_note'] = str(exc)
            for routing in ([] if graph_result else figure['_routes']):
                result = rank_directions(routing['templates'], staple_list['sequences'], scaffold)
                for hypothesis in result['hypotheses']:
                    alternatives.append({**hypothesis, 'calibration': routing['calibration'],
                                         'source_paths': routing['source_paths'],
                                         'observed_partner_indices': routing['templates']})
            if graph_result:
                graph = graph_result['graph']
                deleted = {tuple(p) for p in graph['deletions']}
                total = sum(sum(tuple(p) not in deleted for p in path) for path in graph['paths']['stap'])
                for hypothesis in graph_result['alternatives']:
                    if not hypothesis['matched_staples']:
                        continue
                    alternatives.append({
                        'scaffold_direction': 'reversed' if hypothesis['scaffold_reverse'] else 'image graph order',
                        'staple_direction': 'resolved independently per path',
                        'scaffold_offset': hypothesis['offset'], 'matched_staples': hypothesis['matched_staples'],
                        'list_rows': len(staple_list['sequences']), 'paired_bases_verified': hypothesis['paired_bases_verified'],
                        'unknown_bases': sum(m['unknown_bases'] for m in hypothesis['assignments']),
                        'evidence_score': round(100*hypothesis['paired_bases_verified']/max(1,total),1),
                        'matches': hypothesis['assignments'],
                        'calibration': {**graph['calibration'], 'method': 'visible ruler and numbered image rows'},
                    })
            alternatives.sort(key=lambda h: (-h['matched_staples'], -h['paired_bases_verified']))
            best = alternatives[0] if alternatives else None
            ties = sum((h['matched_staples'], h['paired_bases_verified']) ==
                       (best['matched_staples'], best['paired_bases_verified']) for h in alternatives) if best else 0
            # Sequence support dominates text-only pairing; unrelated lists stay unassigned.
            likely = bool(best and best['matched_staples'] >= 3) or score >= 20
            if likely:
                figure['pairings'].append({'list_id': staple_list['id'], 'label': staple_list['label'],
                                          'list_rows': len(staple_list['sequences']), 'context_score': score, 'shared_labels': shared,
                                          'table_import': staple_list.get('table_import'),
                                          'table_page': staple_list['page'], 'table_source_sha256': staple_list['source_sha256'],
                                          'basis': 'sequence agreement' if best and best['matched_staples'] >= 3 else 'caption/context only',
                                          'direction_resolved': bool(best and best['matched_staples'] >= 3 and ties == 1),
                                          'alternatives': alternatives[:8], 'best_ties': ties,
                                          'routing_recovered': bool(graph_result and graph_result['resolved']),
                                          'routing': ({'directed_paths': graph_result['directed_paths'],
                                                       'deletions': graph_result['graph']['deletions'],
                                                       'lattice': graph_result['graph']['lattice'],
                                                       'source_sha256': graph_result['source_sha256'],
                                                       'method': graph_result['method']}
                                                      if graph_result and graph_result['resolved'] else None)})
        figure['pairings'].sort(key=lambda p: (p['basis'] == 'sequence agreement',
                                             p['alternatives'][0]['matched_staples'] if p['alternatives'] else 0,
                                             p['context_score']), reverse=True)
        figure['limitations'] = [
            'Image rows and PDF paths are observations, not verified helix identities or strand boundaries.',
            'Scale and PDF path connectivity are hypotheses. Insertions, deletions, fragmented paths and stretched drawings may prevent matching.',
            'Unknown scaffold partners remain unknown; a sequence score is not a calibrated reconstruction probability.',
            'No molecular model is created; complete topology and geometry remain unverified.']
        figure['publication_pairings_tested'] = len(figure.pop('_publication', []))
        figure['route_hypotheses_tested'] = len(figure.pop('_routes')) + bool(figure.pop('_graph', None))
    return {'designs': figures, 'staple_lists': [{k: v for k, v in item.items() if k != 'sequences'} | {'count': len(item['sequences'])} for item in lists],
            'notes': notes, 'method': 'vector-raster-and-structured-tables-v3',
            'scaffold': {'name': 'custom' if payload.get('scaffold_sequence') else 'M13mp18 hypothesis', 'length': len(scaffold)},
            'can_reconstruct': False}
