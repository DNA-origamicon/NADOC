"""Compile public coating choices into ordinary native feature definitions.

Preparation reads only fixed server assets, outside the document lock. Prefer
calling it inside the existing worker AFTER proving the current recipe and
rebuilding its prefix, then call ``compile_steps``. Publication bytes are pinned
at that evaluation, not at submission. This module does not replay, execute
geometry, encode recovery or publish a design. New source bytes must not be
merged before source proof or added to the public operation envelope.

``repack`` is resize-only and retains the active set feature's recorded inputs.
Removing an absent coating is an error; deleting uncoated gold is one ordinary
gold-delete step. Coated deletion and coated creation each emit two steps for
the caller's existing atomic append/recovery pipeline.
"""

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.api import part_nanoparticle_commands as gold
from backend.api import part_streptavidin_commands as coating
from backend.core.models import SnapshotLogEntry
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_history_proof import AUTHORING_FIELDS, ProofBudgetExceeded
from backend.core.part_input_sources import (
    EmbeddedInput, EmbeddedResolver, InputSource, SourceContractError, describe, embed, read_verified,
)
from backend.core.part_operation_input import validate_operation_input
from backend.core.part_streptavidin_contract import contract_defaults


MAX_HISTORY_ROWS = 32
MAX_INPUT_SOURCES = MAX_HISTORY_ROWS + 1
_DATA = Path(__file__).resolve().parents[1] / "data/proteins"
_PDB = InputSource(sha256=coating.PDB_SHA256, size_bytes=coating.PDB_SIZE,
                   format="pdb", media_type="chemical/x-pdb")


class _Public(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    @model_validator(mode="before")
    @classmethod
    def bounded_json(cls, value):
        validate_operation_input(value)
        return value


class CoatingChoices(_Public):
    coverage_reference: coating._CoverageId | None = None
    count_override: Annotated[StrictInt, Field(ge=1, le=coating.MAX_REQUESTED_SITES)] | None = None
    mode: Literal["adsorption", "biotin_tether"] = "adsorption"
    footprint_nm2: Annotated[gold._Number, Field(ge=25, le=100)] = 40.0
    spacer_nm: Annotated[gold._Number, Field(ge=0, le=20)] | None = None
    seed: StrictInt = Field(default=1, ge=0, le=2_147_483_647)


class SetRequest(_Public):
    action: Literal["set"]
    nanoparticle_id: gold._Id
    diameter_nm: coating._Diameter | None = None
    coating: CoatingChoices = Field(default_factory=CoatingChoices)


class CreateRequest(_Public):
    action: Literal["create"]
    diameter_nm: coating._Diameter
    coating: CoatingChoices = Field(default_factory=CoatingChoices)


class RepackRequest(_Public):
    action: Literal["repack"]
    nanoparticle_id: gold._Id
    diameter_nm: coating._Diameter


class MoveRequest(_Public):
    action: Literal["move"]
    nanoparticle_id: gold._Id
    pose: list[gold._Number] | None = Field(default=None, min_length=16, max_length=16)
    gizmo_move: gold.GizmoMove | None = None

    @model_validator(mode="after")
    def has_motion(self):
        if self.pose is None and self.gizmo_move is None:
            raise ValueError("Coating motion requires an explicit pose or gizmo movement")
        return self


class RemoveRequest(_Public):
    action: Literal["remove"]
    nanoparticle_id: gold._Id


class DeleteRequest(_Public):
    action: Literal["delete"]
    nanoparticle_id: gold._Id


_REQUESTS = {"set": SetRequest, "create": CreateRequest, "repack": RepackRequest,
             "move": MoveRequest, "remove": RemoveRequest, "delete": DeleteRequest}


def parse_request(value):
    if type(value) in _REQUESTS.values():
        return value
    validate_operation_input(value)
    action = value.get("action") if type(value) is dict else None
    model = _REQUESTS.get(action) if type(action) is str else None
    if model is None:
        raise ValueError("Coating append requires a supported explicit action")
    return model.model_validate(value)


@dataclass(frozen=True)
class PreparedSources:
    """Private preparation result; never a public request field.

    Frozen descriptors and immutable embedded records are pickle-compatible,
    but the public operation envelope stays unchanged. The compiler verifies
    them again before returning any definitions.
    """

    pdb_source: InputSource | None = None
    coverage_source: InputSource | None = None
    entries: tuple[tuple[str, EmbeddedInput], ...] = ()


@dataclass(frozen=True)
class NativeStep:
    identity: str
    kind: str
    label: str
    params: dict


@dataclass(frozen=True)
class CompiledAppend:
    steps: tuple[NativeStep, ...]
    input_sources: dict[str, EmbeddedInput]
    nanoparticle_id: str


@dataclass(frozen=True)
class _CoverageSelection:
    coverage_source: InputSource | None
    coverage_reference: str | None


def prepare_sources(request):
    """Read bounded fixed server assets outside locks; never probe the runtime."""
    request = parse_request(request)
    if not isinstance(request, (SetRequest, CreateRequest)):
        return PreparedSources()
    raw = read_verified(_DATA / "1STP-assembly1.pdb", _PDB)
    entries = [(_PDB.sha256, embed(_PDB, raw))]
    publication = None
    if request.coating.coverage_reference is not None:
        try:
            with (_DATA / "streptavidin_coverage.json").open("rb") as handle:
                raw = handle.read(coating.MAX_COVERAGE_BYTES + 1)
        except OSError as error:
            raise CommandContractError("Bundled coating publication is unavailable",
                                       code="source_unavailable") from error
        if len(raw) > coating.MAX_COVERAGE_BYTES:
            raise CommandContractError("Bundled coating publication exceeds its byte allowance",
                                       code="source_limit")
        publication = describe(raw, format="json", media_type="application/json")
        entries.append((publication.sha256, embed(publication, raw)))
        # Reuse the native strict publication parser; no PDB parsing occurs.
        coating._coverage(_CoverageSelection(publication, request.coating.coverage_reference),
                          EmbeddedResolver(dict(entries)))
    return PreparedSources(_PDB, publication, tuple(entries))


def _unsupported(detail):
    raise CommandContractError(detail, code="unsupported_coating_scope")


def _definitions(design):
    if len(design.feature_log) > MAX_HISTORY_ROWS:
        raise ProofBudgetExceeded("Coating append admits at most 32 flat history rows")
    definitions, identities = [], set()
    for entry in design.feature_log:
        if type(entry) is not SnapshotLogEntry or entry.feature_type != "snapshot":
            _unsupported("Coating append requires flat native gold/coating definitions")
        if type(entry.id) is not str or entry.id in identities:
            _unsupported("Coating append requires unique feature identities")
        identities.add(entry.id)
        validate_operation_input(entry.params)
        if type(entry.params) is not dict:
            _unsupported("Coating feature inputs must be objects")
        if "coating_version" in entry.params:
            command = coating.parse_command(entry.op_kind, entry.params)
        else:
            model = {"nanoparticle-create": gold.CreateRequest, "nanoparticle-patch": gold.PatchRequest,
                     "nanoparticle-delete": gold.DeleteRequest}.get(entry.op_kind)
            if model is None:
                _unsupported("Coating append requires native gold/coating definitions")
            command = model.model_validate(entry.params)
        definitions.append((entry.op_kind, command))
    return definitions, identities


def _scope(design, request):
    if set(type(design).model_fields) != set(FIELD_ROLES):
        _unsupported("Coating append cannot classify this document schema")
    root = design.recipe_root
    if (root is None or root.kind != "empty" or root.version != 1
            or root.source_json is not None or root.source_sha256 is not None):
        _unsupported("Coating append initially requires an explicit empty recipe root")
    if design.feature_log_cursor != -1 or design.feature_log_sub_cursor is not None:
        _unsupported("Coating append requires the current recipe cursor")
    for name in AUTHORING_FIELDS - {"nanoparticles", "metadata", "tm_settings", "lattice_type"}:
        if getattr(design, name):
            _unsupported(f"Coating append does not yet admit additional {name}")
    if isinstance(request, CreateRequest):
        if design.nanoparticles:
            _unsupported("Coated creation initially requires no existing particles")
        return None
    matches = [item for item in design.nanoparticles if item.id == request.nanoparticle_id]
    if len(matches) != 1:
        coating._reference(request.nanoparticle_id, "Coating particle is missing or ambiguous", missing=not matches)
    if len(design.nanoparticles) != 1:
        _unsupported("Coating append initially admits at most one gold particle")
    particle = matches[0]
    if particle.kind != "gold_nanosphere" or particle.quantum_dot is not None or particle.biotin_dna:
        coating._reference(particle.id, "Coating append requires unowned source-free gold metadata")
    if (not math.isfinite(particle.diameter_nm) or not 0 < particle.diameter_nm <= 1000
            or len(particle.pose.values) != 16 or not all(math.isfinite(value) for value in particle.pose.values)):
        coating._reference(particle.id, "Coating particle needs a finite diameter and pose")
    return particle


def _active_set(definitions, identity):
    active = None
    for kind, command in definitions:
        if command.nanoparticle_id != identity:
            continue
        if kind in {"nanoparticle-create", "nanoparticle-delete"} or isinstance(command, coating.RemoveRequest):
            active = None
        elif isinstance(command, coating.SetRequest):
            active = command
    return active


def _sources(design, request, prepared, definitions):
    if (type(prepared) is not PreparedSources or type(prepared.entries) is not tuple or len(prepared.entries) > 2
            or any(type(item) is not tuple or len(item) != 2 for item in prepared.entries)
            or any(source is not None and not isinstance(source, InputSource)
                   for source in (prepared.pdb_source, prepared.coverage_source))):
        _unsupported("Coating append requires its private bounded source preparation")
    if len(design.input_sources) > MAX_INPUT_SOURCES:
        raise ProofBudgetExceeded("Coating append source table exceeds its history allowance")
    needs_new = isinstance(request, (SetRequest, CreateRequest))
    if not needs_new and prepared != PreparedSources():
        _unsupported("This coating action does not accept newly prepared inputs")
    table = dict(prepared.entries)
    if len(table) != len(prepared.entries):
        _unsupported("Coating preparation repeats an input identity")
    declared = []
    if needs_new:
        if prepared.pdb_source != _PDB:
            _unsupported("Coating preparation requires the fixed complete 1STP source")
        if (prepared.coverage_source is None) != (request.coating.coverage_reference is None):
            _unsupported("Coating preparation does not match the requested publication")
        declared = [prepared.pdb_source]
        if prepared.coverage_source is not None:
            source = prepared.coverage_source
            if (source.format != "json" or source.media_type != "application/json"
                    or source.size_bytes > coating.MAX_COVERAGE_BYTES):
                _unsupported("Prepared coating publication exceeds its JSON source contract")
            declared.append(prepared.coverage_source)
        if set(table) != {source.sha256 for source in declared}:
            _unsupported("Coating preparation contains undeclared or missing inputs")
        resolver = EmbeddedResolver(table)
        for source in declared:
            resolver(source)
    elif table:
        _unsupported("This coating action does not accept source bytes")
    # Even if a caller violates the required prove-before-compile ordering, a
    # new set must not silently heal unavailable/corrupt evidence of an old row.
    previous = [source for _, command in definitions if isinstance(command, coating.SetRequest)
                for source in (command.pdb_source, command.coverage_source) if source is not None]
    for source in previous:
        if source.sha256 in table and source.sha256 not in design.input_sources:
            raise SourceContractError("Existing feature input is missing; use explicit source repair",
                                      source=source, code="source_unavailable")
    merged = dict(design.input_sources)
    for source in declared:
        blob = table[source.sha256]
        if source.sha256 in merged and merged[source.sha256] != blob:
            raise SourceContractError("Existing input bytes differ; use explicit source repair",
                                      source=source, code="source_integrity_mismatch")
        merged[source.sha256] = blob
    if len(merged) > MAX_INPUT_SOURCES:
        raise ProofBudgetExceeded("Coating append source table exceeds its history allowance")
    return merged


def compile_steps(design, request, prepared, *, history_seed):
    """Return input definitions for an already-proven worker replay prefix.

    The host owns ``history_seed`` and supplies a UUID; scientific RNG ``seed``
    remains an independent authored coating choice. Existing rows and their
    numerical pins are never rewritten. Pin selection occurs only here, in the
    isolated single-thread worker, after bounded source/scope/count admission.
    """
    request = parse_request(request)
    if type(history_seed) is not str:
        raise ValueError("Coating append needs its host UUID identity seed")
    namespace = UUID(history_seed)
    particle = _scope(design, request)
    definitions, used_ids = _definitions(design)
    identity = str(uuid5(namespace, "nadoc:coating-append:v1:particle")) if particle is None else particle.id
    active = _active_set(definitions, identity)
    if particle is not None:
        if (particle.coating is None) != (active is None):
            _unsupported("Current coating and its active native set definition disagree")
        if particle.coating is not None and any(getattr(particle.coating, field) != getattr(active, field)
                for field in ("mode", "footprint_nm2", "spacer_nm", "seed", "coverage_reference", "count_override")):
            _unsupported("Current coating settings differ from their active native inputs")
    count = 2 if isinstance(request, CreateRequest) or (
        isinstance(request, DeleteRequest) and particle.coating is not None) else 1
    if len(definitions) + count > MAX_HISTORY_ROWS:
        raise ProofBudgetExceeded("Coating append would exceed 32 flat history rows")
    table = _sources(design, request, prepared, definitions)
    resolver = EmbeddedResolver(table)
    steps = []

    def emit(role, kind, label, params):
        step_id = str(uuid5(namespace, f"nadoc:coating-append:v1:feature:{role}"))
        if step_id in used_ids:
            _unsupported("Coating append identity seed was already used in this recipe")
        used_ids.add(step_id)
        steps.append(NativeStep(step_id, kind, label, params))

    base = {"_proof_version": 1, "coating_version": 1, "nanoparticle_id": identity}
    gold_base = {"_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": identity}
    if isinstance(request, (SetRequest, CreateRequest, RepackRequest)):
        if isinstance(request, RepackRequest):
            if active is None:
                coating._reference(identity, "Repacking requires an active native coating definition", missing=True)
            # Copy authored inputs, never the materialized tetramers/asset.
            params = active.model_dump(by_alias=True, mode="json")
            params["diameter_nm"] = request.diameter_nm
        else:
            choices = request.coating.model_dump(mode="json")
            params = {**base, **choices, "action": "set", "pdb_source": prepared.pdb_source.model_dump(),
                "coverage_source": prepared.coverage_source.model_dump() if prepared.coverage_source else None,
                "diameter_nm": request.diameter_nm}
        coverage = coating._coverage(_CoverageSelection(
            InputSource.model_validate(params["coverage_source"]) if params["coverage_source"] else None,
            params["coverage_reference"]), resolver)
        from backend.core.streptavidin import coating_parameters_from_inputs
        diameter = params["diameter_nm"] if params["diameter_nm"] is not None else particle.diameter_nm
        try:
            spacer, requested, _ = coating_parameters_from_inputs(diameter, params["mode"], params["footprint_nm2"],
                params["spacer_nm"], params["coverage_reference"], params["count_override"], coverage_data=coverage)
        except OverflowError as error:
            coating._source_error(InputSource.model_validate(params["coverage_source"]),
                f"Coverage request exceeds finite count arithmetic: {error}", parameter="coverage_source")
        if requested > coating.MAX_REQUESTED_SITES:
            raise ProofBudgetExceeded("Coating append admits at most 64 requested sites")
        params["spacer_nm"] = spacer
        descriptor = InputSource.model_validate(params["pdb_source"])
        coating._pdb_descriptor(descriptor)
        resolver(descriptor)
        params.update(contract_defaults())
        command = coating.parse_command("nanoparticle-patch", params)
        if particle is not None:
            coating._target(design, command)
        else:
            emit("gold-create", "nanoparticle-create", f"Create {diameter:g} nm gold nanosphere",
                 {**gold_base, "diameter_nm": diameter})
        emit("coating-set", "nanoparticle-patch", "Repack streptavidin coating" if isinstance(request, RepackRequest)
             else "Apply streptavidin coating", command.model_dump(by_alias=True, mode="json"))
    elif isinstance(request, MoveRequest):
        params = {**base, **request.model_dump(exclude={"nanoparticle_id"}, mode="json")}
        coating._target(design, coating.parse_command("nanoparticle-patch", params))
        emit("coating-move", "nanoparticle-patch", "Move coated gold nanosphere", params)
    else:
        if isinstance(request, RemoveRequest) or particle.coating is not None:
            params = {**base, "action": "remove"}
            coating._target(design, coating.parse_command("nanoparticle-patch", params))
            emit("coating-remove", "nanoparticle-patch", "Remove streptavidin coating", params)
        elif not gold.source_free_target(design, identity):
            coating._reference(identity, "Deleting this particle requires a separately reviewed ownership contract")
        if isinstance(request, DeleteRequest):
            emit("gold-delete", "nanoparticle-delete", "Delete gold nanosphere", gold_base)
    return CompiledAppend(tuple(steps), table, identity)
