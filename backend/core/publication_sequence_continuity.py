"""Sequence-conditioned continuity across small raster gaps.

Image hypotheses never turn absence of ink into evidence of a nick. Exact
sequence support is conditional on the proposed image register; competing
registers and table identities remain explicit until calibrated independently.
"""
import math


def continuity_candidates(classified, anchors, rows, scaffold, *, maximum_gap_pixels=3,
                          maximum_candidates=500):
    if not 0 < maximum_gap_pixels <= 8 or not 1 <= maximum_candidates <= 5000:
        raise ValueError('Invalid continuity search bounds.')
    source = {r['id']: r['sequence'].upper() for r in rows}
    scaffold = scaffold.upper()
    complement = str.maketrans('ACGT', 'TGCA')
    verified = []
    for anchor in anchors.get('anchors', []):
        sequence = source.get(anchor['row_id'], '')
        start, length = anchor['oligo_start'], anchor['length']
        if not scaffold or start < 0 or start + length > len(sequence):
            continue
        expected = ''.join(scaffold[(anchor['scaffold_start'] - k) % len(scaffold)].translate(complement)
                           for k in range(length))
        if sequence[start:start + length] == expected and anchor['status'] == 'provisional_sequence_anchor':
            verified.append(anchor)
    candidates = []; truncated = False
    for panel in classified.get('panels', []):
        domains = [(t, d) for t in panel['traces'] if t['kind'] == 'staple' and t['color_continuity_supported']
                   for d in t['domains'] if d['kind'] == 'staple' and d['approximate_cells'] > 1]
        scale = panel.get('pixels_per_pdf_point')
        # Old evidence without its image scale cannot establish a pixel gap bound.
        if not scale:
            continue
        for index, (left_trace, left) in enumerate(domains):
            for right_trace, right in domains[index + 1:]:
                if left['observed_row_index'] != right['observed_row_index']:
                    continue
                a, b = sorted(((left_trace, left), (right_trace, right)), key=lambda v:v[1]['span_pdf'][0][0])
                lt, ld = a; rt, rd = b
                if lt['trace_id'] == rt['trace_id'] or not set(lt['hue_bins']) & set(rt['hue_bins']):
                    continue
                gap = (rd['span_pdf'][0][0] - ld['span_pdf'][1][0]) * scale
                dy = abs(rd['span_pdf'][0][1] - ld['span_pdf'][1][1]) * scale
                if not 0 < gap <= maximum_gap_pixels + 1 or dy > 1:
                    continue
                pitch = (ld['span_pdf'][1][0] - ld['span_pdf'][0][0]) / (ld['approximate_cells'] - 1)
                total = (rd['span_pdf'][1][0] - ld['span_pdf'][0][0]) / pitch + 1
                matches = []
                for anchor in verified:
                    # The exact core must cover both fragments, not just touch one side.
                    for direction in (-1, 1):
                        for offset in range(max(0, math.floor(total + 1 - anchor['length']) + 1)):
                            lo, hi = (offset, offset + anchor['length'] - 1) if direction == 1 else (total - offset - anchor['length'], total - 1 - offset)
                            if lo < ld['approximate_cells'] - 1 and hi > total - rd['approximate_cells']:
                                matches.append({'row_id':anchor['row_id'], 'oligo_start':anchor['oligo_start'],
                                                'scaffold_start':anchor['scaffold_start'], 'length':anchor['length'],
                                                'direction':direction, 'start_cell':offset})
                if not matches:
                    continue
                if len(candidates) >= maximum_candidates:
                    truncated = True
                    continue
                candidates.append({'placement_index':panel['placement_index'],
                                   'trace_ids':[lt['trace_id'], rt['trace_id']],
                                   'observed_row_index':ld['observed_row_index'],
                                   'span_pdf':[ld['span_pdf'][0], rd['span_pdf'][1]],
                                   'missing_ink_pixels':max(0, gap - 1), 'matches':matches,
                                   'status':'sequence_supported_conditional_continuity',
                                   'register_verified':False, 'connections_applied':False})
    # Check short endpoint-adjacent fragments too: they may be shorter than
    # the stable-core cutoff. Exact matches nominate table identities, not routes.
    connector_checks = []; checks_truncated = False
    rc = scaffold.translate(complement)[::-1]
    for panel in classified.get('panels', []):
        for connector in panel.get('partial_connectors', {}).get('candidates', []):
            hits = 0
            for trace in panel['traces']:
                if trace['kind'] != 'staple' or not trace['color_continuity_supported']:
                    continue
                for domain in trace['domains']:
                    if domain['kind'] != 'staple' or domain['observed_row_index'] != connector['observed_row_index']:
                        continue
                    x0, x1 = [p[0] for p in domain['span_pdf']]
                    pitch = (x1 - x0) / max(1, domain['approximate_cells'] - 1)
                    c0, c1 = [p[0] for p in connector['span_pdf']]
                    if max(x0 - c1, c0 - x1, 0) > 2 * pitch:
                        continue
                    length = max(6, math.floor(domain['approximate_cells']))
                    if length > domain['approximate_cells'] + 1 or not rc:
                        continue
                    circle = (rc * (2 + length // len(rc)))[:len(rc) + length - 1]
                    for row_id, sequence in source.items():
                        for start in range(len(sequence) - length + 1):
                            core = sequence[start:start + length]
                            site = circle.find(core)
                            while 0 <= site < len(rc):
                                if hits >= 32:
                                    checks_truncated = True
                                    break
                                connector_checks.append({'placement_index':panel['placement_index'],
                                    'connector_id':connector['candidate_id'], 'trace_id':trace['trace_id'],
                                    'span_pdf':domain['span_pdf'], 'row_id':row_id, 'oligo_start':start,
                                    'scaffold_start':(len(rc)-1-site) % len(rc), 'length':length,
                                    'directions':[-1,1], 'sequence_complement_verified':True,
                                    'image_identity_verified':False,
                                    'status':'endpoint_supported_sequence_candidate'})
                                hits += 1
                                site = circle.find(core, site + 1)
    return {'candidates':candidates, 'connector_sequence_checks':connector_checks,
            'connector_checks_truncated':checks_truncated,
            'truncated':truncated,
            'maximum_gap_pixels':maximum_gap_pixels, 'native_routing_resolved':False,
            'limitation':'Exact table/scaffold cores support continuity conditional on each listed image register. '
                         'Small raster gaps are not strand breaks. Competing identities and directions remain unresolved.'}
