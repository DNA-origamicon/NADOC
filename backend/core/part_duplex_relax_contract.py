"""Pinned native duplex relaxation inputs; no solver runs during admission."""

from bisect import bisect_left, bisect_right
from copy import deepcopy
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StringConstraints, model_validator

from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_numerical_runtime import digest, file_digest, runtime_fingerprint


ENGINE_ID = "nadoc.duplex-relax-native.v1"
MAX_SOURCE_NUCLEOTIDES = 50_000
_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATHS = tuple(f"backend/core/{name}.py" for name in (
    "part_duplex_relax_contract", "part_numerical_runtime", "part_numerical_schema_compatibility",
    "direct_relax", "duplex_cluster",
    "linker_relax", "bond_relax", "duplex", "constants", "geometry", "design_geometry",
    "deformation", "deformation_scope", "sweep_path", "native_full_placement",
    "native_slab_placement", "measured_atomistic", "measured_positioning", "nucleotide_landmarks",
    "junction_topology", "flexible_segments", "aptamer", "lattice", "sequences", "models",
    "sweep_model", "lattice_frame_model", "dimensions", "part_history_contract",
    "cluster_autodetect", "feature_identity",
)) + ("backend/api/part_duplex_commands.py",)
DATA_PATHS = ("backend/core/data/measured_atomistic_template.json",)
AUTHORING = frozenset(key for key, role in FIELD_ROLES.items() if role == "authoring")
_BLOCKED_FIELDS = frozenset("""
protein_assets protein_attachments nanoparticles nanoparticle_conjugations
nanoparticle_connection_versions extensions overhang_connections photoproduct_junctions
""".split())
_ALLOWED_FIELDS = frozenset("""
dimensions lattice_frames helices strands lattice_type metadata deformations
cluster_transforms nucleotide_transforms cluster_joints cluster_join_constraints
overhangs overhang_bindings connection_versions duplexes flexible_segment_marks
flexible_connections tm_settings staple_groups crossovers crossover_constraints forced_ligations
""".split())
Identity = Annotated[str, StringConstraints(min_length=1, max_length=256)]
Hash = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class DuplexRelaxContractError(CommandContractError):
    def __init__(self, detail, *, code, fields=()):
        super().__init__(detail, code=code)
        self.fields = tuple(fields)

    def as_issue(self):
        result = super().as_issue()
        if self.fields:
            result["fields"] = list(self.fields)
        return result


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class NativeSource(_Strict):
    kind: Literal["native"]


class EnginePin(_Strict):
    id: Literal["nadoc.duplex-relax-native.v1"]
    implementation_sha256: Hash
    runtime_sha256: Hash


class RelaxInputs(_Strict):
    source: NativeSource
    duplex_id: Identity
    history_seed: Identity

    @model_validator(mode="after")
    def canonical_identity(self):
        if str(UUID(self.history_seed)) != self.history_seed:
            raise ValueError("history_seed must be a canonical UUID")
        return self


class RelaxCommand(RelaxInputs):
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    relaxation_version: Annotated[StrictInt, Field(ge=1, le=1)]
    engine: EnginePin
    driver_overhang_id: Identity
    driven_overhang_id: Identity
    joint_ids: list[Identity] = Field(max_length=64)
    driver_cluster_id: Identity | None
    driven_cluster_id: Identity | None
    duplex_cluster_id: Identity | None

    @model_validator(mode="after")
    def unique_joints(self):
        if len(set(self.joint_ids)) != len(self.joint_ids):
            raise ValueError("Relaxation joint identities must be unique")
        return self


def parse_command(params):
    return RelaxCommand.model_validate(params)


def implementation_manifest():
    return {"id": ENGINE_ID, "solver": "direct-binding-arc-midpoint-clash-v1",
        "placement": "native-full-o5-v1", "source_policy": "native-dna-direct-duplex-v1",
        "files": {name: file_digest(_ROOT / name, error_type=DuplexRelaxContractError,
                                    label="duplex relaxation") for name in SOURCE_PATHS},
        "data": {name: file_digest(_ROOT / name, error_type=DuplexRelaxContractError,
                                   label="duplex relaxation") for name in DATA_PATHS}}


def contract_defaults():
    return {"_proof_version": 1, "relaxation_version": 1,
        "engine": {"id": ENGINE_ID, "implementation_sha256": digest(implementation_manifest()),
                   "runtime_sha256": digest(runtime_fingerprint())}}


def validate_environment(command):
    from backend.core.part_numerical_schema_compatibility import require_implementation

    transition = require_implementation(ENGINE_ID, command.engine.implementation_sha256,
        implementation_manifest(), error_type=DuplexRelaxContractError,
        detail="Duplex relaxation code/data differs from the authored engine")
    if command.engine.runtime_sha256 != digest(runtime_fingerprint()):
        raise DuplexRelaxContractError("Duplex relaxation runtime differs from the authored engine",
                                       code="runtime_mismatch")
    return transition


def _reference(detail, kind, identity, path, *, invalid=False):
    raise ReferenceResolutionError(detail, code="invalid_selection" if invalid else "missing_reference",
        references=[{"kind": kind, "identity": identity, "parameter_path": path}])


def _one(records, identity, kind, path):
    found = [item for item in records if item.id == identity]
    if len(found) != 1:
        _reference("Relaxation reference is missing or ambiguous", kind, identity, path, invalid=bool(found))
    return found[0]


def _target(design, identity):
    edge = _one(design.duplexes, identity, "duplex", ["duplex_id"])
    if not edge.bound:
        _reference("Relaxation requires a bound duplex", "duplex", identity, ["duplex_id"], invalid=True)
    domains = []
    for side in ("left", "right"):
        end = getattr(edge, side)
        spec = _one(design.overhangs, end.overhang_id, "overhang", ["duplex_id"])
        matches = [(strand, index, domain) for strand in design.strands for index, domain in enumerate(strand.domains)
                   if domain.overhang_id == end.overhang_id]
        if len(matches) != 1:
            _reference("Duplex overhang has no unique backing domain", "overhang", spec.id,
                       ["duplex_id"], invalid=bool(matches))
        strand, index, domain = matches[0]
        if strand.id != spec.strand_id or domain.helix_id != spec.helix_id:
            _reference("Duplex overhang ownership is inconsistent", "overhang", spec.id, ["duplex_id"], invalid=True)
        _one(design.helices, domain.helix_id, "helix", ["duplex_id"])
        lo, hi = sorted((domain.start_bp, domain.end_bp))
        if not (lo <= end.start_bp <= hi and lo <= end.end_bp <= hi):
            _reference("Duplex register no longer resolves to its backing domain", "duplex", edge.id,
                       ["duplex_id"], invalid=True)
        domains.append((strand, index, domain))
    driver, driven = (edge.left, edge.right) if edge.driver == "left" else (edge.right, edge.left)
    driver_domain = domains[0 if edge.driver == "left" else 1][2]
    driven_strand, index, driven_domain = domains[1 if edge.driver == "left" else 0]
    if (driver_domain.helix_id != driven_domain.helix_id or driver_domain.direction == driven_domain.direction
            or len(driven_strand.domains) < 2 or index not in (0, len(driven_strand.domains) - 1)):
        _reference("Relaxation requires the existing antiparallel relocated tip and its root domain",
                   "duplex", edge.id, ["duplex_id"], invalid=True)
    root = driven_strand.domains[1 if index == 0 else index - 1]
    _one(design.helices, root.helix_id, "helix", ["duplex_id"])
    return driver.overhang_id, driven.overhang_id


def validate_source(design):
    if (_ALLOWED_FIELDS | _BLOCKED_FIELDS != AUTHORING or set(type(design).model_fields) != set(FIELD_ROLES)):
        raise DuplexRelaxContractError("Design schema requires a new relaxation source contract", code="unsupported_source")
    blocked = sorted(field for field in _BLOCKED_FIELDS if getattr(design, field))
    if any(helix.native_residues or helix.native_source is not None for helix in design.helices):
        blocked.append("helices.native_residues/native_source")
    if any(helix.id.startswith(("__np__", "__strep_dna__", "__lnk__")) for helix in design.helices):
        blocked.append("helices.synthetic_carrier")
    if any(strand.is_reference or strand.strand_type.value not in {"scaffold", "staple"} for strand in design.strands):
        blocked.append("strands.reference_or_asset_type")
    if any(domain.binds_overhang_id for strand in design.strands for domain in strand.domains):
        blocked.append("strands.domains.linker_reference")
    if blocked:
        raise DuplexRelaxContractError("This relaxation engine supports native DNA and direct duplexes only",
                                       code="unsupported_source", fields=blocked)
    for field in ("helices", "strands", "overhangs", "cluster_transforms", "cluster_joints"):
        records = getattr(design, field)
        if len({item.id for item in records}) != len(records):
            raise DuplexRelaxContractError("Native relaxation source has ambiguous identities",
                                           code="unsupported_source", fields=[field])
    spans = {helix.id: [helix.bp_start, helix.bp_start + helix.length_bp - 1] for helix in design.helices}
    loops = {}
    for helix in design.helices:
        positions, prefix = [], [0]
        for mark in sorted(helix.loop_skips, key=lambda item: item.bp_index):
            positions.append(mark.bp_index)
            prefix.append(prefix[-1] + max(0, mark.delta))
        loops[helix.id] = positions, prefix
    emitted = 0
    for strand in design.strands:
        for domain in strand.domains:
            if domain.helix_id not in spans:
                _reference("Native relaxation strand refers to a missing helix", "helix", domain.helix_id, ["source"])
            lo, hi = sorted((domain.start_bp, domain.end_bp))
            extent = spans[domain.helix_id]
            extent[0], extent[1] = min(extent[0], lo), max(extent[1], hi)
            positions, prefix = loops[domain.helix_id]
            emitted += hi - lo + 1 + prefix[bisect_right(positions, hi)] - prefix[bisect_left(positions, lo)]
    span_work = sum(2 * (max(0, hi - lo + 1) + loops[identity][1][-1]) for identity, (lo, hi) in spans.items())
    estimate = max(emitted, span_work) + sum(len(item.extra_bases or "") for item in (*design.crossovers, *design.forced_ligations))
    if estimate > MAX_SOURCE_NUCLEOTIDES:
        raise DuplexRelaxContractError("Native relaxation source exceeds its nucleotide work budget", code="source_limit")
    return estimate


def _selection(design, driver, driven):
    from backend.core.direct_relax import direct_relax_selection

    children = [cluster for cluster in design.cluster_transforms if cluster.overhang_duplex_driver_id == driver]
    if len(children) > 1:
        _reference("Driver has ambiguous duplex clusters", "overhang", driver, ["driver_overhang_id"], invalid=True)
    return direct_relax_selection(design, driver, driven)


def prepare_command(design, inputs):
    """Capture only in the isolated worker; caller cannot provide pins or output."""
    authored = RelaxInputs.model_validate(inputs)
    driver, driven = _target(design, authored.duplex_id)
    validate_source(design)
    selected = _selection(design, driver, driven)
    return parse_command({**authored.model_dump(mode="json"), **selected,
        "driver_overhang_id": driver, "driven_overhang_id": driven,
        **contract_defaults()}).model_dump(mode="json", by_alias=True)


def validate_inputs(design, params):
    command = parse_command(params)
    driver, driven = _target(design, command.duplex_id)
    validate_source(design)
    for field, actual in (("driver_overhang_id", driver), ("driven_overhang_id", driven)):
        identity = getattr(command, field)
        _one(design.overhangs, identity, "overhang", [field])
        if identity != actual:
            _reference("Selected duplex driver relationship changed", "overhang", identity, [field], invalid=True)
    for index, identity in enumerate(command.joint_ids):
        joint = _one(design.cluster_joints, identity, "cluster_joint", ["joint_ids", index])
        _one(design.cluster_transforms, joint.cluster_id, "cluster", ["joint_ids", index])
    for field in ("driver_cluster_id", "driven_cluster_id", "duplex_cluster_id"):
        identity = getattr(command, field)
        if identity is not None:
            _one(design.cluster_transforms, identity, "cluster", [field])
    selected = _selection(design, driver, driven)
    for field, actual in selected.items():
        if getattr(command, field) != actual:
            _reference("Relaxation selection no longer matches the authored references", "duplex", command.duplex_id,
                       [field], invalid=True)
    return command


def native_source(design):
    from backend.core.models import Design
    return Design.model_construct(id=design.id, **deepcopy({name: getattr(design, name) for name in AUTHORING}))
