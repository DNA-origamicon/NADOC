"""Bounded, source-free thiol graft recipes with explicit removal ownership.

The native nanoparticle builder remains the geometry/coverage authority. These
commands only admit inputs, assign stable identities, and protect consumers of
the radial handles being replaced or removed.
"""

from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

from backend.core.cluster_autodetect import with_default_cluster
from backend.core.conjugate_strands import assign_conjugate_group, groups_without_strands
from backend.core.feature_identity import identity_factory
from backend.core.models import OverhangSpec
from backend.core.nanoparticle import build_thiol_conjugation
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_scope_references import COLLECTIONS, identity_index, referenced_resources


KINDS = frozenset({"nanoparticle-conjugate", "nanoparticle-conjugation-delete"})
MAX_HANDLES = 128
MAX_BASES = 50_000
_Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias="_proof_version")
    thiol_version: StrictInt = Field(ge=1, le=1)
    history_seed: _Id
    nanoparticle_id: _Id
    replace_conjugation_ids: list[_Id] = Field(max_length=MAX_HANDLES)

    @field_validator("history_seed")
    @classmethod
    def canonical_seed(cls, value):
        if str(UUID(value)) != value:
            raise ValueError("history_seed must be a canonical UUID")
        return value

    @field_validator("replace_conjugation_ids")
    @classmethod
    def unique_owned(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("replace_conjugation_ids must be unique")
        return value


class CreateRequest(_Input):
    conjugation_id: _Id
    scheme: Literal["direct_thiol", "alkyl_thiol", "peg_thiol", "peg_backfill"]
    sequence: Annotated[str, Field(strict=True, min_length=1, max_length=500)]
    count: Annotated[StrictInt, Field(ge=1, le=MAX_HANDLES)]
    attach_end: Literal["5p", "3p"] = "5p"
    spacer_nm: Annotated[float, Field(strict=True, ge=0, le=100, allow_inf_nan=False)] | None = None
    seed: Annotated[StrictInt, Field(ge=-(2**63), le=2**63 - 1)] = 1

    @field_validator("sequence")
    @classmethod
    def dna(cls, value):
        value = value.strip().upper()
        if not value or any(base not in "ACGTN" for base in value):
            raise ValueError("sequence must contain one or more A/C/G/T/N bases")
        return value

    @model_validator(mode="after")
    def bounded_work(self):
        if self.count * len(self.sequence) > MAX_BASES:
            raise ValueError("Native thiol grafts admit at most 50,000 generated nucleotides")
        return self


class DeleteRequest(_Input):
    pass


def parse_command(kind, params):
    model = {"nanoparticle-conjugate": CreateRequest,
             "nanoparticle-conjugation-delete": DeleteRequest}.get(kind)
    if model is None:
        raise ValueError("Unsupported native thiol command")
    return model.model_validate(params)


def resources(kind, params):
    parse_command(kind, params)
    return {"sources": (), "imports": False}


def _fail(detail, kind, identity, path, *, missing=False):
    raise ReferenceResolutionError(detail, code="missing_reference" if missing else "invalid_selection",
        references=[{"kind": kind, "identity": identity, "parameter_path": path}])


def _target(design, identity):
    matches = [item for item in design.nanoparticles if item.id == identity]
    if len(matches) != 1:
        _fail("Nanoparticle target is missing or ambiguous", "nanoparticle", identity,
              ["nanoparticle_id"], missing=not matches)
    return matches[0]


def _source_free(particle):
    return (particle.kind == "gold_nanosphere" and particle.quantum_dot is None
            and particle.coating is None and not particle.biotin_dna)


def native_route_eligible(design, identity, *, count=0, sequence="", seed=1):
    """Scope admission; locked build still rejects stale or invalid ownership.

    Existing larger/asset-backed routes remain explicitly unverified. Reference
    errors within this bounded scope never trigger a fallback after evaluation.
    """
    matches = [item for item in design.nanoparticles if item.id == identity]
    if len(matches) != 1:
        return True  # Reference errors must reach the locked native builder.
    particle = matches[0]
    owned = [item for item in design.nanoparticle_conjugations if item.nanoparticle_id == identity]
    bounded = (_source_free(particle) and count <= MAX_HANDLES and count * len(sequence.strip()) <= MAX_BASES
            and -(2**63) <= seed < 2**63
            and sum(len(item.surface_strands) for item in owned) <= MAX_HANDLES
            and not any(item.nanoparticle_id == identity for item in design.nanoparticle_connection_versions))
    if not bounded:
        return False
    try:
        # Read only reference descriptors, never geometry, asset bytes or
        # recovery snapshots. Unsupported opaque ownership keeps its existing
        # unverified live route; malformed supported references still reach the
        # strict builder inside the transaction and cannot fall back afterward.
        for field in COLLECTIONS:
            for item in getattr(design, field):
                referenced_resources(item)
    except NotImplementedError:
        return False
    except ValueError:
        return True
    return True


def _owned(design, command, index):
    """Resolve the entire declared radial child graph before deleting anything."""
    owned = [item for item in design.nanoparticle_conjugations
             if item.nanoparticle_id == command.nanoparticle_id]
    expected = set(command.replace_conjugation_ids)
    actual = {item.id for item in owned}
    if expected != actual:
        identity = sorted(expected - actual or actual - expected)[0]
        path = (["replace_conjugation_ids", command.replace_conjugation_ids.index(identity)]
                if identity in expected else ["replace_conjugation_ids"])
        _fail("Thiol replacement must select exactly the particle's current conjugations",
              "nanoparticle_conjugation", identity, path, missing=identity not in actual)
    if sum(len(item.surface_strands) for item in owned) > MAX_HANDLES:
        raise CommandContractError("Native thiol removal exceeds its 128-handle admission", code="unsupported_thiol_source")
    removed = {("nanoparticle_conjugation", item.id) for item in owned}

    def selected(kind, identity, path):
        if identity is None or (kind, identity) not in index:
            _fail("Thiol-owned resource is missing", kind, identity or "", path, missing=True)
        key = (kind, identity)
        if key in removed:
            _fail("Thiol-owned resource is shared between surface records", kind, identity, path)
        removed.add(key)
        return index[key]

    for item in owned:
        path = ["replace_conjugation_ids", command.replace_conjugation_ids.index(item.id)]
        if len(item.surface_strands) != item.requested_count:
            _fail("Thiol surface record count disagrees with its owner", "nanoparticle_conjugation", item.id, path)
        for record in item.surface_strands:
            if record.bound_overhang_id is not None:
                _fail("Unbind nanoparticle strands before replacing or deleting conjugation",
                      "overhang", record.bound_overhang_id, path)
            helix = selected("helix", record.helix_id, path)
            strand = selected("strand", record.strand_id, path)
            spec = selected("overhang", record.overhang_id, path)
            try:
                referenced_resources(spec)
            except NotImplementedError as error:
                raise CommandContractError(f"Thiol endpoint ownership cannot be resolved: {error}",
                                           code="unsupported_thiol_source") from error
            if (not helix.id.startswith("__np__") or len(strand.domains) != 1
                    or spec.helix_id != helix.id or spec.strand_id != strand.id
                    or not spec.auxiliary_endpoint or spec.parent_overhang_id is not None
                    or strand.is_reference):
                _fail("Thiol surface ownership is inconsistent", "nanoparticle_conjugation", item.id, path)
            domain = strand.domains[0]
            if (domain.helix_id != helix.id or domain.overhang_id != spec.id or domain.binds_overhang_id
                    or sorted((domain.start_bp, domain.end_bp)) != [helix.bp_start, helix.bp_start + helix.length_bp - 1]):
                _fail("Thiol surface backing domain is inconsistent", "strand", strand.id, path)
            removed.update(("sub_domain", sub.id) for sub in spec.sub_domains)
    return removed


def _incoming(design, removed, outputs):
    """One typed reference pass; no geometry construction or snapshot decoding."""
    try:
        for field, kind in COLLECTIONS.items():
            for item in getattr(design, field):
                if (kind, item.id) in removed:
                    continue
                refs = referenced_resources(item)
                retained_collision = refs & outputs
                if retained_collision:
                    key = sorted(retained_collision)[0]
                    _fail("Thiol output identity already has an incoming reference", *key, ["history_seed"])
                touched = refs & removed
                if not touched:
                    continue
                if field == "staple_groups":
                    continue  # Existing group helper removes only the owned members.
                if (field == "cluster_transforms" and item.is_default and not item.domain_ids
                        and item.parent_cluster_id is None and item.overhang_duplex_driver_id is None):
                    continue  # Prune whole-helix default membership; preserve its pose.
                key = sorted(touched)[0]
                _fail(f"Thiol resource is still used by {kind} {item.id}", *key, ["replace_conjugation_ids"])
    except NotImplementedError as error:
        raise CommandContractError(f"Thiol ownership cannot be resolved: {error}", code="unsupported_thiol_source") from error


def build(kind, design, params):
    command = parse_command(kind, params)
    particle = _target(design, command.nanoparticle_id)
    if not _source_free(particle):
        _fail("Native thiol grafts require an uncoated, source-free gold particle",
              "nanoparticle", particle.id, ["nanoparticle_id"])
    if any(item.nanoparticle_id == particle.id for item in design.nanoparticle_connection_versions):
        _fail("Remove nanoparticle connection ownership before replacing or deleting conjugation",
              "nanoparticle", particle.id, ["nanoparticle_id"])
    index, _ = identity_index(design)
    removed = _owned(design, command, index)
    strand_ids = {identity for resource, identity in removed if resource == "strand"}
    helix_ids = {identity for resource, identity in removed if resource == "helix"}
    overhang_ids = {identity for resource, identity in removed if resource == "overhang"}
    pruned_groups = {item.id: item for item in groups_without_strands(design, strand_ids)}
    retained_groups = [pruned_groups[item.id] if set(item.strand_ids) & strand_ids else item
                       for item in design.staple_groups
                       if not set(item.strand_ids) & strand_ids or item.id in pruned_groups]
    candidate = design.copy_with(
        helices=[item for item in design.helices if item.id not in helix_ids],
        strands=[item for item in design.strands if item.id not in strand_ids],
        overhangs=[item for item in design.overhangs if item.id not in overhang_ids],
        nanoparticle_conjugations=[item for item in design.nanoparticle_conjugations
                                  if ("nanoparticle_conjugation", item.id) not in removed],
        staple_groups=retained_groups,
        cluster_transforms=[item.model_copy(update={"helix_ids": [identity for identity in item.helix_ids
                                                               if identity not in helix_ids]})
                            if set(item.helix_ids) & helix_ids else item for item in design.cluster_transforms],
    )
    outputs = set()
    if kind == "nanoparticle-conjugate":
        factory = identity_factory(command.history_seed)
        conjugation, helices, strands = build_thiol_conjugation(
            particle, scheme=command.scheme, sequence=command.sequence, count=command.count,
            attach_end=command.attach_end, spacer_nm=command.spacer_nm, seed=command.seed,
            identity_factory=factory, conjugation_id=command.conjugation_id)
        strands, group = assign_conjugate_group(candidate, strands, prefix="NP", fallback="NP",
                                               group_id="conjugate-" + factory("thiol-group", []))
        overhangs = [OverhangSpec(id=record.overhang_id, helix_id=record.helix_id, strand_id=strand.id,
                                sequence=strand.sequence, label=strand.name, auxiliary_endpoint=True)
                    for record, strand in zip(conjugation.surface_strands, strands)]
        outputs = {("nanoparticle_conjugation", conjugation.id), ("staple_group", group.id)}
        outputs.update(("helix", item.id) for item in helices)
        outputs.update(("strand", item.id) for item in strands)
        outputs.update(("overhang", item.id) for item in overhangs)
        outputs.update(("sub_domain", sub.id) for item in overhangs for sub in item.sub_domains)
        # Replacement gets a new feature namespace. Replaying the same feature
        # never consumes its own prior output; it starts from its input prefix.
        for key in sorted(outputs & index.keys()):
            _fail("Thiol output identity already exists", *key, ["history_seed"])
        candidate = candidate.copy_with(helices=[*candidate.helices, *helices], strands=[*candidate.strands, *strands],
            overhangs=[*candidate.overhangs, *overhangs], nanoparticle_conjugations=[*candidate.nanoparticle_conjugations, conjugation],
            staple_groups=[*retained_groups, group])
        candidate = with_default_cluster(candidate, identity_factory=lambda *_: factory("thiol-default-cluster", []))
        outputs.update(("cluster", item.id) for item in candidate.cluster_transforms
                       if ("cluster", item.id) not in index)
    _incoming(design, removed, outputs)
    return candidate


def record(kind, label, inputs):
    """Resolve replacement ownership and geometry together under the state lock."""
    from backend.api import state

    params = {**inputs, "_proof_version": 1, "thiol_version": 1, "history_seed": str(uuid4())}
    if kind == "nanoparticle-conjugate":
        params["conjugation_id"] = str(uuid4())

    def native(design):
        params["replace_conjugation_ids"] = [item.id for item in design.nanoparticle_conjugations
                                              if item.nanoparticle_id == params["nanoparticle_id"]]
        try:
            return build(kind, design, params)
        except ReferenceResolutionError as error:
            raise HTTPException(404 if error.code == "missing_reference" else 422, detail=error.as_issue()) from error
        except CommandContractError as error:
            raise HTTPException(422, detail=error.as_issue()) from error
        except ValueError as error:
            raise HTTPException(400, detail=str(error)) from error

    return state.mutate_with_feature_log(kind, label, params, native)
