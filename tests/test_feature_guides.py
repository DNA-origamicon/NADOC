"""Documentation checks use opaque bytes, never construct molecular designs."""
import json
from pathlib import Path

import pytest

from scripts import check_feature_guides as cli
from scripts.feature_guides import (
    GUIDES, directory_hashes, inspect_guides, inventory, promote_directory,
    render_guide, render_ledger, snapshot,
)


@pytest.fixture
def library(tmp_path):
    (tmp_path / 'FEATURES.md').write_text('# Features\n## Design\n- **Extrude**\n  - Length\n- **Sweep**\n  - Path\n')
    (tmp_path / 'src').mkdir()
    (tmp_path / 'src/tool.js').write_text('version one')
    features = inventory(tmp_path)
    for feature in features.values():
        feature.update(status='planned', guide=None)
    feature = features['extrude']
    feature.update(status='partial', guide='extrude', watch=['src/*.js'],
                   covered_workflows=['New extrusion'], introduction='Create a new extrusion.')
    catalog = {'schema': 1, 'shared_watch': [], 'features': features}
    base = tmp_path / GUIDES
    guide = base / 'extrude'
    guide.mkdir(parents=True)
    (base / 'catalog.json').write_text(json.dumps(catalog))
    steps = {'title': 'Extrude', 'steps': [{'number': 1, 'caption': 'Click Extrude', 'file': '01.png'}]}
    (guide / 'steps.json').write_text(json.dumps(steps))
    (guide / 'README.md').write_text(render_guide(steps, feature))
    # Artifact integrity is tested with opaque bytes; no molecular authoring occurs.
    for name in ('example.nadoc', '01.png', 'verification.json'):
        (guide / name).write_bytes(b'opaque artifact placeholder')
    manifest = {'schema': 1, 'feature': 'extrude', 'created_at': '2026-11-11T12:00:00-07:00',
                'captured_at': '2026-11-11T13:00:00-07:00', 'source': snapshot(tmp_path, catalog, feature),
                'covered_workflows': feature['covered_workflows'], 'introduction': feature['introduction'],
                'assets': directory_hashes(guide)}
    (guide / 'manifest.json').write_text(json.dumps(manifest))
    (base / 'LEDGER.md').write_text(render_ledger(tmp_path))
    return tmp_path, catalog, guide


def first(library):
    return inspect_guides(library[0])['guides'][0]


def save_catalog(library):
    (library[0] / GUIDES / 'catalog.json').write_text(json.dumps(library[1]))


def test_current_without_git_or_app(library):
    assert first(library)['state'] == 'current'
    assert inspect_guides(library[0])['guides'][1]['state'] == 'not-created'


@pytest.mark.parametrize('change', ['modified', 'added', 'deleted'])
def test_dirty_new_and_deleted_dependencies(library, change):
    root = library[0]
    if change == 'modified':
        (root / 'src/tool.js').write_text('unsaved-to-git change')
    elif change == 'added':
        (root / 'src/new.js').write_text('new dependency')
    else:
        (root / 'src/tool.js').unlink()
    row = first(library)
    assert row['state'] in {'stale', 'broken'}
    assert row['changes'][0]['change'] == change


def test_unrelated_change_does_not_invalidate(library):
    (library[0] / 'unrelated.md').write_text('notes')
    assert first(library)['state'] == 'current'


def test_watch_rule_change_cannot_silently_rebaseline(library):
    library[1]['features']['extrude']['watch'] = ['src/tool.js']
    save_catalog(library)
    assert first(library)['state'] == 'stale'
    assert first(library)['changes'] == [{'path': 'catalog watch patterns', 'change': 'modified'}]


@pytest.mark.parametrize('action', ['delete', 'edit', 'extra'])
def test_asset_damage(library, action):
    target = library[2] / '01.png'
    if action == 'delete':
        target.unlink()
    elif action == 'edit':
        target.write_bytes(b'different pixels')
    else:
        (library[2] / 'unexpected.txt').write_text('not in manifest')
    assert first(library)['state'] == 'broken'


def test_missing_manifest_remains_reportable(library):
    (library[2] / 'manifest.json').unlink()
    assert first(library)['state'] == 'broken'
    assert 'Missing manifest' in render_ledger(library[0])


@pytest.mark.parametrize('text', ['- **New Feature**\n', '  - New variant\n'])
def test_feature_inventory_drift(library, text):
    path = library[0] / 'FEATURES.md'
    path.write_text(path.read_text() + text)
    assert inspect_guides(library[0])['inventory_problems']


def test_scope_change_requires_review(library):
    library[1]['features']['extrude']['covered_workflows'].append('Continuation')
    save_catalog(library)
    assert first(library)['state'] == 'stale'


def test_paths_cannot_escape(library):
    library[1]['features']['extrude']['watch'] = ['../outside/*']
    save_catalog(library)
    assert first(library)['state'] == 'broken'


def test_markdown_has_relative_images_and_dates(library):
    assert '](01.png)' in (library[2] / 'README.md').read_text()
    ledger = render_ledger(library[0])
    assert '2026-11-11T12:00:00-07:00' in ledger
    assert '2026-11-11T13:00:00-07:00' in ledger
    assert '[extrude](extrude/README.md)' in ledger


def test_editorial_chapters_keep_captions_and_images_in_order(library):
    steps = {'title': 'Extrude', 'sections': [
        {'title': 'Choose a plane', 'body': 'Choose before painting.'},
        {'title': 'Apply', 'body': 'Inspect the preview.'}], 'steps': [
            {'number': 1, 'section': 'Choose a plane', 'caption': 'Choose XY.', 'file': '01.png'},
            {'number': 2, 'section': 'Apply', 'caption': 'Click Extrude.', 'file': '02.png'}]}
    text = render_guide(steps, library[1]['features']['extrude'])
    assert '[Choose a plane](#choose-a-plane)' in text
    assert text.index('## Choose a plane') < text.index('](01.png)') < text.index('## Apply') < text.index('](02.png)')
    assert 'Numbered arrows' in text


def test_cli_status_and_write_ledger_never_refreshes_baseline(library, monkeypatch, capsys):
    monkeypatch.setattr(cli, 'REPO', library[0])
    manifest = (library[2] / 'manifest.json').read_bytes()
    assert cli.main([]) == 0
    assert cli.main(['--require-all']) == 1
    (library[0] / 'src/tool.js').write_text('changed')
    assert cli.main(['--write-ledger']) == 1
    assert (library[2] / 'manifest.json').read_bytes() == manifest
    capsys.readouterr()
    assert cli.main(['--json']) == 1
    assert json.loads(capsys.readouterr().out)['guides'][0]['state'] == 'stale'


def test_replace_refuses_concurrent_edits(tmp_path):
    output, stage = tmp_path / 'guide', tmp_path / 'stage'
    output.mkdir()
    stage.mkdir()
    (output / 'README.md').write_text('old')
    expected = directory_hashes(output)
    (output / 'README.md').write_text('concurrent edit')
    with pytest.raises(ValueError, match='changed'):
        promote_directory(stage, output, expected)
    assert (output / 'README.md').read_text() == 'concurrent edit'


def test_replace_rolls_back_on_failure(tmp_path, monkeypatch):
    output, stage = tmp_path / 'guide', tmp_path / 'stage'
    output.mkdir()
    stage.mkdir()
    (output / 'README.md').write_text('old')
    expected = directory_hashes(output)
    rename = Path.rename
    def fail_stage(self, target):
        if self == stage:
            raise OSError('injected failure')
        return rename(self, target)
    monkeypatch.setattr(Path, 'rename', fail_stage)
    with pytest.raises(OSError, match='injected'):
        promote_directory(stage, output, expected)
    assert (output / 'README.md').read_text() == 'old'
    assert not list(tmp_path.glob('.guide-backup-*'))


def test_successful_replace_removes_backup(tmp_path):
    output, stage = tmp_path / 'guide', tmp_path / 'stage'
    output.mkdir()
    stage.mkdir()
    (output / 'README.md').write_text('old')
    (stage / 'README.md').write_text('new')
    promote_directory(stage, output, directory_hashes(output))
    assert (output / 'README.md').read_text() == 'new'
    assert not list(tmp_path.glob('.guide-backup-*'))


@pytest.mark.parametrize('guide_id', ['bend', 'twist'])
def test_deformation_html_uses_own_assets_and_scope(library, monkeypatch, guide_id):
    from scripts import render_feature_guide_html as html
    root, _, _ = library
    directory = root / GUIDES / guide_id
    directory.mkdir()
    (directory / 'steps.json').write_text(json.dumps({
        'title': 'Bend', 'sections': [{'title': 'Apply', 'body': 'Review the bend.'}],
        'steps': [{'number': 1, 'section': 'Apply', 'caption': 'Click Apply.', 'file': '01.png'}],
    }))
    (directory / 'manifest.json').write_text(json.dumps({
        'introduction': 'Bend the bundle.', 'covered_workflows': ['Set the bend angle'],
        'captured_at': '2026-11-12T10:00:00-07:00',
    }))
    monkeypatch.setattr(html, 'REPO', root)
    result = html.render(guide_id)
    assert f'src="{guide_id}/01.png"' in result
    assert f'href="{guide_id}/example.nadoc"' in result
    assert 'Set the bend angle' in result
    assert 'extrude/' not in result
    assert 'deformed continuation' not in result


def test_multiple_lessons_keep_inventory_and_check_each_baseline(library):
    import shutil
    from scripts.feature_guides import select_guide
    root, catalog, original = library
    extra = {**catalog['features']['extrude'], 'guide': 'continuation',
             'covered_workflows': ['Continue a bundle']}
    catalog['features']['extrude']['additional_guides'] = [extra]
    save_catalog(library)
    target = original.parent / 'continuation'
    shutil.copytree(original, target)
    manifest = json.loads((target / 'manifest.json').read_text())
    manifest.update(guide='continuation', covered_workflows=extra['covered_workflows'])
    (target / 'manifest.json').write_text(json.dumps(manifest))
    report = inspect_guides(root)
    assert report['inventory_problems'] == []
    assert [r['state'] for r in report['guides']] == ['current', 'current', 'not-created']
    assert report['guides'][1]['feature_id'] == 'extrude'
    assert select_guide(catalog, 'extrude', 'continuation')['guide'] == 'continuation'
    assert '[continuation](continuation/README.md)' in render_ledger(root)
    with pytest.raises(ValueError, match='Unknown guide'):
        select_guide(catalog, 'extrude', 'missing')
    (target / '01.png').write_bytes(b'changed')
    assert [r['state'] for r in inspect_guides(root)['guides']][:2] == ['current', 'broken']


def test_additional_guide_paths_are_validated(library):
    from scripts.feature_guides import load_catalog
    library[1]['features']['extrude']['additional_guides'] = [{'guide': '../outside'}]
    save_catalog(library)
    with pytest.raises(ValueError, match='relative'):
        load_catalog(library[0])
