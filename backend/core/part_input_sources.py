"""Immutable external inputs for part recipes, separate from generated output.

Resolution is explicit and read-only. A command receives a resolver bound to
admitted bytes; it never searches the workspace, a process library or a URL.
The same compact descriptor is used by portable documents and the project store.
"""

import base64
import binascii
import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from backend.core.part_command_errors import CommandContractError


MAX_SOURCE_BYTES = 50_000_000
MAX_ENCODED_BYTES = 4 * ((MAX_SOURCE_BYTES + 2) // 3)
MAX_SOURCES = 256
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$", strict=True)]


class InputSource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    version: int = Field(default=1, ge=1, le=1)
    sha256: Digest
    size_bytes: int = Field(ge=0, le=MAX_SOURCE_BYTES)
    format: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    media_type: str = Field(min_length=3, max_length=128, pattern=r"^[a-z0-9.+-]+/[a-z0-9.+-]+$")


class EmbeddedInput(BaseModel):
    """Deduplicated portable source bytes; no mutable decoded-array cache."""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    data_b64: str = Field(max_length=MAX_ENCODED_BYTES)


class SourceContractError(CommandContractError):
    """Unavailable evidence is unverified, never a cascade-deletion reason."""

    def __init__(self, detail, *, source: InputSource, code: str):
        super().__init__(detail, code=code)
        self.source = source

    def as_issue(self):
        return {**super().as_issue(), "references": [{
            "kind": "input_source", "identity": self.source.sha256,
            "parameter_path": ["source"],
        }]}


def _error(source, detail, *, missing=False):
    raise SourceContractError(detail, source=source,
        code="source_unavailable" if missing else "source_integrity_mismatch")


def describe(data: bytes, *, format: str, media_type: str) -> InputSource:
    if not isinstance(data, bytes) or len(data) > MAX_SOURCE_BYTES:
        raise ValueError("Input source must be bounded immutable bytes")
    return InputSource(sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data),
                       format=format, media_type=media_type)


def verify(source: InputSource, data: bytes) -> bytes:
    if not isinstance(data, bytes) or len(data) != source.size_bytes:
        _error(source, "Input source length does not match the feature's pinned source")
    if hashlib.sha256(data).hexdigest() != source.sha256:
        _error(source, "Input source checksum does not match the feature's pinned source")
    return data


def embed(source: InputSource, data: bytes) -> EmbeddedInput:
    return EmbeddedInput(data_b64=base64.b64encode(verify(source, data)).decode("ascii"))


def decode(source: InputSource, blob: EmbeddedInput) -> bytes:
    # Bound before allocating decoded bytes. Whitespace and noncanonical base64
    # are rejected instead of changing the immutable file silently on replay.
    expected = 4 * ((source.size_bytes + 2) // 3)
    if len(blob.data_b64) != expected:
        _error(source, "Embedded source length does not match its descriptor")
    try:
        data = base64.b64decode(blob.data_b64, validate=True)
    except (ValueError, binascii.Error) as exc:
        _error(source, f"Embedded source is not valid base64: {exc}")
    verify(source, data)
    if base64.b64encode(data).decode("ascii") != blob.data_b64:
        _error(source, "Embedded source has a noncanonical encoding")
    return data


class EmbeddedResolver:
    """A captured source table with no implicit network/filesystem fallback."""

    def __init__(self, sources: Mapping[str, EmbeddedInput], *, max_encoded_bytes=MAX_ENCODED_BYTES):
        if len(sources) > MAX_SOURCES:
            raise CommandContractError("Input source table exceeds its entry budget", code="source_limit")
        total = 0
        for key, value in sources.items():
            if not isinstance(key, str) or not re.fullmatch(r"[0-9a-f]{64}", key):
                raise ValueError("Input table keys must be source digests")
            if not isinstance(value, EmbeddedInput):
                raise TypeError("Source resolver requires immutable admitted input records")
            total += len(value.data_b64)
            if total > max_encoded_bytes:
                raise CommandContractError("Input source table exceeds its byte budget", code="source_limit")
        self._sources = dict(sources)

    def __call__(self, source: InputSource) -> bytes:
        blob = self._sources.get(source.sha256)
        if blob is None:
            _error(source, "The feature's pinned input source is unavailable", missing=True)
        return decode(source, blob)


def read_verified(path: Path, source: InputSource) -> bytes:
    """Read at most the declared length plus one byte, then verify content."""
    try:
        with path.open("rb") as handle:
            data = handle.read(source.size_bytes + 1)
    except OSError as exc:
        _error(source, f"The feature's pinned input source is unavailable: {exc.strerror}", missing=True)
    return verify(source, data)


def command_source_bindings(kind, params) -> tuple[tuple[str, InputSource], ...]:
    """Parameter names and descriptors owned by source-bearing command families.

    This cheap declaration is shared by portability and explicit source audit;
    executor schemas still decide whether a command is admitted for proof.
    """
    if (kind == "nanoparticle-patch" and params.get("_proof_version") == 1
            and "coating_version" in params and params.get("action") == "set"):
        return tuple((key, InputSource.model_validate(params[key]))
                     for key in ("pdb_source", "coverage_source") if params.get(key) is not None)
    source_bearing = kind in {"protein-import", "aptamer-import", "cadnano-import"} or (
        kind == "nanoparticle-create" and "quantum_dot_version" in params)
    if (not source_bearing or params.get("_proof_version") != 1 or "source" not in params):
        return ()
    return (("source", InputSource.model_validate(params["source"])),)


def command_sources(kind, params) -> tuple[InputSource, ...]:
    return tuple(source for _, source in command_source_bindings(kind, params))


def portable_sources(design) -> dict[str, InputSource]:
    """Validate portable byte closure without parsing or regenerating geometry.

    Source-bearing contracts declare their named input descriptors. Legacy
    receipts without them are left legacy; this does not invent sources.
    Unreferenced retained inputs are checked too, so undo/drafts can reuse them.
    """
    from backend.core.part_overlay_commands import command_input

    resolver = EmbeddedResolver(design.input_sources)
    descriptors = {}
    for entry in design.feature_log:
        children = entry.children if entry.feature_type == "routing-cluster" else [entry]
        for child in children:
            kind, params = command_input(child)
            for source in command_sources(kind, params):
                resolver(source)
                descriptors[source.sha256] = source
    for sha256, blob in design.input_sources.items():
        if sha256 in descriptors:
            continue
        encoded = blob.data_b64
        size = (len(encoded) // 4) * 3 - (len(encoded) - len(encoded.rstrip("=")))
        source = InputSource(sha256=sha256, size_bytes=max(0, size),
                             format="blob", media_type="application/octet-stream")
        resolver(source)
        descriptors[sha256] = source
    return descriptors
