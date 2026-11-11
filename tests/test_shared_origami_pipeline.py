"""Publication gates and saved/reopened replay for the shared reconstruction workflow."""

import hashlib
import json

import pytest

from experiments.recorded_review_process import ProcessRequired
from tools.design_archive.recorded_authoring import construct
from tools.design_archive.shared_pipeline import run as pipeline_run


def run(**kwargs):
    return pipeline_run(**kwargs, development_root=kwargs['shared_root'].parent / 'development')


def recipe(tmp_path):
    source = tmp_path / 'figure-evidence.txt'
    source.write_text('Test-only explicit helix/strand selections, not a publication reconstruction.')
    value = {'version': 1, 'design_id': 'D003', 'name': '__test__ recorded recipe',
             'lattice': 'SQUARE', 'unresolved': [],
             'folded_geometry': {'required': False, 'evidence': 'Synthetic straight helix software fixture'},
             'sources': [{'path': source.name, 'role': 'test_evidence',
                         'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}],
             'operations': [
                 {'kind': 'helix-add-at-cell', 'label': 'Add selected cell', 'params': {
                     'row': 0, 'col': 0, 'length_bp': 32, 'populate_strands': False,
                     '_helix_id': '00000000-0000-4000-8000-000000000001'}},
                 {'kind': 'strand-add', 'label': 'Draw selected scaffold domain', 'params': {
                     '_strand_id': 'selected-strand', 'strand_type': 'scaffold',
                     'sequence': 'ACGTACGT', 'domains': [{'helix_id': '00000000-0000-4000-8000-000000000001',
                     'start_bp': 0, 'end_bp': 7, 'direction': 'FORWARD'}]}},
             ]}
    path = tmp_path / 'recipe.json'
    path.write_text(json.dumps(value))
    return path, value


def test_shared_publication_reopens_and_replays_native_operations(tmp_path):
    from backend.core.models import Design
    from scripts.agent_structure_guard import audit
    from backend.core.part_history_proof import command_rows
    path, _ = recipe(tmp_path)
    output, report = run(design_id='D003', run_id='test', shared_root=tmp_path / 'shared', recipe_path=path)
    saved = Design.model_validate_json((output / 'D003.nadoc').read_text())
    assert audit(saved)['status'] == 'verified'
    kinds = [kind for _, kind, _ in command_rows(saved, 2000)]
    assert 'helix-add-at-cell' in kinds and 'strand-add' in kinds and 'cluster_create' in kinds
    assert not any('import' in kind for kind in kinds)
    assert saved.strands[0].sequence == 'ACGTACGT'
    assert report['outputs'][0]['saved_reopened_replay']['recovery_snapshots_used'] is False
    assert report['simulation_ready'] is False
    from pathlib import Path
    assert (Path(report['development_directory']) / report['inputs'][0]['path']).is_file()
    assert [p.name for p in output.iterdir()] == ['D003.nadoc']
    with pytest.raises(FileExistsError):
        run(design_id='D003', run_id='test', shared_root=tmp_path / 'shared', recipe_path=path)


@pytest.mark.parametrize('kind', ['cadnano-import', 'diagnostic-process', 'assembly-flatten'])
def test_capture_and_private_operations_refused(tmp_path, kind):
    _, value = recipe(tmp_path)
    value['operations'][0]['kind'] = kind
    with pytest.raises(ProcessRequired, match='No admitted'):
        construct(value)


def test_source_tampering_blocks_before_publication(tmp_path):
    path, value = recipe(tmp_path)
    (tmp_path / value['sources'][0]['path']).write_text('changed')
    with pytest.raises(ProcessRequired, match='hash mismatch'):
        run(design_id='D003', run_id='test', shared_root=tmp_path / 'shared', recipe_path=path)
    output = tmp_path / 'development/D003/test'
    assert not list(output.glob('*.nadoc'))
    assert json.loads((output / 'run.json').read_text())['status'] == 'blocked'


def test_unresolved_topology_refused(tmp_path):
    _, value = recipe(tmp_path)
    value['unresolved'] = ['polarity evidence missing']
    with pytest.raises(ProcessRequired, match='Unresolved'):
        construct(value)


def test_old_image_import_cannot_publish_snapshot(tmp_path):
    from tools.design_archive.relax_image_import import write_relaxed_image_import
    with pytest.raises(ProcessRequired):
        write_relaxed_image_import({'vstrands': []}, tmp_path)
    assert not list(tmp_path.iterdir())


def test_unrecorded_post_construction_changes_rejected(tmp_path):
    from scripts.agent_structure_guard import audit
    _, value = recipe(tmp_path)
    design = construct(value)
    design.strands[0].sequence = 'TTTTTTTT'
    with pytest.raises(ProcessRequired, match='Unrecorded'):
        audit(design)


def test_recorded_relaxation_preserves_topology_and_independently_audits_all_bases(tmp_path):
    from backend.core.models import Design
    from scripts.agent_structure_guard import audit
    path, value = recipe(tmp_path)
    second = '00000000-0000-4000-8000-000000000002'
    value['operations'].insert(1, {'kind': 'helix-add-at-cell', 'label': 'Second test cell',
        'params': {'row': 10, 'col': 0, 'length_bp': 32, 'populate_strands': False, '_helix_id': second}})
    strand = value['operations'][-1]['params']
    strand['sequence'] = None
    strand['domains'][0]['end_bp'] = 30
    strand['domains'].append({'helix_id': second, 'start_bp': 30, 'end_bp': 0, 'direction': 'REVERSE'})
    source = construct(value)
    value['folded_geometry']['required'] = True
    path.write_text(json.dumps(value))
    output, run_report = run(design_id='D003', run_id='fit', shared_root=tmp_path / 'shared', recipe_path=path)
    result = Design.model_validate_json((output / 'D003.nadoc').read_text())
    report = run_report['stages'][-1]
    assert result.strands == source.strands
    assert report['relaxation']['status'] == 'applied'
    assert sum(b['nucleotides_checked'] for b in report['independent_geometry_audit']['bodies']) == 62
    assert report['independent_geometry_audit']['clearance']['interbody_helix_pairs_below_2nm'] == 0
    assert audit(result)['status'] == 'verified'


def test_requested_unsupported_fit_does_not_publish(tmp_path):
    path, _ = recipe(tmp_path)
    with pytest.raises(ProcessRequired, match='Required folded-geometry'):
        run(design_id='D003', run_id='test', shared_root=tmp_path / 'shared', recipe_path=path, relax=True)
    assert not list((tmp_path / 'shared/D003/test').glob('*.nadoc'))


def test_continuation_retains_upstream_history_and_portable_evidence(tmp_path):
    from backend.core.models import Design
    path, _ = recipe(tmp_path)
    first, _ = run(design_id='D003', run_id='first', shared_root=tmp_path / 'shared', recipe_path=path)
    second, report = run(design_id='D003', run_id='second', shared_root=tmp_path / 'shared',
                         source_part=first / 'D003.nadoc')
    original = Design.model_validate_json((first / 'D003.nadoc').read_text())
    continued = Design.model_validate_json((second / 'D003.nadoc').read_text())
    assert continued.feature_log == original.feature_log
    assert continued.cluster_transforms == original.cluster_transforms
    from pathlib import Path
    assert all((Path(report['development_directory']) / source['path']).is_file() for source in report['inputs'])
    assert report['upstream_source_citations']
    assert [p.name for p in second.iterdir()] == ['D003.nadoc']
    assert report['outputs'][0]['saved_reopened_replay']['status'] == 'verified'
