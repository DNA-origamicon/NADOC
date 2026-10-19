"""Bounded native protein–overhang conjugation with explicit ownership.

Only the existing binder, grouping, placement and element-validation algorithms
produce geometry. Inputs select references and identities, never solved poses.
Conjugate movement/deletion and linker-coupled targets need separate contracts.
"""

from typing import Annotated, Literal
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.api.part_protein_commands import (
    MAX_PROTEIN_ATOM_RECORDS, MAX_PROTEIN_BONDS, _atom, _reference, _selected,
)
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import ProofBudgetExceeded


KINDS = frozenset({"protein-conjugate"})
MAX_GEOMETRY_BASES = 50_000
_Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]


class ConjugateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    protein_version: StrictInt = Field(ge=1, le=1)
    conjugation_version: StrictInt = Field(ge=1, le=1)
    asset_id: _Id
    overhang_id: _Id
    conjugation_atom_serial: Annotated[StrictInt, Field(ge=1)]
    azide_end: Literal["5p", "3p"]
    attachment_id: _Id
    binder_strand_id: _Id
    group_id: _Id
    source_attachment_id: _Id | None = None
    # Route idempotence is metadata, not a geometry source. Preserve it on edit.
    operation_id: _Id | None = None

    @model_validator(mode="after")
    def preserves_converted_identity(self):
        if self.source_attachment_id is not None and self.source_attachment_id != self.attachment_id:
            raise ValueError("Conjugation must preserve the converted free attachment identity")
        return self


class ConjugationValidationError(CommandContractError):
    """The unchanged native element gate rejected the isolated candidate."""

    status = "failed"

    def __init__(self, report):
        super().__init__("Protein conjugate failed native element validation",
                         code="element_validation_failed")
        self.report = report

    def as_issue(self):
        return {**super().as_issue(), "element_validation": self.report}


def parse_command(kind, params):
    if kind not in KINDS:
        raise ValueError("Unsupported native protein conjugation command")
    return ConjugateRequest.model_validate(params)


def resources(kind, params):
    parse_command(kind, params)
    return {"sources": (), "imports": False}


def _unsupported(detail):
    raise CommandContractError(detail, code="unsupported_conjugation_source")


def _references(design):
    """Typed ownership checks, excluding atom arrays and unrelated CPD reports."""
    from backend.core.part_scope_references import referenced_resources

    result = []
    fields = (
        "extensions", "staple_groups", "flexible_segment_marks", "flexible_connections",
        "protein_attachments", "nanoparticles", "nanoparticle_conjugations",
        "nanoparticle_connection_versions", "cluster_transforms", "deformations",
        "duplexes", "overhang_bindings",
    )
    try:
        for field in fields:
            for item in getattr(design, field):
                result.append((field, referenced_resources(item)))
    except NotImplementedError as error:
        _unsupported(f"Conjugation cannot resolve existing ownership: {error}")
    return result


def _admit_geometry(design, asset, *, extra_domain_bases=0):
    if len(asset.atoms) > MAX_PROTEIN_ATOM_RECORDS or len(asset.bonds) > MAX_PROTEIN_BONDS:
        raise ProofBudgetExceeded("Native conjugation supports at most 1,000 protein atoms and 4,000 bonds")
    # Full native geometry is the established route's source. Bound the whole
    # supplied design, including sparse domains outside the nominal helix span.
    # Linker geometry has a separate ownership/allocation contract, still open.
    if design.overhang_connections:
        _unsupported("Native conjugation v1 does not admit designs with linker connections")
    spans = {helix.id: [helix.bp_start, helix.bp_start + max(0, helix.length_bp - 1)]
             for helix in design.helices}
    occupied = extra_domain_bases
    for strand in design.strands:
        for domain in strand.domains:
            lo, hi = sorted((domain.start_bp, domain.end_bp))
            occupied += hi - lo + 1
            if domain.helix_id in spans:
                span = spans[domain.helix_id]
                span[0], span[1] = min(span[0], lo), max(span[1], hi)
    emitted = 2 * sum(hi - lo + 1 for lo, hi in spans.values())
    emitted += 2 * sum(max(0, item.delta) for helix in design.helices for item in helix.loop_skips)
    emitted += sum(len(extension.sequence or "") for extension in design.extensions)
    if max(occupied, emitted) > MAX_GEOMETRY_BASES:
        raise ProofBudgetExceeded("Native conjugation exceeds its 50,000 nucleotide geometry admission")


def _coupled_target(references, overhang_id):
    coupled = {"duplexes", "overhang_bindings", "nanoparticle_conjugations", "nanoparticle_connection_versions"}
    return any(field in coupled and ("overhang", overhang_id) in refs for field, refs in references)


def native_route_eligible(design, asset_id, overhang_id):
    """Cheap scope admission only; invalid references must reach strict build.

    The route decides legacy/native before starting its transaction. A later
    source change is checked again by build and can never trigger a fallback
    after partial candidate evaluation.
    """
    assets = [asset for asset in design.protein_assets if asset.id == asset_id]
    if not assets:
        return False
    if len(assets) != 1:
        return True  # Ambiguity is a failed reference, not legacy admission.
    prospective = sum(abs(domain.end_bp - domain.start_bp) + 1
                      for strand in design.strands for domain in strand.domains
                      if domain.overhang_id == overhang_id)
    try:
        _admit_geometry(design, assets[0], extra_domain_bases=prospective)
        return not _coupled_target(_references(design), overhang_id)
    except ProofBudgetExceeded:
        return False
    except CommandContractError as error:
        # Only an explicitly unsupported scope selects legacy. A reference
        # error must still pass through the strict transactional error path.
        return error.code != "unsupported_conjugation_source"


def _resolve(design, command):
    asset = _selected(design.protein_assets, command.asset_id, "protein_asset", ["asset_id"])
    _atom(asset, command.conjugation_atom_serial, ["conjugation_atom_serial"])
    spec = _selected(design.overhangs, command.overhang_id, "overhang", ["overhang_id"])
    _selected(design.helices, spec.helix_id, "helix", ["overhang_id"])
    _selected(design.strands, spec.strand_id, "strand", ["overhang_id"])
    domains = [(strand, domain) for strand in design.strands for domain in strand.domains
               if domain.overhang_id == spec.id]
    if len(domains) != 1:
        _reference("overhang", spec.id, ["overhang_id"], "Overhang backing domain is missing or ambiguous",
                   missing=not domains)
    strand, domain = domains[0]
    if strand.id != spec.strand_id or domain.helix_id != spec.helix_id:
        _reference("overhang", spec.id, ["overhang_id"], "Overhang ownership disagrees with its backing domain")
    if any(domain.binds_overhang_id == spec.id for strand in design.strands for domain in strand.domains):
        _reference("overhang", spec.id, ["overhang_id"], "The selected overhang already has a binder")

    source = None
    if command.source_attachment_id is not None:
        source = _selected(design.protein_attachments, command.source_attachment_id,
                           "protein_attachment", ["source_attachment_id"])
        if (source.asset_id != asset.id or source.target.kind != "free"
                or source.binder_strand_id or source.azide_end):
            _reference("protein_attachment", source.id, ["source_attachment_id"],
                       "Conjugation can convert only an unowned free placement of the selected asset")
    elif any(item.id == command.attachment_id for item in design.protein_attachments):
        _reference("protein_attachment", command.attachment_id, ["attachment_id"],
                   "Protein attachment output identity already exists")

    for field, identity, kind, path in (
        ("strands", command.binder_strand_id, "strand", "binder_strand_id"),
        ("staple_groups", command.group_id, "staple_group", "group_id"),
    ):
        if any(item.id == identity for item in getattr(design, field)):
            _reference(kind, identity, [path], "Conjugation output identity already exists")
    references = _references(design)
    if (any(spec.strand_id == command.binder_strand_id for spec in design.overhangs)
            or any(("strand", command.binder_strand_id) in refs for _, refs in references)):
        _reference("strand", command.binder_strand_id, ["binder_strand_id"],
                   "Binder output identity is already referenced by an existing record")
    if _coupled_target(references, spec.id):
        _reference("overhang", spec.id, ["overhang_id"],
                   "The selected overhang has coupled ownership outside the native conjugation contract")
    _admit_geometry(design, asset, extra_domain_bases=abs(domain.end_bp - domain.start_bp) + 1)
    return asset, spec, source


def evaluate(kind, design, params):
    """Return the isolated native candidate and its unchanged element report."""
    import numpy as np

    from backend.core.cluster_autodetect import with_default_cluster
    from backend.core.conjugate_strands import assign_conjugate_group
    from backend.core.conjugation import conjugation_candidate_for_serial
    from backend.core.design_geometry import _geometry_for_helices
    from backend.core.feature_identity import identity_factory
    from backend.core.lattice import make_binder_for_overhang  # own binder_cardinality validation; occupancy is checked at publication
    from backend.core.models import Mat4x4, ProteinAttachment, ProteinTargetDesign
    from backend.core.protein import _conjugate_terminus_position, azide_attach_end, resolve_overhang_anchor
    from backend.core.protein_validation import validate_protein_conjugate

    command = parse_command(kind, params)
    asset, spec, source = _resolve(design, command)
    selected = conjugation_candidate_for_serial(asset, command.conjugation_atom_serial)
    if selected is None:
        _reference("protein_atom", f"{asset.id}:{command.conjugation_atom_serial}", ["conjugation_atom_serial"],
                   "Conjugation requires a supported surface-accessible reactive site")
    binder_design = make_binder_for_overhang(design, spec.id, strand_id=command.binder_strand_id)
    binder = _selected(binder_design.strands, command.binder_strand_id, "strand", ["binder_strand_id"])
    binders, group = assign_conjugate_group(design, [binder], prefix=asset.name, fallback="Protein",
                                          group_id=command.group_id)
    binder = binders[0]
    geometry = _geometry_for_helices(binder_design)
    attachment = ProteinAttachment(
        id=command.attachment_id, asset_id=asset.id,
        target=ProteinTargetDesign(overhang_id=spec.id, attach_end=azide_attach_end(
            geometry, spec.id, binder.id, command.azide_end)),
        conjugation_atom_serial=command.conjugation_atom_serial,
        conjugation_chemistry=selected["chemistry"], conjugation_accessible_fraction=selected["accessible"],
        binder_strand_id=binder.id, azide_end=command.azide_end, handle_sequence=binder.sequence,
    )
    binder_tip = _conjugate_terminus_position(geometry, attachment)
    overhang_tip, _ = resolve_overhang_anchor(geometry, spec.id, attachment.target.attach_end)
    root_tip, _ = resolve_overhang_anchor(geometry, spec.id, "root")
    free_tip, _ = resolve_overhang_anchor(geometry, spec.id, "free_end")
    if any(tip is None for tip in (binder_tip, overhang_tip, root_tip, free_tip)):
        _reference("overhang", spec.id, ["overhang_id"], "Native conjugation anchor geometry is unavailable")
    values = np.eye(4)
    values[:3, 3] = binder_tip - overhang_tip
    attachment.pose = Mat4x4.from_array(values)
    candidate = design.copy_with(
        strands=[*design.strands, binder], staple_groups=[*design.staple_groups, group],
        protein_attachments=[*[item for item in design.protein_attachments
                               if source is None or item.id != source.id], attachment],
    )
    report = validate_protein_conjugate(design, candidate, asset=asset, attachment=attachment,
        binder=binder, geometry=geometry, source_attachment_id=command.source_attachment_id)
    if not report["valid"]:
        raise ConjugationValidationError(report)
    namespace = uuid5(NAMESPACE_URL, f"nadoc:protein-command:v1:{kind}:{command.attachment_id}")
    candidate = with_default_cluster(candidate, identity_factory=identity_factory(namespace))
    return candidate, report


def build(kind, design, params):
    return evaluate(kind, design, params)[0]
