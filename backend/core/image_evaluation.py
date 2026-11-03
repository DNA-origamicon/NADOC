"""Read-only PDF diagram evidence. Pixel distances are never molecular geometry.

Recognition is heuristic; lattice/index hypotheses require user calibration.
No design objects, workspace writes, or topology mutation occur here.
"""
from __future__ import annotations

import base64
import hashlib
from collections import Counter, defaultdict
from statistics import median

MAX_BYTES = 25 * 1024 * 1024
MAX_PAGES = 100
MAX_FIGURES = 16


def clusters(values, tolerance):
    groups = []
    for value in sorted(values):
        if not groups or value - median(groups[-1]) > tolerance:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [median(group) for group in groups]


def diagram_evidence(paths):
    """Find axis-aligned routing evidence in one spatial/color group."""
    lines = [item for p in paths for item in p['items']
             if item[0] == 'l' and abs(item[1].y - item[2].y) < .35
             and abs(item[1].x - item[2].x) > 5]
    rows = clusters([i[1].y for i in lines], .6)
    if len(rows) < 6 or len(lines) < 12:
        return None
    curves = []
    for path in paths:
        items = path['items']
        for j, item in enumerate(items):
            if item[0] not in ('c', 'l'):
                continue
            a, b = item[1], item[-1]
            if abs(a.x - b.x) > 2 or abs(a.y - b.y) < 2:
                continue
            ia = min(range(len(rows)), key=lambda k: abs(rows[k] - a.y))
            ib = min(range(len(rows)), key=lambda k: abs(rows[k] - b.y))
            if ia == ib or max(abs(rows[ia] - a.y), abs(rows[ib] - b.y)) > 1:
                continue
            previous = items[j - 1] if j else None
            side = 'unknown'
            if previous and previous[0] == 'l':
                side = 'left' if previous[1].x < a.x else 'right'
            curves.append({'x': (a.x + b.x) / 2, 'y1': a.y, 'y2': b.y,
                           'rows': sorted([ia, ib]), 'side': side})
    if len(curves) < 6:
        return None
    # Group the two branches of a junction, not their Bézier control points.
    columns = clusters([c['x'] for c in curves], 2)
    if len(columns) < 3:
        return None
    for curve in curves:
        curve['column'] = min(range(len(columns)), key=lambda k: abs(columns[k] - curve['x']))
    gaps = [b - a for a, b in zip(columns, columns[1:])]
    baseline = median(sorted(gaps)[:max(1, (len(gaps) + 1) // 2)])
    flags = []
    for i, gap in enumerate(gaps):
        if gap > baseline * 1.65:
            flags.append({'kind': 'spacing', 'x': (columns[i] + columns[i + 1]) / 2,
                          'y': rows[0], 'column': i,
                          'detail': f'Column gap is {gap / baseline:.2f}× the shorter-gap baseline. '
                          'Possible stretched drawing, skipped planes, or missing evidence; not proof of extra DNA.'})
    groups = defaultdict(list)
    for c in curves:
        groups[(tuple(c['rows']), c['column'])].append(c)
    for (pair, column), members in groups.items():
        sides = {m['side'] for m in members}
        if len(members) == 1 and 'unknown' not in sides:
            flags.append({'kind': 'single-branch', 'x': members[0]['x'],
                          'y': (rows[pair[0]] + rows[pair[1]]) / 2, 'column': column,
                          'detail': f'Rows {pair[0]}–{pair[1]}: only the {members[0]["side"]} branch was detected. '
                          'May be intentional; do not automatically complete the junction.'})
    for pair in {pair for pair, _ in groups}:
        occupied = sorted(col for p, col in groups if p == pair)
        periods = Counter(b - a for a, b in zip(occupied, occupied[1:]))
        if periods:
            period, count = periods.most_common(1)[0]
            if period in (3, 4) and count >= 2:
                for col in range(occupied[0] % period, len(columns), period):
                    if col not in occupied:
                        flags.append({'kind': 'missing-site', 'x': columns[col],
                                      'y': (rows[pair[0]] + rows[pair[1]]) / 2, 'column': col,
                                      'detail': f'Rows {pair[0]}–{pair[1]}: no junction detected at column {col}, '
                                      f'where extrapolating their {period}-column repeat suggests an opportunity. '
                                      'Possible intentional omission, end effect, or detection failure; not a required bond.'})
        for a, b in zip(occupied, occupied[1:]):
            if b - a > 3:
                flags.append({'kind': 'occupancy', 'x': (columns[a] + columns[b]) / 2,
                              'y': (rows[pair[0]] + rows[pair[1]]) / 2, 'column': a,
                              'detail': f'Rows {pair[0]}–{pair[1]}: a gap in repeated junction occupancy. '
                              'Possible deliberately skipped crossover; lattice-dependent, not a design error.'})
    endpoints = []
    for path in paths:
        items = path['items']
        if not items:
            continue
        for point in (items[0][1], items[-1][-1]):
            if not hasattr(point, 'y'):
                continue
            row = min(range(len(rows)), key=lambda k: abs(rows[k] - point.y))
            if abs(rows[row] - point.y) < 1:
                endpoints.append({'x': point.x, 'y': point.y, 'row': row})
    xs = [p.x for item in lines for p in (item[1], item[-1])]
    return {'rows': rows, 'columns': columns, 'crossovers': curves, 'endpoints': endpoints,
            'flags': flags, 'path_count': len(paths), 'bounds': [min(xs), rows[0], max(xs), rows[-1]],
            'limitations': [
                'Candidate recognition is heuristic; confirm this is a caDNAno-style routing diagram.',
                'Row numbers are inferred top-to-bottom, not verified helix identities or lattice adjacency.',
                'Path endpoints are possible termini/nicks; PDF path fragmentation and arrowheads can mimic nicks.',
                'BP labels assume one lattice plane per detected column. Missing planes and local stretching are ambiguous.',
                'Scaffold register, polarity, insertions/deletions, TT/CPD chemistry, overhang lengths and sequences are not established by this analysis.',
                'No molecular design or simulation is created or modified.',
            ]}


def evaluate_pdf(data):
    import pymupdf

    if len(data) > MAX_BYTES:
        raise ValueError('PDF exceeds the 25 MiB limit.')
    if not data.startswith(b'%PDF-'):
        raise ValueError('Select a valid PDF file.')
    try:
        doc = pymupdf.open(stream=data, filetype='pdf')
    except Exception as exc:
        raise ValueError('The PDF could not be opened.') from exc
    figures, notes = [], []
    page_count = len(doc)
    with doc:
        if doc.needs_pass:
            raise ValueError('Password-protected PDFs are not supported. Import an unlocked copy.')
        if len(doc) > MAX_PAGES:
            raise ValueError('PDF exceeds 100 pages. Export the relevant supplement pages first.')
        for page_number, page in enumerate(doc):
            if len(figures) >= MAX_FIGURES:
                notes.append('Stopped after 16 candidates; import a smaller page range to inspect additional figures.')
                break
            drawings = page.get_drawings()
            if len(drawings) > 30000:
                notes.append(f'Page {page_number + 1}: too many vector paths; skipped.')
                continue
            by_color = defaultdict(list)
            for path in drawings:
                # Panel/image frames can otherwise masquerade as paired junctions.
                edges = [i for i in path['items'] if i[0] != 'l' or abs(i[1].x - i[-1].x) + abs(i[1].y - i[-1].y) > .01]
                if (len(edges) == 4 and all(i[0] == 'l' for i in edges)
                        and len({round(p.x, 2) for i in edges for p in (i[1], i[-1])}) == 2
                        and len({round(p.y, 2) for i in edges for p in (i[1], i[-1])}) == 2):
                    continue
                if path.get('color') is not None and any(i[0] == 'l' for i in path['items']):
                    color = tuple(round(c, 2) for c in path['color'])
                    by_color[color].append(path)
            # Separate spatially disjoint figures before evaluating their tracks.
            candidates = []
            for paths in by_color.values():
                chunks = []
                for path in sorted(paths, key=lambda p: p['rect'].y0):
                    expanded = path['rect'] + (-30, -30, 30, 30)
                    touching = [i for i, (rect, _) in enumerate(chunks) if expanded.intersects(rect)]
                    merged = [path]
                    rect = pymupdf.Rect(path['rect'])
                    for i in reversed(touching):
                        other, members = chunks.pop(i)
                        rect |= other
                        merged.extend(members)
                    chunks.append((rect, merged))
                for _, chunk in chunks:
                    evidence = diagram_evidence(chunk)
                    if evidence:
                        candidates.append(evidence)
            candidates.sort(key=lambda e: len(e['crossovers']), reverse=True)
            accepted = []
            for evidence in candidates:
                rect = pymupdf.Rect(evidence['bounds'])
                if any((rect & other).get_area() / max(1, min(rect.get_area(), other.get_area())) > .7 for other in accepted):
                    continue
                accepted.append(rect)
                clip = (rect + (-16, -18, 16, 12)) & page.rect
                scale = min(2, 1800 / max(clip.width, clip.height))
                pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=clip, alpha=False)
                # Normalize all annotations to the exact rendered pixmap bounds.
                ox, oy = pix.x / scale, pix.y / scale
                width, height = pix.width / scale, pix.height / scale
                def nx(x): return (x - ox) / width * 1000
                def ny(y): return (y - oy) / height * 1000
                evidence['columns'] = [nx(x) for x in evidence['columns']]
                evidence['rows'] = [ny(y) for y in evidence['rows']]
                for c in evidence['crossovers']:
                    c.update(x=nx(c['x']), y1=ny(c['y1']), y2=ny(c['y2']))
                for item in evidence['endpoints'] + evidence['flags']:
                    item.update(x=nx(item['x']), y=ny(item['y']))
                text = page.get_text('text')
                import re
                captions = re.findall(r'(?:Fig\.?|Figure)\s+[S\d][\w.]*[^\n]{0,100}', text)
                evidence.update(id=f'p{page_number + 1}-f{len(accepted)}', page=page_number + 1,
                                label=f'Page {page_number + 1} · routing candidate {len(accepted)}',
                                page_captions=captions[:6], image='data:image/png;base64,' + base64.b64encode(pix.tobytes('png')).decode(),
                                aspect=width / height, source_bounds=list(clip))
                figures.append(evidence)
                if len(figures) >= MAX_FIGURES:
                    break
            if not accepted and page.get_images():
                notes.append(f'Page {page_number + 1}: embedded raster images found; vector routing could not be recognized. Raster interpretation is not yet supported.')
    return {'figures': figures, 'notes': notes, 'pages': page_count,
            'source_sha256': hashlib.sha256(data).hexdigest(), 'method': 'vector-routing-evidence-v1'}
