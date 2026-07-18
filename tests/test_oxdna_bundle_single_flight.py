"""Single-flight guard on the atomistic display-bundle route.

The bundle build (topology + stamp descriptor) is a ~10 s all-atom construction.
Two concurrent first-clicks for the same job — or a warm-ahead prefetch racing a
real click — must collapse to ONE build, not stack N of them.  These tests stub the
builder with a counting/sleeping fake and prove the collapse + per-topology keying.
"""
from __future__ import annotations

import asyncio
import json
import threading

import pytest

import backend.api.routes_oxdna as R


class _FakeJob:
    def __init__(self, jd):
        self._jd = jd
        self.job_id = "fake"

    def job_dir(self, _ws):
        return self._jd


@pytest.fixture
def _stub_bundle(tmp_path, monkeypatch):
    """Point the route at a tmp job dir with a design.json, and replace the heavy
    builder + hash with fast counting stubs."""
    jd = tmp_path / "job"
    jd.mkdir()
    # Any parseable design.json; the stubbed builder/hash ignore its contents.
    from backend.core.models import Design
    (jd / "design.json").write_text(Design().model_dump_json())

    monkeypatch.setattr(R, "_load_job", lambda jid: _FakeJob(jd))

    calls = {"n": 0}
    lock = threading.Lock()

    def _counting_build(design):
        with lock:
            calls["n"] += 1
        # Simulate a slow build so concurrent requests overlap inside the lock window.
        import time
        time.sleep(0.3)
        return {"topology_hash": "THASH", "atoms": [], "bonds": []}

    import backend.core.atomistic as A
    monkeypatch.setattr(A, "atomistic_reference_topology_hash", lambda d: "THASH")
    monkeypatch.setattr(A, "atomistic_display_bundle", _counting_build)
    # Fresh lock registry + guard per test — each test runs its own event loop via
    # asyncio.run(), and an asyncio.Lock binds to the loop it is first used in.
    R._BUNDLE_BUILD_LOCKS.clear()
    R._BUNDLE_LOCKS_GUARD = asyncio.Lock()
    return jd, calls


def test_concurrent_first_clicks_build_once(_stub_bundle):
    jd, calls = _stub_bundle

    async def _run():
        # 5 concurrent requests for the same job → exactly one build; rest take cache.
        return await asyncio.gather(*[
            R.get_oxdna_atomistic_display_bundle("fake") for _ in range(5)
        ])

    results = asyncio.run(_run())
    assert calls["n"] == 1, f"expected single-flight (1 build), got {calls['n']}"
    assert all(r["topology_hash"] == "THASH" for r in results)
    # And the disk cache was written, so a later cold request is free.
    assert (jd / "atomistic_display_bundle.json").exists()


def test_second_request_after_build_is_cached(_stub_bundle):
    jd, calls = _stub_bundle

    async def _run():
        await R.get_oxdna_atomistic_display_bundle("fake")
        await R.get_oxdna_atomistic_display_bundle("fake")

    asyncio.run(_run())
    assert calls["n"] == 1, "second request must hit the disk cache, not rebuild"


def test_distinct_topologies_get_distinct_locks(_stub_bundle):
    async def _run():
        lk_a = await R._bundle_build_lock("A")
        lk_b = await R._bundle_build_lock("B")
        lk_a2 = await R._bundle_build_lock("A")
        return lk_a, lk_b, lk_a2

    lk_a, lk_b, lk_a2 = asyncio.run(_run())
    assert lk_a is lk_a2 and lk_a is not lk_b
