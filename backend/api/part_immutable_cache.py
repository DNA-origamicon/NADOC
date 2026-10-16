"""Bounded durable bytes for strict parts; no restore/publication authority.

This unmounted file layer never decodes a Design, creates a session, prunes a
record or follows a record symlink. Its advisory directory lock serializes NADOC
writers; it is not protection against arbitrary external filesystem mutation.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
from re import fullmatch
import stat
import struct
from uuid import uuid4

from backend.api.document_identity import require_document_identity
from backend.api.part_immutable_revision import is_prepared_revision
from backend.api.part_evaluation_worker import MAX_CANDIDATE_BYTES
from backend.core.part_command_errors import CommandContractError


NAMESPACE = ".session-strict-v1"
MAX_RECORDS = 50
MAX_MANIFEST_BYTES = 4096
_MAGIC = b"NADOC-STRICT-PART-CACHE\x00\x01"
_SUFFIX = ".partcache"


def _refuse(detail, code="strict_cache_invalid"):
    raise CommandContractError(detail, code=code)


@dataclass(frozen=True, slots=True)
class CacheManifest:
    doc_id: str
    payload_bytes: int
    payload_sha256: str
    storage_version: int = 1


@dataclass(frozen=True, slots=True, init=False)
class CacheLease:
    """Writer-owned observed file identity, never a reproducibility receipt."""

    _owner: object
    doc_id: str
    _fingerprint: tuple | None

    def __init__(self):
        raise TypeError("Cache leases are acquired from their owning store")


@dataclass(frozen=True, slots=True)
class StoredRevision:
    manifest: CacheManifest
    payload: bytes
    lease: CacheLease


@dataclass(frozen=True, slots=True)
class Discovery:
    manifests: tuple[CacheManifest, ...]
    issues: tuple[dict, ...]


def _record_name(doc_id):
    return sha256(require_document_identity(doc_id).encode("utf-8")).hexdigest() + _SUFFIX


def _manifest_bytes(manifest):
    return json.dumps({"storage_version": manifest.storage_version, "doc_id": manifest.doc_id,
        "payload_bytes": manifest.payload_bytes, "payload_sha256": manifest.payload_sha256},
        sort_keys=True, separators=(",", ":"), allow_nan=False).encode("ascii")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _refuse("Strict cache manifest contains duplicate fields")
        result[key] = value
    return result


def _parse_manifest(raw, name):
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
        if (type(data) is not dict or set(data) != {"storage_version", "doc_id", "payload_bytes", "payload_sha256"}
                or type(data["storage_version"]) is not int or data["storage_version"] != 1
                or type(data["payload_bytes"]) is not int or not 0 < data["payload_bytes"] <= MAX_CANDIDATE_BYTES
                or type(data["payload_sha256"]) is not str
                or fullmatch(r"[0-9a-f]{64}", data["payload_sha256"]) is None
                or _record_name(data["doc_id"]) != name):
            _refuse("Strict cache manifest identity, version or size is unsupported")
        manifest = CacheManifest(**data)
    except (ValueError, TypeError, KeyError, RecursionError) as error:
        if isinstance(error, CommandContractError):
            raise
        _refuse("Strict cache manifest is malformed")
    if _manifest_bytes(manifest) != raw:
        _refuse("Strict cache manifest must use its exact canonical representation")
    return manifest


def _fingerprint(status, manifest):
    return (status.st_dev, status.st_ino, status.st_size, status.st_mtime_ns,
            status.st_ctime_ns, manifest)


class StrictPartCache:
    """One typed namespace under a trusted existing workspace directory."""

    def __init__(self, workspace):
        self.directory = Path(workspace).resolve(strict=True) / NAMESPACE
        self._owner = object()

    @contextmanager
    def _directory(self, *, create=False):
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            _refuse("Strict cache requires qualified no-follow filesystem operations", "strict_cache_unavailable")
        import fcntl

        descriptor = None
        try:
            if create:
                try:
                    self.directory.mkdir(mode=0o700)
                except FileExistsError:
                    pass
            descriptor = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                _refuse("Another strict cache operation is active; retry later", "strict_cache_busy")
            yield descriptor
        except OSError as error:
            _refuse(f"Strict cache filesystem access failed: {error.strerror}", "strict_cache_unavailable")
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _lease(self, doc_id, fingerprint):
        value = object.__new__(CacheLease)
        object.__setattr__(value, "_owner", self._owner)
        object.__setattr__(value, "doc_id", doc_id)
        object.__setattr__(value, "_fingerprint", fingerprint)
        return value

    def _check_lease(self, lease):
        if type(lease) is not CacheLease or getattr(lease, "_owner", None) is not self._owner:
            _refuse("Strict cache write has no lease from this store", "strict_cache_changed")
        return _record_name(lease.doc_id)

    @staticmethod
    def _names(directory):
        names = []
        with os.scandir(directory) as entries:
            for entry in entries:
                if len(names) >= MAX_RECORDS:
                    _refuse("Strict cache discovery exceeds its record allowance; existing files are preserved",
                            "strict_cache_limit")
                names.append(entry.name)
        return sorted(names)

    @staticmethod
    def _read(directory, name, *, payload):
        before = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            _refuse("Strict cache record must be a regular file")
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            status = os.fstat(stream.fileno())
            if (not stat.S_ISREG(status.st_mode) or status.st_nlink != 1
                    or status.st_size > len(_MAGIC) + 4 + MAX_MANIFEST_BYTES + MAX_CANDIDATE_BYTES):
                _refuse("Strict cache record is not a bounded, exclusively owned regular file")
            if stream.read(len(_MAGIC)) != _MAGIC:
                _refuse("Strict cache record has an unsupported framing version")
            length = stream.read(4)
            if len(length) != 4:
                _refuse("Strict cache record has a truncated manifest length")
            count = struct.unpack("!I", length)[0]
            if not 0 < count <= MAX_MANIFEST_BYTES:
                _refuse("Strict cache manifest exceeds its fixed allowance")
            raw = stream.read(count)
            if len(raw) != count:
                _refuse("Strict cache record has a truncated manifest")
            manifest = _parse_manifest(raw, name)
            if status.st_size != len(_MAGIC) + 4 + count + manifest.payload_bytes:
                _refuse("Strict cache payload length does not match its manifest")
            body = None
            if payload:
                body = stream.read(manifest.payload_bytes + 1)
                if len(body) != manifest.payload_bytes or sha256(body).hexdigest() != manifest.payload_sha256:
                    _refuse("Strict cache payload does not match its manifest", "strict_cache_integrity")
            if _fingerprint(os.fstat(stream.fileno()), manifest) != _fingerprint(status, manifest):
                _refuse("Strict cache record changed while being read", "strict_cache_changed")
            return manifest, body, _fingerprint(status, manifest)

    def acquire_absent(self, doc_id):
        """Existing content, even invalid content, blocks fresh empty creation."""
        name = _record_name(doc_id)
        with self._directory(create=True) as directory:
            names = self._names(directory)
            if name in names:
                _refuse("This document has pending durable content; recover it or use a new document identity",
                        "strict_cache_pending")
            if len(names) >= MAX_RECORDS:
                _refuse("Strict cache has no free record allowance; existing files are preserved", "strict_cache_limit")
        return self._lease(doc_id, None)

    def read(self, doc_id):
        name = _record_name(doc_id)
        with self._directory() as directory:
            manifest, payload, fingerprint = self._read(directory, name, payload=True)
        return StoredRevision(manifest, payload, self._lease(doc_id, fingerprint))

    def assert_current(self, lease):
        """Recheck a host file lease outside the document state lock."""
        with self.checked_lease(lease):
            pass

    @contextmanager
    def checked_lease(self, lease):
        """Hold cooperating-writer exclusion through a short host publication.

        Acquisition and file checks precede the caller's state lock. The body
        must perform no disk work; arbitrary external replacement is outside
        this advisory locking contract.
        """
        name = self._check_lease(lease)
        with self._directory() as directory:
            if lease._fingerprint is None:
                if name in self._names(directory):
                    _refuse("Durable content appeared after empty admission", "strict_cache_changed")
            else:
                _manifest, _payload, current = self._read(directory, name, payload=False)
                if current != lease._fingerprint:
                    _refuse("Durable content changed after its lease was acquired", "strict_cache_changed")
            yield

    def inspect(self, doc_id):
        """Bounded exact-record header inspection, without proof or decode."""
        name = _record_name(doc_id)
        try:
            os.lstat(self.directory)
        except FileNotFoundError:
            return None
        with self._directory() as directory:
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                return None
            manifest, _payload, _fingerprint = self._read(directory, name, payload=False)
            return manifest

    def discover(self):
        if not self.directory.exists() and not self.directory.is_symlink():
            return Discovery((), ())
        manifests, issues = [], []
        with self._directory() as directory:
            for name in self._names(directory):
                try:
                    if fullmatch(r"[0-9a-f]{64}\.partcache", name) is None:
                        _refuse("Unrecognized strict cache entry is preserved")
                    manifest, _payload, _fingerprint = self._read(directory, name, payload=False)
                    manifests.append(manifest)
                except (CommandContractError, OSError) as error:
                    issues.append({"record": name[:256], "code": getattr(error, "code", "strict_cache_unavailable")})
        return Discovery(tuple(manifests), tuple(issues))

    def write(self, lease, revision):
        """Replace only the writer's observed record; no active model is accepted."""
        name = self._check_lease(lease)
        if not is_prepared_revision(revision):
            _refuse("Strict cache writes require a privately prepared immutable revision")
        manifest = CacheManifest(lease.doc_id, len(revision.payload), sha256(revision.payload).hexdigest())
        raw = _manifest_bytes(manifest)
        if len(raw) > MAX_MANIFEST_BYTES:
            _refuse("Strict cache manifest exceeds its fixed allowance")
        temporary = ".write-" + uuid4().hex
        created = False
        with self._directory(create=True) as directory:
            try:
                if lease._fingerprint is None:
                    names = self._names(directory)
                    if name in names:
                        _refuse("Durable content appeared after empty admission", "strict_cache_changed")
                    if len(names) >= MAX_RECORDS:
                        _refuse("Strict cache has no free record allowance", "strict_cache_limit")
                else:
                    _manifest, _payload, current = self._read(directory, name, payload=False)
                    if current != lease._fingerprint:
                        _refuse("Durable content changed after its lease was acquired", "strict_cache_changed")
                descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     0o600, dir_fd=directory)
                created = True
                with os.fdopen(descriptor, "wb") as stream:
                    stream.write(_MAGIC)
                    stream.write(struct.pack("!I", len(raw)))
                    stream.write(raw)
                    stream.write(revision.payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                if lease._fingerprint is None:
                    os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
                    os.unlink(temporary, dir_fd=directory)
                    created = False
                else:
                    os.replace(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
                    created = False
                os.fsync(directory)
                _manifest, _payload, current = self._read(directory, name, payload=False)
            finally:
                if created:
                    os.unlink(temporary, dir_fd=directory)
        return self._lease(lease.doc_id, current)
