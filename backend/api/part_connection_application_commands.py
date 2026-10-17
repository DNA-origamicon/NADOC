"""Bounded versioned ordinary-linker Apply over existing native algorithms.

The pure builder and private recording adapter share one admitted selection and
the unchanged native materializer. V1 stays finite-only; V2 also admits indirect
links and exact zero-bridge removal. Direct bindings retain their legacy callback.
"""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from math import isfinite
from typing import Annotated, Literal, get_args
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from backend.core.cluster_reconcile import MutationReport
from backend.core.models import ConnectionVersion, OverhangConnection, StrandType
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_operation_input import MAX_OPERATION_BYTES, MAX_OPERATION_NODES, validate_operation_input
from backend.core.part_scope_references import COLLECTIONS, SCHEMAS, identity_index, referenced_resources


ACTION = "connection-version-apply-linker"
# Provisional pure-builder ceiling, not a live-route latency qualification. This
# stays below the ordinary proof/capture ceilings and never raises those limits.
MAX_APPLICATION_BASES = 4_096
MAX_CONFLICTS = 128
_Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
_FiniteType = Literal[
    "root-to-root-ssdna-linker", "root-to-end-ssdna-linker",
    "end-to-root-ssdna-linker", "end-to-end-ssdna-linker",
    "root-to-root-dsdna-linker", "root-to-end-dsdna-linker",
    "end-to-root-dsdna-linker", "end-to-end-dsdna-linker",
]
_IndirectType = Literal["root-to-root-indirect", "end-to-end-indirect"]
INDIRECT_TYPES = frozenset(get_args(_IndirectType))


def supported_types(version):
    if type(version) is not int or version not in {1, 2}:
        raise ValueError("Unsupported native linker contract version")
    return frozenset(get_args(_FiniteType)) | (INDIRECT_TYPES if version == 2 else frozenset())


_SOURCE_FIELDS = frozenset({
    "dimensions", "lattice_frames", "helices", "strands", "cluster_transforms",
    "nucleotide_transforms", "overhangs", "overhang_connections", "connection_versions",
    "crossovers", "crossover_constraints", "forced_ligations", "staple_groups",
})


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    connection_application_version: Annotated[StrictInt, Field(ge=1, le=1)]
    action: Literal["connection-version-apply-linker"]
    version_id: _Id
    overhang_a_id: _Id
    overhang_b_id: _Id
    connection_type: _FiniteType
    # Generated strand IDs add the seven-character prefix and three-character
    # suffix. Keep their complete identities within the source's 256-char limit.
    connection_id: Annotated[str, Field(strict=True, min_length=1, max_length=246)]
    conflict_connection_ids: list[_Id] = Field(max_length=MAX_CONFLICTS)
    conflict_version_ids: list[_Id] = Field(max_length=MAX_CONFLICTS)

    @field_validator("conflict_connection_ids", "conflict_version_ids")
    @classmethod
    def unique_conflicts(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("Application conflict selections must be unique")
        return value


class ApplyRequestV2(ApplyRequest):
    connection_application_version: Annotated[StrictInt, Field(ge=2, le=2)]
    connection_type: _FiniteType | _IndirectType


def parse_command(params):
    validate_operation_input(params)
    if type(params) is not dict:
        raise ValueError("Native connection inputs require an object")
    model = ApplyRequestV2 if params.get("connection_application_version") == 2 else ApplyRequest
    return model.model_validate(params)


def dependency_contract(params, *, topology):
    from backend.core.part_dependencies import Dependencies, Resource
    try:
        command = parse_command(params)
    except ValueError:
        return Dependencies(known=False)
    versions = {Resource("connection_version", identity) for identity in command.conflict_version_ids}
    reads = {topology, Resource("connection_version", command.version_id),
             Resource("overhang", command.overhang_a_id), Resource("overhang", command.overhang_b_id),
             *versions, *(Resource("overhang_connection", identity) for identity in command.conflict_connection_ids)}
    prefix = f"__lnk__{command.connection_id}"
    suffixes = ("a", "b") if "dsdna" in command.connection_type else ("s",)
    writes = {topology, Resource("overhang_connection", command.connection_id),
              *versions, *(Resource("strand", f"{prefix}__{suffix}") for suffix in suffixes)}
    if command.connection_type not in INDIRECT_TYPES:
        writes.add(Resource("helix", prefix))
    return Dependencies(frozenset(reads), frozenset(writes), barrier=True)


def _unsupported(detail):
    raise CommandContractError(detail, code="unsupported_connection_application_source")


def _fail(detail, kind, identity, path, *, missing=False):
    raise ReferenceResolutionError(detail, code="missing_reference" if missing else "invalid_selection",
        references=[{"kind": kind, "identity": identity,
                     "parameter_path": [path] if isinstance(path, str) else path}])


def _resolve(index, kind, identity, path):
    value = index.get((kind, identity))
    if value is None:
        _fail("Selected linker application input is missing", kind, identity, path, missing=True)
    return value


def _bounded_source(design, *, extra_fields=frozenset()):
    """Bound declared source work before indexing references or building arrays.

    Unlike command JSON, these are typed model records. Visit only the admitted
    authoring collections, never history, source blobs, presentation or recovery.
    This pass validates finite scalar transport and charges mutable nested data;
    the shared reference schema remains responsible for reference meaning.
    """
    if sum(len(getattr(design, field)) for field in COLLECTIONS) > MAX_OPERATION_NODES:
        _unsupported("Linker application exceeds its source record allowance")
    source_fields = _SOURCE_FIELDS | extra_fields
    for field in COLLECTIONS.keys() - source_fields:
        if getattr(design, field):
            _unsupported(f"Finite linker application does not yet admit {field}")
    for helix in design.helices:
        if helix.native_residues or helix.native_source:
            _unsupported("Finite linker application requires native DNA hosts")
    pending = [(getattr(design, field), 0) for field in source_fields]
    nodes, size = 0, 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        size += 16
        if nodes > MAX_OPERATION_NODES or size > MAX_OPERATION_BYTES or depth > 64:
            _unsupported("Linker application exceeds its source metadata allowance")
        if isinstance(item, BaseModel):
            if item.model_extra:
                _unsupported("Linker application source has unclassified model fields")
            schema = SCHEMAS.get(type(item))
            if schema is not None and schema.identity:
                identity = item.id
                if type(identity) is not str or not identity or len(identity) > 256:
                    _unsupported("Linker application source has an unsupported identity")
            children = [getattr(item, name) for name in type(item).model_fields]
        elif type(item) in {list, tuple}:
            children = item
        elif type(item) is dict:
            if nodes + len(pending) + 2 * len(item) > MAX_OPERATION_NODES:
                _unsupported("Linker application exceeds its source metadata allowance")
            children = [*item.keys(), *item.values()]
        elif isinstance(item, str):
            size += 4 * len(item)
            if size > MAX_OPERATION_BYTES:
                _unsupported("Linker application exceeds its source byte allowance")
            continue
        elif item is None or type(item) is bool:
            continue
        elif type(item) is int:
            if item.bit_length() > 64:
                _unsupported("Linker application source integer exceeds its supported range")
            continue
        elif type(item) is float:
            if not isfinite(item):
                _unsupported("Linker application requires finite source values")
            continue
        else:
            _unsupported("Linker application source has unsupported mutable values")
        if nodes + len(pending) + len(children) > MAX_OPERATION_NODES:
            _unsupported("Linker application exceeds its source metadata allowance")
        pending.extend((child, depth + 1) for child in children)


def _work_admission(design, bridge_length, complement_domains):
    helix_bases, emitted = bridge_length, 2 * bridge_length
    if emitted > MAX_APPLICATION_BASES:
        _unsupported("Linker application exceeds its emitted-base allowance")
    loop_positions = {}
    for helix in design.helices:
        if type(helix.length_bp) is not int or helix.length_bp < 1:
            _unsupported("Linker application requires positive native helix spans")
        insertions = []
        for entry in helix.loop_skips:
            if entry.delta not in {-1, 1}:
                _unsupported("Linker application has unsupported loop work")
            if entry.delta == 1:
                # Geometry sums duplicate descriptors; the sequence map is
                # last-wins. Retaining every positive descriptor bounds both.
                insertions.append(entry.bp_index)
        helix_bases += helix.length_bp + len(insertions)
        if helix_bases > MAX_APPLICATION_BASES:
            _unsupported("Linker application exceeds its helix-slot allowance")
        loop_positions[helix.id] = sorted(insertions)

    def domain_work(domain):
        lo, hi = sorted((domain.start_bp, domain.end_bp))
        insertions = loop_positions.get(domain.helix_id, ())
        return hi - lo + 1 + bisect_right(insertions, hi) - bisect_left(insertions, lo)

    # The native complementary domains inherit exactly these backing spans.
    # Charge their loop copies before any sequence patch or anchor geometry.
    emitted += sum(domain_work(domain) for domain in complement_domains)
    if emitted > MAX_APPLICATION_BASES:
        _unsupported("Linker application exceeds its emitted-base allowance")
    for strand in design.strands:
        if strand.is_reference:
            _unsupported("Finite linker application does not yet admit reference strands")
        if len(strand.sequence or "") > MAX_APPLICATION_BASES:
            _unsupported("Linker application exceeds its sequence allowance")
        for domain in strand.domains:
            # Charge every domain, including repeated/unvalidated occupancy.
            # Retaining skipped positions is conservative; no derived sequence
            # or geometry is computed during this bounded admission pass.
            emitted += domain_work(domain)
            if emitted > MAX_APPLICATION_BASES:
                _unsupported("Linker application exceeds its emitted-base allowance")
    for record in [*design.crossovers, *design.forced_ligations]:
        if record.extra_bases:
            _unsupported("Finite linker application does not yet admit inserted crossover bases")
    if any(item.kind != "base" for item in design.nucleotide_transforms):
        _unsupported("Finite linker application does not yet admit extra-base poses")


def _target(design, index, backings, host_owners, identity, path):
    spec = _resolve(index, "overhang", identity, path)
    helix = _resolve(index, "helix", spec.helix_id, path)
    strand = _resolve(index, "strand", spec.strand_id, path)
    owned = backings.get(identity, ())
    if (spec.auxiliary_endpoint or spec.parent_overhang_id is not None or len(owned) != 1
            or owned[0][0] is not strand or owned[0][1].helix_id != helix.id
            or owned[0][1].binds_overhang_id or strand.is_reference):
        _fail("Application requires one consistent ordinary overhang backing domain", "overhang", identity, path)
    domain = owned[0][1]
    if (host_owners.get(helix.id) != [identity]
            or sorted((domain.start_bp, domain.end_bp)) != [helix.bp_start, helix.bp_start + helix.length_bp - 1]):
        _unsupported("Finite linker application requires dedicated full-span overhang hosts; shared or partial hosts are not admitted")
    from backend.core.overhang_ops import SubDomainTilingError, validate_sub_domain_tiling
    try:
        validate_sub_domain_tiling(design, identity)
    except SubDomainTilingError as error:
        _fail(str(error), "overhang", identity, path)
    return spec, strand, domain, helix


def _conflicts(design, body, index):
    selected = {body.overhang_a_id, body.overhang_b_id}
    connections = [item for item in design.overhang_connections
                   if selected.intersection((item.overhang_a_id, item.overhang_b_id))]
    versions = [item for item in design.connection_versions
                if selected.intersection((item.overhang_a_id, item.overhang_b_id))]
    for rows, expected, kind, path in (
        (connections, body.conflict_connection_ids, "overhang_connection", "conflict_connection_ids"),
        (versions, body.conflict_version_ids, "connection_version", "conflict_version_ids"),
    ):
        actual = [item.id for item in rows]
        if actual != expected:
            offset = next((i for i, identity in enumerate(expected) if (kind, identity) not in index), None)
            if offset is not None:
                _fail("Selected application conflict is missing", kind, expected[offset], [path, offset], missing=True)
            identity = next((value for value in actual if value not in expected), None)
            if identity is None:
                identity = next((value for value in expected if value not in actual), None)
            _fail("Application must select the exact ordered conflict set", kind,
                  identity or (actual or expected or [body.version_id])[0], path)
    return connections


def _removed_ownership(design, index, connections, backings, host_owners, *, allow_indirect=False):
    removed = set()
    for offset, connection in enumerate(connections):
        path = ["conflict_connection_ids", offset]
        prefix = f"__lnk__{connection.id}"
        if allow_indirect and connection.length_value == 0:
            from backend.api.part_indirect_linker_ownership import removed_resources
            targets = {identity: _target(design, index, backings, host_owners, identity, path)
                       for identity in (connection.overhang_a_id, connection.overhang_b_id)}
            removed.update(removed_resources(design, index, connection, targets, path))
            continue
        if (connection.linker_type not in {"ss", "ds"} or connection.length_unit != "bp"
                or connection.length_value < 1 or not float(connection.length_value).is_integer()):
            _fail("Only finite native linker ownership can be replaced", "overhang_connection", connection.id, path)
        expected_strands = {f"{prefix}__s"} if connection.linker_type == "ss" else {f"{prefix}__a", f"{prefix}__b"}
        actual_helices = {item.id for item in design.helices if item.id.startswith(prefix)}
        actual_strands = {item.id for item in design.strands if item.id.startswith(prefix)}
        if actual_helices != {prefix} or actual_strands != expected_strands:
            _fail("Removed linker has incomplete or prefix-colliding ownership", "overhang_connection", connection.id, path)
        targets = {identity: _target(design, index, backings, host_owners, identity, path)
                   for identity in (connection.overhang_a_id, connection.overhang_b_id)}
        host = index[("helix", prefix)]
        if host.bp_start != 0 or host.length_bp != connection.length_value:
            _fail("Removed linker host disagrees with its declared length", "helix", prefix, path)
        for identity in expected_strands:
            strand = index[("strand", identity)]
            bridges = [domain for domain in strand.domains if domain.helix_id == prefix]
            complements = [domain for domain in strand.domains if domain.binds_overhang_id]
            expected_ends = ({connection.overhang_a_id, connection.overhang_b_id}
                if connection.linker_type == "ss" else
                {connection.overhang_a_id if identity.endswith("__a") else connection.overhang_b_id})
            if (strand.strand_type != StrandType.LINKER or strand.is_reference or len(bridges) != 1
                    or len(strand.domains) != len(expected_ends) + 1
                    or len(complements) != len(expected_ends)
                    or {domain.binds_overhang_id for domain in complements} != expected_ends
                    or any(domain.overhang_id for domain in strand.domains)
                    or sorted((bridges[0].start_bp, bridges[0].end_bp)) != [0, host.length_bp - 1]):
                _fail("Removed linker strand is not wholly owned by its connection", "strand", identity, path)
            from backend.core.lattice import _make_complement_domain
            for domain in complements:
                expected = _make_complement_domain(targets[domain.binds_overhang_id][2], domain.binds_overhang_id)
                if domain != expected:
                    _fail("Removed linker complement has authored topology outside this contract", "strand", identity, path)
        removed.add(("overhang_connection", connection.id))
        removed.add(("helix", prefix))
        removed.update(("strand", identity) for identity in expected_strands)
    return removed


def _complement_ownership(design, index, targets, removed):
    """Do not adopt retained occupants or dangling addresses as new binders."""
    from backend.core.lattice import _make_complement_domain

    selected_hosts = {target[3].id for target in targets}
    for cluster in design.cluster_transforms:
        if not cluster.domain_ids:
            continue
        scoped_hosts = set(cluster.helix_ids)
        for ref in cluster.domain_ids:
            owner = index.get(("strand", ref.strand_id))
            if owner is None or not 0 <= ref.domain_index < len(owner.domains):
                _unsupported("Finite linker application requires resolvable cluster domain scopes")
            scoped_hosts.add(owner.domains[ref.domain_index].helix_id)
        if selected_hosts & scoped_hosts:
            _unsupported("Finite linker application does not yet admit domain-level clusters on selected overhang hosts")

    for target, path in zip(targets, ("overhang_a_id", "overhang_b_id")):
        spec, _, backing, _ = target
        complement = _make_complement_domain(backing, spec.id)
        lo, hi = sorted((complement.start_bp, complement.end_bp))

        def addressed(helix_id, bp_index, direction):
            return helix_id == complement.helix_id and direction == complement.direction and lo <= bp_index <= hi

        for strand in design.strands:
            if ("strand", strand.id) in removed:
                continue
            for domain in strand.domains:
                if (domain.helix_id == complement.helix_id and domain.direction == complement.direction
                        and max(lo, min(domain.start_bp, domain.end_bp)) <= min(hi, max(domain.start_bp, domain.end_bp))):
                    _fail("Prospective linker complement already has a retained strand owner", "overhang", spec.id, path)
        for pose in design.nucleotide_transforms:
            if addressed(pose.helix_id, pose.bp_index, pose.direction):
                _fail("Prospective linker complement has an existing nucleotide pose", "overhang", spec.id, path)
        for crossover in design.crossovers:
            if any(addressed(half.helix_id, half.index, half.strand) for half in (crossover.half_a, crossover.half_b)):
                _fail("Prospective linker complement has an existing crossover address", "overhang", spec.id, path)
        for ligation in design.forced_ligations:
            if (addressed(ligation.three_prime_helix_id, ligation.three_prime_bp, ligation.three_prime_direction)
                    or addressed(ligation.five_prime_helix_id, ligation.five_prime_bp, ligation.five_prime_direction)):
                _fail("Prospective linker complement has an existing ligation address", "overhang", spec.id, path)


def _incoming(design, removed, outputs):
    try:
        for field, kind in COLLECTIONS.items():
            for record in getattr(design, field):
                if (kind, record.id) in removed:
                    continue
                refs = referenced_resources(record)
                collision, consumed = refs & outputs, refs & removed
                if collision:
                    _fail("Linker output identity already has an incoming owner", *sorted(collision)[0], "connection_id")
                if consumed:
                    _fail(f"Removed linker is still used by {kind} {record.id}",
                          *sorted(consumed)[0], "conflict_connection_ids")
    except (NotImplementedError, TypeError) as error:
        _unsupported(f"Linker application cannot classify source ownership: {error}")


@dataclass(frozen=True, slots=True)
class _Selected:
    version: object
    connections: tuple
    bridge_length: int


def _source_index(design):
    _bounded_source(design)
    try:
        index, _ = identity_index(design)
    except NotImplementedError as error:
        _unsupported(str(error))
    return index


def _select_inputs(design, body, index):
    version = _resolve(index, "connection_version", body.version_id, "version_id")
    for field in ("overhang_a_id", "overhang_b_id"):
        _resolve(index, "overhang", getattr(body, field), field)
        if getattr(version, field) != getattr(body, field):
            _fail("Selected version endpoint changed", "overhang", getattr(body, field), field)
    if body.overhang_a_id == body.overhang_b_id:
        _fail("Linker application requires two distinct endpoints", "overhang", body.overhang_b_id, "overhang_b_id")
    if version.connection_type != body.connection_type:
        _fail("Selected version connection type changed", "connection_version", version.id, "connection_type")
    if type(version.bridge_length) is not int or version.bridge_length < 0:
        _unsupported("Selected version has an unsupported bridge length")
    bridge_length = 0 if body.connection_type in INDIRECT_TYPES else max(1, version.bridge_length)
    backings, host_owners = {}, {}
    for strand in design.strands:
        for domain in strand.domains:
            if domain.overhang_id is not None:
                backings.setdefault(domain.overhang_id, []).append((strand, domain))
    for spec in design.overhangs:
        host_owners.setdefault(spec.helix_id, []).append(spec.id)
    targets = [_target(design, index, backings, host_owners, getattr(body, field), field)
               for field in ("overhang_a_id", "overhang_b_id")]
    _work_admission(design, bridge_length, [target[2] for target in targets])
    connections = _conflicts(design, body, index)
    removed = _removed_ownership(design, index, connections, backings, host_owners,
                                 allow_indirect=body.connection_application_version == 2)
    _complement_ownership(design, index, targets, removed)
    return _Selected(version, tuple(connections), bridge_length), removed


def _check_outputs(design, body, index, removed):
    prefix = f"__lnk__{body.connection_id}"
    strands = {f"{prefix}__a", f"{prefix}__b"} if "dsdna" in body.connection_type else {f"{prefix}__s"}
    # Reserve the complete removal namespace even when an indirect output emits
    # no helix. A retained/dangling helix owner must not enter that namespace.
    outputs = {("overhang_connection", body.connection_id), ("helix", prefix),
               *(("strand", identity) for identity in strands)}
    collisions = outputs & index.keys()
    if collisions:
        _fail("Linker output identity already exists", *sorted(collisions)[0], "connection_id")
    for item in [*design.helices, *design.strands]:
        if item.id.startswith(prefix):
            _fail("Linker output prefix collides with existing topology", "overhang_connection", body.connection_id, "connection_id")
    for connection in design.overhang_connections:
        if (("overhang_connection", connection.id) not in removed
                and prefix.startswith(f"__lnk__{connection.id}")):
            _fail("Linker output enters a retained connection's removal namespace",
                  "overhang_connection", body.connection_id, "connection_id")
    _incoming(design, removed, outputs)


def _select(design, body):
    index = _source_index(design)
    selected, removed = _select_inputs(design, body, index)
    _check_outputs(design, body, index, removed)
    return selected


def _materialize(design, body, selected):
    """Existing finite callback order; no placement or sequence formulas here."""
    from backend.api.overhang_patch import OverhangPatchRequest, _build_overhang_patch
    from backend.api.routes_connection_versions import (
        _cv_attach_pair, _cv_linker_type, _cv_sequence_for_live_overhang,
    )
    from backend.core.lattice import (
        assign_overhang_connection_names, generate_linker_topology, remove_linker_topology,
    )
    from backend.core.sequences import overhang_dependent_strand_ids, reassign_strands

    version, a_id, b_id = selected.version, body.overhang_a_id, body.overhang_b_id
    applied_a_seq = _cv_sequence_for_live_overhang(design, a_id, version.overhang_a_seq)
    applied_b_seq = _cv_sequence_for_live_overhang(design, b_id, version.overhang_b_seq)
    result = design
    if applied_a_seq:
        result = _build_overhang_patch(result, a_id, OverhangPatchRequest(sequence=applied_a_seq))[0]
    if applied_b_seq:
        result = _build_overhang_patch(result, b_id, OverhangPatchRequest(sequence=applied_b_seq))[0]
    for connection in selected.connections:
        result = remove_linker_topology(result.copy_with(overhang_connections=[
            item for item in result.overhang_connections if item.id != connection.id]), connection.id)
    attach_a, attach_b = _cv_attach_pair(body.connection_type)
    connection = OverhangConnection(id=body.connection_id, overhang_a_id=a_id, overhang_a_attach=attach_a,
        overhang_b_id=b_id, overhang_b_attach=attach_b, linker_type=_cv_linker_type(body.connection_type),
        length_value=selected.bridge_length, length_unit="bp",
        bridge_sequence=(version.bridge_seq or "").upper().strip() or None)
    result = assign_overhang_connection_names(result.copy_with(
        overhang_connections=[*result.overhang_connections, connection]))
    result = generate_linker_topology(result, connection)
    bridge_id = f"__lnk__{connection.id}"
    affected = overhang_dependent_strand_ids(result, [a_id, b_id], extra_helix_ids=[bridge_id])
    result = reassign_strands(result, affected)
    selected_ids = set(body.conflict_version_ids)
    result = result.copy_with(connection_versions=[item.model_copy(update={
        "applied": item.id == body.version_id,
        **({"overhang_a_seq": applied_a_seq} if item.id == body.version_id and applied_a_seq else {}),
        **({"overhang_b_seq": applied_b_seq} if item.id == body.version_id and applied_b_seq else {}),
    }) if item.id in selected_ids else item for item in result.connection_versions])
    return result, MutationReport(new_helix_origins={bridge_id: None})


def build(design, params):
    body = parse_command(params)
    return _materialize(design, body, _select(design, body))


def _route_version(design, version_id):
    """Classify a bounded selected version before full-source preparation."""
    versions = design.connection_versions
    if type(versions) is not list or len(versions) > MAX_OPERATION_NODES:
        _unsupported("Finite application cannot inspect this version table")
    selected = None
    for version in versions:
        if type(version) is not ConnectionVersion:
            _unsupported("Finite application requires ordinary connection versions")
        if version.id == version_id:
            if selected is not None:
                _fail("Selected connection version identity is ambiguous", "connection_version", version_id, "version_id")
            selected = version
    if selected is None:
        _fail("Selected linker application input is missing", "connection_version", version_id, "version_id", missing=True)
    return selected


def try_record(version_id, *, contract_version=1):
    """Record one finite Apply under the existing document transaction lock.

    Only explicitly unsupported input scope returns None. Selection finishes
    before undo allocation; an admitted failure never retries through legacy.
    The prepared selection lives only within this source-owned lock scope.
    """
    from fastapi import HTTPException
    from backend.api import state
    from backend.api.feature_recording import record_feature
    from backend.api.part_source_bound_route import require_current

    allowed = supported_types(contract_version)
    try:
        with state._lock:
            require_current()
            state._require_compatibility_write("finite_connection_apply")
            session = state._session()
            source = session.design
            if source is None:
                raise HTTPException(404, detail="No active design.")
            try:
                version = _route_version(source, version_id)
                if version.connection_type not in allowed:
                    return None
                state._assert_active_loadout_editable(source)
                if contract_version == 2 and (source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None):
                    raise HTTPException(409, detail="Return to the latest feature before Apply.")
                index = _source_index(source)
                endpoints = {version.overhang_a_id, version.overhang_b_id}
                values = {"_proof_version": 1, "connection_application_version": contract_version, "action": ACTION,
                    "version_id": version.id, "overhang_a_id": version.overhang_a_id,
                    "overhang_b_id": version.overhang_b_id, "connection_type": version.connection_type,
                    "connection_id": "pending",
                    "conflict_connection_ids": [item.id for item in source.overhang_connections
                        if endpoints.intersection((item.overhang_a_id, item.overhang_b_id))],
                    "conflict_version_ids": [item.id for item in source.connection_versions
                        if endpoints.intersection((item.overhang_a_id, item.overhang_b_id))]}
                if any(len(values[field]) > MAX_CONFLICTS for field in
                       ("conflict_connection_ids", "conflict_version_ids")):
                    _unsupported("Finite application exceeds its selected conflict allowance")
                body = parse_command(values)
                selected, removed = _select_inputs(source, body, index)
                # The placeholder never reaches output ownership or recording.
                values["connection_id"] = str(uuid4())
                body = parse_command(values)
                _check_outputs(source, body, index, removed)
            except CommandContractError as error:
                if error.code == "unsupported_connection_application_source":
                    return None
                raise

            def native(design):
                require_current()
                if session.design is not source or design is not source:
                    raise HTTPException(409, detail="Connection application source changed before recording.")
                result, report = _materialize(design, body, selected)
                # Recording appends in place; keep the source's history list
                # independent without adding another whole-model clone.
                return result.copy_with(feature_log=list(design.feature_log)), report

            a = index[("overhang", body.overhang_a_id)].label
            b = index[("overhang", body.overhang_b_id)].label
            label = f"Apply version {version.name or version.id[:8]} ({a}↔{b})"
            updated, report, entry = record_feature(session, "overhang-bulk", label, values, native)
            return source, updated, report, entry
    except ReferenceResolutionError as error:
        raise HTTPException(404 if error.code == "missing_reference" else 422, detail=error.as_issue()) from error
    except (CommandContractError, ValueError) as error:
        raise HTTPException(422, detail=error.as_issue() if isinstance(error, CommandContractError) else str(error)) from error
