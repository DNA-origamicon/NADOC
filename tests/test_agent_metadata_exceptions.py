"""A reviewed title cannot excuse a changed document or another replay defect."""
from copy import deepcopy
from types import SimpleNamespace

from backend.core.document_operations import content_digest
from scripts import agent_metadata_exceptions as exceptions


def test_exception_requires_exact_document_and_exact_old_title(monkeypatch):
    raw = {'metadata': {'name': 'D003'}, 'commands': ['original'], 'molecular': [1, 2]}
    design = SimpleNamespace(model_dump=lambda **kw: deepcopy(raw))
    monkeypatch.setattr(exceptions, '_D003_DIGESTS', {content_digest(raw)})
    replayed = {'metadata': {'name': exceptions._OLD_NAME, 'author': 'original'}, 'molecular': [1, 2]}
    before = deepcopy(replayed)
    reviewed = exceptions.reviewed_replay_value(design, replayed)
    assert reviewed == {**replayed, 'metadata': {'name': 'D003', 'author': 'original'}}
    assert replayed == before
    raw['commands'].append('unapproved')
    assert exceptions.reviewed_replay_value(design, replayed) == replayed
    raw['commands'].pop()
    replayed['metadata']['name'] = 'Another unrecorded title'
    assert exceptions.reviewed_replay_value(design, replayed) == replayed


def test_exception_does_not_hide_other_replay_differences(monkeypatch):
    raw = {'metadata': {'name': 'D003', 'author': 'original'}, 'molecular': [1, 2]}
    design = SimpleNamespace(model_dump=lambda **kw: deepcopy(raw))
    monkeypatch.setattr(exceptions, '_D003_DIGESTS', {content_digest(raw)})
    for key, value in [('author', 'unrecorded')]:
        replayed = deepcopy(raw)
        replayed['metadata'].update(name=exceptions._OLD_NAME, **{key: value})
        assert exceptions.reviewed_replay_value(design, replayed) != raw
    replayed = deepcopy(raw)
    replayed['metadata']['name'] = exceptions._OLD_NAME
    replayed['molecular'][0] = 99
    assert exceptions.reviewed_replay_value(design, replayed) != raw
    raw['molecular'][0] = 99
    assert exceptions.reviewed_replay_value(design, replayed) == replayed
