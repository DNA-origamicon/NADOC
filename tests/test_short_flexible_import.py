"""Two-nt scaffold marks through recorded import and ordinary editor commands."""
import json

import pytest
from fastapi import Response, HTTPException

from backend.api import state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.crud import ScadnanoImportRequest, import_scadnano_design
from backend.api.routes_flexible_segments import FlexibleSegmentBatchBody, batch_flexible_segment
from backend.core.models import Design
from scripts.agent_structure_guard import audit


def short_hinge_source():
    return {"name": "__e2e__short-flexible", "version": "0.19.0", "grid": "square",
        "helices": [{"grid_position": [0, 0], "max_offset": 8},
                    {"grid_position": [9, 0], "max_offset": 8}],
        "strands": [
            {"is_scaffold": True, "domains": [
                {"helix": 0, "forward": True, "start": 0, "end": 8},
                {"helix": 1, "forward": False, "start": 0, "end": 8}]},
            {"domains": [{"helix": 0, "forward": False, "start": 0, "end": 7}]},
            {"domains": [{"helix": 1, "forward": True, "start": 0, "end": 7}]},
        ]}


@pytest.mark.parametrize('same_cluster', [False, True])
def test_two_nt_scaffold_mark_reopens_replays_and_undoes(same_cluster):
    token = set_current_doc('short-flexible-import-test')
    try:
        source = short_hinge_source()
        if same_cluster:
            source['helices'] = source['helices'][:1]
            source['strands'] = [
                {'is_scaffold': True, 'domains': [{'helix': 0, 'forward': True, 'start': 0, 'end': 8}]},
                {'domains': [{'helix': 0, 'forward': False, 'start': 0, 'end': 3}]},
                {'domains': [{'helix': 0, 'forward': False, 'start': 5, 'end': 8}]},
            ]
        import_scadnano_design(ScadnanoImportRequest(content=json.dumps(source)))
        before = state.get_or_404().model_dump_json()
        scaffold = next(s for s in state.get_or_404().strands if s.is_scaffold)
        marks = [dict(strand_id=scaffold.id, domain_index=i, bp_index=7,
                      direction=d.direction.value) for i, d in enumerate(scaffold.domains)]
        if same_cluster:
            marks = [dict(strand_id=scaffold.id, domain_index=0, bp_index=bp,
                          direction='FORWARD') for bp in (3, 4)]
        if same_cluster:
            revision, depth = state.revision(), state.undo_depth()
            with pytest.raises(HTTPException) as error:
                batch_flexible_segment(FlexibleSegmentBatchBody(marks=marks), Response())
            assert error.value.status_code == 422
            assert error.value.detail['message'] == 'flexible connections must be between two different cluster'
            assert state.get_or_404().model_dump_json() == before
            assert (state.revision(), state.undo_depth()) == (revision, depth)
            audit(state.get_or_404())
            return
        result = batch_flexible_segment(FlexibleSegmentBatchBody(marks=marks), Response())
        reopened = Design.model_validate_json(state.get_or_404().model_dump_json())
        assert len(reopened.flexible_segment_marks) == 2
        assert len(reopened.flexible_connections) == 1
        assert reopened.flexible_connections[0].n_ss_bases == 2
        assert reopened.flexible_connections[0].contour_length_nm == pytest.approx(1.18)
        audit(reopened)
        assert reopened.strands == Design.model_validate_json(before).strands
        assert sum(n['is_flexible_segment'] for n in result['nucleotides']) == 2
        state.undo()
        assert state.get_or_404().model_dump_json() == before
        state.redo()
        assert state.get_or_404().flexible_segment_marks == reopened.flexible_segment_marks
    finally:
        state.close_session()
        reset_current_doc(token)


def test_mixed_batch_does_not_partially_mark_or_destroy_existing_tether():
    token = set_current_doc('mixed-short-flexible-import-test')
    try:
        source = short_hinge_source()
        source['strands'][1]['domains'][0]['end'] = 3
        source['strands'].append({'domains': [
            {'helix': 0, 'forward': False, 'start': 5, 'end': 7}]})
        import_scadnano_design(ScadnanoImportRequest(content=json.dumps(source)))
        scaffold = next(s for s in state.get_or_404().strands if s.is_scaffold)
        valid = [dict(strand_id=scaffold.id, domain_index=i, bp_index=7,
                      direction=d.direction.value) for i, d in enumerate(scaffold.domains)]
        invalid = [dict(strand_id=scaffold.id, domain_index=0, bp_index=bp,
                        direction='FORWARD') for bp in (3, 4)]
        before = state.get_or_404().model_dump_json()
        with pytest.raises(HTTPException):
            batch_flexible_segment(FlexibleSegmentBatchBody(marks=valid + invalid), Response())
        assert state.get_or_404().model_dump_json() == before
        batch_flexible_segment(FlexibleSegmentBatchBody(marks=valid), Response())
        before = state.get_or_404().model_dump_json()
        with pytest.raises(HTTPException):
            batch_flexible_segment(FlexibleSegmentBatchBody(marks=invalid, replace=True), Response())
        assert state.get_or_404().model_dump_json() == before
        audit(state.get_or_404())
        batch_flexible_segment(FlexibleSegmentBatchBody(replace=True), Response())
        assert not state.get_or_404().flexible_segment_marks
        audit(state.get_or_404())
    finally:
        state.close_session()
        reset_current_doc(token)


@pytest.mark.parametrize('deleted_bp', [0, 2])
def test_two_nt_domain_skips_deleted_anchor_and_replays(deleted_bp):
    token = set_current_doc('deleted-anchor-short-flexible-test')
    try:
        source = {'name': 'deleted-anchor', 'version': '0.19.0', 'grid': 'square',
            'helices': [{'grid_position': [i * 9, 0], 'max_offset': 8} for i in range(3)],
            'strands': [
                {'is_scaffold': True, 'domains': [
                    {'helix': 0, 'forward': True, 'start': 0, 'end': 8},
                    {'helix': 1, 'forward': False, 'start': 0, 'end': 3, 'deletions': [deleted_bp]},
                    {'helix': 2, 'forward': True, 'start': 0, 'end': 8}]},
                *[{'domains': [{'helix': h, 'forward': False, 'start': 0, 'end': 8}]} for h in (0, 2)]]}
        import_scadnano_design(ScadnanoImportRequest(content=json.dumps(source)))
        scaffold = next(s for s in state.get_or_404().strands if s.is_scaffold)
        marks = [dict(strand_id=scaffold.id, domain_index=1, bp_index=bp,
                      direction='REVERSE') for bp in range(3) if bp != deleted_bp]
        batch_flexible_segment(FlexibleSegmentBatchBody(marks=marks), Response())
        design = state.get_or_404()
        conn, = design.flexible_connections
        assert conn.n_ss_bases == 2
        assert {conn.anchor_a.domain_index, conn.anchor_b.domain_index} == {0, 2}
        from backend.core.design_geometry import _geometry_for_design
        actual = {(n['strand_id'], n['domain_index'], n['bp_index'], n['direction'])
                  for n in _geometry_for_design(design) if not n['is_flexible_segment']}
        for anchor in (conn.anchor_a, conn.anchor_b):
            assert (anchor.strand_id, anchor.domain_index, anchor.bp_index, anchor.direction) in actual
        from backend.core.flexible_segments import unpaired_bead_keys
        assert (scaffold.domains[1].helix_id, deleted_bp, scaffold.domains[1].direction) not in unpaired_bead_keys(design)
        audit(Design.model_validate_json(design.model_dump_json()))
    finally:
        state.close_session()
        reset_current_doc(token)


def test_relax_response_keeps_flexible_flags_on_partial_helices():
    from backend.api.routes_flexible_segments import FlexibleRelaxBody, flexible_relax

    token = set_current_doc('short-flexible-relax-response-test')
    try:
        import_scadnano_design(ScadnanoImportRequest(content=json.dumps(short_hinge_source())))
        scaffold = next(s for s in state.get_or_404().strands if s.is_scaffold)
        marks = [dict(strand_id=scaffold.id, domain_index=i, bp_index=7,
                      direction=d.direction.value) for i, d in enumerate(scaffold.domains)]
        batch_flexible_segment(FlexibleSegmentBatchBody(marks=marks), Response())
        before = state.get_or_404()
        from backend.core.native_compact_geometry import native_compact_geometry
        assert native_compact_geometry(before) is None  # retain flexible metadata on binary feeds too
        cluster = next(c for c in before.cluster_transforms if c.id == before.flexible_connections[0].cluster_a_id)
        result = flexible_relax(FlexibleRelaxBody(transforms=[dict(
            cluster_id=cluster.id, pivot=cluster.pivot, rotation=cluster.rotation,
            translation=[1, 0, 0],
        )]))
        after = state.get_or_404()
        assert after.flexible_segment_marks == before.flexible_segment_marks
        assert after.flexible_connections == before.flexible_connections
        assert after.strands == before.strands
        assert result['partial_geometry']
        flagged = {(hid, bp, direction)
                   for hid, dirs in result['nucleotides_compact'].items()
                   for direction, bucket in dirs.items()
                   for bp, flexible in zip(bucket['bp'], bucket.get('flex', [False] * len(bucket['bp'])))
                   if flexible}
        expected = {(scaffold.domains[m['domain_index']].helix_id, m['bp_index'], m['direction'])
                    for m in marks if scaffold.domains[m['domain_index']].helix_id in result['changed_helix_ids']}
        assert expected
        assert flagged == expected
        state.undo()
        assert state.get_or_404().flexible_segment_marks == before.flexible_segment_marks
        state.redo()
        assert state.get_or_404().flexible_segment_marks == before.flexible_segment_marks
    finally:
        state.close_session()
        reset_current_doc(token)
