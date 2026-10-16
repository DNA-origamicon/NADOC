"""Typed cache adapter; retain bytes under the state lock and write afterward.

Bindings describe file ownership only. They contain weak revision references,
never decoded models, and do not authorize creation, restore or publication.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import os
from threading import Lock
from weakref import ref

from backend.api.part_immutable_cache import MAX_RECORDS, StrictPartCache, _record_name
from backend.api.part_immutable_storage import is_immutable, require_sealed
from backend.core.part_command_errors import CommandContractError


@dataclass(frozen=True, slots=True)
class PersistenceCapture:
    doc_id: str
    session_identity: str
    revision: int
    source: object


@dataclass(frozen=True, slots=True)
class _Binding:
    session_identity: str
    revision: int
    source: ref
    lease: object


def capture_immutable(doc_id):
    """Constant-size locked capture, or None for the existing legacy writer."""
    from backend.api import state

    with state._lock:
        session = state._sessions.get(doc_id)
        if session is None or not is_immutable(session.design):
            return None
        require_sealed(session.design)
        return PersistenceCapture(doc_id, session.identity, session.revision, session.design)


def _refuse(detail, code="strict_cache_unbound"):
    raise CommandContractError(detail, code=code)


def _check_capture(capture):
    if (type(capture) is not PersistenceCapture or type(capture.session_identity) is not str
            or not 0 < len(capture.session_identity) <= 128
            or type(capture.revision) is not int or capture.revision < 1):
        _refuse("Strict persistence needs the exact host session and assigned revision")
    _record_name(capture.doc_id)
    require_sealed(capture.source)


class StrictPersistence:
    def __init__(self, workspace):
        self.cache = StrictPartCache(workspace)
        self._lock = Lock()
        self._bindings = {}

    @contextmanager
    def _writer(self):
        if not self._lock.acquire(blocking=False):
            _refuse("Another strict persistence operation is active; retry later", "strict_cache_busy")
        try:
            yield
        finally:
            self._lock.release()

    def discover(self):
        return self.cache.discover()

    def shadows_legacy(self, doc_id):
        """Exact filename presence shadows old part restore, even if corrupt.

        Directory/access/busy refusal propagates; callers must preserve/report
        an unavailable namespace, never treat the refusal as an absent record.
        Assemblies are independently handled by the existing cache host.
        """
        try:
            os.lstat(self.cache.directory)
        except FileNotFoundError:
            return False
        # Legacy paths predate exact identity admission. An unsafe legacy name
        # cannot be a valid typed manifest identity; leave its old policy alone.
        from backend.api.document_identity import UnsafeDocumentIdentity
        try:
            name = _record_name(doc_id)
        except UnsafeDocumentIdentity:
            return False
        with self.cache._directory() as directory:
            try:
                os.stat(name, dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                return False
            return True

    def reserve_empty(self, doc_id):
        return self.cache.acquire_absent(doc_id)

    def read_pending(self, doc_id):
        return self.cache.read(doc_id)

    def _bind_locked(self, capture, lease):
        _check_capture(capture)
        self.cache._check_lease(lease)
        if lease.doc_id != capture.doc_id or lease._fingerprint is None:
            _refuse("Strict persistence needs the written record's exact document lease")
        manifest = lease._fingerprint[-1]
        if (len(capture.source.payload) != manifest.payload_bytes
                or sha256(capture.source.payload).hexdigest() != manifest.payload_sha256):
            _refuse("Strict persistence binding does not match the durable bytes", "strict_cache_changed")
        if capture.doc_id not in self._bindings and len(self._bindings) >= MAX_RECORDS:
            _refuse("Strict persistence exceeds its bounded host bindings", "strict_cache_limit")
        self._bindings[capture.doc_id] = _Binding(capture.session_identity, capture.revision,
                                                ref(capture.source), lease)

    def write_initial(self, capture, absent_lease):
        """Write first durable bytes before a separate host CAS publication.

        If publication subsequently fails, these complete bytes stay pending.
        This function never creates, replaces or closes a document session.
        """
        _check_capture(capture)
        self.cache._check_lease(absent_lease)
        if absent_lease.doc_id != capture.doc_id or absent_lease._fingerprint is not None:
            _refuse("Initial strict persistence requires its absent-record lease")
        # Check binding admission before any durable write; no failed bound
        # can turn a resource refusal into an unexpected pending record.
        with self._writer():
            if capture.doc_id not in self._bindings and len(self._bindings) >= MAX_RECORDS:
                _refuse("Strict persistence exceeds its bounded host bindings", "strict_cache_limit")
            lease = self.cache.write(absent_lease, capture.source)
            self._bind_locked(capture, lease)
        return lease

    def bind_qualified_record(self, capture, lease):
        """File ownership after the caller's independent cold qualification.

        The caller still needs a distinct restore permit and locked publication.
        No result label or bound file lease grants that authority.
        """
        with self._writer():
            self.cache.assert_current(lease)
            self._bind_locked(capture, lease)

    @contextmanager
    def bind_for_publication(self, capture, lease):
        """Prepare file ownership, then retain its lease through host CAS.

        File checks and the payload digest finish before yielding. The host
        performs its separate permitted publication under the state lock.
        Failure restores only this file binding, never removes durable bytes.
        """
        _check_capture(capture)
        with self._writer(), self.cache.checked_lease(lease):
            previous = self._bindings.get(capture.doc_id)
            self._bind_locked(capture, lease)
            try:
                yield
            except BaseException:
                if previous is None:
                    self._bindings.pop(capture.doc_id, None)
                else:
                    self._bindings[capture.doc_id] = previous
                raise

    def write_capture(self, capture):
        """Persist a previously captured handle; no state lock is acquired here."""
        _check_capture(capture)
        with self._writer():
            binding = self._bindings.get(capture.doc_id)
            if binding is None or binding.session_identity != capture.session_identity:
                _refuse("This strict session has no qualified durable binding; recover or use a new identity")
            if capture.revision < binding.revision:
                return binding.revision  # Never replace newer bytes with an older captured revision.
            if capture.revision == binding.revision:
                if binding.source() is not capture.source:
                    _refuse("The captured revision no longer has its original content", "strict_cache_changed")
                return binding.revision
            lease = self.cache.write(binding.lease, capture.source)
            self._bind_locked(capture, lease)
            return capture.revision

    def write_if_immutable(self, doc_id):
        """Return the actual saved part revision, or None for compatibility."""
        capture = capture_immutable(doc_id)
        return None if capture is None else self.write_capture(capture)
