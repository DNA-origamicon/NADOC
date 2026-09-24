import pytest
from tools.vr_workflows.workspace import initialize, campaign_workspace, reset_parts
from tools.vr_workflows.acceptance import evaluate, WORKFLOWS, PROFILES, SEEDS


def test_reset_deletes_edited_parts_but_preserves_outside_and_notes(tmp_path):
    root = initialize(tmp_path/'VR Testing')
    outside = tmp_path/'important.nadoc'
    outside.write_text('user design')
    (root/'edited.nadoc').write_text('arbitrary user edits, not parsed')
    (root/'notes.txt').write_text('keep notes')
    (root/'nested').mkdir()
    (root/'nested'/'renamed.NADOC').write_text('edited')
    (root/'outside').symlink_to(tmp_path, target_is_directory=True)
    (root/'linked.nadoc').symlink_to(outside)
    with campaign_workspace(root):
        assert reset_parts(root) == ['edited.nadoc', 'linked.nadoc', 'nested/renamed.NADOC']
        with pytest.raises(BlockingIOError):
            with campaign_workspace(root):
                pass
    assert outside.read_text() == 'user design'
    assert (root/'notes.txt').read_text() == 'keep notes'


def test_cannot_reset_unmarked_or_adopt_nonempty_folder(tmp_path):
    (tmp_path/'user.nadoc').write_text('keep')
    with pytest.raises(ValueError):
        reset_parts(tmp_path)
    with pytest.raises(ValueError):
        initialize(tmp_path)
    assert (tmp_path/'user.nadoc').exists()


def cohort():
    return [{'workflow': workflow, 'profile': profile, 'seed': seed,
             'stages': {stage: {'passed': True, 'evidence': 'test-only-placeholder'} for stage in stages}}
            for workflow, stages in WORKFLOWS.items() for profile in PROFILES for seed in SEEDS]


def test_threshold_requires_each_group_and_complete_cohort():
    rows = cohort()
    for row in rows:
        if row['seed'] < 2:
            row['stages']['independent_geometry']['passed'] = False
    assert evaluate(rows)['complete']
    rows[2]['stages']['independent_geometry']['passed'] = False
    assert not evaluate(rows)['complete']
    assert not evaluate(cohort()[:-1])['complete']
    assert not evaluate([])['complete']


def test_no_retry_replacement_or_missing_stage_evidence():
    rows = cohort()
    with pytest.raises(ValueError):
        evaluate(rows+[rows[0]])
    for row in rows:
        row['stages']['cadnano_edit']['evidence'] = ''
    assert not evaluate(rows)['complete']


def test_publish_validates_before_reset_and_rejects_review_as_input(tmp_path):
    from tools.vr_workflows.workspace import publish_parts
    root=initialize(tmp_path/'review')
    old=root/'edited.nadoc'
    old.write_text('user edits')
    invalid=tmp_path/'bad.nadoc'
    invalid.write_text('invalid')
    with pytest.raises(ValueError):
        publish_parts(root,{'vr-first':invalid})
    assert old.read_text()=='user edits'
    with pytest.raises(ValueError,match='cannot be publication inputs'):
        publish_parts(root,{'vr-first':old})
    assert old.exists()


def test_publish_preserves_exact_bytes_and_deletes_edited_parts(tmp_path):
    from tools.vr_workflows.workspace import publish_parts
    from backend.core.models import Design, Helix
    root=initialize(tmp_path/'review')
    (root/'edited.nadoc').write_text('edited')
    source=tmp_path/'verified.nadoc'
    design=Design(helices=[Helix(id='h1',grid_pos=(0,0),length_bp=42,axis_start={'x':0,'y':0,'z':0},axis_end={'x':0,'y':0,'z':14.028})])
    source.write_text(design.to_json())
    result=publish_parts(root,{'vr-first':source})
    assert result['deleted']==['edited.nadoc']
    assert (root/'vr-first.nadoc').read_bytes()==source.read_bytes()
    assert len(result['written'])==1
