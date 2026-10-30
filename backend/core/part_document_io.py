"""Bounded document transport, separate from native proof admission budgets.

These are byte bounds before JSON/model parsing, not process heap limits. A
portable document includes history and display data that proof must never read.
"""

import base64
import binascii
from contextlib import contextmanager
import gzip
import io
from pathlib import Path
import zlib
import zipfile

MAX_DOCUMENT_BYTES = 256 * 1024 * 1024
MAX_COMPRESSED_BYTES = 512 * 1024 * 1024  # existing peer snapshot transfer ceiling
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_ZIP_DIRECTORY_BYTES = 16 * 1024 * 1024
MAX_ZIP_MEMBERS = 100_000
_CHUNK = 1024 * 1024


class DocumentLimit(ValueError):
    code = "document_transport_limit"

    def __init__(self, label, limit):
        self.limit = limit
        super().__init__(f"{label} exceeds its {limit:,}-byte transport limit")

    def as_issue(self):
        return {"code": self.code, "detail": str(self), "limit_bytes": self.limit}


def read_bounded(stream, *, limit=None, label="Part document") -> bytes:
    """Read incrementally, retaining at most limit + one detection byte."""
    limit = MAX_DOCUMENT_BYTES if limit is None else limit
    if limit < 0:
        raise ValueError("Read limit must be nonnegative")
    output = io.BytesIO()
    size = 0
    while True:
        chunk = stream.read(min(_CHUNK, limit - size + 1))
        if not chunk:
            return output.getvalue()
        size += len(chunk)
        if size > limit:
            raise DocumentLimit(label, limit)
        output.write(chunk)


def read_file(path, *, limit=None, label="Part document") -> bytes:
    limit = MAX_DOCUMENT_BYTES if limit is None else limit
    with Path(path).open("rb") as stream:
        # A changing file is still checked by read_bounded after this cheap gate.
        import os
        if os.fstat(stream.fileno()).st_size > limit:
            raise DocumentLimit(label, limit)
        return read_bounded(stream, limit=limit, label=label)


async def read_async_bounded(chunks, *, limit=MAX_COMPRESSED_BYTES, label="Peer snapshot") -> bytes:
    """Admit network chunks before retaining them as one portable object."""
    output = io.BytesIO()
    async for chunk in chunks:
        if output.tell() + len(chunk) > limit:
            raise DocumentLimit(label, limit)
        output.write(chunk)
    return output.getvalue()


def check_text(text, *, limit=None, label="Part document") -> str:
    """Check existing JSON text without allocating another full encoded copy."""
    limit = MAX_DOCUMENT_BYTES if limit is None else limit
    if len(text) > limit:
        raise DocumentLimit(label, limit)
    # Built-in ASCII strings have exactly one UTF-8 byte per character.
    # Subclasses retain their original slicing/encoding behavior below.
    if type(text) is str and text.isascii():
        return text
    size = 0
    for start in range(0, len(text), _CHUNK):
        size += len(text[start:start + _CHUNK].encode("utf-8"))
        if size > limit:
            raise DocumentLimit(label, limit)
    return text


def decode_gzip(data, *, limit=None, label="Part snapshot") -> bytes:
    if len(data) > MAX_COMPRESSED_BYTES:
        raise DocumentLimit(f"Compressed {label}", MAX_COMPRESSED_BYTES)
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data), mode="rb") as stream:
            return read_bounded(stream, limit=limit, label=label)
    except (gzip.BadGzipFile, EOFError, zlib.error) as exc:
        raise ValueError(f"{label} checksum/decompression failure") from exc


def decode_snapshot_bytes(payload, *, limit=None) -> bytes:
    if not isinstance(payload, str) or not payload:
        raise ValueError("empty loadout snapshot payload")
    # Preserve MIME-wrapped legacy base64 while bounding before ASCII conversion
    # or decoded allocation. Modern native input blobs remain strictly canonical.
    encoded_limit = 4 * ((MAX_COMPRESSED_BYTES + 2) // 3)
    encoded_limit += encoded_limit // 76 * 2 + 4
    if len(payload) > encoded_limit:
        raise DocumentLimit("Encoded part snapshot", encoded_limit)
    try:
        output = io.BytesIO()
        pending = b""
        ended = False
        for start in range(0, len(payload), _CHUNK):
            block = payload[start:start + _CHUNK].encode("ascii").translate(None, b" \t\r\n\v\f")
            if not block:
                continue
            if ended:
                raise ValueError("Data after snapshot base64 padding")
            block = pending + block
            count = len(block) // 4 * 4
            pending = block[count:]
            decoded = base64.b64decode(block[:count], validate=True)
            ended = b"=" in block[:count]
            if output.tell() + len(decoded) > MAX_COMPRESSED_BYTES:
                raise DocumentLimit("Compressed part snapshot", MAX_COMPRESSED_BYTES)
            output.write(decoded)
        if pending:
            raise ValueError("Incomplete snapshot base64 group")
        compressed = output.getvalue()
    except DocumentLimit:
        raise
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid part snapshot base64") from exc
    return decode_gzip(compressed, limit=limit)


def read_member(archive, name, *, limit=None, label="Package part") -> bytes:
    limit = MAX_DOCUMENT_BYTES if limit is None else limit
    info = archive.getinfo(name)
    if info.file_size > limit:
        raise DocumentLimit(label, limit)
    with archive.open(info) as stream:
        return read_bounded(stream, limit=limit, label=label)


class _DirectoryReader:
    """Cap stdlib's directory allocation without duplicating ZIP/ZIP64 parsing."""

    def __init__(self, stream):
        self.stream = stream
        self.admitting = True

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def read(self, size=-1):
        if self.admitting:
            if size < 0:
                position = self.stream.tell()
                size = self.stream.seek(0, 2) - position
                self.stream.seek(position)
            if size > MAX_ZIP_DIRECTORY_BYTES:
                raise DocumentLimit("ZIP directory", MAX_ZIP_DIRECTORY_BYTES)
        return self.stream.read(size)


@contextmanager
def open_archive(path):
    """Admit metadata before ZipFile reads it; simulation members stay streamed."""
    with Path(path).open("rb") as stream:
        reader = _DirectoryReader(stream)
        with zipfile.ZipFile(reader) as archive:
            if len(archive.infolist()) > MAX_ZIP_MEMBERS:
                raise ValueError(f"ZIP directory exceeds its {MAX_ZIP_MEMBERS:,}-member limit")
            reader.admitting = False
            yield archive
