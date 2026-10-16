"""Bounded definition-only draft capture, with no source decoding or hashing."""

from dataclasses import dataclass, field
from math import isfinite
from time import monotonic

from pydantic import BaseModel

from backend.core.models import Direction
from backend.core.part_input_sources import MAX_SOURCES, EmbeddedInput, command_source_bindings
from backend.core.part_overlay_commands import KINDS as OVERLAY_KINDS, command_input
from backend.core.part_repair_draft import RepairDraft
from backend.core.part_repair_inputs import MAX_REPAIR_ACTIONS
from backend.core.part_repair_proposal import proposed_inputs
from backend.core.part_verification_capture import CaptureLimit


@dataclass(frozen=True)
class DraftCapture:
    """Private capture, not persisted state or a publishable model."""

    id: str
    source_revision: int
    draft: RepairDraft | None
    definitions_captured: bool
    recipe_root: object | None = None
    feature_log: list = field(default_factory=list)
    feature_log_cursor: int = -1
    feature_log_sub_cursor: int | None = None
    input_sources: dict = field(default_factory=dict)


class _Copier:
    def __init__(self, nodes, size, seconds):
        self.nodes, self.size = nodes, size
        self.deadline = monotonic() + seconds

    def check(self):
        if self.nodes < 0 or self.size < 0 or monotonic() > self.deadline:
            raise CaptureLimit("Repair draft capture budget exceeded")

    def clone(self, value, depth=0):
        self.nodes -= 1
        self.size -= 16
        self.check()
        if depth > 64:
            raise CaptureLimit("Repair draft capture depth exceeded")
        if type(value) is Direction:
            # Resolved native deformation ranges retain this closed immutable
            # enum. Do not admit arbitrary Enum subclasses or stringify them.
            self.size -= 4 * len(value.value)
            result = value
        elif type(value) is str:
            self.size -= 4 * len(value)
            result = value  # immutable; charge before retaining it
        elif value is None or type(value) is bool:
            result = value
        elif type(value) is int:
            if value.bit_length() > 64:
                raise ValueError("Repair draft capture integer exceeds the supported range")
            result = value
        elif type(value) is float:
            if not isfinite(value):
                raise ValueError("Repair draft capture requires finite numbers")
            result = value
        elif isinstance(value, BaseModel):
            names = type(value).model_fields
            if len(names) > self.nodes:
                raise CaptureLimit("Repair draft capture node budget exceeded")
            copied = {name: self.clone(getattr(value, name), depth + 1) for name in names}
            result = type(value).model_construct(**copied)
        elif type(value) in {list, tuple, dict}:
            if len(value) > self.nodes:
                raise CaptureLimit("Repair draft capture node budget exceeded")
            if type(value) is dict:
                result = {}
                for key, child in value.items():
                    if type(key) is not str:
                        raise ValueError("Repair draft capture keys must be strings")
                    result[self.clone(key, depth + 1)] = self.clone(child, depth + 1)
            else:
                children = [self.clone(child, depth + 1) for child in value]
                result = tuple(children) if type(value) is tuple else children
        else:
            raise ValueError("Repair draft capture supports typed definitions and JSON inputs only")
        self.check()
        return result


def capture_draft_inputs(design, *, source_revision, draft=None, proposed_actions=(),
                         include_definitions=True, max_entries=2000,
                         max_nodes=30_000, max_bytes=2_000_000, seconds=0.025):
    """Caller owns the state lock; mutable definitions are cloned before return.

    Include proposed actions only when needed for the current explicit request.
    Source-bearing patches are applied to private inputs solely to discover
    named descriptors. Immutable source records are shared after byte charging.
    Discard uses ``include_definitions=False`` so broken/large history cannot
    prevent clearing a draft. Limits bound cooperative work, not OS wall time.
    """
    from backend.core.models import (
        ClusterCreateLogEntry, ClusterOpLogEntry, DeformationLogEntry,
        OverhangRotationLogEntry, RoutingClusterLogEntry,
    )

    if type(source_revision) is not int or source_revision < 0:
        raise ValueError("Draft capture requires a trusted nonnegative session revision")
    if draft is not None and not isinstance(draft, RepairDraft):
        raise TypeError("Draft capture requires an admitted RepairDraft")
    copier = _Copier(max_nodes, max_bytes, seconds)
    identity = copier.clone(design.id)
    captured_draft = copier.clone(draft)
    if not include_definitions:
        if proposed_actions:
            raise ValueError("Metadata-only capture cannot discover proposed source inputs")
        return DraftCapture(identity, source_revision, captured_draft, False)
    if len(proposed_actions) > MAX_REPAIR_ACTIONS:
        raise CaptureLimit("Repair draft capture action budget exceeded")
    actions = copier.clone(list(proposed_actions))
    root = copier.clone(design.recipe_root)
    if len(design.feature_log) > max_entries:
        raise CaptureLimit("Repair draft capture entry budget exceeded")
    remaining = max_entries

    def header(entry):
        nonlocal remaining
        remaining -= 1
        if remaining < 0:
            raise CaptureLimit("Repair draft capture entry budget exceeded")
        if entry.feature_type in OVERLAY_KINDS:
            # These entry types are themselves authored input definitions.
            return copier.clone(entry)
        names = ("id", "feature_type", "op_kind", "op_subtype", "params")
        values = {name: copier.clone(getattr(entry, name)) for name in names if name in type(entry).model_fields}
        return type(entry).model_construct(**values)

    log = []
    for entry in design.feature_log:
        copier.check()
        if entry.feature_type == "routing-cluster":
            remaining -= 1
            if remaining < len(entry.children):
                raise CaptureLimit("Repair draft capture entry budget exceeded")
            log.append(RoutingClusterLogEntry.model_construct(id=copier.clone(entry.id),
                children=[header(child) for child in entry.children]))
        else:
            log.append(header(entry))
    result = DraftCapture(identity, source_revision, captured_draft, True, root, log,
        copier.clone(design.feature_log_cursor), copier.clone(design.feature_log_sub_cursor))
    descriptors = {}

    def remember(kind, params):
        copier.check()
        for _, source in command_source_bindings(kind, params):
            descriptors[source.sha256] = source
            if len(descriptors) > MAX_SOURCES:
                raise CaptureLimit("Repair draft capture source count budget exceeded")

    # These exact typed overlay contracts have no command_source_bindings.
    # Keep the list/version inventory explicit: a future kind or contract must
    # follow ordinary discovery until its source ownership is reviewed.
    source_free_overlays = {
        ClusterCreateLogEntry: ("cluster_create", (1, 2)),
        ClusterOpLogEntry: ("cluster_op", (1,)),
        DeformationLogEntry: ("deformation", (1,)),
        OverhangRotationLogEntry: ("overhang_rotation", (1,)),
    }
    for entry in log:
        for child in entry.children if entry.feature_type == "routing-cluster" else [entry]:
            declaration = source_free_overlays.get(type(child))
            if declaration is not None and child.feature_type == declaration[0] and (
                child.proof_version is None
                or type(child.proof_version) is int and child.proof_version in declaration[1]
            ):
                continue
            remember(*command_input(child))
    for kind, params in proposed_inputs(result, actions, copy_value=copier.clone, check_expectations=False):
        remember(kind, params)
    for digest in descriptors:
        copier.check()
        blob = design.input_sources.get(digest)
        if blob is None:
            continue  # absence is explicit fingerprint/audit evidence later
        if not isinstance(blob, EmbeddedInput):
            raise TypeError("Draft capture requires immutable admitted source records")
        copier.clone(blob.data_b64)  # strings shared, charged before admission
        result.input_sources[digest] = blob
    copier.check()
    return result
