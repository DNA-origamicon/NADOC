"""Stable reconstruction issue codes and output status for publication reports."""
from collections import defaultdict
from pathlib import PurePosixPath


class ReconstructionBlocked(ValueError):
    """A known reconstruction limit, with a code independent of message text."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


ISSUE_GUIDANCE = {
    'diagram_page_out_of_range': 'Select a diagram page from the uploaded PDF.',
    'base_register_unresolved': 'Supply a routing figure with a readable base ruler or a calibrated routing file.',
    'helix_labels_unresolved': 'Supply a figure with visible helix labels aligned to the routing rows.',
    'diagram_route_unresolved': 'Supply a routing map with clearer strand paths, ends and junctions.',
    'endpoint_table_unavailable': 'Select a matching endpoint table, or supply the original routing file.',
    'table_selection_invalid': 'Select valid table pages and module names from Detect designs.',
    'table_variants_unselected': 'Select the modules and variants belonging to this figure.',
    'table_row_continuation_unresolved': 'Verify whether the indicated table lines are continuations or separate oligos.',
    'raster_lane_classification_incomplete': 'Check overlapping panels and provide a clearer routing export where lanes cannot be separated.',
    'sequence_alignment_unresolved': 'Verify scaffold identity, strand polarity, and the sequence-to-image register.',
    'sequence_search_limited': 'Review the retained search alternatives. Try a narrower selection or add source constraints.',
    'image_search_limited': 'Review the retained image evidence. A bound was reached before all candidates could be tested.',
    'insertions_unresolved': 'Verify the source positions and lengths of insertions and deletions.',
    'overhangs_unresolved': 'Verify the attachment, polarity and sequence of the overhangs.',
    'lattice_placement_unresolved': 'Provide the slice view or source lattice coordinates and a supported polarity mapping.',
    'lattice_type_unsupported': 'Use a native routing file for this lattice, or extend the publication compiler to support it.',
    'staple_route_ambiguous': 'Review competing staple placements at the reported table rows.',
    'staple_route_unmatched': 'Review the reported table rows against the figure and confirm the design variant.',
    'staple_route_conflict': 'Review rows that compete for the same routing sites.',
    'staple_search_limited': 'Review incomplete staple searches before interpreting a missing candidate.',
    'staple_sequence_invalid': 'Check the affected table sequences against the source.',
    'scaffold_length_discrepancy': 'Check the reported scaffold length and omitted sequence positions against the source.',
    'unclassified_route': 'Review the reported paths for strand role and direction.',
    'unpaired_scaffold_unresolved': 'Check whether the reported unpaired regions are loops, termini or incomplete evidence.',
    'base_conflict': 'Review the listed image/table disagreements and the selected bases.',
    'modification_unsupported': 'Review the reported chemical annotations before using the reconstructed design.',
    'annotation_pending_route': 'Check the terminal labels and labeled overhangs once strand placement is verified.',
    'process_required': 'Resolve the recorded construction or independent replay failure before publishing a native file.',
    'bond_review_required': 'Review the reported bonds and resolve the publication gate.',
    'construction_failed': 'Review the recorded construction error and source evidence.',
    'extraction_failed': 'Review the extraction error and the retained source evidence.',
    'verification_failed': 'Review the source comparison or native verification error.',
    'publication_failed': 'Review the publication error and saved-file audit.',
    'source_evidence_unavailable': 'Check the selected source and pages, then retry evidence extraction.',
    'figure_scope_incomplete': 'Supply a full routing map or explicitly select a separately reconstructable component.',
    'table_variant_unverified': 'Identify the sequence table for the exact object shown in the figure.',
}

ISSUE_STAGES = {
    'diagram_page_out_of_range': 'source',
    'base_register_unresolved': 'diagram',
    'helix_labels_unresolved': 'diagram',
    'diagram_route_unresolved': 'diagram',
    'endpoint_table_unavailable': 'table',
    'table_selection_invalid': 'table',
    'sequence_alignment_unresolved': 'sequence',
    'insertions_unresolved': 'routing',
    'overhangs_unresolved': 'routing',
    'lattice_placement_unresolved': 'lattice',
    'lattice_type_unsupported': 'lattice',
}

STAPLE_ISSUES = {
    'ambiguous': 'staple_route_ambiguous',
    'no_match': 'staple_route_unmatched',
    'conflicts_with_other_row': 'staple_route_conflict',
    'budget_exhausted': 'staple_search_limited',
    'invalid_sequence': 'staple_sequence_invalid',
}


def classify_reconstruction(report, *, native_file=None, source_evidence=None, failure=None):
    """Classify observed failures and omissions without inferring missing source facts."""
    issues = []
    output = 'report_only' if native_file is None else report['status']
    if failure:
        stage, code, message = failure
        issues.append(_issue(code, ISSUE_STAGES.get(code, stage), 'blocking', detail=message))

    grouped = defaultdict(list)
    for index, omission in enumerate(report.get('omissions', [])):
        kind = omission['kind']
        code = {
            'scaffold_length_discrepancy': 'scaffold_length_discrepancy',
            'unclassified_path': 'unclassified_route',
            'unpaired_scaffold_review': 'unpaired_scaffold_unresolved',
        }.get(kind, 'unclassified_route')
        if kind == 'missing_staple':
            code = STAPLE_ISSUES.get(omission.get('status'), 'staple_route_unmatched')
        grouped[code].append(index)
    for code, indices in grouped.items():
        issues.append(_issue(code, 'routing', 'omission', omission_indices=indices))
    if report.get('base_conflicts'):
        issues.append(_issue('base_conflict', 'sequence', 'review', count=len(report['base_conflicts'])))
    if report.get('source_evidence_error'):
        issues.append(_issue('source_evidence_unavailable', 'source', 'review',
                             detail=report['source_evidence_error']))
    if source_evidence and native_file is None:
        issues.extend(issue for issue in _source_issues(source_evidence)
                      if issue['code'] != (failure[1] if failure else None))
    return {'schema_version': 1, 'output': output, 'native_file': native_file, 'issues': issues}


def _issue(code, stage, severity, **evidence):
    return {'code': code, 'stage': stage, 'severity': severity,
            'action': ISSUE_GUIDANCE[code], **evidence}


def _source_issues(evidence):
    raster = evidence.get('raster_evidence') or {}
    fallback = evidence.get('sequence_fallback') or {}
    table = evidence.get('table_import') or {}
    selected = set(evidence.get('selected_row_ids', []))
    if fallback.get('status') == 'select_modules_first':
        yield _issue('table_variants_unselected', 'table', 'review')
    continuations = [row['id'] for row in table.get('rows', [])
                     if row['id'] in selected and row.get('possible_continuation_of')]
    if continuations:
        yield _issue('table_row_continuation_unresolved', 'table', 'review', row_ids=continuations)

    panels = raster.get('classified_tracing', {}).get('panels', [])
    if raster.get('status') == 'pixel_traces_unregistered_to_bases':
        yield _issue('base_register_unresolved', 'diagram', 'review')
    supported = sum(p['lane_classification']['status'] == 'panel_pattern_supported' for p in panels)
    placements = len(raster.get('placements', []))
    if supported < placements:
        yield _issue('raster_lane_classification_incomplete', 'diagram', 'review',
                     supported_placements=supported, total_placements=placements)
    if (raster.get('truncated') or any(
            p.get('truncated') or p.get('connector_search', {}).get('budget_exhausted') or
            p.get('offset_marker_annotations', {}).get('truncated') or
            p.get('partial_connectors', {}).get('truncated') for p in panels)):
        yield _issue('image_search_limited', 'diagram', 'review')

    if (fallback.get('status') == 'row_budget_exceeded' or fallback.get('image_continuity', {}).get('truncated')
            or fallback.get('image_continuity', {}).get('connector_checks_truncated') or any(
                p['compatibility'].get('candidate_pool_complete') is False for p in fallback.get('passes', []))):
        yield _issue('sequence_search_limited', 'sequence', 'review')
    for code, predicate in (
        ('modification_unsupported', lambda row: any(m['status'].startswith('unsupported') for m in row['modifications'])),
        ('annotation_pending_route', lambda row: row['overhangs'] or any(
            m['status'] == 'supported_terminal_label_pending_route' for m in row['modifications'])),
    ):
        row_ids = [row['row_id'] for row in evidence.get('annotations', []) if predicate(row)]
        if row_ids:
            yield _issue(code, 'annotation', 'review', row_ids=row_ids)


def package_entry(report_name, report):
    """Index the files actually present in the reconstruction package."""
    return {'name': PurePosixPath(report_name).name.removesuffix('.reconstruction.json'),
            'report_file': report_name, 'source_evidence': report.get('source_evidence'),
            'source_file': report['source_file'],
            'diagram_page': report['diagram_page'], 'table_page': report['table_page'],
            'source_sha256': report['source_sha256'], **report['classification']}


def classify_reviewed_source(*, image_kind, staple_list_status):
    """Classify reviewed catalog scope, independently of parser success."""
    issues = []
    if image_kind in {'conceptual_illustration', 'partial_design', 'component_only'}:
        issues.append(_issue('figure_scope_incomplete', 'source', 'review', image_kind=image_kind))
    if staple_list_status in {'paper_lists_available_variant_unmatched', 'not_verified_for_this_illustration'}:
        issues.append(_issue('table_variant_unverified', 'table', 'review', list_status=staple_list_status))
    return issues
