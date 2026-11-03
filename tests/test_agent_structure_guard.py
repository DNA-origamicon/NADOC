"""Agent publication refuses missing process, invented history and hidden atoms."""

import json
from uuid import UUID

import pytest

from backend.core import models as m
from backend.core.part_history_proof import import_root
from experiments.recorded_review_process import Process, ProcessRequired, verify
from scripts.agent_structure_guard import publish


def part():
    process = Process('Agent process test')
    process.append('bundle-create', {'_proof_version':1,
        'history_seed':str(UUID(int=12)), 'cells':[[0,0]], 'length_bp':4,
        'name':'Agent process test', 'lattice_type':'HONEYCOMB', 'ligate_adjacent':False},
        'Create one four-base-pair helix')
    return process


def test_native_process_replays_after_recovery_payloads_are_destroyed(tmp_path):
    design = part().design
    for row in design.feature_log:
        row.design_snapshot_gz_b64 = 'not-evidence'
        row.post_state_gz_b64 = 'not-evidence'
    result = publish(design, tmp_path/'good.nadoc')
    assert result['status'] == 'verified' and not result['recovery_snapshots_used']
    assert verify(m.Design.from_json((tmp_path/'good.nadoc').read_text()))['commands'] == 1


@pytest.mark.parametrize('root', ['missing','capture'])
def test_history_free_structure_cannot_be_published(tmp_path, root):
    design = part().design.copy_with(feature_log=[],recipe_root=None)
    if root == 'capture':
        design.recipe_root = import_root(design)
    with pytest.raises(ProcessRequired, match='complete construction'):
        publish(design,tmp_path/'bad.nadoc')
    assert list(tmp_path.iterdir()) == []


def test_nonempty_log_does_not_hide_unrecorded_geometry(tmp_path):
    design = part().design
    design.helices[0].phase_offset += .2
    with pytest.raises(ProcessRequired,match='helices'):
        publish(design,tmp_path/'bad.nadoc')
    assert list(tmp_path.iterdir()) == []


def test_atomistic_override_is_also_subject_to_process_proof(tmp_path):
    process = part()
    process.diagnostic('native-atoms',{},'Build native atoms')
    assert verify(process.design)['commands'] == 2
    # Hide the placement step: the remaining native construction cannot justify
    # this reference, even if the atom coordinates were left unchanged.
    process.design.feature_log.pop()
    process.design.atomistic_reference.atoms[0].x += .1
    with pytest.raises(ProcessRequired,match='atomistic_reference'):
        publish(process.design,tmp_path/'bad.nadoc')
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(('action', 'inputs'), [
    ('document-name', {'name':'Private rename'}),
    ('native-atoms', {}),
    ('assembly-add', {'assembly_id':str(UUID(int=501)),
                      'instance_id':str(UUID(int=502)), 'name':'Private assembly'}),
])
def test_replayable_private_steps_cannot_be_published_as_part_features(tmp_path, action, inputs):
    from scripts.agent_structure_guard import audit

    process = part()
    process.diagnostic(action, inputs, 'Private operation')
    assert verify(process.design)['status'] == 'verified'
    with pytest.raises(ProcessRequired, match='not a user-facing part operation'):
        audit(process.design)
    with pytest.raises(ProcessRequired, match='not a user-facing part operation'):
        publish(process.design, tmp_path/'private.nadoc')
    assert list(tmp_path.iterdir()) == []


def test_diagnostic_step_cannot_smuggle_a_final_atom_payload():
    process = part()
    with pytest.raises(ProcessRequired,match='no atom payload'):
        process.diagnostic('native-atoms',{'atoms':[]},'Fake build')


def test_changed_implementation_requires_rebuild():
    process = part()
    process.diagnostic('document-name',{'name':'Renamed'},'Rename')
    process.design.feature_log[-1].params['implementation'] = {}
    with pytest.raises(ProcessRequired,match='implementation changed'):
        verify(process.design)


def test_reconstructed_connectivity_has_stable_replay_identities():
    from experiments.fh27_review_parts import two_hb

    process = two_hb()
    assert process.design.crossovers
    assert verify(process.design)['commands'] == 8


def test_replacement_is_bound_and_a_refusal_preserves_destination(tmp_path):
    path = tmp_path/'existing.nadoc'
    path.write_text('existing user data')
    with pytest.raises(ProcessRequired,match='destination changed'):
        publish(part().design,path,expected_existing_sha256='wrong')
    assert path.read_text() == 'existing user data'
    assert not path.with_name(path.name+'.agent-writing').exists()


def test_unknown_stage_does_not_fall_back_to_snapshot():
    process = part()
    with pytest.raises(ProcessRequired,match='Unsupported process stage'):
        process.diagnostic('load-final-design',{'design':json.loads(process.design.to_json())},'Invented process')


def test_publication_preserves_another_writers_staging_file(tmp_path):
    target = tmp_path/'new.nadoc'
    staging = tmp_path/'new.nadoc.agent-writing'
    staging.write_text('owned by another writer')
    with pytest.raises(FileExistsError):
        publish(part().design,target)
    assert staging.read_text() == 'owned by another writer'
    assert not target.exists()


def test_retired_snapshot_writer_cannot_create_a_structure():
    from experiments.terminal_extension_review_nadoc import write_pair

    with pytest.raises(ValueError,match='AGENT_PROCESS_REQUIRED'):
        write_pair(None,None,None,None,None,None)


def test_history_seek_restores_the_recorded_molecular_stage():
    from backend.api.crud import _seek_feature_log
    from backend.core.part_overlay_recovery import restore_diagnostic_reference

    process = part()
    process.diagnostic('native-atoms',{},'Build native atoms')
    final = process.design
    earlier = _seek_feature_log(final,0)
    assert earlier.atomistic_reference is None
    assert m.Design.model_validate_json(earlier.model_dump_json()).helices
    restored = _seek_feature_log(earlier,-1)
    assert restored.atomistic_reference == final.atomistic_reference
    assert _seek_feature_log(restored,-2).atomistic_reference is None
    # Ordinary histories do not opt in to diagnostic reference recovery.
    ordinary = final.copy_with(feature_log=final.feature_log[:1])
    assert restore_diagnostic_reference(ordinary,earlier).atomistic_reference == final.atomistic_reference


def test_diagnostic_seek_restores_source_placement_owners():
    from backend.api.crud import _seek_feature_log

    process = part()
    source = process.design
    process.diagnostic('document-name',{'name':'Recorded review'},'Name')
    # Materialized assemblies no longer have the input part's placements.
    materialized = process.design.copy_with(cluster_transforms=[],lattice_frames=[])
    earlier = _seek_feature_log(materialized,0)
    assert earlier.cluster_transforms == source.cluster_transforms
    assert m.Design.model_validate_json(earlier.model_dump_json()).lattice_frames == source.lattice_frames


def test_molecular_history_change_requires_a_complete_render_refresh():
    from backend.core.render_diff import _diff_is_cluster_only, _topology_diff_field

    process = part()
    process.diagnostic('native-atoms',{},'Native atoms')
    before = process.design
    after = before.model_copy(deep=True)
    after.atomistic_reference.atoms[0].x += .1
    after.cluster_transforms[0].translation[0] += 1
    assert not _diff_is_cluster_only(before,after)
    assert _topology_diff_field(before,after) == 'atomistic_reference'


def test_saved_main_loadout_requires_a_recorded_publication_contract(tmp_path):
    """ISSUE-171: native construction is proven, but Save adds an unlogged branch."""
    from backend.core.design_loadouts import decode_snapshot
    from backend.core.project_revisions import refresh_active_revision
    from experiments.recorded_review_process import structural_value
    from scripts.agent_structure_guard import audit

    source = part().design
    assert audit(source)['status'] == 'verified'
    saved = refresh_active_revision(tmp_path / 'revisions', source)
    before, after = structural_value(source), structural_value(saved)
    assert {key for key in before if before[key] != after[key]} == {
        'loadouts', 'active_loadout_id',
    }
    assert saved.loadouts[0].name == 'Main'
    assert saved.feature_log == source.feature_log
    branch = decode_snapshot(saved.loadouts[0].design_snapshot_gz_b64)
    assert audit(branch)['status'] == 'verified'
    with pytest.raises(ProcessRequired, match='active_loadout_id, loadouts'):
        publish(saved, tmp_path / 'must-not-publish.nadoc')
    assert not (tmp_path / 'must-not-publish.nadoc').exists()
