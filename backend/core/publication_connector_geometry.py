"""Recognize drawn same-lane detours without assigning nucleotide length.

The user identifies these as same-helix forced-ligation drawing conventions.
Recognition records image evidence; it does not author a native forced ligation.
"""
from collections import Counter

import numpy as np
from skimage.draw import line

from backend.core.publication_lane_classification import classify_point


def dense_path(points):
    result = []
    for a, b in zip(points, points[1:]):
        first, last = sorted((tuple(a),tuple(b)))
        yy, xx = line(round(first[1]), round(first[0]), round(last[1]), round(last[0]))
        values = list(zip(xx.tolist(), yy.tolist()))
        if tuple(a)!=first:values.reverse()
        result.extend(values if not result else values[1:])
    return result


def recognize_offset_connectors(points, lanes, pitch, *, maximum_excursion=None):
    """Require continuous on-lane anchors on both sides of a visible detour.

    No proximity joining or gap filling. A sustained visit to a different lane
    is not a same-lane connector. Unknown rows cannot supply attachment anchors.
    """
    if pitch <= 0:
        raise ValueError('Grid pitch must be positive.')
    pixels = dense_path(points)
    if not pixels:
        return {'annotations': [], 'domain_paths': [], 'status': 'empty_path'}
    assignments = [classify_point(y, lanes) for _, y in pixels]
    runs = []
    start = 0
    for stop in range(1, len(pixels) + 1):
        if stop == len(pixels) or assignments[stop] != assignments[start]:
            kind, row, side = assignments[start]
            xs = [p[0] for p in pixels[start:stop]]
            if kind == 'staple' and max(xs) - min(xs) >= 2 * pitch:
                runs.append((start, stop - 1, row, side))
            start = stop
    # A ligation drawing can attach directly to two endpoint markers without
    # appreciable on-lane strand on either side. Retain those contacts as weaker
    # evidence, rather than requiring two full flanking domains.
    for index in (0,len(pixels)-1):
        kind,row,side=assignments[index]
        if kind=='staple' and not any(a<=index<=b for a,b,_,_ in runs):
            runs.append((index,index,row,side))
    runs.sort()
    annotations = []
    rejected_counts = Counter()
    by_row = {r['observed_row_index']: r for r in lanes.get('rows', [])}
    for left, right in zip(runs, runs[1:]):
        begin, end = left[1], right[0]
        if left[2:] != right[2:] or end - begin < 3:
            rejected_counts['different_lane_or_no_excursion']+=1
            continue
        row, side = left[2:]
        lane = by_row[row]
        y = lane['lane_y'][side]
        path = pixels[begin:end + 1]
        excursion = max(abs(p[1] - y) for p in path)
        limit = maximum_excursion if maximum_excursion is not None else 2.5 * pitch
        if not pitch * .4 <= excursion <= limit:
            rejected_counts['offset_outside_bounds']+=1
            continue
        if abs(path[-1][0] - path[0][0]) < 2 * pitch or np.ptp([p[0] for p in path]) > pitch * 128:
            rejected_counts['attachment_span_outside_bounds']+=1
            continue
        # A connector may cross another lane at a point, but must not run along
        # that lane. Sustained different-lane occupancy is a different topology.
        foreign_run = 0
        rejected = False
        for kind, other_row, other_side in assignments[begin:end + 1]:
            foreign = kind in ('staple', 'scaffold') and (other_row, other_side) != (row, side)
            foreign_run = foreign_run + 1 if foreign else 0
            if foreign_run > pitch:
                rejected = True
                break
        if rejected:
            rejected_counts['runs_along_another_lane']+=1
            continue
        # Require an extended displaced run, rather than an arrowhead/endpoint
        # marker making a tiny triangular excursion around the lane.
        displaced = [(x, yy) for x, yy in path if abs(yy-y) >= pitch*.4]
        plateau = max((max(x for x,yy in displaced if abs(yy-level)<=pitch*.2) -
                       min(x for x,yy in displaced if abs(yy-level)<=pitch*.2)
                       for level in {yy for _,yy in displaced}), default=0)
        if plateau < 2*pitch:
            rejected_counts['no_extended_offset_run']+=1
            continue
        annotations.append({'kind': 'same_helix_offset_connector',
                            'observed_row_index': row, 'lane_side': side,
                            'attachment_pixels': [list(path[0]), list(path[-1])],
                            'drawing_path_pixels': [list(p) for p in path],
                            'maximum_offset_pixels': float(excursion),
                            'dense_path_interval': [begin, end],
                            'interpretation': 'same_helix_ligation_drawing_candidate',
                            'attachment_evidence': 'flanking_lane_segments' if left[1]>left[0] and right[1]>right[0] else 'terminal_lane_contacts',
                            'base_count_from_drawing': None,
                            'exclude_drawing_from_domain_lengths': True,
                            'native_connection_type': 'unassigned', 'native_routing_resolved': False})
    pieces = []
    start = 0
    for item in annotations:
        begin, end = item['dense_path_interval']
        pieces.append(pixels[start:begin + 1]); start = end
    pieces.append(pixels[start:])
    return {'annotations': annotations, 'domain_paths': pieces, 'rejection_counts':dict(rejected_counts),
            'attachment_runs':len(runs),
            'status': 'connector_drawings_observed' if annotations else 'no_supported_connector',
            'limitation': 'Same-lane drawing geometry only; scaffold pairing, inserted sequence, native endpoint identities and physical ligation remain unverified.'}
