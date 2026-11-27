"""Classify observed caDNAno lanes from paired rows and recurring color/phase.

No helix numbers, strand polarity, native geometry, or fixed scaffold hue are
assumed. Unsupported or contradictory rows remain unknown.
"""
import colorsys

import numpy as np
from scipy.ndimage import binary_opening
from scipy.signal import find_peaks


def chromatic_labels(rgb):
    rgb = np.asarray(rgb)
    low = rgb.min(axis=2)
    contrast = rgb.max(axis=2).astype(float) - low
    mask = (contrast > 55) & (low < 200)
    palette = np.array([colorsys.hsv_to_rgb(i / 12, 1, 1) for i in range(12)])
    normalized = (rgb.astype(float) - low[:, :, None]) / np.maximum(1, contrast)[:, :, None]
    labels = np.full(mask.shape, -1, dtype=np.int8)
    labels[mask] = np.argmin(((normalized[mask, None, :] - palette[None, :, :]) ** 2).sum(axis=2), axis=1)
    return labels


def trace_ink_labels(rgb):
    """Include dark neutral ink only when it separates from sampled empty grid."""
    labels = chromatic_labels(rgb)
    high = rgb.max(axis=2)
    neutral = high.astype(float)-rgb.min(axis=2) < 25
    width = rgb.shape[1]
    patch = slice(round(width*.09), round(width*.25))
    values = high[:,patch][neutral[:,patch]]
    threshold = min(170., float(np.percentile(values,1))-40) if len(values) else 0.
    if threshold >= 60:
        labels[neutral & (high < threshold)] = 12  # neutral ink; never an inferred hue
    return labels, {'neutral_ink_threshold':threshold if threshold >= 60 else None,
                    'method':'dark-ink-versus-empty-grid',
                    'limitation':'Neutral ink may include text or markers; lane and connector evidence are still required.'}


def classify_lanes(rgb, grid):
    """Infer recurring scaffold lane phase, then require local corroboration.

    All thresholds are image-screening heuristics, not probabilities. Both lanes
    may share a color; a supported panel phase distinguishes them. A missing
    recurring color or a local contradiction leaves that row unclassified.
    """
    labels, ink = trace_ink_labels(rgb)
    mask = labels >= 0
    mask[:, :round(labels.shape[1] * .08)] = False
    pitch, row_pitch = grid['grid_pitch'], grid['row_pitch']
    rows = grid['row_centers']
    if pitch < 2 or row_pitch < 8 or len(rows) < 4:
        return {'status': 'insufficient_lane_resolution', 'rows': [], 'native_routing_resolved': False}
    horizontal = binary_opening(mask, structure=np.ones((1, max(3, round(pitch * 3)))))
    radius = round(row_pitch * .3)
    profile = np.zeros(2 * radius + 1)
    for center in rows:
        for offset in range(-radius, radius + 1):
            y = round(center + offset)
            if 0 <= y < len(mask):
                profile[offset + radius] += horizontal[y].sum()
    peaks, _ = find_peaks(profile, distance=max(2, round(pitch * .5)))
    pair = sorted(sorted(peaks, key=lambda p: -profile[p])[:2])
    if len(pair) != 2 or pair[1] - pair[0] < pitch * .5:
        return {'status': 'paired_lanes_not_detected', 'rows': [], 'native_routing_resolved': False}
    offsets = [int(p - radius) for p in pair]
    evidence, centers = [], []
    for center in rows:
        lane_counts, lane_centers = [], []
        for offset in offsets:
            nominal = round(center + offset)
            neighborhood = range(max(0, nominal - round(pitch * .3)), min(len(mask), nominal + round(pitch * .3) + 1))
            if not neighborhood:
                lane_centers.append(float(nominal)); lane_counts.append([0] * 13)
                continue
            y = max(neighborhood, key=lambda k: horizontal[k].sum())
            lane_centers.append(float(y))
            ys = slice(max(0, y - 1), min(len(mask), y + 2))
            lane_counts.append([int(np.any((labels[ys] == hue) & horizontal[ys], axis=0).sum()) for hue in range(13)])
        evidence.append(lane_counts); centers.append(lane_centers)
    evidence = np.asarray(evidence)
    totals = evidence.sum(axis=2)
    hypotheses = []
    for hue in range(13):
        fractions = evidence[:, :, hue] / np.maximum(1, totals)
        side = np.argmax(fractions, axis=1)
        reliable = (fractions.max(axis=1) >= .5) & (np.abs(fractions[:, 0] - fractions[:, 1]) >= .25)
        recurrence = float(np.mean(fractions.max(axis=1) >= .5))
        count = int(reliable.sum())
        if count < max(4, len(rows) * .35) or recurrence < .65:
            continue
        votes = [float(np.mean(side[reliable] == ((np.arange(len(rows)) + phase) % 2)[reliable])) for phase in (0, 1)]
        phase = int(np.argmax(votes))
        if votes[phase] >= .8:
            hypotheses.append({'hue_bin': hue, 'phase': phase, 'phase_support': votes[phase],
                               'recurrence': recurrence, 'distinct_sided_rows': count})
    hypotheses.sort(key=lambda h: (-h['distinct_sided_rows'], -h['phase_support'], h['hue_bin']))
    if not hypotheses or (len(hypotheses) > 1 and hypotheses[1]['distinct_sided_rows'] >= hypotheses[0]['distinct_sided_rows'] * .85):
        return {'status': 'scaffold_lane_pattern_ambiguous', 'rows': [], 'hypotheses': hypotheses,
                'native_routing_resolved': False}
    best = hypotheses[0]
    result = []
    for i, ys in enumerate(centers):
        scaffold_side = (i + best['phase']) % 2
        fraction = evidence[i, scaffold_side, best['hue_bin']] / max(1, totals[i, scaffold_side])
        opposite_fraction = evidence[i, 1 - scaffold_side, best['hue_bin']] / max(1, totals[i, 1 - scaffold_side])
        contradicted = opposite_fraction >= .5 and opposite_fraction - fraction >= .25
        supported = fraction >= .4 and totals[i, scaffold_side] >= pitch * 3 and not contradicted
        separation = abs(ys[1] - ys[0])
        supported &= separation >= pitch * .5
        result.append({'observed_row_index': i, 'lane_y': ys,
                       'scaffold_side': scaffold_side if supported else None,
                       'staple_side': 1 - scaffold_side if supported else None,
                       'scaffold_color_fraction': float(fraction), 'local_phase_contradiction': bool(contradicted),
                       'status': 'color_and_panel_phase_supported' if supported else 'unclassified_local_evidence',
                       'tolerance_pixels': min(pitch * .3, separation * .4)})
    return {'method': 'paired-lane-color-phase-v1', 'status': 'panel_pattern_supported',
            'scaffold_hypothesis': best, 'hypotheses': hypotheses, 'rows': result,
            'lane_offsets': offsets, 'ink_classification': ink, 'native_routing_resolved': False,
            'limitation': 'Panel layout and color evidence classify observed lanes only. Helix labels, strand polarity, absolute base register and molecular connectivity remain unverified.'}


def classify_point(y, lanes):
    candidates = []
    for row in lanes.get('rows', []):
        for side, lane_y in enumerate(row['lane_y']):
            distance = abs(y - lane_y)
            if distance <= row['tolerance_pixels']:
                kind = 'unclassified' if row['scaffold_side'] is None else 'scaffold' if side == row['scaffold_side'] else 'staple'
                candidates.append((distance, kind, row['observed_row_index'], side))
    if not candidates:
        return 'unclassified', None, None
    candidates.sort()
    _, kind, row, side = candidates[0]
    return kind, row, side
