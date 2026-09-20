"""The scientific opt-in must survive broad, narrow and legacy selections."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.conftest import pytest_collection_modifyitems
from tests.scientific_validation import CAMPAIGNS, campaign_reason


@pytest.mark.parametrize("scientific", [False, True])
@pytest.mark.parametrize("legacy", ["", "1"])
def test_campaign_gate(scientific, legacy, monkeypatch):
    monkeypatch.setenv("NADOC_RUN_OXDNA_SLOW", legacy)

    class Item:
        cls = None
        def __init__(self, nodeid):
            self.nodeid = nodeid
            self.name = nodeid.split("::")[-1]
            self.module = SimpleNamespace(__name__=nodeid.split("/")[-1].split(".")[0])
            self.markers = {}
        def add_marker(self, marker):
            self.markers[marker.name] = marker
        def get_closest_marker(self, name):
            return self.markers.get(name)

    ordinary = Item("tests/test_openmm_checker.py::TestOpenMMSmoke::test_start")
    campaign = Item("tests/test_skip_twist_tuning_production.py::test_full_scale_converges_3x6x400")
    decorated = Item("tests/test_future_campaign.py::test_physics")
    decorated.add_marker(pytest.mark.scientific)
    deselected = []
    config = SimpleNamespace(
        getoption=lambda option: scientific,
        hook=SimpleNamespace(pytest_deselected=lambda items: deselected.extend(items)),
    )
    items = [ordinary, campaign, decorated]
    pytest_collection_modifyitems(config, items)
    assert items == ([campaign, decorated] if scientific else [ordinary])
    assert len(items) + len(deselected) == 3
    assert campaign.get_closest_marker("slow")


def test_inventory_entries_exist():
    """Renaming/deleting a campaign must not silently return it to normal tests."""
    for selector in CAMPAIGNS:
        module, *components = selector.split("::")
        tree = ast.parse((Path(__file__).parent / f"{module}.py").read_text())
        for component in components:
            tree = next(node for node in tree.body if getattr(node, "name", None) == component)
        assert campaign_reason(f"tests/{module}.py" + "".join(f"::{c}" for c in components))


def test_parameter_ids_cannot_change_classification():
    assert campaign_reason("tests/test_chudoba_hmc.py::test_hmc_harmonic_bond_distribution[cpu]")
    assert not campaign_reason("tests/test_other.py::test_start[test_skip_twist_tuning_production]")
