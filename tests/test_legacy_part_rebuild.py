"""Legacy reconstruction must preserve content and use independently replayable operations."""
import pytest

from backend.api import headless_build as hb
from backend.core.models import LatticeType
from scripts.rebuild_legacy_part import rebuild, verify_equivalence
from scripts.agent_structure_guard import audit


def bundle(length):
    with hb.scratch_session():
        return hb.create_bundle([(0, 0), (0, 1)], length, lattice=LatticeType.HONEYCOMB)


def test_rebuild_records_commands_and_leaves_source_unchanged():
    source = bundle(21)
    before = source.model_dump_json()
    result = rebuild(source)
    assert source.model_dump_json() == before
    assert result.id != source.id
    assert result.feature_log[0].id != source.feature_log[0].id
    assert result.recipe_root.kind == 'empty'
    assert audit(result)['status'] == 'verified'
    assert verify_equivalence(source, result)['molecular_content_equal']


def test_reconstruction_comparison_rejects_different_molecular_content():
    with pytest.raises(ValueError, match='reconstructed molecular content differs'):
        verify_equivalence(bundle(21), bundle(22))
