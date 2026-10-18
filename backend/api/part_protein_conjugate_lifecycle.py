"""Native lifecycle of explicitly owned, part-overhang protein conjugates.

Constrained movement delegates unchanged native placement. Deletion removes the
declared binder only after checking strand and nucleotide-address dependencies;
feature-log snapshots are never consulted to guess ownership.
"""

from typing import Annotated
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from backend.api.part_protein_commands import GizmoMove, _atom, _delete, _reference, _selected
from backend.api.part_protein_conjugation_commands import _admit_geometry, _coupled_target, _references
from backend.core.models import StrandType
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_history_proof import ProofBudgetExceeded


KINDS = frozenset({"protein-attach-patch", "protein-attach-delete"})
_Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    protein_version: StrictInt = Field(ge=1, le=1)
    conjugation_version: StrictInt = Field(ge=1, le=1)
    attachment_id: _Id
    binder_strand_id: _Id


class PatchRequest(_Input):
    gizmo_move: GizmoMove | None = None
    visible: StrictBool | None = None


class DeleteRequest(_Input):
    pass


class ConjugateOwnershipError(ReferenceResolutionError):
    def __init__(self, binder_id, kind, identity):
        super().__init__("An existing authored resource depends on the conjugate binder selection",
            code="invalid_selection", references=[{
                "kind": "strand", "identity": binder_id, "parameter_path": ["binder_strand_id"],
            }])
        self.dependent = {"kind": kind, "identity": identity}

    def as_issue(self):
        return {**super().as_issue(), "dependent_resources": [self.dependent]}


def parse_command(kind, params):
    model = {"protein-attach-patch": PatchRequest, "protein-attach-delete": DeleteRequest}.get(kind)
    if model is None:
        raise ValueError("Unsupported owned protein lifecycle command")
    return model.model_validate(params)


def resources(kind, params):
    parse_command(kind, params)
    return {"sources": (), "imports": False}


def _unsupported(detail):
    raise CommandContractError(detail, code="unsupported_conjugate_lifecycle")


def _direction(value):
    return getattr(value, "value", value).upper()


def _contains(domains, helix_id, bp_index, direction):
    return any(domain.helix_id == helix_id and _direction(domain.direction) == _direction(direction)
               and min(domain.start_bp, domain.end_bp) <= bp_index <= max(domain.start_bp, domain.end_bp)
               for domain in domains)


def _overlap(left, right):
    return (left.helix_id == right.helix_id and _direction(left.direction) == _direction(right.direction)
            and max(min(left.start_bp, left.end_bp), min(right.start_bp, right.end_bp))
            <= min(max(left.start_bp, left.end_bp), max(right.start_bp, right.end_bp)))


def _owner(design, command):
    attachment = _selected(design.protein_attachments, command.attachment_id,
                           "protein_attachment", ["attachment_id"])
    if (attachment.target.kind != "overhang" or attachment.azide_end not in {"5p", "3p"}
            or attachment.binder_strand_id != command.binder_strand_id):
        _reference("protein_attachment", attachment.id, ["attachment_id"],
                   "The selected placement does not declare this part-overhang binder ownership")
    binder = _selected(design.strands, command.binder_strand_id, "strand", ["binder_strand_id"])
    if (binder.strand_type != StrandType.OH_BINDER or binder.is_reference or len(binder.domains) != 1
            or binder.domains[0].overhang_id is not None
            or binder.domains[0].binds_overhang_id != attachment.target.overhang_id):
        _reference("strand", binder.id, ["binder_strand_id"],
                   "The owned strand is no longer a standalone conjugate binder")
    for item in design.protein_attachments:
        if item.id != attachment.id and item.binder_strand_id == binder.id:
            raise ConjugateOwnershipError(binder.id, "protein_attachment", item.id)
    for strand in design.strands:
        if strand.id == binder.id:
            continue
        if any(_overlap(binder.domains[0], domain) for domain in strand.domains):
            raise ConjugateOwnershipError(binder.id, "strand", strand.id)
    return attachment, binder


def _residue_dependents(design, binder, domains):
    """Check explicit nucleotide addresses without expanding every nucleotide."""
    from backend.core.base_keys import parse_base_key
    from backend.core.part_saved_topology import snapshot_for

    def blocked(kind, identity):
        raise ConjugateOwnershipError(binder.id, kind, identity)

    def crossovers(items, kind="crossover"):
        for item in items:
            if any(_contains(domains, half.helix_id, half.index, half.strand)
                   for half in (item.half_a, item.half_b)):
                blocked(kind, item.id)

    def ligations(items, kind="forced_ligation"):
        for item in items:
            if (_contains(domains, item.three_prime_helix_id, item.three_prime_bp, item.three_prime_direction)
                    or _contains(domains, item.five_prime_helix_id, item.five_prime_bp, item.five_prime_direction)):
                blocked(kind, item.id)

    crossovers(design.crossovers)
    ligations(design.forced_ligations)
    for item in design.nucleotide_transforms:
        if item.kind == "base" and _contains(domains, item.helix_id, item.bp_index, item.direction):
            blocked("nucleotide_transform", item.id)
    for item in design.cluster_join_constraints:
        if any(_contains(domains, endpoint.helix_id, endpoint.bp_index, endpoint.direction)
               for pair in (item.first, item.second) for endpoint in (pair.source, pair.target)):
            blocked("join_constraint", item.id)
    for item in design.deformations:
        if any(_overlap(domain, selected) for domain in domains for selected in (item.target_ranges or [])):
            blocked("deformation", item.id)
    for strand in design.strands:
        if strand.id != binder.id and any(_overlap(domain, selected)
                for domain in domains for selected in (strand.routing_seed or [])):
            blocked("strand", strand.id)
    for item in design.photoproduct_junctions:
        for key in (item.base_key_1, item.base_key_2, *item.design_coordinates, *item.context_coordinates):
            parsed = parse_base_key(key)
            if parsed is None:
                _unsupported("Conjugate lifecycle cannot resolve legacy or malformed photoproduct endpoints")
            if parsed.family == "xover":
                # Current crossover/ligation endpoints were checked above. The
                # inserted bases cannot belong to this binder without that link.
                continue
            if parsed.family == "extension":
                # An owned extension is caught by its explicit strand reference.
                continue
            if _contains(domains, parsed.helix_id, parsed.bp_index, parsed.direction):
                blocked("photoproduct", item.id)
    # Saved relocation state can reintroduce a constraint to the selected
    # residues. Its ownership grammar is parsed by the existing typed contract.
    for item in [*design.duplexes, *design.overhang_bindings]:
        try:
            saved = snapshot_for(item)
        except NotImplementedError as error:
            _unsupported(str(error))
        if saved is not None:
            crossovers(saved.crossovers)
            if saved.ligation is not None:
                ligations([saved.ligation])


def _delete_closure(design, attachment, binder):
    from backend.core.part_scope_references import COLLECTIONS, GLOBALS, referenced_resources
    from backend.core.part_history_proof import AUTHORING_FIELDS

    if set(COLLECTIONS) | GLOBALS != AUTHORING_FIELDS:
        _unsupported("Conjugate deletion has unclassified authored resource collections")
    for field, kind in COLLECTIONS.items():
        if field == "photoproduct_junctions":
            continue  # Canonical endpoints above; solver reports are not refs.
        for item in getattr(design, field):
            if (field == "protein_attachments" and item.id == attachment.id) or field == "staple_groups":
                continue  # Only these declared ownership/membership links are removed.
            try:
                refs = referenced_resources(item)
            except NotImplementedError as error:
                _unsupported(f"Conjugate deletion cannot resolve ownership: {error}")
            if ("strand", binder.id) in refs:
                raise ConjugateOwnershipError(binder.id, kind, item.id)
    _residue_dependents(design, binder, binder.domains)


def _move_target(design, attachment, binder):
    from backend.core.deformation import _overhang_binding_partner_refs

    spec = _selected(design.overhangs, attachment.target.overhang_id, "overhang", ["attachment_id"])
    _selected(design.helices, spec.helix_id, "helix", ["attachment_id"])
    _selected(design.strands, spec.strand_id, "strand", ["attachment_id"])
    domains = [(strand, domain) for strand in design.strands for domain in strand.domains
               if domain.overhang_id == spec.id]
    if len(domains) != 1:
        _reference("overhang", spec.id, ["attachment_id"], "Overhang backing domain is missing or ambiguous",
                   missing=not domains)
    strand, domain = domains[0]
    if strand.id != spec.strand_id or domain.helix_id != spec.helix_id:
        _reference("overhang", spec.id, ["attachment_id"], "Overhang ownership disagrees with its backing domain")
    partners = _overhang_binding_partner_refs(design, spec.helix_id, domain)
    if [(ref.strand_id, ref.domain_index) for ref in partners] != [(binder.id, 0)]:
        _reference("strand", binder.id, ["binder_strand_id"],
                   "Overhang motion no longer has exactly the declared conjugate partner")
    if _coupled_target(_references(design), spec.id):
        _unsupported("Coupled overhang ownership requires a separate conjugate motion contract")
    _residue_dependents(design, binder, [domain, *binder.domains])
    for extension in design.extensions:
        if extension.strand_id in {binder.id, strand.id}:
            raise ConjugateOwnershipError(binder.id, "extension", extension.id)
    return spec


def native_route_eligible(kind, design, attachment, patch=None):
    if (attachment.target.kind != "overhang" or not attachment.binder_strand_id
            or attachment.azide_end not in {"5p", "3p"}):
        return False
    if kind == "protein-attach-delete":
        # Admission is read-only. Opaque legacy owners stay on the legacy
        # route; known missing/dependent references must fail in the locked
        # native callback rather than bypass its closure check.
        try:
            command = DeleteRequest.model_validate({
                "_proof_version": 1, "protein_version": 1, "conjugation_version": 1,
                "attachment_id": attachment.id, "binder_strand_id": attachment.binder_strand_id,
            })
            current, binder = _owner(design, command)
            _delete_closure(design, current, binder)
        except ReferenceResolutionError:
            return True
        except CommandContractError:
            return False
        return True
    patch = patch or {}
    if any(value is not None for name, value in patch.items() if name not in {"gizmo_move", "visible"}):
        return False
    if patch.get("gizmo_move") is None:
        return True
    assets = [asset for asset in design.protein_assets if asset.id == attachment.asset_id]
    if not assets:
        return False  # Preserve legacy mutable-library placement behavior.
    if len(assets) != 1:
        return True
    try:
        _admit_geometry(design, assets[0])
        return not _coupled_target(_references(design), attachment.target.overhang_id)
    except ProofBudgetExceeded:
        return False
    except CommandContractError as error:
        return error.code != "unsupported_conjugation_source"


def evaluate(kind, design, params):
    from backend.core.cluster_autodetect import with_default_cluster
    from backend.core.design_geometry import _geometry_for_helices
    from backend.core.feature_identity import identity_factory
    from backend.core.models import Mat4x4
    from backend.core.protein import _conjugate_terminus_position, constrained_conjugate_move, resolve_overhang_anchor

    command = parse_command(kind, params)
    attachment, binder = _owner(design, command)
    constraint = None
    changed = []
    if kind == "protein-attach-delete":
        _delete_closure(design, attachment, binder)
        groups = []
        for group in design.staple_groups:
            if binder.id not in group.strand_ids:
                groups.append(group)
                continue
            remaining = [identity for identity in group.strand_ids if identity != binder.id]
            if remaining:
                groups.append(group.model_copy(update={"strand_ids": remaining}))
        updated = _delete(design, attachment).copy_with(
            strands=[strand for strand in design.strands if strand.id != binder.id],
            staple_groups=groups,
        )
        changed = sorted({domain.helix_id for domain in binder.domains})
    else:
        updates = {}
        updated = design
        if command.gizmo_move is not None:
            asset = _selected(design.protein_assets, attachment.asset_id, "protein_asset", ["attachment_id"])
            _atom(asset, attachment.conjugation_atom_serial, ["attachment_id"])
            _admit_geometry(design, asset)
            spec = _move_target(design, attachment, binder)
            move = command.gizmo_move
            geometry = _geometry_for_helices(design, frozenset({spec.helix_id}))
            root, _ = resolve_overhang_anchor(geometry, spec.id, "root")
            terminus = _conjugate_terminus_position(geometry, attachment)
            if root is None or terminus is None:
                _reference("overhang", spec.id, ["attachment_id"],
                           "Conjugate constraint cannot resolve its root and binder terminus", missing=True)
            pose, rotation, constraint = constrained_conjugate_move(design, asset, attachment,
                geometry,
                pivot=move.pivot, translation=move.translation, rotation=move.rotation)
            updates["pose"] = Mat4x4.from_array(pose)
            updated = design.copy_with(overhangs=[
                item.model_copy(update={"rotation": rotation}) if item.id == spec.id else item
                for item in design.overhangs])
            changed = [spec.helix_id]
        if command.visible is not None:
            updates["visible"] = command.visible
        updated = updated.copy_with(protein_attachments=[
            item.model_copy(update=updates) if item.id == attachment.id else item
            for item in updated.protein_attachments])
    namespace = uuid5(NAMESPACE_URL, f"nadoc:protein-command:v1:{kind}:{attachment.id}")
    updated = with_default_cluster(updated, identity_factory=identity_factory(namespace))
    return updated, {"protein_constraint": constraint, "changed_helix_ids": changed}


def build(kind, design, params):
    return evaluate(kind, design, params)[0]
