"""Incremental replay (R1): cache exactness and the deformation-independence invariants.

``DEFORMATION_INDEPENDENT`` lets a geometry-only Bend/Twist edit reuse cached
downstream routing results. That is exact only if (1) a deformation command
changes nothing but ``deformations`` and (2) every listed kind passes
deformations through and produces identical other fields for any deformation
parameters. These tests assert both on real recipes recorded by production routes.
"""

from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, state
from backend.api.part_proof_commands import execute
from backend.core import part_replay_cache as cache
from backend.core.part_history_proof import command_rows, root_design

BEND = {"kind": "bend", "curvature_deg_per_bp": 0.5, "direction_deg": 0.0}
TWIST = {"kind": "twist", "total_degrees": 30}
VARIANTS = {
    "bend": [{"params": {**BEND, "curvature_deg_per_bp": 2.0, "direction_deg": 137.0}},
             {"plane_a_bp": 5, "plane_b_bp": 110}],
    "twist": [{"params": {**TWIST, "total_degrees": -170}},
              {"plane_a_bp": 5, "plane_b_bp": 110, "params": {**TWIST, "total_degrees": 400}}],
}
# (lattice, deformation, routing steps after the deformation)
RECIPES = [
    ("HONEYCOMB", "bend", ["/design/auto-scaffold-seamless", "/design/full-autostaple"]),
    ("HONEYCOMB", "twist", ["/design/auto-scaffold-seamed", "/design/crossovers/auto", "/design/auto-break", "/design/auto-merge"]),
    ("SQUARE", "bend", ["/design/auto-scaffold-matched", "/design/full-autostaple"]),
    ("SQUARE", "twist", ["/design/auto-scaffold-seamless", "/design/auto-break"]),
]
CELLS = {"HONEYCOMB": [[0, 0], [0, 1], [1, 0], [1, 1], [2, 0], [2, 1]], "SQUARE": [[0, 0], [0, 1], [1, 0], [1, 1]]}


@pytest.fixture
def recorded(monkeypatch):
    """Record a recipe through the production routes in an isolated document."""
    from backend.api.main import app

    identity = f"replay-cache-{uuid4()}"
    headers = {"X-NADOC-Doc": identity}
    http = TestClient(app)  # no lifespan: autosave/jobs are not started

    def record(lattice, deformation, steps):
        assert http.post("/api/design", headers=headers, json={"name": "replay cache", "lattice_type": lattice}).status_code == 201
        assert http.post("/api/design/bundle", headers=headers,
                         json={"cells": CELLS[lattice], "length_bp": 126, "name": "replay cache"}).status_code == 201
        assert http.post("/api/design/deformation", headers=headers, json={
            "type": deformation, "plane_a_bp": 20, "plane_b_bp": 90,
            "params": BEND if deformation == "bend" else TWIST}).status_code == 200
        for step in steps:
            response = http.post(f"/api/{step.removeprefix('/')}" if not step.startswith("/api") else step,
                                 headers=headers, json={})
            assert response.status_code == 200, (step, response.text)
        token = doc_context.set_current_doc(identity)
        try:
            return state.get_or_404()
        finally:
            doc_context.reset_current_doc(token)

    try:
        yield record
    finally:
        state.drop_doc(identity)
        http.close()


def _replay(design, override=None):
    current = root_design(design.recipe_root, input_sources=design.input_sources)
    trace = []
    for _identity, kind, params in command_rows(design, 100):
        if kind == "deformation" and override is not None:
            params = {**params, **override}
        before = current
        current = execute(kind, current, params)
        trace.append((kind, params, before, current))
    return trace


def _fields(design, *, without=("deformations", "id")):
    return {name: getattr(design, name) for name in type(design).model_fields if name not in without}


@pytest.mark.parametrize("lattice,deformation,steps", RECIPES)
def test_listed_routing_kinds_are_independent_of_deformation_geometry(recorded, lattice, deformation, steps):
    design = recorded(lattice, deformation, steps)
    baseline = _replay(design)
    kinds = [kind for kind, *_ in baseline]
    assert {kind for kind in kinds if kind not in {"bundle-create", "deformation"}} <= cache.DEFORMATION_INDEPENDENT
    for kind, _params, before, after in baseline:
        if kind == "deformation":  # invariant 1: writes deformations only
            assert _fields(before) == _fields(after)
        elif kind in cache.DEFORMATION_INDEPENDENT:  # invariant 2a: passes deformations through
            assert before.deformations == after.deformations
    for override in VARIANTS[deformation]:
        varied = _replay(design, override)
        assert varied[1][3].deformations != baseline[1][3].deformations  # the variant really differs
        for (kind, *_rest, expected), (_, *_r, actual) in zip(baseline, varied):
            if kind in cache.DEFORMATION_INDEPENDENT:  # invariant 2b: identical other fields
                assert _fields(actual) == _fields(expected), kind


@pytest.mark.parametrize("lattice,deformation,steps", RECIPES[:2])
def test_incremental_replay_equals_cold_replay_for_geometry_edits(recorded, monkeypatch, lattice, deformation, steps):
    monkeypatch.setattr(cache, "MIN_CACHE_SECONDS", 0.0)  # cache every result in this small fixture
    design = recorded(lattice, deformation, steps)
    rows = list(command_rows(design, 100))
    chain = cache.ReplayChain.for_design(design)
    current = root_design(design.recipe_root, input_sources=design.input_sources)
    for _identity, kind, params in rows:
        current = chain.run(execute, kind, current, params)
    for override in VARIANTS[deformation]:
        cold = _replay(design, override)[-1][3]
        chain = cache.ReplayChain.for_design(design)
        incremental = root_design(design.recipe_root, input_sources=design.input_sources)
        before = dict(cache.stats)
        for _identity, kind, params in rows:
            if kind == "deformation":
                params = {**params, **override}
            incremental = chain.run(execute, kind, incremental, params)
        assert cache.stats["topology_hits"] - before["topology_hits"] == len(steps)
        assert incremental.model_dump(mode="json", exclude={"id"}) == cold.model_dump(mode="json", exclude={"id"})


def test_full_hit_returns_an_independent_copy(monkeypatch):
    from tests.test_part_deformation_preview import native_source

    monkeypatch.setattr(cache, "MIN_CACHE_SECONDS", 0.0)
    design = native_source("bend")
    rows = list(command_rows(design, 100))
    first = cache.ReplayChain.for_design(design)
    second = cache.ReplayChain.for_design(design)
    a = b = root_design(design.recipe_root, input_sources=design.input_sources)
    for _identity, kind, params in rows:
        a = first.run(execute, kind, a, params)
    for _identity, kind, params in rows:
        b = second.run(lambda *_: pytest.fail("expected a cache hit"), kind, b, params)
    assert a.model_dump(mode="json", exclude={"id"}) == b.model_dump(mode="json", exclude={"id"})
    b.helices.clear()
    assert a.helices  # mutation of a returned copy never reaches the cache or other results


def test_failures_are_not_cached(monkeypatch):
    from tests.test_part_deformation_preview import native_source

    monkeypatch.setattr(cache, "MIN_CACHE_SECONDS", 0.0)
    design = native_source("bend")
    _identity, kind, params = next(iter(command_rows(design, 100)))
    root = root_design(design.recipe_root, input_sources=design.input_sources)

    def failing(*_args):
        raise ValueError("native failure")

    with pytest.raises(ValueError):
        cache.ReplayChain.for_design(design).run(failing, kind, root, params)
    calls = []
    cache.ReplayChain.for_design(design).run(lambda *a: calls.append(a) or execute(*a), kind, root, params)
    assert calls
