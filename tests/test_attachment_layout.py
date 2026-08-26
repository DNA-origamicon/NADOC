"""Parametric named-interface layout: pure spec → route-backed assembly → oracle."""

from __future__ import annotations

import pytest

from backend.api import assembly_state
from backend.api import headless_assembly_build as hab
from backend.core.attachment_layout import linear_attachment_layout
from backend.core.models import ConnectionType
from tests.automation_harness import assert_attachment_layout
from tests.conftest import make_6hb_design


def test_linear_layout_generates_normalized_mixed_interface_specs():
    sites = linear_attachment_layout(
        4,
        pitch_nm=3.5,
        origin=(1, 2, 3),
        direction=(2, 0, 0),
        normal=(0, 0, 4),
        label_prefix="track",
        connection_types=(ConnectionType.BIOTIN, ConnectionType.TOEHOLD),
        clearances_nm=(1.25, 2.0),
    )
    assert [s.label for s in sites] == ["track_0", "track_1", "track_2", "track_3"]
    assert [s.position for s in sites] == [
        (1.0, 2.0, 3.0),
        (4.5, 2.0, 3.0),
        (8.0, 2.0, 3.0),
        (11.5, 2.0, 3.0),
    ]
    assert [s.connection_type for s in sites] == [
        ConnectionType.BIOTIN,
        ConnectionType.TOEHOLD,
        ConnectionType.BIOTIN,
        ConnectionType.TOEHOLD,
    ]
    assert [s.clearance_nm for s in sites] == [1.25, 2.0, 1.25, 2.0]
    assert all(s.normal == (0.0, 0.0, 1.0) for s in sites)


def test_mixed_linear_layout_materializes_and_survives_nass_roundtrip():
    with hab.assembly_scratch_session():
        hab.new_assembly("mixed-interface rod")
        assembly = hab.add_inline_instance(make_6hb_design(), name="6hb rod")
        instance_id = assembly.instances[0].id
        result = hab.add_linear_attachment_layout(
            instance_id,
            5,
            pitch_nm=4.0,
            origin=(0.0, 1.0, 0.0),
            direction=(1.0, 0.0, 0.0),
            normal=(0.0, 1.0, 0.0),
            label_prefix="surface",
            connection_types=("BIOTIN", "TOEHOLD"),
            clearances_nm=(1.0, 1.5),
        )
        measured = assert_attachment_layout(
            result["assembly"], instance_id, result["sites"]
        )
        assert measured["count"] == 5
        assert measured["spacing_nm"] == pytest.approx(4.0)
        assert measured["roundtrip"]["count"] == 5


def test_attachment_layout_oracle_detects_geometry_drift():
    with hab.assembly_scratch_session():
        hab.new_assembly("red path")
        assembly = hab.add_inline_instance(make_6hb_design(), name="rod")
        instance_id = assembly.instances[0].id
        result = hab.add_linear_attachment_layout(instance_id, 3, pitch_nm=2.0)
        current = assembly_state.get_or_404()
        inst = current.instances[0]
        damaged_sites = list(inst.interface_points)
        damaged_sites[1] = damaged_sites[1].model_copy(
            update={"position": damaged_sites[1].position.model_copy(update={"x": 9.0})}
        )
        damaged = current.model_copy(
            update={
                "instances": [
                    inst.model_copy(update={"interface_points": damaged_sites})
                ]
            }
        )
        with pytest.raises(AssertionError):
            assert_attachment_layout(
                damaged, instance_id, result["sites"], roundtrip=False
            )
