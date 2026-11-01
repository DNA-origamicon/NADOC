"""Mixed native histories must not run experimental molecular work implicitly."""

from importlib import import_module
from types import SimpleNamespace

import pytest

from tests.conftest import pytest_collection_modifyitems


@pytest.mark.parametrize("module,function", [
    ("test_part_transform_numerical_host",
     "test_real_numerical_host_prepare_evaluate_apply_undo_reload_and_cold_proof"),
    ("test_part_transform_numerical_history",
     "test_numerical_source_is_a_complete_native_recipe_before_any_solver"),
    ("test_native_schema_compatibility",
     "test_spawned_current_pins_reproduce_and_retired_schema_pins_refuse"),
])
@pytest.mark.parametrize("scientific", [False, True])
def test_mixed_native_parameter_selection(module, function, scientific):
    """Exercise actual parameter marks through the collection gate, without solvers."""
    source = import_module(f"tests.{module}")
    target = getattr(source, function)
    parameters = next(mark.args[1] for mark in target.pytestmark if mark.name == "parametrize")

    class Item:
        cls = None

        def __init__(self, parameter):
            values = getattr(parameter, "values", (parameter,))
            family = values[0]
            self.experimental = family == "cpd" or getattr(family, "__name__", "") == "native_cpd_prefix"
            # Deliberately unrelated IDs: execution policy belongs to the
            # parameter declaration, never the display label's spelling.
            self.name = f"{function}[variant-{len(items)}]"
            self.nodeid = f"tests/{module}.py::{self.name}"
            self.module = source
            self.markers = {mark.name: mark for mark in target.pytestmark}
            for mark in getattr(parameter, "marks", ()):
                self.add_marker(mark)

        def add_marker(self, marker):
            self.markers[marker.name] = marker

        def get_closest_marker(self, name):
            return self.markers.get(name)

    items = []
    for parameter in parameters:
        items.append(Item(parameter))
    expected = [item for item in items if item.experimental == scientific]
    assert expected
    deselected = []
    config = SimpleNamespace(
        getoption=lambda _: scientific,
        hook=SimpleNamespace(pytest_deselected=lambda items: deselected.extend(items)),
    )
    pytest_collection_modifyitems(config, items)
    assert items == expected
    assert len(items) + len(deselected) == len(parameters)
    assert all(item.get_closest_marker("slow") for item in items if item.experimental)
