from backend.core.publication_connector_geometry import recognize_offset_connectors


def lanes():
    return {'rows':[{'observed_row_index':0,'lane_y':[17,23],'scaffold_side':0,'staple_side':1,'tolerance_pixels':1.2},
                    {'observed_row_index':1,'lane_y':[41,47],'scaffold_side':1,'staple_side':0,'tolerance_pixels':1.2}]}


def test_same_lane_detour_is_annotated_and_not_counted_as_domain_length():
    result=recognize_offset_connectors([(20,23),(40,23),(44,29),(70,29),(74,23),(100,23)],lanes(),4)
    assert len(result['annotations'])==1
    annotation=result['annotations'][0]
    assert annotation['kind']=='same_helix_offset_connector'
    assert annotation['base_count_from_drawing'] is None
    assert annotation['exclude_drawing_from_domain_lengths']
    assert not annotation['native_routing_resolved']
    assert len(result['domain_paths'])==2
    assert all(not any(y==29 for x,y in path) for path in result['domain_paths'])


def test_different_lane_and_dangling_excursions_are_not_same_helix_connectors():
    assert not recognize_offset_connectors([(20,23),(40,23),(44,35),(70,41),(100,41)],lanes(),4)['annotations']
    assert not recognize_offset_connectors([(20,23),(40,23),(44,29),(70,29)],lanes(),4)['annotations']


def test_scaffold_lane_visit_is_not_reclassified_as_connector():
    assert not recognize_offset_connectors([(20,23),(40,23),(44,17),(70,17),(74,23),(100,23)],lanes(),4)['annotations']


def test_reversed_trace_keeps_same_connector_endpoints():
    points=[(20,23),(40,23),(44,29),(70,29),(74,23),(100,23)]
    forward=recognize_offset_connectors(points,lanes(),4)['annotations'][0]
    reverse=recognize_offset_connectors(points[::-1],lanes(),4)['annotations'][0]
    assert forward['attachment_pixels']==reverse['attachment_pixels'][::-1]


def test_small_terminal_marker_is_not_a_ligation_connector():
    points=[(20,23),(40,23),(43,27),(46,23),(60,23)]
    assert not recognize_offset_connectors(points,lanes(),4)['annotations']


def test_branch_search_retains_alternative_drawings_without_merging():
    from collections import defaultdict
    from backend.core.publication_connector_search import search_connector_drawings
    anchors={'kind':'staple','observed_row_index':0,'lane_side':1}
    paths=[[(20,23),(40,23)],[(40,23),(44,29),(70,29),(74,23)],
           [(74,23),(100,23)],[(40,23),(44,31),(70,31),(74,23)]]
    edges=[{'points':p,'hue_bin':4,'color_coherence':1.,'roles':{'staple'} if i in (0,2) else set(),
            'domains':[anchors] if i in (0,2) else []} for i,p in enumerate(paths)]
    incident=defaultdict(list)
    for i,path in enumerate(paths):
        incident[tuple(path[0])].append((i,0));incident[tuple(path[-1])].append((i,1))
    report=search_connector_drawings(edges,incident,lanes(),4)
    assert len(report['candidates'])==2
    assert all(c['status']=='unresolved_branch_hypothesis' for c in report['candidates'])
    assert all(len(c['alternative_candidate_ids'])==1 for c in report['candidates'])
    assert all(not c['native_routing_resolved'] for c in report['candidates'])
    bounded=search_connector_drawings(edges,incident,lanes(),4,maximum_states=1)
    assert bounded['budget_exhausted']


def test_marker_only_terminal_contacts_are_retained_as_weaker_evidence():
    report=recognize_offset_connectors([(40,23),(44,29),(70,29),(74,23)],lanes(),4)
    assert len(report['annotations'])==1
    assert report['annotations'][0]['attachment_evidence']=='terminal_lane_contacts'
    assert report['annotations'][0]['native_connection_type']=='unassigned'


def test_partial_offset_run_retains_color_uncertainty_and_does_not_join_contacts():
    import numpy as np
    from backend.core.publication_offset_runs import offset_run_hypotheses, offset_marker_hypotheses
    labels=np.full((60,120),-1,dtype=np.int8)
    labels[23,15:41]=6;labels[23,74:101]=6
    trace={'trace_id':0,'kind':'unclassified','hue_bins':[5],'color_continuity_supported':False,
           'domains':[{'kind':'unclassified','span_pixels':[[44,29],[70,29]]}]}
    report=offset_run_hypotheses([trace],lanes(),labels,4)
    assert len(report['candidates'])==1
    candidate=report['candidates'][0]
    assert not candidate['connections_applied']
    assert not candidate['color_continuity_supported']
    assert not candidate['missing_attachment_sides']
    labels[26:28,38:40]=12
    staple={'trace_id':1,'domains':[{'kind':'staple','observed_row_index':0,'span_pixels':[[44,23],[80,23]]}]}
    markers=offset_marker_hypotheses([staple],lanes(),labels,4)
    assert len(markers['candidates'])==1
    assert markers['candidates'][0]['ligation_assignment']=='unresolved'
