"""Calibrate independently placed vector routing panels from visible labels.

Panel identity comes from the repeated row-label columns. The source drawing
object remains the unit of connectivity, including curves crossing between
panels. No reference routing or table endpoints are used in calibration.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from statistics import median

from backend.core.publication_diagram_labels import numeric_labels
from backend.core.publication_reconstruction_report import ReconstructionBlocked


@dataclass(frozen=True)
class VectorPanel:
    direction: tuple[int, int]
    left: float
    right: float
    rows: dict[int, float]
    scale: float
    origins: tuple[float, ...]
    row_pitch: float

    def project(self, point):
        return project(point.x, point.y, self.direction)


def project(x, y, direction):
    dx, dy = direction
    return x * dx + y * dy, y * dx - x * dy


def calibrate_panels(page):
    by_direction = defaultdict(list)
    for label in numeric_labels(page):
        u, v = project(label['x'], label['y'], label['direction'])
        by_direction[label['direction']].append((u, v, label['value']))
    panels = []
    for direction, observations in by_direction.items():
        columns = defaultdict(set)
        for u, v, value in observations:
            columns[round(u, 1)].add((round(v, 1), value))
        by_signature = defaultdict(list)
        for u, entries in columns.items():
            if len(entries) < 4 or len({value for _, value in entries}) != len(entries):
                continue
            sorted_entries = sorted(entries)
            steps = [b[0] - a[0] for a, b in zip(sorted_entries, sorted_entries[1:])]
            pitch = median(steps)
            if pitch <= 0 or any(abs(step - pitch) > .025 * pitch for step in steps):
                continue
            by_signature[tuple(sorted_entries)].append(u)

        for entries, boundaries in by_signature.items():
            if len(boundaries) != 2:
                continue
            left, right = sorted(boundaries)
            pitch = median(b[0] - a[0] for a, b in zip(entries, entries[1:]))
            # At least four ruler labels must agree on the base scale and origin.
            rulers = defaultdict(set)
            for u, v, value in observations:
                if left < u < right and (
                    entries[0][0] - 2.5 * pitch < v < entries[0][0] - .3 * pitch or
                    entries[-1][0] + .3 * pitch < v < entries[-1][0] + 2.5 * pitch
                ):
                    rulers[round(v, 1)].add((u, value))
            fits = Counter()
            for points in rulers.values():
                points = sorted(points)
                for index, (u, value) in enumerate(points):
                    for end, end_value in points[index + 1:]:
                        if end_value <= value:
                            continue
                        scale = round((end - u) / (end_value - value), 3)
                        if scale <= 0:
                            continue
                        origin = round(u - scale * value, 1)
                        fits[scale, origin] += 1
            if not fits:
                continue
            (scale, origin), count = fits.most_common(1)[0]
            if count < 6:
                continue
            # The figure sometimes repeats the ruler at a shifted position.
            # Retain both origins for independent endpoint-table scoring.
            origins = tuple(sorted({org for (s, org), occurrences in fits.items()
                                    if s == scale and occurrences >= max(6, count / 4)}))
            panels.append(VectorPanel(direction, left, right, {i: v for v, i in entries},
                                      scale, origins or (origin,), pitch))
    return panels


def extract_panel_hypotheses(page, panels, *, maximum_hypotheses=32):
    """Return alternate ruler calibrations and extracted walks for each panel set."""
    from itertools import combinations, product
    from math import floor, prod

    if len(panels) > 8:
        raise ReconstructionBlocked('image_search_limited', 'Panel count exceeds calibration hypothesis budget.')
    compatible_sets = [
        group for size in range(1, len(panels) + 1)
        for group in combinations(panels, size)
        if len(set().union(*(panel.rows for panel in group))) == sum(len(panel.rows) for panel in group)
    ]
    maximal = [group for group in compatible_sets if not any(
        len(other) > len(group) and all(panel in other for panel in group) for other in compatible_sets)]
    if sum(prod(len(p.origins) for p in group) for group in maximal) > maximum_hypotheses:
        raise ReconstructionBlocked('image_search_limited', 'Panel calibration hypothesis budget exceeded.')
    drawings = page.get_drawings()
    for group in maximal:
        for origins in product(*(panel.origins for panel in group)):
            def address(point):
                sites = []
                for panel, origin in zip(group, origins):
                    u, v = panel.project(point)
                    if not max(panel.left, origin - panel.scale * .15) <= u < panel.right:
                        continue
                    helix = min(panel.rows, key=lambda row: abs(v - panel.rows[row]))
                    if abs(v - panel.rows[helix]) > panel.row_pitch * .25:
                        continue
                    sites.append((helix, floor((u - origin) / panel.scale + .02)))
                return sites[0] if len(sites) == 1 and sites[0][1] >= 0 else None

            paths = []
            indels = set()
            rejected = []
            for path_id, drawing in enumerate(drawings):
                items = drawing['items']
                if drawing['color'] is None or drawing.get('fill') is not None:
                    continue
                if len(items) == 2 and all(i[0] == 'c' for i in items):
                    rect = drawing['rect']
                    if abs(items[0][1] - items[-1][-1]) <= .01 and any(
                        .5 * p.scale < rect.width < 2.5 * p.scale and .5 * p.scale < rect.height < 2.5 * p.scale
                        for p in group
                    ):
                        site = address(items[0][1])
                        if site:
                            indels.add(site)
                if not all(i[0] in ('l', 'c') for i in items):
                    continue
                endpoints = [(address(i[1]), address(i[-1])) for i in items]
                if not any(i[0] == 'l' and u and v and u[0] == v[0] and abs(u[1] - v[1]) > 2
                           for i, (u, v) in zip(items, endpoints)):
                    continue
                walk = []
                previous = None
                for item, (u, v) in zip(items, endpoints):
                    if u is None or v is None or (previous is not None and abs(previous - item[1]) > .1):
                        break
                    previous = item[-1]
                    if item[0] == 'l' and u[0] == v[0]:
                        step = 1 if u[1] <= v[1] else -1
                        segment = [(u[0], bp) for bp in range(u[1], v[1] + step, step)]
                    else:
                        segment = [u, v]
                    walk.extend(segment[1:] if walk and walk[-1] == segment[0] else segment)
                else:
                    if len(set(walk)) == len(walk):
                        paths.append({'path_id': path_id, 'sites': walk, 'color': drawing['color']})
                        continue
                rejected.append(path_id)
            yield {'paths': paths, 'insertion_annotations': sorted(indels),
                   'panels': [{'direction': p.direction, 'left': p.left, 'right': p.right,
                               'helix_labels': list(p.rows), 'origin': origin, 'scale': p.scale}
                              for p, origin in zip(group, origins)],
                   'rejected_path_ids': rejected}


def reconcile_panel_registers(graph, table):
    """Use pairs wholly within a panel to test local integer translations."""
    by_helices = defaultdict(list)
    for row in table['rows']:
        start, end = tuple(row['start']), tuple(row['end'])
        by_helices[start[0], end[0]].append((start[1], end[1]))
        if start != end:
            by_helices[end[0], start[0]].append((end[1], start[1]))

    shifts = {}
    evidence = []
    for panel in graph['panels']:
        own = set(panel['helix_labels'])
        votes = Counter()
        for path in graph['paths']:
            (h, bp), (other, other_bp) = path['sites'][0], path['sites'][-1]
            if h not in own or other not in own:
                continue
            votes.update({start - bp for start, end in by_helices[h, other]
                          if start - bp == end - other_bp and abs(start - bp) <= 32})
        ordered = votes.most_common()
        unique = bool(ordered and ordered[0][1] >= 3 and (
            len(ordered) == 1 or ordered[0][1] > ordered[1][1]))
        shift = ordered[0][0] if unique else 0
        shifts.update(dict.fromkeys(own, shift))
        evidence.append({'shift': shift, 'resolved': unique, 'endpoint_votes': ordered[:8]})
    def registered(site):
        helix, bp = site
        return helix, bp + shifts[helix]
    return {**graph, 'paths': [{**p, 'sites': [registered(s) for s in p['sites']]} for p in graph['paths']],
            'insertion_annotations': [registered(s) for s in graph['insertion_annotations']],
            'panel_registers': evidence}


def select_panel_graph(page, table):
    """Select a unique routed graph using endpoint/length evidence from the target table."""
    from backend.core.publication_routing import pair_endpoint_table, recover_lattice

    panels = calibrate_panels(page)
    candidates = []
    for graph in extract_panel_hypotheses(page, panels):
        graph = reconcile_panel_registers(graph, table)
        pairing = pair_endpoint_table(graph, table)
        matches = pairing['matched']
        if len(matches) < 3 or any(bp < 0 for path in graph['paths'] for _, bp in path['sites']):
            continue
        if len({tuple(path['table_row']['start']) for path in matches}) != len(matches):
            continue
        score = (len(matches), sum(p['length_with_unit_insertions_agrees'] or p['length_agrees']
                                  for p in matches), -len(graph['rejected_path_ids']))
        candidates.append((score, graph))
    if not candidates:
        return None
    best_score = max(score for score, _ in candidates)
    best = [graph for score, graph in candidates if score == best_score]
    signatures = {
        (tuple(tuple(path['sites']) for path in graph['paths']), tuple(graph['insertion_annotations']))
        for graph in best
    }
    if len(signatures) != 1:
        raise ReconstructionBlocked('base_register_unresolved', 'Equally supported panel registers give different routes.')
    graph = best[0]
    row_centers = {}
    for index, panel in enumerate(graph['panels']):
        row_centers.update({helix: index * 10000 + position
                            for position, helix in enumerate(panel['helix_labels'])})
    graph['calibration'] = {'row_centers': row_centers}
    graph['lattice'] = recover_lattice(page, numeric_labels(page), row_centers, selected_panel=True)
    # The contiguous-path compiler also accepts optional image-base evidence.
    # Panel-local base-glyph decoding needs its own calibrated transform.
    graph['base_labels'] = []
    graph['panel_selection'] = {'matching_rows': best_score[0],
                                'candidate_count': len(candidates),
                                'equivalent_best_count': len(best)}
    return graph
