from backend.core.publication_reconstruction_report import classify_reconstruction


def test_partial_output_groups_distinct_route_failures_and_preserves_review_notes():
    report = {
        'status': 'partial',
        'omissions': [
            {'kind': 'missing_staple', 'status': 'ambiguous'},
            {'kind': 'missing_staple', 'status': 'budget_exhausted'},
            {'kind': 'missing_staple', 'status': 'ambiguous'},
            {'kind': 'missing_staple', 'status': 'no_match'},
        ],
        'base_conflicts': [{'detail': 'source disagreement'}],
    }
    classified = classify_reconstruction(report, native_file='part.nadoc')
    assert classified['output'] == 'partial'
    issues = {item['code']: item for item in classified['issues']}
    assert issues['staple_route_ambiguous']['omission_indices'] == [0, 2]
    assert issues['staple_search_limited']['omission_indices'] == [1]
    assert issues['staple_route_unmatched']['omission_indices'] == [3]
    assert issues['base_conflict']['severity'] == 'review'


def test_compiler_result_alone_does_not_count_as_native_output():
    classified = classify_reconstruction(
        {'status': 'complete'}, failure=('publication', 'process_required', 'Missing replay operation'))
    assert classified['output'] == 'report_only'
    assert classified['native_file'] is None
    assert classified['issues'][0]['severity'] == 'blocking'


def test_audited_complete_output_can_include_a_review_issue():
    classified = classify_reconstruction(
        {'status': 'complete', 'base_conflicts': [{'detail': 'source disagreement'}]},
        native_file='part.nadoc')
    assert classified['output'] == 'complete'
    assert classified['issues'][0]['code'] == 'base_conflict'


def test_catalog_scope_and_variant_evidence_are_independent():
    from backend.core.publication_reconstruction_report import classify_reviewed_source

    issues = classify_reviewed_source(
        image_kind='conceptual_illustration',
        staple_list_status='paper_lists_available_variant_unmatched')
    assert {issue['code'] for issue in issues} == {
        'figure_scope_incomplete', 'table_variant_unverified'}
    assert classify_reviewed_source(image_kind='complete_design_map',
                                    staple_list_status='available') == []
