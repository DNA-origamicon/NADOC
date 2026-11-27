"""Bounded same-lane connector hypotheses through unresolved pixel junctions.

Candidates never silently merge graph branches. Every traversed branch and
alternative remains evidence for later sequence/endpoint resolution.
"""
from collections import Counter, defaultdict

from backend.core.publication_connector_geometry import recognize_offset_connectors
from backend.core.publication_lane_classification import classify_point


def search_connector_drawings(edges, incident, lanes, pitch, *, maximum_states=12000,
                              maximum_candidates=100, maximum_edges=40):
    if not 1 <= maximum_states <= 50000 or not 1 <= maximum_candidates <= 500 or not 2 <= maximum_edges <= 50:
        raise ValueError('Connector search bounds exceeded.')
    anchors = defaultdict(list)
    for edge_id, edge in enumerate(edges):
        if edge['color_coherence'] < .8 or 'scaffold' in edge['roles']:
            continue
        for domain in edge.get('domains', []):
            if domain['kind'] == 'staple':
                key = (domain['observed_row_index'], domain['lane_side'], edge['hue_bin'])
                anchors[key].append(edge_id)
        for point in (edge['points'][0],edge['points'][-1]):
            kind,row,side=classify_point(point[1],lanes)
            if kind=='staple':
                key=(row,side,edge['hue_bin'])
                if edge_id not in anchors[key]:anchors[key].append(edge_id)
    rows = {r['observed_row_index']: r for r in lanes.get('rows', [])}
    candidates, seen, expanded = [], set(), 0
    screens=Counter(); return_paths=0
    budget_exhausted = False
    for (row, side, hue), seeds in sorted(anchors.items()):
        if budget_exhausted:
            break
        y = rows[row]['lane_y'][side]
        def color_compatible(value):
            return value == hue or (value is not None and value < 12 and hue < 12 and min((value-hue)%12,(hue-value)%12)<=1)
        def short_marker(edge):
            return sum(max(abs(b[0]-a[0]),abs(b[1]-a[1])) for a,b in zip(edge['points'],edge['points'][1:])) <= 2*pitch
        eligible = {i for i, edge in enumerate(edges) if ((color_compatible(edge['hue_bin']) and edge['color_coherence'] >= .8) or short_marker(edge))
                    and 'scaffold' not in edge['roles']
                    and all(abs(p[1] - y) <= 2.5 * pitch for p in edge['points'])}
        seed_set = set(seeds) & eligible
        if len(seed_set) < 2:
            continue
        for seed in sorted(seed_set):
            if budget_exhausted:
                break
            for end_side in (0, 1):
                initial = edges[seed]['points'] if end_side == 1 else edges[seed]['points'][::-1]
                stack = [(tuple(initial[-1]), [seed], initial)]
                while stack:
                    if expanded >= maximum_states or len(candidates) >= maximum_candidates:
                        budget_exhausted = True
                        break
                    node, path_ids, points = stack.pop(); expanded += 1
                    if len(path_ids) >= maximum_edges:
                        continue
                    for edge_id, side_in in incident[node]:
                        if edge_id not in eligible or edge_id in path_ids:
                            continue
                        values = edges[edge_id]['points'] if side_in == 0 else edges[edge_id]['points'][::-1]
                        joined = points + values[1:]
                        ids = path_ids + [edge_id]
                        if edge_id in seed_set:
                            identity = min(tuple(ids), tuple(ids[::-1]))
                            if identity not in seen:
                                seen.add(identity)
                                drawing = recognize_offset_connectors(joined, lanes, pitch)
                                return_paths+=1; screens.update(drawing.get('rejection_counts',{}))
                                if drawing['annotations']:
                                    branches = sorted({tuple(p) for p in joined if len(incident.get(tuple(p), [])) > 2})
                                    candidates.append({'candidate_id': len(candidates), 'source_edge_ids': ids,
                                                       'anchor_edge_ids': [seed, edge_id],
                                                       'observed_row_index': row, 'lane_side': side, 'hue_bin': hue,
                                                       'observed_hue_bins': sorted({edges[i]['hue_bin'] for i in ids}),
                                                       'color_status': 'marker_or_color_transition_unresolved' if any(not color_compatible(edges[i]['hue_bin']) or edges[i]['color_coherence']<.8 for i in ids) else 'adjacent_hue_transition_unresolved' if len({edges[i]['hue_bin'] for i in ids})>1 else 'single_hue',
                                                       'connector_annotations': drawing['annotations'],
                                                       'junction_pixels': [list(p) for p in branches],
                                                       'status': 'unresolved_branch_hypothesis' if branches else 'continuous_connector_hypothesis',
                                                       'native_routing_resolved': False})
                        # A short on-lane fragment is not necessarily the end of
                        # the connector; keep traversing within the explicit bound.
                        stack.append((tuple(values[-1]), ids, joined))
    unique = {}
    for candidate in candidates:
        y = rows[candidate['observed_row_index']]['lane_y'][candidate['lane_side']]
        cores=[]
        for a in candidate['connector_annotations']:
            points=tuple(tuple(p) for p in a['drawing_path_pixels'] if abs(p[1]-y)>pitch*.4)
            cores.append(min(points,points[::-1]))
        key=(candidate['observed_row_index'],candidate['lane_side'],tuple(sorted(cores)))
        if key in unique:
            unique[key]['supporting_edge_paths'].append(candidate['source_edge_ids'])
        else:
            candidate['supporting_edge_paths']=[candidate['source_edge_ids']]
            unique[key]=candidate
    candidates=list(unique.values())
    for i,candidate in enumerate(candidates):candidate['candidate_id']=i
    by_anchors = defaultdict(list)
    for candidate in candidates:
        by_anchors[tuple(sorted(tuple(round(v/pitch) for v in p) for p in candidate['connector_annotations'][0]['attachment_pixels']))].append(candidate['candidate_id'])
    for candidate in candidates:
        candidate['alternative_candidate_ids'] = [i for i in by_anchors[tuple(sorted(tuple(round(v/pitch) for v in p) for p in candidate['connector_annotations'][0]['attachment_pixels']))] if i != candidate['candidate_id']]
    return {'method': 'bounded-same-lane-pixel-graph-search-v1', 'candidates': candidates,
            'return_paths_screened':return_paths, 'geometry_rejections':dict(screens),
            'states_expanded': expanded, 'budget_exhausted': budget_exhausted,
            'maximum_states': maximum_states, 'maximum_candidates': maximum_candidates, 'maximum_edges': maximum_edges,
            'native_routing_resolved': False,
            'limitation': 'Connector shape hypotheses through observed pixels. Branches remain unresolved and are not merged into staple routing; endpoint markers and sequence must resolve alternatives.'}
