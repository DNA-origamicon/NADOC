"""Match sequence cores only to classified staple domains in connected traces.

Length is a necessary screen, never a strand assignment. Missing classification
must not fall back to unclassified colored strokes (including scaffold paths).
"""
import math


def image_span_candidates(raster, anchor_report, *, maximum_spans=3000, maximum_matches=24):
    if not 1 <= maximum_spans <= 10000 or not 1 <= maximum_matches <= 100:
        raise ValueError('Image matching bounds exceeded.')
    classified = raster.get('classified_tracing', {})
    spans = []
    truncated = False
    excluded_scaffold = excluded_mixed = excluded_unknown = 0
    for panel in classified.get('panels', []):
        truncated |= panel.get('truncated', False)
        for trace in panel['traces']:
            if trace['kind'] == 'scaffold':
                excluded_scaffold += len(trace['domains'])
            if trace['kind'] == 'mixed':
                excluded_mixed += 1
            if trace['kind'] != 'staple' or not trace['color_continuity_supported']:
                excluded_unknown += int(trace['kind'] == 'unclassified' or not trace['color_continuity_supported'])
                continue
            for domain_index, domain in enumerate(trace['domains']):
                if domain['kind'] != 'staple' or domain['approximate_cells'] < anchor_report.get('minimum_length', 12):
                    continue
                if len(spans) >= maximum_spans:
                    truncated = True
                    continue
                spans.append({'placement_index': panel['placement_index'], 'xref': panel['xref'],
                              'observed_row_index': domain['observed_row_index'], 'trace_id': trace['trace_id'],
                              'domain_index': domain_index, 'hue_bins': trace['hue_bins'],
                              'span_pdf': domain['span_pdf'], 'approximate_cells': domain['approximate_cells'],
                              'classification': 'staple', 'trace_status': trace['status'],
                              'trace_domain_count': len(trace['domains']),
                              'connector_annotation_count': len(trace.get('connector_annotations',[])),
                              'partial_connector_ids': [c['candidate_id'] for c in panel.get('partial_connectors',{}).get('candidates',[])
                                  if c['observed_row_index'] == domain['observed_row_index']
                                  and c['span_pdf'][0][0] <= domain['span_pdf'][1][0]
                                  and c['span_pdf'][1][0] >= domain['span_pdf'][0][0]],
                              'connector_candidate_ids': [c['candidate_id'] for c in panel.get('connector_search',{}).get('candidates',[])
                                  if set(c['anchor_edge_ids']) & set(trace.get('source_edge_ids',[]))],
                              'endpoint_identity': 'unverified', 'native_routing_resolved': False})
    results = []
    for anchor in anchor_report.get('anchors', []):
        if anchor['status'] != 'provisional_sequence_anchor':
            continue
        matches = [{'span_index': i,
                    'possible_start_cells': max(1, math.floor(s['approximate_cells'] + 1 - anchor['length']) + 1),
                    'directions': [-1, 1]}
                   for i, s in enumerate(spans) if s['approximate_cells'] + 1 >= anchor['length']]
        results.append({'row_id': anchor['row_id'], 'oligo_start': anchor['oligo_start'],
                        'length': anchor['length'], 'candidate_span_count': len(matches),
                        'candidates': matches[:maximum_matches], 'matches_truncated': len(matches) > maximum_matches,
                        'status': 'classified_staple_length_only' if matches else 'no_resolved_staple_span'})
    return {'method': 'classified-staple-core-screen-v2', 'spans': spans, 'anchors': results,
            'offset_marker_count': classified.get('offset_marker_count',0),
            'connector_drawing_count': classified.get('connector_drawing_count',0),
            'connector_candidate_count': classified.get('connector_candidate_count',0),
            'classification_available': bool(classified.get('panels')),
            'excluded_scaffold_domains': excluded_scaffold, 'excluded_mixed_traces': excluded_mixed,
            'excluded_unclassified_or_color_uncertain_traces': excluded_unknown,
            'spans_truncated': truncated, 'native_routing_resolved': False,
            'limitation': 'Only classified staple domains with continuous-color evidence are screened. Length-compatible traces are not table-strand identities; endpoints, absolute base register, polarity and unresolved crossings still prevent native placement.'}
