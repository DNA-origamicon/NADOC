"""One bounded presentation field survives the owned immutable geometry lifecycle."""
from copy import deepcopy
import pytest
from fastapi import HTTPException

from backend.api import part_immutable_revision as revisions
from backend.api import part_immutable_geometry_host as geometry
from backend.api import part_deformation_preview_sessions as preview
from backend.api import part_view_volume_preservation as contract
from backend.api.part_immutable_preservation import preservation_digest
from backend.core.models import ViewVolume
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import digest
from tests.test_part_immutable_geometry_host import document as document, saved
from tests.test_part_immutable_deformation_preview import cleanup as cleanup, install
from tests.test_part_deformation_preview_sessions import update
from tests.test_part_deformation_preview import patch
from tests.test_part_immutable_preservation import projection


def volumes():
    return [ViewVolume(id='focus', name='Focus α', shape='hexagonal', min_corner=(-1, 2, 3),
        max_corner=(4, 5, 6), rotation=(0, 0, .70710678, .70710678),
        representation='surface', coloring='cluster', opacity=.35, outline_visible=False, enabled=False),
        ViewVolume(id='second', name='Second', min_corner=(0, 0, 0), max_corner=(1, 2, 3),
        representation='ballstick', coloring='cpk')]


def populated(document, family='bend'):
    source, origin = install(document, family)
    source.view_volumes = volumes()
    document[1].design = revisions.prepare_geometry_revision(source)
    document[1].redo.clear()
    return source, origin


def test_exact_projection_empty_compatibility_and_batch_refusal(document):
    source, _ = install(document, 'bend')
    assert preservation_digest(source) == preservation_digest(source, allow_view_volumes=True) == digest(projection(source))
    source.view_volumes = volumes()
    original = source.model_dump(mode='json')
    sealed = revisions.prepare_geometry_revision(source)
    assert revisions.materialize_revision(sealed).model_dump(mode='json') == original
    assert revisions.revision_metadata(sealed).preserved_document_sha256 == digest(projection(source))
    with pytest.raises(CommandContractError): preservation_digest(source)
    with pytest.raises(CommandContractError): revisions.prepare_revision(source)


@pytest.mark.parametrize('fault', ['list-subclass', 'count', 'model-subclass', 'extra', 'string',
    'tuple', 'finite', 'bool-number', 'opacity', 'quaternion', 'bounds', 'schema'])
def test_malformed_or_unbounded_records_refuse_before_serialization(monkeypatch, fault):
    records = volumes()
    if fault == 'list-subclass': records = type('Unexpected', (list,), {})(records)
    elif fault == 'count': records *= contract.MAX_VOLUMES
    elif fault == 'model-subclass': records[0] = type('Unexpected', (ViewVolume,), {})(**records[0].model_dump())
    elif fault == 'extra': records[0].__dict__['extra'] = 'unreviewed'
    elif fault == 'string': records[0].name = 'x' * (contract.MAX_STRING + 1)
    elif fault == 'tuple': records[0].min_corner = [0., 0., 0.]
    elif fault == 'finite': records[0].min_corner = (float('nan'), 0., 0.)
    elif fault == 'bool-number': records[0].opacity = True
    elif fault == 'opacity': records[0].opacity = 2.
    elif fault == 'quaternion': records[0].rotation = (0., 0., 0., 0.)
    elif fault == 'bounds': records[0].max_corner = records[0].min_corner
    else: monkeypatch.setattr(ViewVolume, '__pydantic_fields__', {**ViewVolume.model_fields, 'extra': None})
    monkeypatch.setattr(ViewVolume, 'model_dump', lambda *a, **k: pytest.fail('Serialized before admission'))
    with pytest.raises(CommandContractError) as error: contract.projection(records)
    assert error.value.code == 'unsupported_revision_preservation'


def test_exact_limit_and_order_are_preserved():
    records = [volumes()[i % 2] for i in range(contract.MAX_VOLUMES)]
    actual = contract.projection(records)
    assert len(actual) == contract.MAX_VOLUMES
    assert digest(actual) == digest([v.model_dump(mode='json') for v in records])
    assert digest(actual) != digest(list(reversed(actual)))


@pytest.mark.parametrize('family', ['bend', 'twist'])
def test_real_preview_apply_preserves_records_and_exact_undo(document, monkeypatch, family):
    source, origin = populated(document, family)
    before = document[1].design
    original_decode = revisions._decoded_exact
    def no_source_decode(payload, checkpoint):
        assert payload != before.payload, 'Parent decoded canonical source'
        return original_decode(payload, checkpoint)
    monkeypatch.setattr(revisions, '_decoded_exact', no_source_decode)
    opened = preview.prepare(origin)
    receipt = preview.apply(update(opened, params=patch(family)))
    after = document[1].design
    expected = [v.model_dump(mode='json') for v in source.view_volumes]
    assert receipt['revision'] == 8 and after is not before
    assert [v.model_dump(mode='json') for v in revisions.materialize_revision(after).view_volumes] == expected
    geometry.history('undo', expected_design_id=source.id, expected_revision=8)
    assert document[1].design is before
    geometry.history('redo', expected_design_id=source.id, expected_revision=9)
    assert document[1].design is after


@pytest.mark.parametrize('fault', ['drop', 'change', 'reorder'])
def test_candidate_preservation_mismatch_never_publishes(document, monkeypatch, fault):
    source, origin = populated(document)
    opened = preview.prepare(origin)
    before = saved(document[1])
    original = geometry.decode_candidate
    def changed(packet):
        candidate, authoring, recipe = original(packet)
        candidate.view_volumes = deepcopy(candidate.view_volumes)
        if fault == 'drop': candidate.view_volumes = []
        elif fault == 'change': candidate.view_volumes[0].enabled = True
        else: candidate.view_volumes.reverse()
        return candidate, authoring, recipe
    monkeypatch.setattr(geometry, 'decode_candidate', changed)
    with pytest.raises(HTTPException) as error: preview.apply(update(opened, params=patch('bend')))
    assert error.value.detail['code'] == 'revision_preservation_changed'
    assert saved(document[1]) == before
