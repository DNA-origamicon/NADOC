"""Undirected, source-pixel staple traces with explicit crossing uncertainty."""
from collections import Counter, defaultdict

import numpy as np
import pymupdf
from skimage.draw import line

from backend.core.publication_lane_classification import trace_ink_labels, classify_lanes, classify_point


def horizontal_domains(points, lanes, pitch):
    domains, group = [], []
    low_y = high_y = None
    def save(values):
        if len(values) < 2:
            return
        xs, ys = np.asarray(values).T
        if np.ptp(ys) > pitch * .3 or np.ptp(xs) < pitch * 2:
            return
        y = float(np.mean(ys))
        kind, row, side = classify_point(y, lanes)
        domains.append({'kind': kind, 'observed_row_index': row, 'lane_side': side,
                        'span_pixels': [[float(min(xs)), y], [float(max(xs)), y]],
                        'approximate_cells': float(np.ptp(xs) / pitch + 1)})
    for point in points:
        if group and max(high_y, point[1]) - min(low_y, point[1]) > pitch * .3:
            save(group); group = [group[-1], point]
            low_y, high_y = min(p[1] for p in group), max(p[1] for p in group)
        else:
            group.append(point)
            low_y = point[1] if low_y is None else min(low_y, point[1])
            high_y = point[1] if high_y is None else max(high_y, point[1])
    save(group)
    return domains


def _edge_color(points, labels):
    counts = Counter()
    for a, b in zip(points, points[1:]):
        yy, xx = line(int(a[1]), int(a[0]), int(b[1]), int(b[0]))
        counts.update(int(v) for v in labels[yy, xx] if v >= 0)
    if not counts:
        return None, 0.
    hue, size = counts.most_common(1)[0]
    return hue, size / sum(counts.values())


def _outward(points, side, distance):
    values = points if side == 0 else points[::-1]
    origin = np.array(values[0], dtype=float)
    for value in values[1:]:
        delta = np.asarray(value) - origin
        if np.linalg.norm(delta) >= distance:
            return delta / np.linalg.norm(delta)
    return None


def trace_panel(rgb, grid, *, maximum_edges=12000):
    from backend.core.publication_raster_tracing import trace_mask
    from backend.core.publication_connector_geometry import recognize_offset_connectors
    if not 1 <= maximum_edges <= 50000:
        raise ValueError('Invalid trace edge budget.')
    lanes = classify_lanes(rgb, grid)
    if lanes['status'] != 'panel_pattern_supported':
        return {'lane_classification': lanes, 'traces': [], 'status': 'lane_classification_unresolved',
                'native_routing_resolved': False}
    labels, ink = trace_ink_labels(rgb)
    mask = labels >= 0
    mask[:, :round(mask.shape[1] * .08)] = False
    paths, _, truncated = trace_mask(mask, max_edges=maximum_edges)
    edges, incident = [], defaultdict(list)
    for i, points in enumerate(paths):
        hue, coherence = _edge_color(points, labels)
        domains = horizontal_domains(points, lanes, grid['grid_pitch'])
        roles = {d['kind'] for d in domains if d['kind'] != 'unclassified'}
        edges.append({'points': points, 'hue_bin': hue, 'color_coherence': coherence, 'roles': roles, 'domains': domains})
        incident[tuple(points[0])].append((i, 0))
        incident[tuple(points[-1])].append((i, 1))
    joins, crossing_evidence = {}, []
    for node, ends in incident.items():
        if len(ends) != 4:
            continue
        by_color = defaultdict(list)
        for edge_id, side in ends:
            edge = edges[edge_id]
            if edge['color_coherence'] < .8:
                break
            by_color[edge['hue_bin']].append((edge_id, side))
        else:
            if len(by_color) != 2 or any(len(group) != 2 for group in by_color.values()):
                continue
            pairings = []; straight_count = 0; connector_supported = False
            for group in by_color.values():
                a, b = group
                if edges[a[0]]['roles'] | edges[b[0]]['roles'] == {'scaffold', 'staple'}:
                    break
                u = _outward(edges[a[0]]['points'], a[1], grid['grid_pitch'] * .7)
                v = _outward(edges[b[0]]['points'], b[1], grid['grid_pitch'] * .7)
                if u is None or v is None:
                    break
                if float(u @ v) <= -.85:
                    straight_count += 1
                else:
                    # A colored bend is only continued when its two visible arms
                    # establish a same-staple-lane detour, not merely a color match.
                    pa = edges[a[0]]['points'] if a[1] == 1 else edges[a[0]]['points'][::-1]
                    pb = edges[b[0]]['points'] if b[1] == 0 else edges[b[0]]['points'][::-1]
                    drawing = recognize_offset_connectors(pa + pb[1:], lanes, grid['grid_pitch'])
                    if not drawing['annotations']:
                        break
                    connector_supported = True
                pairings.append((a, b))
            else:
                if not straight_count:
                    continue
                for a, b in pairings:
                    joins[a] = b; joins[b] = a
                crossing_evidence.append({'pixel': list(node), 'edge_pairs': pairings,
                                          'method': 'distinct-color-offset-connector' if connector_supported else 'distinct-color-straight-continuation'})
    visited, traces = set(), []
    starts = [(i, side) for i in range(len(edges)) for side in (0, 1) if (i, side) not in joins]
    for start in starts + [(i, 0) for i in range(len(edges))]:
        if start[0] in visited:
            continue
        current, points, ids = start, [], []
        while current[0] not in visited:
            edge_id, side = current
            visited.add(edge_id); ids.append(edge_id)
            values = edges[edge_id]['points'] if side == 0 else edges[edge_id]['points'][::-1]
            points.extend(values if not points else values[1:])
            end = (edge_id, 1 - side)
            if end not in joins:
                break
            current = joins[end]
        coherent = all(edges[i]['color_coherence'] >= .8 for i in ids)
        drawing = recognize_offset_connectors(points, lanes, grid['grid_pitch']) if coherent and not truncated else {'annotations': []}
        domains = [d for path in drawing['domain_paths'] for d in horizontal_domains(path, lanes, grid['grid_pitch'])] if drawing['annotations'] else horizontal_domains(points, lanes, grid['grid_pitch'])
        kinds = {d['kind'] for d in domains if d['kind'] != 'unclassified'}
        kind = next(iter(kinds)) if len(kinds) == 1 else 'mixed' if kinds else 'staple' if drawing['annotations'] else 'unclassified'
        degrees = [len(incident[tuple(points[0])]), len(incident[tuple(points[-1])])]
        unresolved = truncated or any(d > 2 for d in degrees)
        coherent = all(edges[i]['color_coherence'] >= .8 for i in ids)
        status = 'unbranched_staple_trace' if kind == 'staple' and not unresolved and coherent else 'staple_trace_fragment' if kind == 'staple' else kind + '_trace'
        # Retain useful domains and connectors, but not pixel-sized text/grid fragments.
        if domains or drawing['annotations']:
            traces.append({'trace_id': len(traces), 'kind': kind, 'status': status,
                           'points_pixels': points, 'domains': domains, 'source_edge_ids': ids,
                           'connector_annotations': drawing['annotations'],
                           'hue_bins': sorted({edges[i]['hue_bin'] for i in ids if edges[i]['hue_bin'] is not None}),
                           'endpoint_degrees': degrees, 'unresolved_junction': unresolved,
                           'color_continuity_supported': coherent,
                           'terminal_markers_verified': False, 'strand_polarity': 'unresolved',
                           'native_routing_resolved': False})
    from backend.core.publication_connector_search import search_connector_drawings
    connector_search = search_connector_drawings(edges, incident, lanes, grid['grid_pitch']) if not truncated else {'candidates': [], 'budget_exhausted': True}
    from backend.core.publication_offset_runs import offset_run_hypotheses, offset_marker_hypotheses
    partial_connectors = offset_run_hypotheses(traces, lanes, labels, grid['grid_pitch'])
    markers = offset_marker_hypotheses(traces, lanes, labels, grid['grid_pitch'])
    return {'offset_marker_annotations': markers, 'partial_connectors': partial_connectors, 'connector_search': connector_search, 'method': 'classified-continuous-pixel-traces-v2', 'status': 'observed_traces_only',
            'lane_classification': lanes, 'ink_classification': ink, 'traces': traces, 'resolved_crossings': crossing_evidence,
            'unresolved_junction_count': sum(len(ends) > 2 and not all(e in joins for e in ends) for ends in incident.values()),
            'connector_drawing_count': sum(len(t['connector_annotations']) for t in traces),
            'primitive_edge_count': len(edges), 'truncated': truncated, 'native_routing_resolved': False,
            'limitation': 'Undirected pixel connectivity only. An unbranched trace may end at a compression break or crop boundary; full strand endpoints and molecular routing are not established. Same-color junctions and unsupported color changes are not joined.'}


def classify_and_trace_page(page, panel_registration):
    """Trace the visible PDF composition, never hidden original image pixels."""
    panels = {p['xref']: p for p in panel_registration.get('panels', [])}
    results, omitted = [], []
    for index, placement in enumerate(page.get_image_info(xrefs=True)):
        panel = panels.get(placement.get('xref'))
        if panel is None:
            continue
        transform = placement['transform']
        if page.rotation or abs(transform[1]) > 1e-6 or abs(transform[2]) > 1e-6 or transform[0] <= 0 or transform[3] <= 0:
            omitted.append({'placement_index': index, 'reason': 'unsupported_rotated_or_reflected_placement'})
            continue
        box = pymupdf.Rect(placement['bbox'])
        scale = panel['width'] / box.width
        if box.width * box.height * scale * scale > 4_000_000:
            omitted.append({'placement_index': index, 'reason': 'visible_pixel_budget'})
            continue
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), clip=box, alpha=False, colorspace=pymupdf.csRGB)
        rgb = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
        y_scale = box.height * scale / panel['height']
        grid = {'grid_pitch': panel['grid_pitch'], 'row_pitch': panel['row_pitch'] * y_scale,
                'row_centers': [y * y_scale + box.y0 * scale - pix.y for y in panel['row_centers']]}
        result = trace_panel(rgb, grid)
        def pdf_point(point):
            return [(point[0] + pix.x) / scale, (point[1] + pix.y) / scale]
        for row in result['lane_classification'].get('rows', []):
            row['lane_y_pdf'] = [(y + pix.y) / scale for y in row['lane_y']]
            row['tolerance_pdf'] = row['tolerance_pixels'] / scale
        for trace in result['traces']:
            trace['points_pdf'] = [pdf_point(p) for p in trace.pop('points_pixels')]
            for annotation in trace.get('connector_annotations', []):
                annotation['attachment_pdf'] = [pdf_point(p) for p in annotation.pop('attachment_pixels')]
                annotation['drawing_path_pdf'] = [pdf_point(p) for p in annotation.pop('drawing_path_pixels')]
            for domain in trace['domains']:
                domain['span_pdf'] = [pdf_point(p) for p in domain.pop('span_pixels')]
        for marker in result.get('offset_marker_annotations', {}).get('candidates', []):
            marker['center_pdf'] = pdf_point(marker.pop('center_pixels'))
            marker['bounds_pdf'] = [pdf_point(p) for p in marker.pop('bounds_pixels')]
        for candidate in result.get('partial_connectors', {}).get('candidates', []):
            candidate['span_pdf'] = [pdf_point(p) for p in candidate.pop('span_pixels')]
            candidate['contact_candidates_pdf'] = [[pdf_point(p) for p in values] for values in candidate.pop('contact_candidates_pixels')]
        for candidate in result.get('connector_search', {}).get('candidates', []):
            candidate['junctions_pdf'] = [pdf_point(p) for p in candidate.pop('junction_pixels')]
            for annotation in candidate['connector_annotations']:
                annotation['attachment_pdf'] = [pdf_point(p) for p in annotation.pop('attachment_pixels')]
                annotation['drawing_path_pdf'] = [pdf_point(p) for p in annotation.pop('drawing_path_pixels')]
        for crossing in result.get('resolved_crossings', []):
            crossing['point_pdf'] = pdf_point(crossing.pop('pixel'))
        results.append({'placement_index': index, 'xref': placement['xref'], 'bbox': list(box),
                        'pixels_per_pdf_point': scale, **result})
    return {'offset_marker_count': sum(len(p.get('offset_marker_annotations', {}).get('candidates', [])) for p in results),
            'connector_candidate_count': sum(len(p.get('connector_search', {}).get('candidates', [])) + len(p.get('partial_connectors', {}).get('candidates', [])) for p in results),
            'connector_drawing_count': sum(p.get('connector_drawing_count', 0) for p in results),
            'method': 'visible-classified-panel-traces-v2', 'panels': results, 'omitted': omitted,
            'native_routing_resolved': False}
