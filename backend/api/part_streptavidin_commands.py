"""Pinned, bounded coating inputs; no file lookup or output geometry in recipes.

Pure contract only. Explicit job admission and live route integration are owned
separately; ordinary proof capture limits are unchanged. Native preparation,
packing and rigid movement remain the existing scientific/placement algorithms.
"""

from dataclasses import dataclass
import json
import math
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.api.part_nanoparticle_commands import GizmoMove, _Id, _Number
from backend.core.nanoparticle import replace_gold_nanosphere
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS, ProofBudgetExceeded
from backend.core.part_input_sources import EmbeddedResolver, InputSource, SourceContractError, verify
from backend.core.part_streptavidin_contract import EnginePin


KINDS = frozenset({"nanoparticle-patch"})
MAX_REQUESTED_SITES = 64
MAX_PDB_BYTES = 350_000
MAX_COVERAGE_BYTES = 4_096
MAX_ASSET_ATOMS = 4_100
MAX_ASSET_BONDS = 5_000
PDB_SHA256 = "892478b3fbec8bb38fe9a2c5de12ad2b923b42327a43b61d2884d6c3fc59f3f9"
PDB_SIZE = 329_994
_CoverageId = Literal["gold_2007", "gurtovenko_2019", "gold_2017"]
_Diameter = Annotated[_Number, Field(ge=5, le=100)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    coating_version: StrictInt = Field(ge=1, le=1)
    nanoparticle_id: _Id


class SetRequest(_Input):
    action: Literal["set"]
    importer_version: StrictInt = Field(ge=1, le=1)
    engine: EnginePin
    pdb_source: InputSource
    coverage_source: InputSource | None
    mode: Literal["adsorption", "biotin_tether"]
    footprint_nm2: Annotated[_Number, Field(ge=25, le=100)]
    # Defaults are resolved once by the future adapter, not while replaying.
    spacer_nm: Annotated[_Number, Field(ge=0, le=20)]
    seed: StrictInt = Field(ge=0, le=2_147_483_647)
    coverage_reference: _CoverageId | None
    count_override: Annotated[StrictInt, Field(ge=1, le=1500)] | None
    diameter_nm: _Diameter | None = None

    @model_validator(mode="after")
    def coverage_has_source(self):
        if (self.coverage_reference is None) != (self.coverage_source is None):
            raise ValueError("A selected coverage publication requires exactly one pinned coverage source")
        return self


class RemoveRequest(_Input):
    action: Literal["remove"]


class MoveRequest(_Input):
    action: Literal["move"]
    pose: list[_Number] | None = Field(default=None, min_length=16, max_length=16)
    gizmo_move: GizmoMove | None = None

    @model_validator(mode="after")
    def has_motion(self):
        if self.pose is None and self.gizmo_move is None:
            raise ValueError("Coating motion requires an explicit pose or gizmo movement")
        return self


class _CoveragePreset(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: _CoverageId
    label: str = Field(min_length=1, max_length=256)
    effective_area_nm2: Annotated[_Number, Field(gt=0)]
    url: str = Field(min_length=1, max_length=2048, pattern=r"^https?://")
    note: str = Field(max_length=2048)


class _CoverageData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    presets: list[_CoveragePreset] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def unique_presets(self):
        if len({item.id for item in self.presets}) != len(self.presets):
            raise ValueError("Coverage source repeats a publication identity")
        return self


def parse_command(kind, params):
    if kind not in KINDS:
        raise ValueError("Unsupported pinned coating command")
    model = {"set": SetRequest, "remove": RemoveRequest, "move": MoveRequest}.get(params.get("action"))
    if model is None:
        raise ValueError("Coating command requires an explicit set, remove or move action")
    return model.model_validate(params)


def resources(kind, params):
    command = parse_command(kind, params)
    if isinstance(command, SetRequest):
        sources = (command.pdb_source,)
        if command.coverage_source is not None:
            sources += (command.coverage_source,)
        return {"sources": sources, "imports": True}
    return {"sources": (), "imports": False}


def _reference(identity, detail, *, missing=False):
    raise ReferenceResolutionError(detail, code="missing_reference" if missing else "invalid_selection",
        references=[{"kind": "nanoparticle", "identity": identity, "parameter_path": ["nanoparticle_id"]}])


def _unsupported(detail):
    raise CommandContractError(detail, code="unsupported_coating_scope")


def _target(design, command):
    matches = [item for item in design.nanoparticles if item.id == command.nanoparticle_id]
    if len(matches) != 1:
        _reference(command.nanoparticle_id, "Coating particle is missing or ambiguous", missing=not matches)
    particle = matches[0]
    if particle.kind != "gold_nanosphere" or particle.quantum_dot is not None:
        _reference(particle.id, "Pinned coating currently requires source-free gold metadata")
    if (particle.biotin_dna
            or any(item.nanoparticle_id == particle.id for item in design.nanoparticle_conjugations)
            or any(item.nanoparticle_id == particle.id for item in design.nanoparticle_connection_versions)):
        _reference(particle.id, "Remove dependent biotin DNA, thiol handles and connection ownership before changing this coating")
    if not math.isfinite(particle.diameter_nm) or not 0 < particle.diameter_nm <= 1000:
        _reference(particle.id, "Particle diameter must be finite and positive")
    if not all(math.isfinite(value) for value in particle.pose.values):
        _reference(particle.id, "Particle pose must be finite")
    if len(design.nanoparticles) != 1:
        _unsupported("Pinned coating initially admits exactly one particle")
    # This small job contract has no implicit obstacle/ownership context. New
    # authoring collections fail closed here until their meaning is reviewed.
    for field in AUTHORING_FIELDS - {"nanoparticles", "metadata", "tm_settings", "lattice_type"}:
        if getattr(design, field):
            _unsupported(f"Pinned coating does not yet admit additional {field}")
    coating = particle.coating
    if coating is None:
        if not isinstance(command, SetRequest):
            _reference(particle.id, "Coating operation requires an applied coating", missing=True)
        return particle
    if (coating.protein.metadata.get("source_sha256") != PDB_SHA256
            or coating.protein.id != f"streptavidin-1stp-assembly1-{coating.mode}"):
        _unsupported("Existing coating must use the admitted 1STP biological assembly")
    if (not 1 <= coating.target_count <= MAX_REQUESTED_SITES
            or not 1 <= len(coating.poses) <= coating.target_count
            or len(coating.protein.atoms) > MAX_ASSET_ATOMS
            or len(coating.protein.bonds) > MAX_ASSET_BONDS):
        raise ProofBudgetExceeded("Existing coating exceeds the bounded single-particle contract")
    return particle


class _CoatingSourceError(SourceContractError):
    def __init__(self, detail, *, source, code, parameter):
        super().__init__(detail, source=source, code=code)
        self.parameter = parameter

    def as_issue(self):
        issue = super().as_issue()
        issue["references"][0]["parameter_path"] = [self.parameter]
        return issue


def _source_error(source, detail, code="unsupported_source", *, parameter="pdb_source"):
    raise _CoatingSourceError(detail, source=source, code=code, parameter=parameter)


def _read(source, resolver, *, parameter="pdb_source"):
    try:
        return verify(source, (resolver if resolver is not None else EmbeddedResolver({}))(source))
    except SourceContractError as error:
        raise _CoatingSourceError(str(error), source=error.source, code=error.code,
                                  parameter=parameter) from error


def _pdb_descriptor(source):
    if source.size_bytes > MAX_PDB_BYTES:
        _source_error(source, "Coating PDB exceeds its source byte allowance", "source_limit")
    if (source.format != "pdb" or source.media_type != "chemical/x-pdb"
            or source.sha256 != PDB_SHA256 or source.size_bytes != PDB_SIZE):
        _source_error(source, "Coating importer version 1 requires the pinned complete 1STP assembly")


def _coverage(command, resolver):
    source = command.coverage_source
    if source is None:
        return None
    if source.size_bytes > MAX_COVERAGE_BYTES:
        _source_error(source, "Coverage JSON exceeds its 4096-byte source allowance", "source_limit",
                      parameter="coverage_source")
    if source.format != "json" or source.media_type != "application/json":
        _source_error(source, "Coverage input must be pinned JSON", parameter="coverage_source")

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate coverage JSON field")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("Nonfinite coverage JSON value")

    raw = _read(source, resolver, parameter="coverage_source")
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=unique_object,
                           parse_constant=invalid_constant)
        data = _CoverageData.model_validate(value)
    except (ValueError, RecursionError) as error:
        _source_error(source, f"Unsupported coverage publication data: {error}", parameter="coverage_source")
    if command.coverage_reference not in {item.id for item in data.presets}:
        _source_error(source, "Selected coverage publication is absent from its pinned source", parameter="coverage_source")
    return data.model_dump()


@dataclass(frozen=True)
class _Prepared:
    command: SetRequest | RemoveRequest | MoveRequest
    particle: object
    diameter_nm: float
    coverage_data: dict | None = None
    pdb_text: str | None = None


def validate_inputs(kind, design, params, *, resolver=None):
    """Bound scope, sources and requested work without parsing atoms or packing."""
    from backend.core.streptavidin import coating_parameters_from_inputs

    command = parse_command(kind, params)
    particle = _target(design, command)
    if not isinstance(command, SetRequest):
        return _Prepared(command, particle, particle.diameter_nm)
    _pdb_descriptor(command.pdb_source)
    coverage = _coverage(command, resolver)
    diameter = particle.diameter_nm if command.diameter_nm is None else command.diameter_nm
    try:
        _, count, _ = coating_parameters_from_inputs(diameter, command.mode, command.footprint_nm2,
            command.spacer_nm, command.coverage_reference, command.count_override, coverage_data=coverage)
    except OverflowError as error:
        _source_error(command.coverage_source, f"Coverage request exceeds finite count arithmetic: {error}",
                      parameter="coverage_source")
    if count > MAX_REQUESTED_SITES:
        raise ProofBudgetExceeded(f"Pinned coating admits at most {MAX_REQUESTED_SITES} requested sites")
    raw = _read(command.pdb_source, resolver)
    # The admitted digest fixes UTF-8 encoding and atom/model layout. This is
    # source decoding, not atom parsing, preparation or bond inference.
    return _Prepared(command, particle, diameter, coverage, raw.decode("utf-8", errors="strict"))


def build(kind, design, params, *, resolver=None):
    prepared = validate_inputs(kind, design, params, resolver=resolver)
    command, particle = prepared.command, prepared.particle
    if isinstance(command, MoveRequest):
        updated = replace_gold_nanosphere(design, particle.id, pose=command.pose,
            gizmo_move=command.gizmo_move.model_dump() if command.gizmo_move else None)
        if not all(math.isfinite(value) for value in updated.nanoparticles[0].pose.values):
            _reference(particle.id, "Coating motion exceeds finite pose range")
        return updated
    if isinstance(command, RemoveRequest):
        coating = None
    else:
        from backend.core.part_streptavidin_contract import validate_environment
        from backend.core.streptavidin import build_streptavidin_coating_from_inputs, streptavidin_asset_from_text

        validate_environment(command.engine)
        asset = streptavidin_asset_from_text(prepared.pdb_text, command.mode)
        coating = build_streptavidin_coating_from_inputs(prepared.diameter_nm, command.mode,
            command.footprint_nm2, command.spacer_nm, command.seed, command.coverage_reference,
            command.count_override, asset=asset, coverage_data=prepared.coverage_data)
    updated = replace_gold_nanosphere(design, particle.id, diameter_nm=prepared.diameter_nm)
    candidate = updated.copy_with(nanoparticles=[item.model_copy(update={"coating": coating})
                                               for item in updated.nanoparticles])
    if isinstance(command, SetRequest):
        validate_environment(command.engine)
    return candidate
