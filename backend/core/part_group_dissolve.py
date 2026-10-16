"""Bounded, placement-preserving removal of ordinary identity groups.

This command removes grouping records, never DNA or a transform's geometric
effect. Posed, owned or scope-dependent groups require a different contract.
The host owns publication/recovery; this module never reads history or state.
"""

from math import isfinite
from typing import get_args

from pydantic import BaseModel

from backend.core import models as m
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_operation_input import MAX_OPERATION_BYTES, MAX_OPERATION_NODES, validate_operation_input
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_saved_topology import snapshot_for
from backend.core.part_scope_references import COLLECTIONS, GLOBALS, SCHEMAS


KIND = "cluster-dissolve"
MAX_GROUPS = 128
MAX_ID_CHARS = 512
_COLLECTIONS = {
    "cluster_transforms": m.ClusterRigidTransform,
    "lattice_frames": m.LatticeFrame,
    "cluster_joints": m.ClusterJoint,
    "cluster_join_constraints": m.ClusterJoinConstraint,
    "flexible_connections": m.FlexibleConnection,
    "deformations": m.DeformationOp,
    "overhang_bindings": m.OverhangBinding,
    "duplexes": m.Duplex,
    "helices": m.Helix,
    "strands": m.Strand,
}
_SAVED_FIELDS = frozenset({"driver_oh_id", "driven_oh_id", "driven_helix", "strand_id",
    "domain_index", "prior_domain", "prior_ovhg_helix_id", "crossovers"})
# This existing union alternative is intentionally outside generated part
# remapping. Its scalar instance/interface/overhang references cannot own a
# part cluster. Do not make an absent shared schema a general permission.
_EXTERNAL_LEAVES = {m.ProteinTargetAssembly: frozenset({
    "kind", "instance_id", "interface_label", "overhang_id", "attach_end"})}


def _unsupported(detail, *, code="unsupported_group_dissolve"):
    raise CommandContractError(detail, code=code)


def parse_command(params):
    """Validate only bounded command metadata; return ordered immutable IDs."""
    try:
        validate_operation_input(params)
    except ValueError as error:
        _unsupported(str(error), code="invalid_group_dissolve_input")
    if (type(params) is not dict or set(params) != {"_proof_version", "cluster_ids"}
            or type(params["_proof_version"]) is not int or params["_proof_version"] != 1):
        _unsupported("Group dissolution requires the closed version 1 input.", code="invalid_group_dissolve_input")
    ids = params["cluster_ids"]
    if (type(ids) is not list or not 1 <= len(ids) <= MAX_GROUPS
            or any(type(value) is not str or not 1 <= len(value) <= MAX_ID_CHARS for value in ids)
            or len(set(ids)) != len(ids)):
        _unsupported("Select 1–128 unique bounded group identities.", code="invalid_group_dissolve_input")
    return tuple(ids)


class _Budget:
    """Charge typed metadata per occurrence, before parsing/indexing anything."""

    def __init__(self):
        self.nodes = MAX_OPERATION_NODES
        self.bytes = MAX_OPERATION_BYTES

    def item(self, count=1):
        self.nodes -= count
        self.bytes -= 16 * count
        if self.nodes < 0 or self.bytes < 0:
            _unsupported("Group reference inventory exceeds its bounded allowance.", code="group_dissolve_limit")

    def reserve(self, count):
        if count > self.nodes or 16 * count > self.bytes:
            _unsupported("Group reference inventory exceeds its bounded allowance.", code="group_dissolve_limit")

    def text(self, value, *, identity=True):
        self.item()
        if type(value) is not str or (identity and not value):
            _unsupported("Group reference inventory contains an invalid identity.")
        if identity and len(value) > MAX_ID_CHARS:
            _unsupported("Group identity exceeds its bounded allowance.", code="group_dissolve_limit")
        self.bytes -= 4 * len(value)
        self.reserve(0)

    def saved_json(self, value):
        # Only the positively recognized saved-topology grammar enters here.
        # Count repeated aliases independently because its typed codec does too.
        pending = [(value, 0)]
        while pending:
            item, depth = pending.pop()
            self.item()
            if depth > 64:
                _unsupported("Saved group-reference nesting exceeds its allowance.", code="group_dissolve_limit")
            if type(item) is str:
                self.bytes -= 4 * len(item)
                self.reserve(0)
            elif item is None or type(item) is bool:
                pass
            elif type(item) is int:
                if item.bit_length() > 64:
                    _unsupported("Saved topology contains an unsupported integer.")
            elif type(item) is float:
                if not isfinite(item):
                    _unsupported("Saved topology contains a nonfinite scalar.")
            elif type(item) in {dict, list}:
                self.reserve(len(pending) + len(item) * (2 if type(item) is dict else 1))
                if type(item) is dict:
                    for key, child in item.items():
                        if type(key) is not str:
                            _unsupported("Saved topology requires string field names.")
                        pending.extend(((key, depth + 1), (child, depth + 1)))
                else:
                    pending.extend((child, depth + 1) for child in item)
            else:
                _unsupported("Saved topology contains unsupported non-JSON data.")


def _schema(record):
    schema = SCHEMAS.get(type(record))
    if schema is None or schema.fields != type(record).model_fields.keys():
        _unsupported("Group reference inventory has an unclassified model schema.")
    return schema


def _model_types(annotation):
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return {annotation}
    return {model for child in get_args(annotation) for model in _model_types(child)}


def _check_inventory_contract():
    """Class metadata only: close both direct and nested future owner families."""
    authoring = {field for field, role in FIELD_ROLES.items() if role == "authoring"}
    if (set(m.Design.model_fields) - FIELD_ROLES.keys()
            or set(COLLECTIONS) | GLOBALS != authoring):
        _unsupported("Group reference inventory has unclassified authoring fields.")
    cache, active = {}, set()

    def reaches_cluster(model):
        if model in cache:
            return cache[model]
        if model in active:
            _unsupported("Group reference schema contains unsupported recursive owners.")
        schema = SCHEMAS.get(model)
        if schema is None and model in _EXTERNAL_LEAVES:
            if (model.model_fields.keys() != _EXTERNAL_LEAVES[model]
                    or any(_model_types(field.annotation) for field in model.model_fields.values())):
                _unsupported("Group reference inventory has an unclassified external owner schema.")
            cache[model] = False
            return False
        if schema is None or schema.fields != model.model_fields.keys():
            _unsupported("Group reference inventory has an unclassified model schema.")
        active.add(model)
        reachable = ("cluster" in schema.refs.values()
            or "targets" in schema.special or "prior_driven_topology" in schema.special)
        for field in schema.children:
            children = _model_types(model.model_fields[field].annotation)
            if not children:
                _unsupported("Group reference inventory has an unclassified child schema.")
            for child in children:
                reachable = reaches_cluster(child) or reachable
        active.remove(model)
        cache[model] = reachable
        return reachable

    for field in COLLECTIONS:
        roots = _model_types(m.Design.model_fields[field].annotation)
        if not roots:
            _unsupported("Group reference inventory has an unclassified collection schema.")
        for model in roots:
            if reaches_cluster(model) and field not in _COLLECTIONS:
                _unsupported("Group reference inventory requires a newer nested-owner contract.")


def _saved(owner, path, budget):
    value = owner.prior_driven_topology
    if value is None:
        return None
    if (type(value) is not dict or len(value) not in {8, 9}
            or any(type(key) is not str for key in value)
            or set(value) not in (_SAVED_FIELDS, _SAVED_FIELDS | {"forced_ligation"})):
        _unsupported("Saved binding topology has an unknown reference grammar.")
    helix = value["driven_helix"]
    if (type(helix) is not dict or len(helix) != len(m.Helix.model_fields)
            or any(type(key) is not str for key in helix)
            or helix.keys() != m.Helix.model_fields.keys()):
        _unsupported("Saved binding helix has an unknown reference grammar.")
    residues = helix["native_residues"]
    if type(residues) is not list or residues:
        _unsupported("Dissolution does not inspect saved atomistic residue graphs.")
    budget.saved_json(value)
    try:
        return snapshot_for(owner)
    except (NotImplementedError, ValueError, TypeError, KeyError):
        _unsupported(f"Saved binding topology cannot establish reference ownership at {path[0]}.")


def _targets(values, path, owner, budget, incoming):
    if values is None:
        return
    if type(values) is not list:
        _unsupported("Deformation target references have an unsupported shape.")
    budget.reserve(len(values))
    for index, target in enumerate(values):
        budget.item()
        if type(target) is not dict or not 2 <= len(target) <= 3 or any(type(key) is not str for key in target):
            _unsupported("Deformation target references have an unsupported shape.")
        kind = target.get("kind")
        if type(kind) is not str:
            _unsupported("Deformation target kind is unsupported.")
        budget.text(kind)
        if kind in {"cluster", "strand"} and set(target) == {"kind", "id"}:
            budget.text(target["id"])
            if kind == "cluster":
                incoming.append((target["id"], owner, [*path, index, "id"]))
        elif kind == "domain" and set(target) in (
                {"kind", "strandId", "domainIndex"}, {"kind", "strand_id", "domain_index"}):
            identity = "strandId" if "strandId" in target else "strand_id"
            ordinal = "domainIndex" if identity == "strandId" else "domain_index"
            budget.text(target[identity])
            if type(target[ordinal]) is not int or target[ordinal] < 0:
                _unsupported("Deformation domain ordinal is invalid.")
        else:
            _unsupported("Deformation target references have an unknown grammar.")


def _walk(record, path, owner, budget, incoming, depth=0):
    budget.item()
    if depth > 64:
        _unsupported("Group reference nesting exceeds its allowance.", code="group_dissolve_limit")
    schema = _schema(record)
    allowed_special = ({"targets"} if type(record) is m.DeformationOp
        else {"prior_driven_topology"} if type(record) in {m.OverhangBinding, m.Duplex} else set())
    if schema.special - allowed_special:
        _unsupported("Group reference inventory has an unclassified special field.")
    if schema.identity:
        budget.text(record.id)
    for field, kind in schema.refs.items():
        value = getattr(record, field)
        values = value if type(value) is list else [value]
        budget.reserve(len(values))
        for index, identity in enumerate(values):
            if identity is None:
                continue
            budget.text(identity)
            if kind == "cluster":
                incoming.append((identity, owner, [*path, field, *([index] if type(value) is list else [])]))
    for field in schema.children:
        value = getattr(record, field)
        values = value if type(value) is list else [value]
        budget.reserve(len(values))
        for index, child in enumerate(values):
            if child is not None:
                _walk(child, [*path, field, *([index] if type(value) is list else [])],
                    owner, budget, incoming, depth + 1)
    if type(record) is m.DeformationOp:
        _targets(record.targets, [*path, "targets"], owner, budget, incoming)
    if type(record) in {m.OverhangBinding, m.Duplex}:
        snapshot = _saved(record, path, budget)
        if snapshot is not None:
            # Restoration definitions are typed, not opaque permission to drop
            # their external references. Current frames are checked even when
            # the corresponding helix exists only in this retained snapshot.
            for key, definition in snapshot.definitions():
                _walk(definition, [*path, "prior_driven_topology", key[0], key[1]],
                    owner, budget, incoming, depth + 1)


def _inventory(design):
    if type(design) is not m.Design:
        _unsupported("Group dissolution requires an ordinary owned Design.")
    _check_inventory_contract()
    total = 0
    for field in _COLLECTIONS:
        values = getattr(design, field)
        if type(values) is not list:
            _unsupported("Group reference collections must be plain lists.")
        total += len(values)
        if total > MAX_OPERATION_NODES:
            _unsupported("Group reference collection count exceeds its allowance.", code="group_dissolve_limit")
    budget, incoming = _Budget(), []
    for field, model in _COLLECTIONS.items():
        for index, record in enumerate(getattr(design, field)):
            if type(record) is not model:
                _unsupported("Group reference collection has an unsupported record type.")
            schema = _schema(record)
            budget.text(record.id)
            owner = {"kind": schema.identity, "identity": record.id}
            _walk(record, [field, index], owner, budget, incoming)
    return incoming


def _reference(identity, offset, *, missing=False, owner=None, model_path=None):
    ref = {"kind": "cluster", "identity": identity, "parameter_path": ["cluster_ids", offset]}
    if owner is not None:
        ref.update(owner=owner, model_path=model_path)
    raise ReferenceResolutionError(
        "Selected group is missing." if missing else "Group dissolution has an ambiguous or live dependent owner.",
        code="missing_reference" if missing else "invalid_selection", references=[ref])


def _identity_pose(group):
    for field, size in (("translation", 3), ("rotation", 4), ("pivot", 3)):
        value = getattr(group, field)
        if (type(value) is not list or len(value) != size
                or any(type(item) not in {float, int} or not isfinite(item) for item in value)):
            _unsupported("Group pose must be finite and structurally valid.")
    return group.translation == [0, 0, 0] and group.rotation in ([0, 0, 0, 1], [0, 0, 0, -1])


def _scope(group, strands, helices):
    scope = set(group.helix_ids)
    if not scope <= helices:
        _unsupported("Group membership includes missing helices.")
    for ref in group.domain_ids:
        matches = strands.get(ref.strand_id, ())
        if (len(matches) != 1 or type(ref.domain_index) is not int
                or not 0 <= ref.domain_index < len(matches[0].domains)):
            _unsupported("Group domain membership is missing or ambiguous.")
        scope.add(matches[0].domains[ref.domain_index].helix_id)
    if not scope <= helices:
        _unsupported("Group domain membership includes missing helices.")
    return scope


def build(design, params):
    """Remove the entire admitted batch or return no candidate at all."""
    identities = parse_command(params)
    incoming = _inventory(design)
    groups = {}
    for group in design.cluster_transforms:
        groups.setdefault(group.id, []).append(group)
    selected = {}
    for offset, identity in enumerate(identities):
        matches = groups.get(identity, ())
        if len(matches) != 1:
            _reference(identity, offset, missing=not matches)
        selected[identity] = matches[0]
    offsets = {identity: index for index, identity in enumerate(identities)}
    for identity, owner, path in incoming:
        if identity in selected:
            _reference(identity, offsets[identity], owner=owner, model_path=path)
    strands = {}
    for strand in design.strands:
        strands.setdefault(strand.id, []).append(strand)
    helices = {helix.id for helix in design.helices}
    if len(helices) != len(design.helices):
        _unsupported("Group scope has ambiguous helix identities.")
    removed_scope = set()
    for group in selected.values():
        if group.parent_cluster_id is not None or group.overhang_duplex_driver_id is not None:
            _unsupported("Remove the owning connection before dissolving a dependent group.")
        if not _identity_pose(group):
            _unsupported("A posed group cannot be dissolved without changing placement.")
        scope = _scope(group, strands, helices)
        # Even identity arithmetic subtracts/adds pivot in existing kernels.
        # Keep repivoted populated groups unsupported rather than choosing a
        # numerical tolerance or silently changing their floating-point pose.
        if scope and group.pivot != [0, 0, 0]:
            _unsupported("A repivoted group requires a separately qualified dissolution contract.")
        removed_scope.update(scope)
    if removed_scope:
        for op in design.deformations:
            if not op.affected_helix_ids or removed_scope.intersection(op.affected_helix_ids):
                _unsupported("Group dissolution would change an active deformation's arm scope.")
        for group in design.cluster_transforms:
            if group.id not in selected and (not _identity_pose(group) or group.pivot != [0, 0, 0]):
                if removed_scope.intersection(_scope(group, strands, helices)):
                    _unsupported("Group dissolution overlaps a retained pose's placement scope.")
    return design.copy_with(cluster_transforms=[group for group in design.cluster_transforms
        if group.id not in selected])
