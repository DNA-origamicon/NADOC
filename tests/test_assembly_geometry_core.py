"""Direct unit tests for backend/core/assembly_geometry.py (router carve-up #49).

Covers the pure geometry-cache kernel (LRU get/set/clear + cache-key compute)
and the cluster-override merge that were service-pushed out of
``backend/api/assembly.py``. No TestClient — these assert input→output directly.
"""

import pytest

from backend.core import assembly_geometry as ageo
from backend.core.models import (
    ClusterRigidTransform,
    Design,
    PartInstance,
    PartSourceFile,
    PartSourceInline,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Each test starts (and leaves) the module-global LRU empty."""
    ageo.clear_geo_cache()
    yield
    ageo.clear_geo_cache()


# ── LRU get/set/clear ─────────────────────────────────────────────────────────

def test_get_miss_returns_none():
    assert ageo.geo_cache_get("nope") is None


def test_set_then_get_roundtrip():
    ageo.geo_cache_set("k", {"v": 1})
    assert ageo.geo_cache_get("k") == {"v": 1}


def test_clear_empties_cache():
    ageo.geo_cache_set("k", {"v": 1})
    ageo.clear_geo_cache()
    assert ageo.geo_cache_get("k") is None


def test_lru_evicts_oldest_past_max():
    # Fill beyond capacity; the very first inserted key must be evicted.
    for i in range(ageo._GEO_CACHE_MAX + 3):
        ageo.geo_cache_set(f"k{i}", {"i": i})
    assert ageo.geo_cache_get("k0") is None
    assert ageo.geo_cache_get(f"k{ageo._GEO_CACHE_MAX + 2}") == {"i": ageo._GEO_CACHE_MAX + 2}
    # exactly _GEO_CACHE_MAX entries retained
    assert len(ageo._GEO_CACHE) == ageo._GEO_CACHE_MAX


def test_get_refreshes_recency_so_it_survives_eviction():
    ageo.geo_cache_set("keep", {"x": 0})
    # Touch "keep" via get, then flood the rest of capacity with fresh keys.
    for i in range(ageo._GEO_CACHE_MAX - 1):
        ageo.geo_cache_set(f"f{i}", {"i": i})
    ageo.geo_cache_get("keep")               # move "keep" to most-recent
    ageo.geo_cache_set("overflow", {"o": 1})  # evicts the oldest, which is now f0 not keep
    assert ageo.geo_cache_get("keep") == {"x": 0}
    assert ageo.geo_cache_get("f0") is None


def test_set_existing_key_updates_value_not_size():
    ageo.geo_cache_set("k", {"v": 1})
    ageo.geo_cache_set("k", {"v": 2})
    assert ageo.geo_cache_get("k") == {"v": 2}
    assert len(ageo._GEO_CACHE) == 1


# ── cache-key compute ─────────────────────────────────────────────────────────

def _inst(source, overrides=None):
    return PartInstance(source=source, cluster_transform_overrides=overrides or [])


def test_key_inline_source_is_stable_and_id_based():
    d = Design(id="dz")
    inst = _inst(PartSourceInline(design=d))
    key = ageo.geo_cache_key(inst, None)
    assert key == "i:dz:"
    # second call identical (stable)
    assert ageo.geo_cache_key(inst, None) == key


def test_key_inline_changes_with_overrides():
    d = Design(id="dz")
    bare = ageo.geo_cache_key(_inst(PartSourceInline(design=d)), None)
    with_ov = ageo.geo_cache_key(
        _inst(PartSourceInline(design=d), [ClusterRigidTransform(id="c1")]), None
    )
    assert bare != with_ov
    assert bare.endswith(":")          # empty override hash
    assert not with_ov.endswith(":")   # non-empty override hash


def test_key_file_source_resolves_against_workspace(tmp_path):
    part = tmp_path / "part.nadoc"
    part.write_text("{}", encoding="utf-8")
    inst = _inst(PartSourceFile(path="part.nadoc"))
    key = ageo.geo_cache_key(inst, tmp_path)
    assert key is not None
    assert key.startswith(f"f:{(tmp_path / 'part.nadoc').resolve()}:")


def test_key_file_missing_returns_none(tmp_path):
    inst = _inst(PartSourceFile(path="absent.nadoc"))
    assert ageo.geo_cache_key(inst, tmp_path) is None


def test_key_file_uses_workspace_param_not_a_global(tmp_path):
    # Resolution must honor the workspace_dir passed in (the api shim threads
    # the monkeypatch-able _WORKSPACE_DIR here) — a wrong dir → not cacheable.
    part = tmp_path / "p.nadoc"
    part.write_text("{}", encoding="utf-8")
    inst = _inst(PartSourceFile(path="p.nadoc"))
    assert ageo.geo_cache_key(inst, tmp_path) is not None
    assert ageo.geo_cache_key(inst, tmp_path / "elsewhere") is None


def test_key_file_mtime_changes_invalidate(tmp_path):
    part = tmp_path / "part.nadoc"
    part.write_text("{}", encoding="utf-8")
    inst = _inst(PartSourceFile(path="part.nadoc"))
    k1 = ageo.geo_cache_key(inst, tmp_path)
    # bump mtime explicitly (st_mtime_ns is the cache's freshness signal)
    import os
    st = part.stat()
    os.utime(part, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    k2 = ageo.geo_cache_key(inst, tmp_path)
    assert k1 != k2


# ── override merge ────────────────────────────────────────────────────────────

def test_merge_no_overrides_returns_same_object():
    d = Design(id="d", cluster_transforms=[ClusterRigidTransform(id="c1")])
    out = ageo.merge_cluster_overrides(d, [])
    assert out is d  # no copy in the common case


def test_merge_replaces_matching_id():
    base = ClusterRigidTransform(id="c1", name="base")
    over = ClusterRigidTransform(id="c1", name="override")
    d = Design(id="d", cluster_transforms=[base])
    out = ageo.merge_cluster_overrides(d, [over])
    assert out is not d
    assert [c.name for c in out.cluster_transforms] == ["override"]


def test_merge_appends_unknown_id():
    base = ClusterRigidTransform(id="c1")
    extra = ClusterRigidTransform(id="c2")
    d = Design(id="d", cluster_transforms=[base])
    out = ageo.merge_cluster_overrides(d, [extra])
    assert {c.id for c in out.cluster_transforms} == {"c1", "c2"}
