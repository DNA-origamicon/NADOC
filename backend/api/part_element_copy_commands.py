"""Bounded same-part rigid copies, with explicit source and output identities.

This initial contract copies free, unowned protein placements and undecorated
gold/catalog particles. It never reads a clipboard Design, evaluates DNA, imports
assets or rewrites strings. Legacy frozen-clipboard semantics remain separate.
"""

import math
from typing import Annotated

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.api.part_protein_commands import MAX_PROTEIN_ATOM_RECORDS, MAX_PROTEIN_BONDS
from backend.core.models import Mat4x4
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError


KINDS = frozenset({"element-paste"})
# Provisional small-batch scope; no live route is enabled by this module.
# Existing capture/worker limits still apply independently of this work bound.
MAX_ELEMENTS = 16
MAX_ATOM_WORK = 4_000
_Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]


class CopyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    copy_version: StrictInt = Field(ge=1, le=1)
    protein_ids: list[_Id] = Field(max_length=MAX_ELEMENTS)
    protein_output_ids: list[_Id] = Field(max_length=MAX_ELEMENTS)
    nanoparticle_ids: list[_Id] = Field(max_length=MAX_ELEMENTS)
    nanoparticle_output_ids: list[_Id] = Field(max_length=MAX_ELEMENTS)
    paste_index: StrictInt = Field(ge=1, le=10000)

    @model_validator(mode="after")
    def complete_selections(self):
        if not 1 <= len(self.protein_ids) + len(self.nanoparticle_ids) <= MAX_ELEMENTS:
            raise ValueError(f"Copy requires 1–{MAX_ELEMENTS} selected rigid elements")
        for sources, outputs in ((self.protein_ids, self.protein_output_ids),
                                 (self.nanoparticle_ids, self.nanoparticle_output_ids)):
            if len(sources) != len(outputs):
                raise ValueError("Each selected element requires exactly one output identity")
            if len(set(sources)) != len(sources) or len(set(outputs)) != len(outputs):
                raise ValueError("Sources and outputs must each be unique within their resource kind")
        return self


def parse_command(kind, params):
    if kind not in KINDS:
        raise ValueError("Unsupported same-part rigid copy command")
    return CopyRequest.model_validate(params)


def resources(kind, params):
    parse_command(kind, params)
    return {"sources": (), "imports": False}


def _reference(kind, identity, path, detail, *, missing=False):
    raise ReferenceResolutionError(detail, code="missing_reference" if missing else "invalid_selection",
        references=[{"kind": kind, "identity": identity, "parameter_path": path}])


def _unsupported(detail):
    raise CommandContractError(detail, code="unsupported_element_copy_source")


def _selection(records, sources, outputs, kind, parameter):
    selected = set(sources)
    indexed = {}
    for record in records:
        indexed.setdefault(record.id, []).append(record)
    for position, identity in enumerate(sources):
        matches = indexed.get(identity, [])
        if len(matches) != 1:
            _reference(kind, identity, [parameter, position], "Copy source is missing or ambiguous", missing=not matches)
    for position, identity in enumerate(outputs):
        if identity in indexed:
            _reference(kind, identity, [parameter.replace("_ids", "_output_ids"), position],
                       "Copy output identity already exists")
    # Existing paste orders by source collection, not selection-click order.
    return [record for record in records if record.id in selected], dict(zip(sources, outputs))


def _pose(record, kind, path):
    pose = record.pose.to_array()
    if not np.isfinite(pose).all():
        _reference(kind, record.id, path, "Copy source pose must be finite")
    return pose


def evaluate(kind, design, params):
    from backend.core.protein import compose_protein_world_transform

    command = parse_command(kind, params)
    proteins, protein_outputs = _selection(design.protein_attachments, command.protein_ids,
        command.protein_output_ids, "protein_attachment", "protein_ids")
    particles, particle_outputs = _selection(design.nanoparticles, command.nanoparticle_ids,
        command.nanoparticle_output_ids, "nanoparticle", "nanoparticle_ids")
    protein_paths = {identity: ["protein_ids", index] for index, identity in enumerate(command.protein_ids)}
    particle_paths = {identity: ["nanoparticle_ids", index] for index, identity in enumerate(command.nanoparticle_ids)}
    owned_particles = {item.nanoparticle_id for item in design.nanoparticle_conjugations}
    owned_particles.update(item.nanoparticle_id for item in design.nanoparticle_connection_versions)
    for index, identity in enumerate(command.nanoparticle_output_ids):
        if identity in owned_particles:
            _reference("nanoparticle", identity, ["nanoparticle_output_ids", index],
                       "Copy output identity already has incoming ownership")
    needed_assets = {item.asset_id for item in proteins}
    assets = {}
    for asset in design.protein_assets:
        if asset.id in needed_assets:
            assets.setdefault(asset.id, []).append(asset)
    protein_assets = {}
    atom_work = 0
    for attachment in proteins:
        path = protein_paths[attachment.id]
        if attachment.target.kind != "free" or attachment.binder_strand_id or attachment.azide_end:
            _unsupported("Same-part copy requires free protein placements without conjugate ownership")
        matches = assets.get(attachment.asset_id, [])
        if len(matches) != 1:
            _reference("protein_asset", attachment.asset_id, path, "Copy protein asset is missing or ambiguous", missing=not matches)
        asset = matches[0]
        if len(asset.atoms) > MAX_PROTEIN_ATOM_RECORDS or len(asset.bonds) > MAX_PROTEIN_BONDS:
            _unsupported("Copy exceeds the initial 1000-atom/4000-bond protein admission")
        if not asset.atoms:
            _reference("protein_asset", asset.id, path, "Copy protein asset has no atoms", missing=True)
        if attachment.conjugation_atom_serial is None:
            _reference("protein_attachment", attachment.id, path,
                       "Copy requires an explicit protein atom selection for its native placement lifecycle")
        atom_work += len(asset.atoms)
        if atom_work > MAX_ATOM_WORK:
            raise CommandContractError(f"Copy exceeds {MAX_ATOM_WORK} selected protein atoms across placements",
                                       code="source_limit")
        protein_assets[attachment.id] = asset
    # Bound all selected work before world transforms. Repeated placements may
    # share the same resolved asset; validate its coordinates/serials once.
    admitted_assets = {}
    for attachment in proteins:
        asset = protein_assets[attachment.id]
        path = protein_paths[attachment.id]
        if asset.id not in admitted_assets:
            serial_counts = {}
            for atom in asset.atoms:
                serial_counts[atom.serial] = serial_counts.get(atom.serial, 0) + 1
                if not all(math.isfinite(value) for value in (atom.x, atom.y, atom.z)):
                    _reference("protein_asset", asset.id, path, "Copy protein coordinates must be finite")
            admitted_assets[asset.id] = serial_counts
        count = admitted_assets[asset.id].get(attachment.conjugation_atom_serial, 0)
        if count != 1:
            _reference("protein_atom", f"{asset.id}:{attachment.conjugation_atom_serial}", path,
                       "Copy protein atom selection is missing or ambiguous", missing=count == 0)
    worlds, points = {}, []
    for particle in particles:
        path = particle_paths[particle.id]
        if (particle.coating is not None or particle.biotin_dna or particle.id in owned_particles
                or (particle.kind == "gold_nanosphere" and particle.quantum_dot is not None)
                or (particle.kind == "quantum_dot" and particle.quantum_dot is None)
                or particle.kind not in {"gold_nanosphere", "quantum_dot"}):
            _unsupported("Same-part copy requires undecorated gold or catalog particles without DNA or connection ownership")
        if not math.isfinite(particle.diameter_nm) or not 0 < particle.diameter_nm <= 1000:
            _reference("nanoparticle", particle.id, path, "Copy source diameter must be finite and positive")
        center = _pose(particle, "nanoparticle", path)[:3, 3]
        points.extend([center - particle.diameter_nm / 2, center + particle.diameter_nm / 2])
    for attachment in proteins:
        path = protein_paths[attachment.id]
        asset = protein_assets[attachment.id]
        _pose(attachment, "protein_attachment", path)
        world = compose_protein_world_transform(asset, attachment, None, None)
        worlds[attachment.id] = world
        # Keep the exact legacy per-atom matrix multiplication and width formula.
        points.extend((world @ np.array([atom.x, atom.y, atom.z, 1.0]))[:3] for atom in asset.atoms)
    with np.errstate(over="ignore", invalid="ignore"):
        width = float(np.ptp(np.asarray(points)[:, 0])) if points else 0.0
        offset = np.array([(width + 5.0) * command.paste_index, 0.0, 0.0])
    if not np.isfinite(offset).all():
        raise ValueError("Copy placement exceeds finite numeric range")
    shift = np.eye(4)
    shift[:3, 3] = offset
    copied_proteins = []
    for attachment in proteins:
        pose = shift @ worlds[attachment.id]
        if not np.isfinite(pose).all():
            raise ValueError("Copied protein pose exceeds finite numeric range")
        copied_proteins.append(attachment.model_copy(deep=True, update={
            "id": protein_outputs[attachment.id], "pose": Mat4x4.from_array(pose),
        }))
    copied_particles = []
    for particle in particles:
        pose = shift @ particle.pose.to_array()
        if not np.isfinite(pose).all():
            raise ValueError("Copied particle pose exceeds finite numeric range")
        copied_particles.append(particle.model_copy(deep=True, update={
            "id": particle_outputs[particle.id], "pose": Mat4x4.from_array(pose),
        }))
    updated = design.copy_with(
        protein_attachments=[*design.protein_attachments, *copied_proteins],
        nanoparticles=[*design.nanoparticles, *copied_particles],
    )
    refs = ([{"kind": "protein", "id": item.id} for item in copied_proteins]
            + [{"kind": "nanoparticle", "id": item.id} for item in copied_particles])
    return updated, refs


def build(kind, design, params):
    return evaluate(kind, design, params)[0]
