"""Loadout (feature-timeline branch) naming + independence.

Regression coverage for the duplicate-"Loadout 1" bug: creating a loadout while
the implicit first loadout was showing produced two identically named branches.
Names are now picked by the backend as the lowest free "Loadout N", so the
frontend never needs to compute (and mis-compute) a name.
"""

from backend.api.crud import design_state
from backend.api.routes_design_loadouts import (
    LoadoutCreateBody,
    create_loadout,
    delete_loadout,
    select_loadout,
    activate_last_editable_loadout,
)
from backend.api import state as design_state_api
from backend.core.design_loadouts import encode_snapshot, next_default_name
from backend.core.models import Design, DeformationLogEntry, DesignLoadout
from fastapi import HTTPException
import pytest


def _fl(marker: str) -> DeformationLogEntry:
    """A minimal, valid feature-log entry tagged by deformation_id."""
    return DeformationLogEntry(deformation_id=marker, kind="bend", label=marker)


def _names() -> list[str]:
    return [l.name for l in design_state.get_or_404().loadouts]


def test_auto_loadout_name_skips_taken_numbers():
    from backend.core.models import DesignLoadout

    loadouts = [DesignLoadout(name="Loadout 1"), DesignLoadout(name="Loadout 3")]
    # 1 taken, 2 free -> "Loadout 2"; nothing should collide.
    assert next_default_name(loadouts) == "Loadout 2"
    assert next_default_name([]) == "Loadout 1"


def test_first_create_from_implicit_does_not_duplicate_loadout_1():
    # No loadouts yet -> frontend shows the implicit "Loadout 1"; the "+" button
    # now sends NO name, so the backend must materialise "Loadout 1" + "Loadout 2".
    design_state.set_design(
        Design().copy_with(feature_log=[_fl("A")], feature_log_cursor=0)
    )
    create_loadout(LoadoutCreateBody(name=None))
    assert _names() == ["Loadout 1", "Loadout 2"]


def test_repeated_creates_never_collide():
    design_state.set_design(Design())
    for _ in range(4):
        create_loadout(LoadoutCreateBody(name=None))
    names = _names()
    assert names == ["Loadout 1", "Loadout 2", "Loadout 3", "Loadout 4", "Loadout 5"]
    assert len(names) == len(set(names))


def test_create_after_delete_reuses_freed_number_without_collision():
    design_state.set_design(Design())
    create_loadout(LoadoutCreateBody(name=None))  # -> [L1, L2]
    create_loadout(LoadoutCreateBody(name=None))  # -> [L1, L2, L3]
    loadouts = design_state.get_or_404().loadouts
    l2_id = loadouts[1].id
    delete_loadout(l2_id)  # -> [L1, L3]
    assert sorted(_names()) == ["Loadout 1", "Loadout 3"]
    create_loadout(LoadoutCreateBody(name=None))  # "Loadout 2" is free again
    names = _names()
    assert "Loadout 2" in names
    assert len(names) == len(set(names))  # still no duplicates


def test_loadouts_have_independent_feature_logs():
    # Branch from a design carrying [A, B]; both loadouts start as copies.
    design_state.set_design(
        Design().copy_with(feature_log=[_fl("A"), _fl("B")], feature_log_cursor=1)
    )
    create_loadout(LoadoutCreateBody(name=None))  # now active = "Loadout 2"
    loadouts = design_state.get_or_404().loadouts
    l1_id, l2_id = loadouts[0].id, loadouts[1].id

    # Edit inside Loadout 2: replace B with C.
    cur = design_state.get_or_404()
    design_state.set_design(
        cur.copy_with(feature_log=[_fl("A"), _fl("C")], feature_log_cursor=1)
    )

    # Switching to Loadout 1 must restore its untouched [A, B]...
    select_loadout(l1_id)
    assert [e.deformation_id for e in design_state.get_or_404().feature_log] == [
        "A",
        "B",
    ]
    # ...and switching back must preserve Loadout 2's edited [A, C].
    select_loadout(l2_id)
    assert [e.deformation_id for e in design_state.get_or_404().feature_log] == [
        "A",
        "C",
    ]


def test_protected_simulation_loadout_rejects_edits_and_returns_to_last_editable():
    design_state.set_design(Design().copy_with(feature_log=[_fl("editable")]))
    create_loadout(LoadoutCreateBody(name="Working"))
    working = design_state.get_or_404()
    working_id = working.active_loadout_id
    payload, size = encode_snapshot(
        working.copy_with(feature_log=[_fl("simulation")])
    )
    sim = DesignLoadout(
        name="Simulation",
        design_snapshot_gz_b64=payload,
        snapshot_size_bytes=size,
        protected=True,
        simulation_engine="oxdna",
        simulation_job_id="job-1",
    )
    protected = working.copy_with(
        feature_log=[_fl("simulation")],
        loadouts=[*working.loadouts, sim],
        active_loadout_id=sim.id,
        last_editable_loadout_id=working_id,
    )
    design_state_api.set_design_branch(protected)

    with pytest.raises(HTTPException) as exc:
        design_state_api.mutate_and_validate(lambda d: d.feature_log.append(_fl("bad")))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "protected_simulation_loadout"
    assert [e.deformation_id for e in design_state.get_or_404().feature_log] == [
        "simulation"
    ]

    activate_last_editable_loadout()
    restored = design_state.get_or_404()
    assert restored.active_loadout_id == working_id
    design_state_api.mutate_and_validate(lambda d: d.feature_log.append(_fl("new")))
    assert [e.deformation_id for e in design_state.get_or_404().feature_log] == [
        "editable",
        "new",
    ]
