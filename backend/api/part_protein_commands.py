"""Pinned small protein imports with explicit, read-only source resolution.

The existing PDB parser owns atom filtering, serials, bonds and geometry. Recipe
inputs contain source bytes by identity and parsing choices, never parsed atoms.
Library import, free placement and conjugation remain separate operations.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_input_sources import EmbeddedResolver, InputSource, SourceContractError, verify


KINDS = frozenset({"protein-import", "protein-attach", "protein-attach-patch", "protein-attach-delete"})
MAX_PROTEIN_SOURCE_BYTES = 250_000
MAX_PROTEIN_ATOM_RECORDS = 1_000
MAX_PROTEIN_BONDS = 4_000
_Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
_Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
_Count = Annotated[StrictInt, Field(ge=0, le=50_000)]
_Serial = Annotated[StrictInt, Field(ge=1)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    protein_version: StrictInt = Field(ge=1, le=1)


class ImportRequest(_Input):
    importer_version: StrictInt = Field(ge=1, le=1)
    source: InputSource
    asset_id: _Id
    name: str = Field(max_length=1_024)
    source_filename: str = Field(max_length=1_024)
    exclude_dna: StrictBool


class _Target(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class FreeTarget(_Target):
    kind: Literal["free"]


class OverhangTarget(_Target):
    kind: Literal["overhang"]
    overhang_id: _Id
    attach_end: Literal["free_end", "root"]


class GizmoMove(_Target):
    pivot: list[_Number] = Field(min_length=3, max_length=3)
    translation: list[_Number] = Field(min_length=3, max_length=3)
    rotation: list[_Number] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def rotation_exists(self):
        if not any(self.rotation):
            raise ValueError("Gizmo rotation must have a nonzero quaternion")
        return self


class AttachRequest(_Input):
    attachment_id: _Id
    asset_id: _Id
    target: Annotated[FreeTarget | OverhangTarget, Field(discriminator="kind")]
    # Record the chosen atom, not a request to reselect a possibly different
    # default after a source edit. The live adapter resolves its default once.
    conjugation_atom_serial: _Serial
    handle_complement_bp: _Count
    handle_spacer_nt: _Count
    pose: list[_Number] | None = Field(default=None, min_length=16, max_length=16)
    visible: StrictBool = True


class PatchRequest(_Input):
    attachment_id: _Id
    pose: list[_Number] | None = Field(default=None, min_length=16, max_length=16)
    gizmo_move: GizmoMove | None = None
    conjugation_atom_serial: _Serial | None = None
    handle_complement_bp: _Count | None = None
    handle_spacer_nt: _Count | None = None
    visible: StrictBool | None = None


class DeleteRequest(_Input):
    attachment_id: _Id


def parse_command(kind, params):
    model = {"protein-import": ImportRequest, "protein-attach": AttachRequest,
             "protein-attach-patch": PatchRequest, "protein-attach-delete": DeleteRequest}.get(kind)
    if model is None:
        raise ValueError("Unsupported pinned protein command")
    return model.model_validate(params)


def resources(kind, params):
    """Source/provenance admission without resolving bytes or parsing atoms."""
    command = parse_command(kind, params)
    return {"sources": (command.source,), "imports": True} if kind == "protein-import" else {
        "sources": (), "imports": False,
    }


def _asset_error(identity, detail):
    raise ReferenceResolutionError(detail, code="invalid_selection", references=[{
        "kind": "protein_asset", "identity": identity, "parameter_path": ["asset_id"],
    }])


def _source_error(source, detail, *, code: Literal["unsupported_source", "source_limit"]):
    raise SourceContractError(detail, source=source, code=code)


def _import(design, command, resolver):
    if (any(asset.id == command.asset_id for asset in design.protein_assets)
            or any(attachment.asset_id == command.asset_id for attachment in design.protein_attachments)):
        _asset_error(command.asset_id, "Protein output identity already exists or has dependent attachments")
    source = command.source
    if source.format != "pdb" or source.media_type != "chemical/x-pdb":
        _source_error(source, "This protein importer requires a chemical/x-pdb PDB source",
                      code="unsupported_source")
    if source.size_bytes > MAX_PROTEIN_SOURCE_BYTES:
        _source_error(source, "Protein source exceeds the initial 250 KB import contract",
                      code="source_limit")
    # An absent resolver is an unavailable source, never an implicit lookup in
    # the session library, a filename, the workspace or the network.
    data = verify(source, (resolver if resolver is not None else EmbeddedResolver({}))(source))
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise SourceContractError("The pinned PDB source must be UTF-8 text", source=source,
                                  code="unsupported_source") from error
    if sum(line[:6].rstrip() in {"ATOM", "HETATM"} for line in text.splitlines()) > MAX_PROTEIN_ATOM_RECORDS:
        _source_error(source, "Protein source exceeds the initial 1,000 atom-record import contract",
                      code="source_limit")
    from backend.core.protein import parse_protein_pdb

    asset = parse_protein_pdb(text, name=command.name, source_filename=command.source_filename,
                             exclude_dna=command.exclude_dna)
    if not asset.atoms:
        raise ValueError("The pinned protein source contains no supported atoms")
    if len(asset.bonds) > MAX_PROTEIN_BONDS:
        _source_error(source, "Parsed protein exceeds the initial 4,000 bond import contract",
                      code="source_limit")
    asset = asset.model_copy(update={"id": command.asset_id})
    return design.copy_with(protein_assets=[*design.protein_assets, asset])


def _reference(kind, identity, path, detail, *, missing=False):
    raise ReferenceResolutionError(detail, code="missing_reference" if missing else "invalid_selection",
        references=[{"kind": kind, "identity": str(identity), "parameter_path": path}])


def _selected(records, identity, kind, path):
    matches = [record for record in records if record.id == identity]
    if len(matches) != 1:
        _reference(kind, identity, path, "Protein command target is missing or ambiguous", missing=not matches)
    return matches[0]


def _atom(asset, serial, path):
    matches = [atom for atom in asset.atoms if atom.serial == serial]
    if len(matches) != 1:
        _reference("protein_atom", f"{asset.id}:{serial}", path,
                   "The selected atom is missing or ambiguous in the referenced protein asset", missing=not matches)
    return matches[0]


def _overhang(design, target, path):
    spec = _selected(design.overhangs, target.overhang_id, "overhang", path)
    _selected(design.helices, spec.helix_id, "helix", path)
    strand = _selected(design.strands, spec.strand_id, "strand", path)
    domains = [domain for domain in strand.domains
               if domain.overhang_id == spec.id and domain.helix_id == spec.helix_id]
    if not domains:
        _reference("overhang", spec.id, path, "The selected overhang has no backing strand domain", missing=True)
    return spec


def _bound_target(design, target):
    return target.kind == "overhang" and any(
        domain.binds_overhang_id == target.overhang_id
        for strand in design.strands for domain in strand.domains)


def _unconjugated(design, attachment):
    if attachment.target.kind not in {"free", "overhang"}:
        _reference("protein_attachment", attachment.id, ["attachment_id"],
                   "Only free and part-overhang protein placements are supported")
    # Old conjugation records may lack explicit binder ownership. Refuse that
    # ambiguity without reading a historical snapshot or guessing its owner.
    if attachment.binder_strand_id or attachment.azide_end or _bound_target(design, attachment.target):
        _reference("protein_attachment", attachment.id, ["attachment_id"],
                   "Conjugated or ambiguously bound protein placements require a binder ownership contract")


def _attach(design, command):
    from backend.core.conjugation import conjugation_candidate_for_serial
    from backend.core.models import Mat4x4, ProteinAttachment, ProteinTargetDesign, ProteinTargetFree
    from backend.core.protein import reverse_complement

    if any(item.id == command.attachment_id for item in design.protein_attachments):
        _reference("protein_attachment", command.attachment_id, ["attachment_id"],
                   "Protein attachment output identity already exists")
    asset = _selected(design.protein_assets, command.asset_id, "protein_asset", ["asset_id"])
    _atom(asset, command.conjugation_atom_serial, ["conjugation_atom_serial"])
    spec = None
    if command.target.kind == "overhang":
        spec = _overhang(design, command.target, ["target", "overhang_id"])
    target = (ProteinTargetFree() if spec is None else ProteinTargetDesign(
        overhang_id=spec.id, attach_end=command.target.attach_end))
    if _bound_target(design, target):
        _reference("overhang", spec.id, ["target", "overhang_id"],
                   "A bound overhang requires an explicit protein binder ownership contract")
    selected = conjugation_candidate_for_serial(asset, command.conjugation_atom_serial) if spec else None
    attachment = ProteinAttachment(id=command.attachment_id, asset_id=command.asset_id,
        target=target, conjugation_atom_serial=command.conjugation_atom_serial,
        conjugation_chemistry=selected["chemistry"] if selected else None,
        conjugation_accessible_fraction=selected["accessible"] if selected else None,
        handle_complement_bp=command.handle_complement_bp, handle_spacer_nt=command.handle_spacer_nt,
        handle_sequence=reverse_complement(spec.sequence) if spec and spec.sequence else None,
        pose=Mat4x4(values=command.pose) if command.pose is not None else Mat4x4(), visible=command.visible)
    return design.copy_with(protein_attachments=[*design.protein_attachments, attachment])


def _patch(design, command, attachment):
    from backend.core.conjugation import conjugation_candidate_for_serial
    from backend.core.models import Mat4x4
    from backend.core.protein import gizmo_move_to_pose

    asset = _selected(design.protein_assets, attachment.asset_id, "protein_asset", ["attachment_id"])
    serial = command.conjugation_atom_serial if command.conjugation_atom_serial is not None else attachment.conjugation_atom_serial
    _atom(asset, serial, ["conjugation_atom_serial"] if command.conjugation_atom_serial is not None else ["attachment_id"])
    if attachment.target.kind == "overhang":
        _overhang(design, attachment.target, ["attachment_id"])
    updates = {}
    if command.pose is not None:
        updates["pose"] = Mat4x4(values=command.pose)
    if command.gizmo_move is not None:
        move = command.gizmo_move
        updates["pose"] = Mat4x4.from_array(gizmo_move_to_pose(
            attachment.pose.to_array(), move.pivot, move.translation, move.rotation))
    if command.conjugation_atom_serial is not None:
        selected = conjugation_candidate_for_serial(asset, serial)
        if selected is None:
            _reference("protein_atom", f"{asset.id}:{serial}", ["conjugation_atom_serial"],
                       "Conjugation atom must be a supported surface-accessible site")
        updates.update(conjugation_atom_serial=serial, conjugation_chemistry=selected["chemistry"],
                       conjugation_accessible_fraction=selected["accessible"])
    for field in ("handle_complement_bp", "handle_spacer_nt", "visible"):
        value = getattr(command, field)
        if value is not None:
            updates[field] = value
    return design.copy_with(protein_attachments=[
        item.model_copy(update=updates) if item.id == attachment.id else item for item in design.protein_attachments
    ])


def _delete(design, attachment):
    overrides = []
    for override in design.representation_overrides:
        ids = [identity for identity in override.protein_attachment_ids if identity != attachment.id]
        if ids or override.segments:
            overrides.append(override.model_copy(update={"protein_attachment_ids": ids}))
    return design.copy_with(protein_attachments=[
        item for item in design.protein_attachments if item.id != attachment.id
    ], representation_overrides=overrides)


def build(kind, design, params, *, resolver=None):
    from uuid import NAMESPACE_URL, uuid5

    from backend.core.cluster_autodetect import with_default_cluster
    from backend.core.feature_identity import identity_factory

    command = parse_command(kind, params)
    if kind == "protein-import":
        updated = _import(design, command, resolver)
        identity = command.asset_id
    else:
        identity = command.attachment_id
        if kind == "protein-attach":
            updated = _attach(design, command)
        else:
            attachment = _selected(design.protein_attachments, identity,
                                   "protein_attachment", ["attachment_id"])
            _unconjugated(design, attachment)
            updated = _patch(design, command, attachment) if kind == "protein-attach-patch" else _delete(design, attachment)
    # The response adapter bootstraps a default placement umbrella for sparse
    # sources. Author it here with the explicit command identity so replay does
    # not depend on a later response-side UUID or silently modify publication.
    namespace = uuid5(NAMESPACE_URL, f"nadoc:protein-command:v1:{kind}:{identity}")
    return with_default_cluster(updated, identity_factory=identity_factory(namespace))
