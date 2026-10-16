"""Explicit, bounded nanoparticle application over the existing native kernel.

No coordinates or restoration snapshots are accepted as inputs. Bound ownership
is validated separately from radial ownership, then the unchanged native
restore/relocate operations execute with authored output IDs and timestamps.
The conservative v1 work ceiling is not a latency qualification or live gate.
"""

from math import isfinite
from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import Field, StrictBool, StrictInt, field_validator, model_validator

from backend.api import part_nanoparticle_connection_commands as pending
from backend.api.part_thiol_commands import resolve_owned_handles
from backend.core.feature_identity import identity_factory
from backend.core.models import NanoparticleConnectionVersion, OverhangBinding
from backend.core.nanoparticle_connections import ConnectionApplicationError, set_version_applied
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_saved_topology import snapshot_for, validate_owner
from backend.core.part_scope_references import COLLECTIONS, identity_index, referenced_resources


MAX_APPLICATION_BASES = 4_096
MAX_APPLICATION_HANDLES = 16
MAX_VERSIONS = 128
_Time = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]


class _Application(pending._Input):
    nanoparticle_application_version: StrictInt = Field(ge=1, le=1)
    history_seed: pending._Id
    handle_overhang_id: pending._Id
    prior_duplex_id: pending._Id | None
    conflict_version_ids: list[pending._Id] = Field(max_length=MAX_VERSIONS)

    @field_validator("name", check_fields=False)
    @classmethod
    def nonblank_name(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Candidate name must not be blank")
        return value

    @field_validator("history_seed")
    @classmethod
    def canonical_seed(cls, value):
        if str(UUID(value)) != value:
            raise ValueError("history_seed must be a canonical UUID")
        return value

    @field_validator("conflict_version_ids")
    @classmethod
    def unique_conflicts(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("conflict_version_ids must be unique")
        return value


class _Transition(_Application):
    applied: StrictBool
    duplex_id: pending._Id | None = None
    duplex_created_at: _Time | None = None

    @model_validator(mode="after")
    def explicit_outputs(self):
        if self.applied != (self.duplex_id is not None and self.duplex_created_at is not None):
            raise ValueError("Applying requires an explicit duplex ID and creation time")
        if not self.applied and (self.duplex_id is not None or self.duplex_created_at is not None):
            raise ValueError("Unapplying cannot introduce duplex output identities")
        return self


class CreateRequest(_Transition):
    name: pending._Name
    created_at: _Time
    connection_type: Literal["direct"]
    direct_variant: Literal["end-to-root", "root-to-root"]

    @model_validator(mode="after")
    def create_applied(self):
        if not self.applied or self.prior_duplex_id is not None:
            raise ValueError("Application creation requires applied=true and no prior duplex")
        return self


class PatchRequest(_Transition):
    name: pending._Name | None = None


class DeleteRequest(_Application):
    pass


def parse_command(kind, params):
    model = {"nanoparticle-connection-version-create": CreateRequest,
             "nanoparticle-connection-version-patch": PatchRequest,
             "nanoparticle-connection-version-delete": DeleteRequest}.get(kind)
    if model is None:
        raise ValueError("Unsupported nanoparticle application command")
    return model.model_validate(params)


def _unsupported(detail):
    raise CommandContractError(detail, code="unsupported_np_application_source")


def _work_admission(design):
    if not pending._record_count_bounded(design):
        _unsupported("Nanoparticle application exceeds its reference allowance")
    # These families can add opaque geometry, native-residue work or coupled
    # placement. They need a separate qualified contract, not a larger budget.
    for field in ("extensions", "deformations", "nucleotide_transforms", "overhang_connections",
                  "flexible_segment_marks", "flexible_connections", "protein_assets", "protein_attachments",
                  "photoproduct_junctions", "cluster_join_constraints"):
        if getattr(design, field):
            _unsupported(f"Native nanoparticle application does not yet admit {field}")
    bases, helix_bases, loop_entries = 0, 0, 0
    for helix in design.helices:
        if helix.native_residues or helix.native_source:
            _unsupported("Native nanoparticle application does not admit imported residue geometry")
        if helix.length_bp < 1 or not all(isfinite(value) for value in (
                helix.axis_start.x, helix.axis_start.y, helix.axis_start.z,
                helix.axis_end.x, helix.axis_end.y, helix.axis_end.z,
                helix.phase_offset, helix.twist_per_bp_rad)):
            _unsupported("Nanoparticle application requires finite nonempty DNA geometry")
        helix_bases += max(0, helix.length_bp)
        loop_entries += len(helix.loop_skips)
        if helix_bases > MAX_APPLICATION_BASES or loop_entries > MAX_APPLICATION_BASES:
            _unsupported("Nanoparticle application exceeds its emitted-base allowance")
        for entry in helix.loop_skips:
            if entry.delta not in {-1, 1}:
                _unsupported("Nanoparticle application has unsupported loop work")
            bases += 2 * max(0, entry.delta)
            if bases > MAX_APPLICATION_BASES:
                _unsupported("Nanoparticle application exceeds its emitted-base allowance")
    for strand in design.strands:
        if strand.is_reference:
            _unsupported("Native nanoparticle application does not admit reference strands")
        if len(strand.domains) > MAX_APPLICATION_BASES or len(strand.sequence or "") > MAX_APPLICATION_BASES:
            _unsupported("Nanoparticle application exceeds its domain allowance")
        for domain in strand.domains:
            bases += abs(domain.end_bp - domain.start_bp) + 1
            if bases > MAX_APPLICATION_BASES:
                _unsupported("Nanoparticle application exceeds its emitted-base allowance")
    for particle in design.nanoparticles:
        if not pending._source_free(particle):
            _unsupported("Nanoparticle application currently admits source-free uncoated gold only")
        if not all(isfinite(value) for value in particle.pose.values):
            _unsupported("Nanoparticle application requires a finite particle pose")
    for crossover in design.crossovers:
        if crossover.extra_bases:
            _unsupported("Nanoparticle application does not yet admit crossover extra bases")
    for ligation in design.forced_ligations:
        if ligation.extra_bases:
            _unsupported("Nanoparticle application does not yet admit ligation extra bases")
    for duplex in design.duplexes:
        saved = duplex.prior_driven_topology
        if isinstance(saved, dict) and isinstance(saved.get("driven_helix"), dict):
            historical = saved["driven_helix"]
            length = historical.get("length_bp")
            if type(length) is not int or length < 1:
                _unsupported("Saved nanoparticle restoration has invalid emitted work")
            helix_bases += length
            if helix_bases > MAX_APPLICATION_BASES or historical.get("loop_skips"):
                _unsupported("Saved nanoparticle restoration exceeds its admitted work")


def _conflicts(design, body):
    actual = {item.id for item in design.nanoparticle_connection_versions
              if item.id != body.version_id and (item.strand_id == body.strand_id or item.overhang_id == body.overhang_id)}
    expected = set(body.conflict_version_ids)
    if actual != expected:
        identity = sorted(actual - expected or expected - actual)[0]
        pending._fail("Application must select exactly the current conflicting versions",
                      "nanoparticle_connection_version", identity, "conflict_version_ids",
                      missing=not any(item.id == identity for item in design.nanoparticle_connection_versions))


def _restoration(design, index, owner, current):
    """Validate an actual single-domain NP relocation, never invent live state."""
    bad = lambda detail: pending._fail(detail, "nanoparticle_connection_version", current.id, "prior_duplex_id")
    if (not current.applied or current.relaxed or current.residual_nm is not None
            or current.duplex_id is None or current.constraint_root_nm is None
            or current.constraint_radius_nm is None or not isfinite(current.constraint_radius_nm)
            or current.constraint_radius_nm < 0 or not all(isfinite(v) for v in current.constraint_root_nm)):
        bad("Application restoration requires an active, unrelaxed native connection")
    duplex = pending._resolve(index, "duplex", current.duplex_id, "prior_duplex_id")
    records = [record for record in owner.surface_strands if record.strand_id == current.strand_id]
    if len(records) != 1:
        bad("Applied handle ownership is ambiguous")
    record = records[0]
    strand = pending._resolve(index, "strand", record.strand_id, "strand_id")
    endpoint = pending._resolve(index, "overhang", record.overhang_id, "handle_overhang_id")
    if (duplex.driver != "right" or not duplex.bound or duplex.target_joint_id is not None
            or duplex.locked_angle_deg is not None or duplex.binding_mode != "duplex"
            or duplex.connection_type != f"nanoparticle-{current.direct_variant}"
            or duplex.left.overhang_id != endpoint.id or duplex.right.overhang_id != current.overhang_id
            or record.bound_overhang_id != current.overhang_id or len(strand.domains) != 1
            or not endpoint.auxiliary_endpoint or endpoint.strand_id != strand.id
            or record.helix_id != endpoint.helix_id or strand.domains[0].helix_id != endpoint.helix_id
            or strand.domains[0].overhang_id != endpoint.id or strand.domains[0].binds_overhang_id):
        bad("Applied handle, endpoint and duplex ownership disagree")
    try:
        saved = snapshot_for(duplex)
        if saved is None:
            bad("Applied duplex has no restorable native topology")
        validate_owner(saved, index)
    except ReferenceResolutionError as error:
        raise ReferenceResolutionError(str(error), code=error.code, references=[
            {**reference, "parameter_path": ["prior_duplex_id"]} for reference in error.references]) from error
    except NotImplementedError as error:
        _unsupported(str(error))
    if (saved.value["strand_id"] != strand.id or saved.value["domain_index"] != 0
            or saved.value["driven_oh_id"] != endpoint.id or saved.value["driver_oh_id"] != current.overhang_id
            or not saved.helix.id.startswith("__np__") or saved.crossovers or saved.ligation is not None
            or ("helix", saved.helix.id) in index):
        bad("Restoration cannot replace a live or foreign historical resource")
    prior = saved.value["prior_domain"]
    if (sorted((prior["start_bp"], prior["end_bp"])) != [saved.helix.bp_start, saved.helix.bp_start + saved.helix.length_bp - 1]
            or saved.helix.length_bp != abs(strand.domains[0].end_bp - strand.domains[0].start_bp) + 1
            or saved.helix.native_residues or saved.helix.native_source
            or not all(isfinite(value) for value in (
                saved.helix.axis_start.x, saved.helix.axis_start.y, saved.helix.axis_start.z,
                saved.helix.axis_end.x, saved.helix.axis_end.y, saved.helix.axis_end.z,
                saved.helix.phase_offset, saved.helix.twist_per_bp_rad))):
        bad("Restored nanoparticle handle does not own its complete radial helix")
    children = [item for item in design.cluster_transforms if item.overhang_duplex_driver_id == current.overhang_id]
    target = pending._resolve(index, "overhang", current.overhang_id, "overhang_id")
    backing = pending._target_backings(design, {target.id}).get(target.id, ())
    if len(backing) != 1:
        bad("Applied target has an ambiguous backing domain")
    target_strand, target_domain = backing[0]
    expected = {(strand.id, 0), (target_strand.id, target_strand.domains.index(target_domain))}
    if (len(children) != 1 or not children[0].auto_created
            or set(children[0].helix_ids) != {target.helix_id}
            or {(item.strand_id, item.domain_index) for item in children[0].domain_ids} != expected):
        bad("Applied duplex child cluster has ambiguous ownership")
    return duplex, saved, children[0]


def _incoming(design, changed, allowed, outputs):
    """Protect changed endpoints and removed radial/child identities in one pass."""
    for field, kind in COLLECTIONS.items():
        for item in getattr(design, field):
            key = (kind, item.id)
            refs = referenced_resources(item)
            collision = refs & outputs
            if collision:
                resource = sorted(collision)[0]
                pending._fail("Application output already has an incoming reference", *resource, "history_seed")
            if key in allowed or not refs & changed:
                continue
            if field == "staple_groups":
                continue  # The same strand identities remain in their groups.
            if (field == "cluster_transforms" and item.is_default and not item.domain_ids
                    and item.parent_cluster_id is None and item.overhang_duplex_driver_id is None):
                continue  # Ordinary whole-helix catch-all membership is reconciled.
            resource = sorted(refs & changed)[0]
            pending._fail(f"Applied resource is still used by {kind} {item.id}", *resource, "handle_overhang_id")


def _domain_consumers(design, selected):
    """Directional addresses on a shared target helix are not helix-ID edges."""
    domains = [domain for strand in design.strands if strand.id in selected for domain in strand.domains]

    def contains(helix_id, bp, direction):
        return any(domain.helix_id == helix_id and domain.direction == direction
                   and min(domain.start_bp, domain.end_bp) <= bp <= max(domain.start_bp, domain.end_bp)
                   for domain in domains)

    def blocked(kind, identity):
        pending._fail("An authored nucleotide address depends on the moving handle",
                      kind, identity, "handle_overhang_id")

    for strand in design.strands:
        if strand.id not in selected and any(
                left.helix_id == right.helix_id and left.direction == right.direction
                and max(min(left.start_bp, left.end_bp), min(right.start_bp, right.end_bp))
                <= min(max(left.start_bp, left.end_bp), max(right.start_bp, right.end_bp))
                for left in domains for right in strand.domains):
            blocked("strand", strand.id)
    for crossover in design.crossovers:
        if any(contains(half.helix_id, half.index, half.strand) for half in (crossover.half_a, crossover.half_b)):
            blocked("crossover", crossover.id)
    for ligation in design.forced_ligations:
        if (contains(ligation.three_prime_helix_id, ligation.three_prime_bp, ligation.three_prime_direction)
                or contains(ligation.five_prime_helix_id, ligation.five_prime_bp, ligation.five_prime_direction)):
            blocked("forced_ligation", ligation.id)


def _radial_carrier_consumers(design, owners):
    """Removal/restoration requires exclusive carrier ownership in either direction."""
    for strand in design.strands:
        for domain in strand.domains:
            owner = owners.get(domain.helix_id)
            if owner is not None and owner != strand.id:
                pending._fail("Another strand uses the nanoparticle handle's radial carrier",
                              "helix", domain.helix_id, "handle_overhang_id")


def _prospective_occupancy(radial, body, owner, variant):
    """Use the native topology planner to check the full future driven interval.

    This is bounded topology only, before fitting. It avoids guessing the range
    from the shorter pairing register when handle and target lengths differ.
    """
    from backend.core.binding_relax import compute_bind_topology
    from backend.core.duplex import connect_register
    from backend.core.nanoparticle_connections import connection_attaches

    endpoint = next(item for item in radial.overhangs if item.id == body.handle_overhang_id)
    target = next(item for item in radial.overhangs if item.id == body.overhang_id)
    np_attach, target_attach = connection_attaches(owner, variant)
    _left, right = connect_register(radial, endpoint.id, np_attach, target.id, target_attach)
    identifier = identity_factory(body.history_seed)
    temporary = OverhangBinding(id=identifier("duplex-transient", [body.duplex_id]),
        created_at=body.duplex_created_at, name="__duplex_reloc__",
        sub_domain_a_id=target.sub_domains[0].id, sub_domain_b_id=endpoint.sub_domains[0].id,
        overhang_a_id=target.id, overhang_b_id=endpoint.id,
        driver_oh_id=target.id, driven_oh_id=endpoint.id)
    topology = compute_bind_topology(radial, temporary, driver_side="a",
        target_start_override=right.end_bp, target_end_override=right.start_bp,
        forced_ligation_id=identifier("duplex-ligation", [body.duplex_id]))
    driven = radial.find_strand(body.strand_id)
    if (abs(topology.target_end_bp - topology.target_start_bp)
            != abs(driven.domains[0].end_bp - driven.domains[0].start_bp)):
        pending._fail("The selected target is too short to preserve the complete nanoparticle handle",
                      "overhang", target.id, "overhang_id")
    domain = driven.domains[0].model_copy(update={"helix_id": topology.target_helix_id,
        "start_bp": topology.target_start_bp, "end_bp": topology.target_end_bp,
        "direction": topology.target_direction})
    # The native planner supplies all placement arithmetic. This private view
    # is only an occupancy query; it never becomes a published materialization.
    prospective = radial.model_copy(update={"strands": [
        item.model_copy(update={"domains": [domain]}) if item.id == driven.id else item
        for item in radial.strands]})
    _domain_consumers(prospective, {driven.id})


def build(kind, design, params):
    body = parse_command(kind, params)
    _work_admission(design)
    prepared = pending._prepare_source(design)
    index = prepared.index
    particle = pending._resolve(index, "nanoparticle", body.nanoparticle_id, "nanoparticle_id")
    owner = pending._resolve(index, "nanoparticle_conjugation", body.conjugation_id, "conjugation_id")
    strand = pending._resolve(index, "strand", body.strand_id, "strand_id")
    target = pending._resolve(index, "overhang", body.overhang_id, "overhang_id")
    endpoint = pending._resolve(index, "overhang", body.handle_overhang_id, "handle_overhang_id")
    if owner.nanoparticle_id != particle.id:
        pending._fail("Application conjugation belongs to another particle", "nanoparticle_conjugation", owner.id, "conjugation_id")
    if len(owner.surface_strands) > MAX_APPLICATION_HANDLES:
        _unsupported("Native nanoparticle application currently admits at most 16 handles")
    handles = [item for item in owner.surface_strands if item.strand_id == strand.id]
    if len(handles) != 1 or handles[0].overhang_id != endpoint.id:
        pending._fail("Application auxiliary endpoint disagrees with its selected handle", "overhang", endpoint.id, "handle_overhang_id")
    if len(design.nanoparticle_connection_versions) > MAX_VERSIONS:
        _unsupported("Native nanoparticle application exceeds its version allowance")
    _conflicts(design, body)
    creating, applying = isinstance(body, CreateRequest), isinstance(body, _Transition) and body.applied
    current = None
    if creating:
        if ("nanoparticle_connection_version", body.version_id) in index:
            pending._fail("Connection output identity already exists", "nanoparticle_connection_version", body.version_id, "version_id")
    else:
        current = pending._resolve(index, "nanoparticle_connection_version", body.version_id, "version_id")
        for field, resource in (("nanoparticle_id", "nanoparticle"), ("strand_id", "strand"), ("overhang_id", "overhang")):
            if getattr(current, field) != getattr(body, field):
                pending._fail("Application selection no longer matches its version", resource, getattr(body, field), field)
        if body.prior_duplex_id != current.duplex_id:
            pending._fail("Application must select the exact current duplex", "duplex", body.prior_duplex_id or "", "prior_duplex_id")
    variant = body.direct_variant if creating else current.direct_variant
    attaches = pending._validate_endpoint(index, owner, strand, target, variant,
        pending._target_backings(design, {target.id}).get(target.id, ()), version=current)
    relevant = ([current] if current is not None else []) + ([index[("nanoparticle_connection_version", identity)]
        for identity in body.conflict_version_ids] if applying else [])
    active = [item for item in design.nanoparticle_connection_versions if item.nanoparticle_id == particle.id and item.applied]
    if len(active) > 1:
        _unsupported("Native nanoparticle application admits one active version per particle")
    restoring = []
    for item in relevant:
        if pending._pending(item):
            continue
        if item.nanoparticle_id != particle.id:
            _unsupported("Native nanoparticle application cannot displace another particle's applied version")
        restoring.append((item, *_restoration(design, index, owner, item)))
    if any(item.id not in {version.id for version, *_ in restoring} for item in active):
        _unsupported("Another applied handle lies outside the selected restoration")
    changed = {("overhang", body.overhang_id), ("strand", strand.id), ("overhang", endpoint.id)}
    allowed = {("nanoparticle_conjugation", owner.id), ("strand", strand.id), ("overhang", endpoint.id),
               ("overhang", target.id), ("strand", target.strand_id)}
    allowed.update(("nanoparticle_connection_version", identity) for identity in [body.version_id, *body.conflict_version_ids])
    radial = design
    for old, duplex, saved, child in restoring:
        changed.update({("duplex", duplex.id), ("cluster", child.id), ("strand", old.strand_id),
                        ("overhang", saved.value["driven_oh_id"]), ("overhang", old.overhang_id)})
        allowed.update({("duplex", duplex.id), ("cluster", child.id), ("strand", old.strand_id),
                        ("overhang", saved.value["driven_oh_id"]), ("overhang", old.overhang_id),
                        ("strand", index[("overhang", old.overhang_id)].strand_id)})
        # No fitting/solver work: native restoration supplies the exact radial
        # owner for the existing strict unbound resolver; no parallel geometry.
        radial = set_version_applied(radial, old.id, False)
    radial_index = identity_index(radial)[0] if restoring else index
    try:
        resolve_owned_handles(radial, particle.id, [owner.id], radial_index, parameter="conjugation_id")
    except ReferenceResolutionError as error:
        raise ReferenceResolutionError(str(error), code=error.code, references=[
            {**reference, "parameter_path": ["conjugation_id"]} for reference in error.references]) from error
    radial_owners = {}
    for record in radial_index[("nanoparticle_conjugation", owner.id)].surface_strands:
        if ("strand", record.strand_id) in changed:
            changed.add(("helix", record.helix_id))
            radial_owners[record.helix_id] = record.strand_id
    _radial_carrier_consumers(radial, radial_owners)
    if applying and not restoring and (list(target.rotation) != [0., 0., 0., 1.] or list(target.translation) != [0., 0., 0.]):
        _unsupported("Native application requires an unposed target overhang before relocation")
    outputs = set()
    if creating:
        outputs.add(("nanoparticle_connection_version", body.version_id))
    if applying:
        factory = identity_factory(body.history_seed)
        outputs.update({("duplex", body.duplex_id), ("cluster", factory("duplex-cluster", [body.duplex_id])),
                        ("forced_ligation", factory("duplex-ligation", [body.duplex_id])),
                        ("overhang_binding", factory("duplex-transient", [body.duplex_id]))})
    for resource in sorted(outputs & index.keys()):
        pending._fail("Application output identity already exists", *resource,
                      "duplex_id" if resource[0] == "duplex" else "history_seed")
    _incoming(design, changed, allowed, outputs)
    _domain_consumers(design, {identity for kind, identity in changed if kind == "strand"})
    if applying:
        try:
            _prospective_occupancy(radial, body, owner, variant)
        except (HTTPException, ConnectionApplicationError, ValueError) as error:
            # Structured resource failures keep their original selectors.
            if isinstance(error, CommandContractError):
                raise
            pending._fail(str(getattr(error, "detail", error)), "overhang", body.overhang_id, "overhang_id")
    candidate = design
    if creating:
        current = NanoparticleConnectionVersion(id=body.version_id, name=body.name, created_at=body.created_at,
            nanoparticle_id=particle.id, strand_id=strand.id, overhang_id=target.id,
            connection_type=body.connection_type, direct_variant=variant,
            nanoparticle_attach=attaches[0], target_attach=attaches[1])
        candidate = candidate.copy_with(nanoparticle_connection_versions=[*candidate.nanoparticle_connection_versions, current])
    elif isinstance(body, PatchRequest) and body.name is not None:
        candidate = candidate.copy_with(nanoparticle_connection_versions=[
            item.model_copy(update={"name": body.name}) if item.id == current.id else item
            for item in candidate.nanoparticle_connection_versions])
    try:
        candidate = set_version_applied(candidate, body.version_id, applying,
            duplex_id=body.duplex_id if applying else None,
            duplex_created_at=body.duplex_created_at if applying else None,
            identity_seed=body.history_seed if applying else None)
    except (HTTPException, ConnectionApplicationError) as error:
        pending._fail(str(error.detail), "overhang", body.overhang_id, "overhang_id")
    if isinstance(body, DeleteRequest):
        candidate = candidate.copy_with(nanoparticle_connection_versions=[
            item for item in candidate.nanoparticle_connection_versions if item.id != body.version_id])
    return candidate
