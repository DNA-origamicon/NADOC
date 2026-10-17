"""Closed input recipes for terminal annotations; native geometry stays derived."""

from copy import deepcopy
import re

from backend.core.models import StrandExtension, VALID_MODIFICATIONS
from backend.core.part_command_errors import (
    CommandContractError,
    ReferenceResolutionError,
)
from backend.core.part_dependencies import Dependencies, Resource
from backend.core.part_operation_input import validate_operation_input

KINDS = frozenset({"extension-upsert", "extension-delete"})
MAX_ENTRIES = 256
MAX_SEQUENCE = 4096
_FIELDS = frozenset({"id", "strand_id", "end", "sequence", "modification", "label"})


def _reject(message):
    raise CommandContractError(message, code="invalid_extension_input")


def _identity(value):
    if type(value) is not str or not 1 <= len(value) <= 256:
        _reject("Extension references require bounded nonempty identities")


def parse_command(kind, params):
    validate_operation_input(params)
    field = "entries" if kind == "extension-upsert" else "extension_ids"
    if (
        kind not in KINDS
        or type(params) is not dict
        or set(params) != {"_proof_version", field}
    ):
        _reject("Terminal extensions require exact versioned inputs")
    if type(params["_proof_version"]) is not int or params["_proof_version"] != 1:
        _reject("Terminal extension proof version must be 1")
    values = params[field]
    if type(values) is not list or not 1 <= len(values) <= MAX_ENTRIES:
        _reject("Terminal extensions require 1–256 entries")
    identities, termini = set(), set()
    for item in values:
        if kind == "extension-delete":
            identity = item
            _identity(identity)
        else:
            if (
                type(item) is not dict
                or set(item) != {"create", "extension"}
                or type(item["create"]) is not bool
            ):
                _reject(
                    "Each extension requires explicit creation intent and complete authored fields"
                )
            ext = item["extension"]
            if type(ext) is not dict or set(ext) != _FIELDS:
                _reject("Extension fields must be complete and closed")
            identity = ext["id"]
            _identity(identity)
            _identity(ext["strand_id"])
            if ext["end"] not in ("five_prime", "three_prime"):
                _reject("Extension end must be five_prime or three_prime")
            key = ext["strand_id"], ext["end"]
            if key in termini:
                _reject("Extension command repeats a strand terminus")
            termini.add(key)
            seq, mod, label = ext["sequence"], ext["modification"], ext["label"]
            if seq is not None and (
                type(seq) is not str
                or not 1 <= len(seq) <= MAX_SEQUENCE
                or re.fullmatch("[ACGTN]+", seq) is None
            ):
                _reject("Extension sequence requires bounded uppercase ACGTN bases")
            if mod is not None and (
                type(mod) is not str or mod not in VALID_MODIFICATIONS
            ):
                _reject("Unknown extension modification")
            if seq is None and mod is None:
                _reject("An extension requires sequence or modification")
            if label is not None and (type(label) is not str or len(label) > 1024):
                _reject("Extension label exceeds its bounded text allowance")
        if identity in identities:
            _reject("Extension command repeats an identity")
        identities.add(identity)
    return deepcopy(params)


def _reference(kind, identity, path, *, ambiguous=False):
    raise ReferenceResolutionError(
        "Extension target is ambiguous or changed"
        if ambiguous
        else "Extension target no longer exists",
        code="invalid_selection" if ambiguous else "missing_reference",
        references=[{"kind": kind, "identity": identity, "parameter_path": path}],
    )


def build(kind, design, params):
    parsed = parse_command(kind, params)
    extensions, strands, termini = {}, {}, {}
    for ext in design.extensions:
        extensions.setdefault(ext.id, []).append(ext)
        termini.setdefault((ext.strand_id, ext.end), []).append(ext.id)
    for strand in design.strands:
        strands.setdefault(strand.id, []).append(strand)
    if kind == "extension-delete":
        for i, identity in enumerate(parsed["extension_ids"]):
            if len(extensions.get(identity, [])) != 1:
                _reference(
                    "extension",
                    identity,
                    ["extension_ids", i],
                    ambiguous=identity in extensions,
                )
        removed = set(parsed["extension_ids"])
        return design.copy_with(
            extensions=[ext for ext in design.extensions if ext.id not in removed]
        )
    changes = {}
    for i, item in enumerate(parsed["entries"]):
        ext = item["extension"]
        path = ["entries", i, "extension"]
        if len(strands.get(ext["strand_id"], [])) != 1:
            _reference(
                "strand",
                ext["strand_id"],
                [*path, "strand_id"],
                ambiguous=ext["strand_id"] in strands,
            )
        matches = extensions.get(ext["id"], [])
        occupied = termini.get((ext["strand_id"], ext["end"]), [])
        if item["create"]:
            if matches or occupied:
                _reference("extension", ext["id"], [*path, "id"], ambiguous=True)
        elif len(matches) != 1:
            _reference("extension", ext["id"], [*path, "id"], ambiguous=bool(matches))
        elif occupied != [ext["id"]] or (matches[0].strand_id, matches[0].end) != (
            ext["strand_id"],
            ext["end"],
        ):
            _reference("extension", ext["id"], path, ambiguous=True)
        changes[ext["id"]] = StrandExtension.model_validate(ext)
    result = [changes.pop(ext.id, ext) for ext in design.extensions]
    result.extend(changes.values())
    return design.copy_with(extensions=result)


def dependencies(kind, params):
    try:
        parsed = parse_command(kind, params)
    except (ValueError, TypeError):
        return Dependencies(known=False)
    if kind == "extension-delete":
        refs = frozenset(
            Resource("extension", value) for value in parsed["extension_ids"]
        )
        return Dependencies(refs, refs)
    reads, writes = set(), set()
    for item in parsed["entries"]:
        ext = item["extension"]
        resource = Resource("extension", ext["id"])
        reads.add(Resource("strand", ext["strand_id"]))
        writes.add(resource)
        if not item["create"]:
            reads.add(resource)
    # Upsert retains the ordinary route's global reconcile/pending-ligation
    # pass. Its indirect topology writes must remain a conservative barrier.
    return Dependencies(frozenset(reads), frozenset(writes), barrier=True)
