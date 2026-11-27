from backend.core.publication_sequence_continuity import continuity_candidates


def inputs():
    def trace(i, left, right):
        return {'trace_id':i,'kind':'staple','color_continuity_supported':True,'hue_bins':[6],
                'status':'staple_trace_fragment','domains':[{'kind':'staple','observed_row_index':0,
                'span_pdf':[[left,10],[right,10]],'approximate_cells':right-left+1}]}
    classified={'panels':[{'placement_index':1,'xref':2,'pixels_per_pdf_point':1,
                           'traces':[trace(0,0,5),trace(1,8,13)],
                           'partial_connectors':{'candidates':[]}}]}
    anchors={'minimum_length':4,'anchors':[{'row_id':'a','oligo_start':0,'length':14,
              'scaffold_start':13,'status':'provisional_sequence_anchor'}]}
    return classified,anchors,[{'id':'a','sequence':'T'*14}],'A'*20


def test_small_gap_with_exact_sequence_support_retains_both_directions():
    result=continuity_candidates(*inputs())
    assert len(result['candidates'])==1
    candidate=result['candidates'][0]
    assert candidate['missing_ink_pixels']==2
    assert {m['direction'] for m in candidate['matches']}=={-1,1}
    assert not candidate['register_verified']
    assert not candidate['connections_applied']


def test_sequence_conflict_large_gap_and_wrong_row_are_not_bridged():
    data=inputs();data[2][0]['sequence']='C'*14
    assert not continuity_candidates(*data)['candidates']
    data=inputs();data[0]['panels'][0]['traces'][1]['domains'][0]['observed_row_index']=1
    assert not continuity_candidates(*data)['candidates']
    assert not continuity_candidates(*inputs(),maximum_gap_pixels=1)['candidates']


def test_offset_endpoint_continues_sequence_check_without_perfect_connectivity():
    data=inputs();panel=data[0]['panels'][0]
    panel['traces'][0]['domains'][0].update(span_pdf=[[0,10],[13,10]],approximate_cells=14)
    panel['partial_connectors']['candidates']=[{'candidate_id':0,'observed_row_index':0,'span_pdf':[[4,9],[7,9]]}]
    result=continuity_candidates(*data)
    assert result['connector_sequence_checks']
    assert all(c['sequence_complement_verified'] and not c['image_identity_verified'] for c in result['connector_sequence_checks'])
    data[2][0]['sequence']='C'*14
    assert not continuity_candidates(*data)['connector_sequence_checks']
