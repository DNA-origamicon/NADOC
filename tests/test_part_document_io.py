"""Document transport admission precedes decompression/model allocation."""

import base64
import gzip
import io
import json
import struct
import zipfile

import pytest

from backend.core import part_document_io as transport


class TrackingStream(io.BytesIO):
    def __init__(self, value):
        super().__init__(value)
        self.requests = []

    def read(self, size=-1):
        assert size >= 0, "Unbounded transport read"
        self.requests.append(size)
        return super().read(size)


def test_incremental_read_retains_only_allowance_and_one_detection_byte(monkeypatch):
    monkeypatch.setattr(transport, "_CHUNK", 4)
    stream = TrackingStream(b"x" * 100)
    with pytest.raises(transport.DocumentLimit) as error:
        transport.read_bounded(stream, limit=9)
    assert stream.tell() == 10
    assert stream.requests == [4, 4, 2]
    assert error.value.as_issue()["limit_bytes"] == 9
    assert transport.read_bounded(TrackingStream(b"x" * 9), limit=9) == b"x" * 9


def test_file_size_gate_precedes_read(tmp_path, monkeypatch):
    path = tmp_path / "part.nadoc"
    path.write_bytes(b"x" * 20)
    monkeypatch.setattr(transport, "read_bounded", lambda *a, **kw: pytest.fail("Read oversized file"))
    with pytest.raises(transport.DocumentLimit):
        transport.read_file(path, limit=19)


def test_text_bound_counts_utf8_without_reencoding_the_whole_document(monkeypatch):
    monkeypatch.setattr(transport, "_CHUNK", 2)
    assert transport.check_text("éé", limit=4) == "éé"
    with pytest.raises(transport.DocumentLimit):
        transport.check_text("éé", limit=3)


@pytest.mark.parametrize("joined", [False, True])
def test_gzip_bomb_is_bounded_and_exact_limit_keeps_multimember_compatibility(joined):
    raw = b"x" * 1000
    packed = gzip.compress(raw[:500]) + gzip.compress(raw[500:]) if joined else gzip.compress(raw)
    with pytest.raises(transport.DocumentLimit):
        transport.decode_gzip(packed, limit=20)
    assert transport.decode_gzip(packed, limit=1000) == raw


@pytest.mark.parametrize("corrupt", ["truncated", "crc", "not-gzip"])
def test_gzip_checks_integrity_even_when_output_fits(corrupt):
    packed = gzip.compress(b"tiny")
    if corrupt == "truncated":
        packed = packed[:-1]
    elif corrupt == "crc":
        packed = packed[:-8] + bytes([packed[-8] ^ 1]) + packed[-7:]
    else:
        packed = b"not gzip"
    with pytest.raises(ValueError, match="checksum/decompression"):
        transport.decode_gzip(packed, limit=100)


def test_snapshot_base64_is_incremental_and_accepts_legacy_mime_lines(monkeypatch):
    monkeypatch.setattr(transport, "_CHUNK", 7)
    raw = b"legacy snapshot" * 20
    payload = base64.encodebytes(gzip.compress(raw)).decode("ascii")
    assert transport.decode_snapshot_bytes(payload, limit=len(raw)) == raw
    with pytest.raises(transport.DocumentLimit):
        transport.decode_snapshot_bytes(payload, limit=len(raw) - 1)
    with pytest.raises(ValueError, match="base64"):
        transport.decode_snapshot_bytes(payload + "AAAA")


def test_base64_length_gate_precedes_ascii_copy_and_decode(monkeypatch):
    class NoCopy(str):
        def encode(self, *_a, **_kw):
            pytest.fail("Copied oversized base64")
        def __getitem__(self, _key):
            pytest.fail("Sliced oversized base64")
    monkeypatch.setattr(transport, "MAX_COMPRESSED_BYTES", 10)
    with pytest.raises(transport.DocumentLimit):
        transport.decode_snapshot_bytes(NoCopy("A" * 100))


def test_decoded_compressed_limit_precedes_gzip(monkeypatch):
    monkeypatch.setattr(transport, "MAX_COMPRESSED_BYTES", 10)
    monkeypatch.setattr(transport, "decode_gzip", lambda *_a, **_kw: pytest.fail("Reached gzip"))
    with pytest.raises(transport.DocumentLimit):
        transport.decode_snapshot_bytes(base64.b64encode(b"x" * 11).decode())


def test_zip_directory_bound_precedes_stdlib_allocation(tmp_path, monkeypatch):
    path = tmp_path / "directory.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(10):
            archive.writestr(f"member-{index}", "")
    monkeypatch.setattr(transport, "MAX_ZIP_DIRECTORY_BYTES", 100)
    with pytest.raises(transport.DocumentLimit, match="ZIP directory"):
        with transport.open_archive(path):
            pytest.fail("Admitted oversized directory")


@pytest.mark.parametrize("zip64", [False, True])
def test_zip64_and_comments_remain_stdlib_responsibility(tmp_path, monkeypatch, zip64):
    path = tmp_path / "package.zip"
    if zip64:
        monkeypatch.setattr(zipfile, "ZIP64_LIMIT", 10)
    with zipfile.ZipFile(path, "w", allowZip64=True) as archive:
        archive.comment = b"ordinary comment"
        archive.writestr("manifest.json", json.dumps({"version": 1}))
        archive.writestr("large-simulation.dat", b"x" * 1000)
    with transport.open_archive(path) as archive:
        assert json.loads(transport.read_member(archive, "manifest.json", limit=30)) == {"version": 1}
        # Simulation bytes are larger than the per-document read in this test.
        with archive.open("large-simulation.dat") as stream:
            assert sum(len(chunk) for chunk in iter(lambda: stream.read(20), b"")) == 1000
        with pytest.raises(transport.DocumentLimit):
            transport.read_member(archive, "large-simulation.dat", limit=30)


def test_forged_zip_directory_length_cannot_allocate_from_eocd(tmp_path):
    path = tmp_path / "forged.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("a", "b")
    data = bytearray(path.read_bytes())
    end = data.rfind(b"PK\x05\x06")
    struct.pack_into("<I", data, end + 12, transport.MAX_ZIP_DIRECTORY_BYTES + 1)
    path.write_bytes(data)
    # Stdlib may reject its impossible start first; neither path reads the size.
    with pytest.raises((transport.DocumentLimit, zipfile.BadZipFile)):
        with transport.open_archive(path):
            pytest.fail("Admitted forged directory")


def test_loadout_limit_precedes_model_validation(monkeypatch):
    from backend.core import design_loadouts
    from backend.core.models import Design
    payload = base64.b64encode(gzip.compress(b"x" * 100)).decode()
    monkeypatch.setattr(Design, "model_validate_json", lambda *_a: pytest.fail("Parsed oversized snapshot"))
    with pytest.raises(transport.DocumentLimit):
        design_loadouts.decode_snapshot(payload, max_bytes=99)


def test_revision_bomb_never_publishes_snapshot_or_branch(tmp_path, monkeypatch):
    from backend.core.project_revisions import ProjectRevisionStore
    monkeypatch.setattr(transport, "MAX_DOCUMENT_BYTES", 100)
    store = ProjectRevisionStore(tmp_path)
    with pytest.raises(transport.DocumentLimit):
        store.ingest_snapshot("project", "a" * 64, gzip.compress(b"x" * 101))
    assert not store.root.exists()


def test_revision_load_bounds_external_and_legacy_embedded_snapshots(tmp_path, monkeypatch):
    from backend.core.models import Design
    from backend.core.project_revisions import ProjectRevisionStore
    store = ProjectRevisionStore(tmp_path)
    revision = store.commit(Design(id="project"), loadout_id="main", loadout_name="Main",
                            parent_revision_id=None, expected_head=None)
    record_path = store.object_path("project", revision.revision_id)
    record = json.loads(record_path.read_text())
    monkeypatch.setattr(transport, "MAX_DOCUMENT_BYTES", 1000)
    bomb = gzip.compress(b"x" * 1001)
    store.snapshot_path("project", revision.snapshot_sha256).write_bytes(bomb)
    with pytest.raises(transport.DocumentLimit):
        store.load_design("project", revision.revision_id)
    record["snapshot_gz_b64"] = base64.b64encode(bomb).decode()
    record_path.write_text(json.dumps(record))
    with pytest.raises(transport.DocumentLimit):
        store.load_design("project", revision.revision_id)


def test_package_document_limit_leaves_no_installed_part_or_store(tmp_path, monkeypatch):
    from backend.core import native_part_package as package
    from backend.core.models import Design
    source = tmp_path / "source"
    source.mkdir()
    (source / "part.nadoc").write_text(Design().to_json())
    monkeypatch.setattr(package, "_job_classes", lambda: ())
    archive = tmp_path / "part.pkg"
    package.create_package(source, "part.nadoc", archive, mode="thin")
    monkeypatch.setattr(transport, "MAX_DOCUMENT_BYTES", 100)
    with pytest.raises(transport.DocumentLimit):
        package.import_package(tmp_path / "target", archive, "part.nadoc")
    assert not (tmp_path / "target").exists()


def test_peer_chunked_request_stops_before_unbounded_body_or_publication(monkeypatch):
    import asyncio
    from fastapi import HTTPException
    from backend.api import routes_project_collaboration as routes

    monkeypatch.setattr(routes, "MAX_SNAPSHOT_BYTES", 10)
    monkeypatch.setattr(routes, "_require_peer", lambda *_: None)
    monkeypatch.setattr(routes, "ProjectRevisionStore", lambda *_: pytest.fail("Published oversized input"))

    class Request:
        headers = {}
        yielded = 0
        async def body(self):
            pytest.fail("Allocated full request body")
        async def stream(self):
            for _ in range(100):
                self.yielded += 1
                yield b"1234"

    request = Request()
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.put_snapshot("project", "a" * 64, request, authorization=None))
    assert error.value.status_code == 413
    assert request.yielded == 3


def test_peer_pull_stream_closes_at_limit_without_reading_remaining_response():
    import asyncio
    import httpx
    from backend.core.collaboration_peers import _bounded_peer_bytes

    class Stream(httpx.AsyncByteStream):
        yielded = 0
        closed = False
        async def __aiter__(self):
            for _ in range(100):
                self.yielded += 1
                yield b"1234"
        async def aclose(self):
            self.closed = True

    stream = Stream()
    async def run():
        async with httpx.AsyncClient(base_url="http://localhost", transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=stream))) as client:
            with pytest.raises(transport.DocumentLimit):
                await _bounded_peer_bytes(client, "/snapshot", {}, limit=10, label="Peer snapshot")
    asyncio.run(run())
    assert stream.yielded == 3
    assert stream.closed


def test_library_open_limit_is_explicit_and_precedes_identity_rewrite(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from backend.api import routes_assembly_workspace as routes
    from backend.core import design_identity
    path = tmp_path / "large.nadoc"
    path.write_bytes(b"x" * 20)
    monkeypatch.setattr(transport, "MAX_DOCUMENT_BYTES", 10)
    monkeypatch.setattr(design_identity, "reconcile_open_identity", lambda *_: pytest.fail("Rewrote rejected input"))
    with pytest.raises(HTTPException) as error:
        routes._reconcile_nadoc_file(path, "large.nadoc")
    assert error.value.status_code == 413
    assert error.value.detail["code"] == "document_transport_limit"
    assert path.read_bytes() == b"x" * 20


@pytest.mark.parametrize('text', ['', 'ascii', 'éé', '🧬', 'aé🧬'])
def test_text_admission_exact_utf8_boundary(text):
    size = len(text.encode('utf-8'))
    assert transport.check_text(text, limit=size) is text
    with pytest.raises(transport.DocumentLimit):
        transport.check_text(text, limit=size - 1)


def test_text_admission_keeps_subclass_and_surrogate_behavior():
    class Expanded(str):
        def __getitem__(self, key):
            return 'é'
    with pytest.raises(transport.DocumentLimit):
        transport.check_text(Expanded('a'), limit=1)
    with pytest.raises(UnicodeEncodeError):
        transport.check_text('\ud800', limit=10)
