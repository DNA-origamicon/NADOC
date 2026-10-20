"""Exactness guards for the S61 preview-latency changes (October 19, 2026)."""

import gc
import json
import math

import numpy as np
import pytest

from backend.api.part_deformation_preview_dto import _encoded_size
from backend.core.gc_pause import paused_gc
from backend.core.part_command_errors import CommandContractError
from backend.core.part_dna_comparison import _finite_bulk


def test_encoded_size_matches_compact_json_and_refuses_nonfinite():
    value = {"a": [1.5, 2, None, "x"], "b": {"c": [0.1, -3.25]}, "d": True}
    assert _encoded_size(value) == len(json.dumps(value, separators=(",", ":")))
    for bad in (math.nan, math.inf, np.float64("nan")):
        with pytest.raises(ValueError):
            _encoded_size({"nested": [{"x": bad}]})
    assert _encoded_size({"n": np.float64(2.5)}) == len('{"n":2.5}')


def test_trusted_subtrees_are_not_rewalked_but_still_counted():
    trusted = [[1.0, math.nan]]  # a validated pane would never hold NaN; proves the skip
    assert _encoded_size({"rows": trusted, "k": 1}, trusted=trusted) > 0
    with pytest.raises(ValueError):
        _encoded_size({"rows": trusted})


def test_bulk_finite_check_keeps_exact_type_rules():
    _finite_bulk([0, 1.5, -2])
    for bad in ([True], ["1.0"], [None], [math.nan], [math.inf]):
        with pytest.raises(CommandContractError):
            _finite_bulk(bad)


def test_gc_pause_is_reentrant_and_restores_previous_state():
    assert gc.isenabled()
    with paused_gc():
        assert not gc.isenabled()
        with paused_gc():
            assert not gc.isenabled()
        assert not gc.isenabled()
    assert gc.isenabled()
    gc.disable()
    try:
        with paused_gc():
            pass
        assert not gc.isenabled()  # never enables collection the caller had disabled
    finally:
        gc.enable()


def test_preview_projection_bounds_keep_native_values():
    from backend.core.part_dna_comparison import project_for_deformation_preview
    from tests.test_part_deformation_preview import native_source

    design = native_source("bend")
    pane = project_for_deformation_preview(design)
    from backend.core.part_dna_comparison_codec import unpack_records
    points = [r[f] for r in unpack_records(pane["nucleotides"]) for f in ("backbone_position", "base_position", "slab_position")]
    for axis in pane["helix_axes"]:
        points += [axis["start"], axis["end"], *axis["samples"]]
        for segment in axis["segments"]:
            points += [segment["start"], segment["end"], *segment.get("samples", ())]
    assert pane["bounds_nm"]["minimum"] == [min(p[i] for p in points) for i in range(3)]
    assert pane["bounds_nm"]["maximum"] == [max(p[i] for p in points) for i in range(3)]


def test_loopback_preview_responses_skip_gzip_and_remote_ones_keep_it():
    from types import SimpleNamespace
    from backend.api.routes_part_deformation_preview import _loopback

    assert _loopback(SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")))
    assert _loopback(SimpleNamespace(client=SimpleNamespace(host="::1")))
    assert not _loopback(SimpleNamespace(client=SimpleNamespace(host="192.168.1.20")))
    assert not _loopback(SimpleNamespace(client=None))


@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_session_delta_restores_exact_full_projection_and_checks_coordinates(kind, monkeypatch):
    from backend.api import part_deformation_preview as native
    from backend.api import part_deformation_preview_dto as dto
    from backend.core.part_verification_capture import capture
    from tests.test_part_deformation_preview import native_source

    prepared = native.prepare_from_capture(capture(native_source(kind), preserve_entry_types=True), "edited-feature")
    prefix = prepared.copy_prefix()
    original = native.evaluate(prepared, {})
    cache = {}
    opened = dto.prepare_display(prefix, original, envelope={"lease_id": "lease"}, display_cache=cache)
    patch = {"params": ({"curvature_deg_per_bp": .6, "direction_deg": 15} if kind == "bend" else {"total_degrees": 40})}
    patch["params"]["kind"] = kind
    evaluated = native.evaluate(prepared, patch)
    full = dto.evaluate_display(prefix, evaluated, envelope={"lease_id": "lease"})
    delta = dto.evaluate_display(prefix, evaluated, envelope={"lease_id": "lease"}, display_cache=cache)
    packed = delta["candidate"]["nucleotides"]
    assert packed.pop("rows_ref") == "lease"
    packed["rows"] = opened["before"]["nucleotides"]["rows"]
    assert delta == full
    assert dto.evaluate_display(prefix, evaluated, envelope={"lease_id": "other"}, display_cache=cache)["candidate"] == full["candidate"]
    cache["rows"][0][0] = "changed-owner"
    assert dto.evaluate_display(prefix, evaluated, envelope={"lease_id": "lease"}, display_cache=cache) == full

    from backend.core import design_geometry
    real_geometry = design_geometry._geometry_for_design

    def corrupt(design):
        records = real_geometry(design)
        records[0]["slab_position"][0] += 1
        return records

    monkeypatch.setattr(design_geometry, "_geometry_for_design", corrupt)
    with pytest.raises(CommandContractError, match="slab|registration"):
        dto.evaluate_display(prefix, evaluated, envelope={"lease_id": "lease"}, display_cache=cache)


def test_cached_occupancy_reuses_only_equal_topology_and_checks_new_references():
    from backend.core.part_dna_comparison_contract import inventory
    from tests.test_part_dna_comparison import small

    original = small("bend")
    cached = inventory(original)
    changed = original.model_copy(deep=True)
    changed.deformations[0].params.curvature_deg_per_bp = 3
    assert inventory(changed, previous=cached).sites is cached.sites
    changed.strands[0].domains[0].end_bp -= 1
    assert inventory(changed, previous=cached).sites == inventory(changed).sites
    assert inventory(changed, previous=cached).sites is not cached.sites
    changed = original.model_copy(deep=True)
    changed.deformations[0].affected_helix_ids = ["missing"]
    with pytest.raises(CommandContractError, match="unresolved"):
        inventory(changed, previous=cached)
