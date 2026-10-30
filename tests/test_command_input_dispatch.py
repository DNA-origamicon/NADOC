"""History command identity precedence survives lazy fallback lookup."""
from types import SimpleNamespace
import pytest
from backend.core.models import SnapshotLogEntry, MinorMutationLogEntry
from backend.core.part_overlay_commands import command_input


@pytest.mark.parametrize('entry,expected', [
    (SnapshotLogEntry(op_kind='nick', label='Nick', params={'x': 1}), ('nick', {'x': 1})),
    (MinorMutationLogEntry(op_subtype='nick', label='Nick', params={'x': 2}), ('nick', {'x': 2})),
    (SimpleNamespace(feature_type='future', op_kind=None, op_subtype='ignored', params={}), (None, {})),
    (SimpleNamespace(feature_type='future', op_subtype='legacy'), ('legacy', {})),
    (SimpleNamespace(feature_type='future'), ('future', {})),
])
def test_command_identity_and_parameters(entry, expected):
    assert command_input(entry) == expected
