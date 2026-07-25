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
        return {"topology_hash": "THASH", "atoms": [{"serial": 0}], "bonds": [[0, 1]]}

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


def test_build_also_writes_the_packed_bin_cache(_stub_bundle, monkeypatch):
    """The binary blob is packed off the IN-MEMORY bundle at build time.  Deriving it
    lazily on the first bin request instead would re-read and re-parse the ~129 MB JSON
    cache (~1.4 s) just to throw the dict away again."""
    jd, calls = _stub_bundle

    # A stub that is actually packable (the shared fixture's is deliberately minimal).
    def _packable_build(design):
        return {
            "topology_hash": "THASH",
            "atoms": [{"serial": i, "element": "P", "x": 0.0, "y": 0.0, "z": 0.0,
                       "strand_id": "s", "helix_id": "h", "bp_index": i,
                       "direction": "FORWARD", "aux_helix_id": "", "aux_t": 0.0}
                      for i in range(3)],
            "bonds": [[0, 1], [1, 2]],
            "element_meta": {},
            "n_nuc": 1,
            "atom_nuc": [0, 0, 0],
            "atom_local": [0.0] * 9,
            "nonrigid_serials": [],
        }

    import backend.core.atomistic as A
    monkeypatch.setattr(A, "atomistic_display_bundle", _packable_build)

    asyncio.run(R.get_oxdna_atomistic_display_bundle("fake"))
    bins = list(jd.glob("atomistic_display_bundle_*.bin"))
    assert len(bins) == 1, f"expected one packed blob, found {bins}"
    assert bins[0].read_bytes()[:4] == b"1BAN", "not the NAB1 magic"
    # …and the bin route then serves it without touching the JSON cache at all.
    (jd / "atomistic_display_bundle.json").unlink()
    resp = asyncio.run(R.get_oxdna_atomistic_display_bundle_bin("fake"))
    assert resp.body == bins[0].read_bytes()


def test_bonds_false_omits_bonds_but_still_caches_them(_stub_bundle):
    """The VDW rep draws no cylinders, so it asks for the bundle without the (huge) bond
    list.  The DISK CACHE must still hold the full bundle — a later ball-and-stick request
    has to get bonds back without triggering a rebuild."""
    jd, calls = _stub_bundle

    async def _run():
        lean = await R.get_oxdna_atomistic_display_bundle("fake", bonds=False)
        full = await R.get_oxdna_atomistic_display_bundle("fake")
        return lean, full

    lean, full = asyncio.run(_run())
    assert "bonds" not in lean, "bonds=False must not ship the bond list"
    assert lean["atoms"] == [{"serial": 0}], "everything else is unchanged"
    assert full["bonds"] == [[0, 1]], "the cached bundle still carries bonds"
    assert calls["n"] == 1, "bonds=False must not cause a second build"

    cached = json.loads((jd / "atomistic_display_bundle.json").read_text())
    assert cached["bonds"] == [[0, 1]], "the disk cache holds the FULL bundle"


def test_distinct_topologies_get_distinct_locks(_stub_bundle):
    async def _run():
        lk_a = await R._bundle_build_lock("A")
        lk_b = await R._bundle_build_lock("B")
        lk_a2 = await R._bundle_build_lock("A")
        return lk_a, lk_b, lk_a2

    lk_a, lk_b, lk_a2 = asyncio.run(_run())
    assert lk_a is lk_a2 and lk_a is not lk_b
