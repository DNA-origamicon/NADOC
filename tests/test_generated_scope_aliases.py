"""Generated local identity collisions must fail before invoking a builder."""

import pytest

from backend.api.generated_native_scope import execute as scoped_execute, namespaced
from backend.api.part_proof_commands import execute
from backend.core.models import Design, Helix, Vec3


GROUP = "00000000-0000-0000-0000-000000000001"


def helix(identity, length):
    return Helix(
        id=identity, length_bp=length,
        axis_start=Vec3(x=0, y=0, z=0), axis_end=Vec3(x=0, y=0, z=3),
    )


def update_params(retained):
    return {
        "_proof_version": 1, "helix_id": retained, "length_bp": 30,
        "axis_start": {"x": 0, "y": 0, "z": 0},
        "axis_end": {"x": 0, "y": 0, "z": 9},
        "_generated_scope": {"group_id": GROUP, "input_ids": [retained]},
    }


def test_retained_generated_alias_cannot_edit_the_wrong_helix(monkeypatch):
    from backend.api import part_structural_commands

    design = Design(helices=[helix("raw", 10), helix(namespaced("raw", GROUP), 20)])
    before = design.model_dump_json()

    def forbidden(*_args):
        pytest.fail("Ambiguous identity reached the native builder")

    monkeypatch.setattr(part_structural_commands, "build", forbidden)
    with pytest.raises(ValueError, match="identity aliases are ambiguous"):
        execute("helix-update", design, update_params("raw"))
    assert design.model_dump_json() == before


def test_different_namespace_markers_cannot_alias_one_local_identity():
    design = Design(helices=[
        helix(f"gen_{GROUP}_raw", 10), helix(f"__np__gen_{GROUP}_raw", 20),
    ])
    before = design.model_dump_json()

    def forbidden(*_args):
        pytest.fail("Ambiguous namespace markers reached the native builder")

    with pytest.raises(ValueError, match="identity aliases are ambiguous"):
        scoped_execute("helix-update", design, {
            "_generated_scope": {"group_id": GROUP, "input_ids": []},
        }, forbidden)
    assert design.model_dump_json() == before


def test_unambiguous_retained_target_and_generated_neighbor_remain_distinct():
    generated = namespaced("raw", GROUP)
    design = Design(helices=[helix("retained", 10), helix(generated, 20)])
    before = design.model_dump_json()
    result = execute("helix-update", design, update_params("retained"))
    assert {h.id: h.length_bp for h in result.helices} == {
        "retained": 30, generated: 20,
    }
    assert design.model_dump_json() == before
