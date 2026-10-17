"""Repeated assembly reads/part edits must reuse unchanged native Full payloads."""

from collections import Counter

import pytest
from fastapi.testclient import TestClient

from backend.api import assembly as assembly_api, assembly_state, crud
from backend.api.main import app
from backend.core import assembly_geometry, design_geometry
from backend.core.lattice import make_bundle_design
from backend.core.models import Assembly, ClusterRigidTransform, PartInstance, PartSourceFile


@pytest.fixture
def cached_parts(tmp_path, monkeypatch):
    assembly_state.close_session()
    assembly_geometry.clear_geo_cache()
    monkeypatch.setattr(assembly_api, "_WORKSPACE_DIR", tmp_path)
    designs = [make_bundle_design([(0, 0)], 14, name=name) for name in ("A", "B")]
    instances = []
    for name, design in zip(("a", "b"), designs):
        path = tmp_path / f"{name}.nadoc"
        path.write_text(design.to_json())
        instances.append(PartInstance(id=name, source=PartSourceFile(path=path.name)))
    assembly_state.set_assembly(Assembly(instances=instances))
    calls, packs = Counter(), []
    original_geometry = crud._geometry_for_design
    original_pack = design_geometry._compact_geometry_from_nucleotides

    def geometry(design, *args, **kwargs):
        calls[design.id] += 1
        return original_geometry(design, *args, **kwargs)

    def pack(nucleotides):
        packs.append(len(nucleotides))
        return original_pack(nucleotides)

    monkeypatch.setattr(crud, "_geometry_for_design", geometry)
    monkeypatch.setattr(design_geometry, "_compact_geometry_from_nucleotides", pack)
    yield TestClient(app), designs, calls, packs
    assembly_state.close_session()
    assembly_geometry.clear_geo_cache()


def test_repeated_instance_and_batch_reads_pack_native_geometry_once(cached_parts):
    client, designs, calls, packs = cached_parts
    first = client.get("/api/assembly/instances/a/geometry")
    assert first.status_code == 200, first.text
    again = client.get("/api/assembly/instances/a/geometry")
    batch = client.get("/api/assembly/geometry")
    assert again.json() == first.json()
    body = batch.json()
    assert not body["errors"]
    assert body["sources"][body["instances"]["a"]] == first.json()
    assert calls == {design.id: 1 for design in designs}
    assert len(packs) == 2
    # Only compact arrays are retained; the large raw nucleotide dictionaries
    # must not sit alongside a second response representation in the LRU.
    assert all("nucleotides" not in entry for entry in assembly_geometry._GEO_CACHE.values())


def test_editing_one_source_keeps_other_parts_warm_and_updates_changed_geometry(cached_parts):
    client, designs, calls, packs = cached_parts
    before = client.get("/api/assembly/geometry").json()
    moved = designs[0].copy_with(cluster_transforms=[ClusterRigidTransform(
        id="move", helix_ids=[h.id for h in designs[0].helices], translation=[3, 0, 0])])
    edit = client.patch("/api/assembly/instances/a/design", json={"content": moved.to_json()})
    assert edit.status_code == 200, edit.text
    after = client.get("/api/assembly/geometry").json()
    assert not after["errors"]
    assert calls == {designs[0].id: 2, designs[1].id: 1}
    assert len(packs) == 3
    assert before["sources"][before["instances"]["b"]] == after["sources"][after["instances"]["b"]]
    old = before["sources"][before["instances"]["a"]]["nucleotides_compact"]
    new = after["sources"][after["instances"]["a"]]["nucleotides_compact"]
    hid = designs[0].helices[0].id
    assert new[hid]["FORWARD"]["bb"][0][0] == pytest.approx(old[hid]["FORWARD"]["bb"][0][0] + 3)


def test_seek_prewarms_the_key_used_by_subsequent_geometry_reads(cached_parts):
    client, designs, calls, packs = cached_parts
    client.get("/api/assembly/instances/b/geometry")
    seek = client.post("/api/assembly/instances/a/features/seek", json={"position": -1})
    assert seek.status_code == 200, seek.text
    subsequent = client.get("/api/assembly/instances/a/geometry")
    batch = client.get("/api/assembly/geometry")
    assert subsequent.status_code == batch.status_code == 200
    assert subsequent.json()["nucleotides_compact"] == seek.json()["geometry"]["nucleotides_compact"]
    assert subsequent.json()["helix_axes"] == seek.json()["geometry"]["helix_axes"]
    assert calls == {design.id: 1 for design in designs}
    assert len(packs) == 2


def test_negotiated_binary_reads_match_json_and_reuse_cached_native_geometry(cached_parts):
    from backend.core.native_geometry_binary import MEDIA_TYPE, unpack_geometry_binary

    client, designs, calls, packs = cached_parts
    for path in ("/api/assembly/instances/a/geometry", "/api/assembly/geometry"):
        ordinary = client.get(path)
        binary = client.get(path + "?format=ndgb1", headers={"Accept-Encoding": "gzip"})
        assert ordinary.status_code == binary.status_code == 200
        assert binary.headers["content-type"] == MEDIA_TYPE
        assert binary.headers["content-encoding"] == "identity"
        assert unpack_geometry_binary(binary.content) == ordinary.json()
    assert calls == {design.id: 1 for design in designs}
    assert len(packs) == 2


def test_binary_cold_array_path_is_identical_and_warms_default_json_cache(cached_parts):
    from backend.core.native_geometry_binary import unpack_geometry_binary

    client, designs, calls, packs = cached_parts
    binary = client.get('/api/assembly/geometry?format=ndgb1')
    assert binary.status_code == 200
    decoded = unpack_geometry_binary(binary.content)
    assert not decoded['errors']
    ordinary = client.get('/api/assembly/geometry')
    assert ordinary.json() == decoded
    assert not calls and not packs  # direct canonical arrays; no transient records
    for instance, design in zip(('a', 'b'), designs):
        assert decoded['sources'][decoded['instances'][instance]]['nucleotides_compact'] == design_geometry._compact_geometry_for_design(design)
