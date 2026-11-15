"""Guide assembly publication must detect unrecorded structure and upstream edits."""
import pytest
from backend.api import headless_build as parts, headless_assembly_build as assemblies
from backend.api.routes_scaffold_routing import route_for_polymerization_endpoint
from backend.api import state as design_state
from backend.core.models import Assembly, LatticeType
from experiments.recorded_review_process import ProcessRequired
from scripts.guide_assembly_audit import audit, publish


@pytest.fixture(autouse=True)
def cleanup_examples(tmp_path):
    yield
    for path in tmp_path.glob("*.nass"):
        path.unlink()


@pytest.fixture
def polymer():
    with parts.scratch_session(LatticeType.HONEYCOMB):
        parts.create_bundle([[0,1],[1,1],[1,2],[1,3],[0,3],[0,2]], 42, lattice=LatticeType.HONEYCOMB)
        parts.auto_scaffold()
        parts.full_autostaple()
        route_for_polymerization_endpoint()
        design = design_state.get_or_404()
    with assemblies.assembly_scratch_session():
        assembly = assemblies.add_inline_instance(design)
        return assemblies.polymerize_periodic(assembly.instances[0].id, count=3)


def test_saved_polymer_replays_and_reopens(polymer, tmp_path):
    proof = publish(polymer, tmp_path / 'example.nass')
    assert proof['commands'] == 2
    assert proof['instances'] == 3
    assert proof['joints'] == 2
    assert proof['recovery_snapshots_used'] is False
    assert audit(Assembly.from_json((tmp_path / 'example.nass').read_text()), tmp_path)['status'] == 'verified'


def test_unrecorded_instance_transform_refused(polymer, tmp_path):
    changed = polymer.model_copy(deep=True)
    changed.instances[-1].transform.values[3] += 1
    with pytest.raises(ProcessRequired, match='differs'):
        publish(changed, tmp_path / 'bad.nass')
    assert not (tmp_path / 'bad.nass').exists()


def test_missing_command_refused(polymer, tmp_path):
    changed = polymer.model_copy(deep=True)
    changed.feature_log = changed.feature_log[:1]
    with pytest.raises(ProcessRequired, match='differs'):
        audit(changed, tmp_path)


def test_unrecorded_upstream_change_refused(polymer, tmp_path):
    changed = polymer.model_copy(deep=True)
    changed.instances[0].source.design.helices[0].length_bp += 1
    with pytest.raises(ProcessRequired):
        audit(changed, tmp_path)
