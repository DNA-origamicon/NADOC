"""An exported example must keep and verify both real part histories."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from backend.api import headless_build as parts
from backend.api.part_cadnano_import_recording import prepare_ordinary
from backend.core.cadnano import export_cadnano
from backend.core.models import LatticeType
from experiments.recorded_review_process import ProcessRequired
from scripts.agent_structure_guard import publish
from scripts.guide_cadnano_audit import publish_source


@pytest.fixture
def family():
    with TemporaryDirectory(prefix='__e2e__cadnano-audit-') as root:
        root = Path(root)
        with parts.scratch_session(LatticeType.HONEYCOMB):
            source = parts.create_bundle([[0, 0], [1, 0]], 21, lattice=LatticeType.HONEYCOMB)
        source_file = root / 'original.nadoc'
        publish(source, source_file)
        raw = json.dumps(export_cadnano(source), separators=(',', ':')).encode()
        exported = root / 'export.json'
        exported.write_bytes(raw)
        (imported, _), excluded = prepare_ordinary(raw.decode())
        assert excluded is None
        destination = root / 'published'
        destination.mkdir()
        yield source_file, imported, exported, destination


def test_source_history_and_exact_export_are_replayed(family):
    result = publish_source(*family)
    assert result['status'] == 'verified'
    assert result['upstream_history_preserved']
    assert result['import_operation'] == 'cadnano-import'
    assert result['recovery_snapshots_used'] is False
    assert (family[-1] / 'source.nadoc').is_file()


def test_changed_export_is_rejected(family):
    # Same molecular JSON, different bytes: transport evidence must be exact.
    family[2].write_bytes(family[2].read_bytes() + b' ')
    with pytest.raises(ProcessRequired, match='download differs'):
        publish_source(*family)


def test_different_recorded_import_is_rejected(family):
    data = json.loads(family[2].read_bytes())
    data['name'] = 'Different export source'
    (other, _), _ = prepare_ordinary(json.dumps(data))
    with pytest.raises(ProcessRequired, match='does not pin'):
        publish_source(family[0], other, family[2], family[3])
