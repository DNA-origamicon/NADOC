"""Versioned duplex definitions shared by HTTP authoring and native replay.

Registers, attachment choices and stable identities are inputs. Relocation and
restoration snapshots are produced by the existing molecular builders only.
"""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from backend.core.feature_identity import identity_factory
from backend.core.models import Duplex
from backend.core.part_command_errors import ReferenceResolutionError


KINDS = frozenset({"duplex-create", "duplex-connect", "duplex-patch", "duplex-delete", "duplex-sync-bindings", "duplex-relax"})
_Id = Annotated[str, Field(min_length=1, max_length=256, strict=True)]
_Bp = Annotated[StrictInt, Field(ge=-1_000_000, le=1_000_000)]
_Bindings = Annotated[list[_Id], Field(max_length=128)]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DuplexEndBody(_Body):
    overhang_id: _Id
    start_bp: _Bp
    end_bp: _Bp

    @model_validator(mode="after")
    def bounded_window(self):
        if abs(self.end_bp - self.start_bp) >= 50_000:
            raise ValueError("Duplex register exceeds the supported nucleotide budget")
        return self


class CreateDuplexBody(_Body):
    left: DuplexEndBody
    right: DuplexEndBody
    driver: Literal["left", "right"] = "left"
    bound: StrictBool = False
    binding_mode: Literal["duplex", "toehold"] = "duplex"
    allow_n_wildcard: StrictBool = True
    connection_type: Annotated[str, Field(max_length=256, strict=True)] | None = None


class ConnectDuplexBody(_Body):
    overhang_a_id: _Id
    overhang_a_attach: Literal["root", "free_end"] = "free_end"
    overhang_b_id: _Id
    overhang_b_attach: Literal["root", "free_end"] = "root"
    driver: Literal["left", "right"] | None = None
    allow_n_wildcard: StrictBool = True


class PatchDuplexBody(_Body):
    left: DuplexEndBody | None = None
    right: DuplexEndBody | None = None
    driver: Literal["left", "right"] | None = None
    bound: StrictBool | None = None
    name: Annotated[str, Field(max_length=256, strict=True)] | None = None

    @model_validator(mode="after")
    def meaningful_patch(self):
        for field in ("driver", "bound", "name"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        if self.name is not None and not self.name.strip():
            raise ValueError("name must be non-empty")
        return self


class _Versioned(_Body):
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(default=1, alias="_proof_version")
    history_seed: _Id

    @model_validator(mode="after")
    def identity_namespace(self):
        UUID(self.history_seed)
        return self


class _Native(_Versioned):
    duplex_id: _Id


class CreateRequest(CreateDuplexBody, _Native):
    created_at: float = Field(ge=0, allow_inf_nan=False)


class ConnectRequest(ConnectDuplexBody, _Native):
    created_at: float = Field(ge=0, allow_inf_nan=False)
    binding_ids: _Bindings


class PatchRequest(PatchDuplexBody, _Native):
    binding_ids: _Bindings | None = None

    @model_validator(mode="after")
    def driver_dependencies(self):
        if ("driver" in self.model_fields_set) != (self.binding_ids is not None):
            raise ValueError("Only driver edits require a selected binding list")
        return self


class DeleteRequest(_Native):
    pass


class SyncRequest(_Versioned):
    binding_ids: _Bindings
    duplex_ids: _Bindings
    created_at: list[Annotated[float, Field(ge=0, allow_inf_nan=False)]] = Field(max_length=128)

    @model_validator(mode="after")
    def aligned_identities(self):
        if not len(self.binding_ids) == len(self.duplex_ids) == len(self.created_at):
            raise ValueError("Sync binding, duplex identity and creation-time lists must align")
        if len(set(self.binding_ids)) != len(self.binding_ids) or len(set(self.duplex_ids)) != len(self.duplex_ids):
            raise ValueError("Sync binding and duplex identities must be unique")
        return self


def parse_command(kind, params):
    if kind == "duplex-relax":
        from backend.core.part_duplex_relax_contract import parse_command as parse_relax
        return parse_relax(params)
    model = {"duplex-create": CreateRequest, "duplex-connect": ConnectRequest,
             "duplex-patch": PatchRequest, "duplex-delete": DeleteRequest,
             "duplex-sync-bindings": SyncRequest}.get(kind)
    if model is None:
        raise NotImplementedError(kind)
    return model.model_validate(params)


class DuplexReferenceError(ReferenceResolutionError):
    def __init__(self, detail, kind, identity, path, *, missing=False, status=422):
        super().__init__(detail, code="missing_reference" if missing else "invalid_selection",
                         references=[{"kind": kind, "identity": identity, "parameter_path": path}])
        self.http_status = 404 if missing else status


def _resolve(records, identity, kind, path):
    matches = [item for item in records if item.id == identity]
    if len(matches) != 1:
        raise DuplexReferenceError(f"{kind} {identity!r} is missing or ambiguous", kind,
                                   identity, path, missing=not matches, status=409)
    return matches[0]


def find_duplex(design, identity):
    return _resolve(design.duplexes, identity, "duplex", ["duplex_id"])


def _domain(design, identity, path):
    overhang = _resolve(design.overhangs, identity, "overhang", path)
    matches = [(strand, domain) for strand in design.strands for domain in strand.domains
               if domain.overhang_id == identity]
    if len(matches) != 1:
        raise DuplexReferenceError(f"Overhang {identity!r} has no unique backing domain",
                                   "overhang", identity, path, missing=not matches)
    strand, domain = matches[0]
    if strand.id != overhang.strand_id or domain.helix_id != overhang.helix_id:
        raise DuplexReferenceError("Overhang ownership does not match its backing domain",
                                   "overhang", identity, path)
    _resolve(design.strands, strand.id, "strand", path)
    return domain


def validate_placement(design, duplex, *, ignore_id=None, check_wc=True):
    from backend.core.duplex import duplex_wc_ok

    for side in ("left", "right"):
        end = getattr(duplex, side)
        domain = _domain(design, end.overhang_id, [side, "overhang_id"])
        lo, hi = sorted((end.start_bp, end.end_bp))
        if lo < min(domain.start_bp, domain.end_bp) or hi > max(domain.start_bp, domain.end_bp):
            raise HTTPException(422, detail=f"{side} interval is outside its overhang backing domain")
        for other in design.duplexes:
            if other.id == ignore_id:
                continue
            for claimed in (other.left, other.right):
                a, b = sorted((claimed.start_bp, claimed.end_bp))
                if claimed.overhang_id == end.overhang_id and max(lo, a) <= min(hi, b):
                    raise HTTPException(409, detail=f"Bases on {end.overhang_id} are already paired by another duplex")
    if not check_wc:
        return
    ok, reason = duplex_wc_ok(design, duplex)
    if not ok:
        raise HTTPException(422, detail=f"duplex register is not complementary: {reason}")


def _pair_bindings(design, left, right):
    pair = {left, right}
    return [item for item in design.overhang_bindings
            if {item.overhang_a_id, item.overhang_b_id} == pair]


def _bindings(design, identities, left, right):
    selected = [_resolve(design.overhang_bindings, identity, "overhang_binding", ["binding_ids", i])
                for i, identity in enumerate(identities)]
    if len(set(identities)) != len(identities) or identities != [item.id for item in _pair_bindings(design, left, right)]:
        raise DuplexReferenceError("Selected backing bindings no longer match the duplex pair",
                                   "overhang", left, ["binding_ids"])
    return selected


def _geometry_references(design, identities):
    for side, identity in identities:
        domain = _domain(design, identity, [side])
        _resolve(design.helices, domain.helix_id, "helix", [side])


def _fresh(records, identity, kind, *, path=None):
    if any(item.id == identity for item in records):
        raise DuplexReferenceError(f"{kind} output identity already exists", kind,
                                   identity, path or ["duplex_id"], status=409)


def _patched(current, body):
    values = body.model_dump(mode="json", exclude_unset=True,
                             include={"left", "right", "driver", "bound", "name"})
    values = {key: value for key, value in values.items() if key not in {"left", "right"} or value is not None}
    if "name" in values:
        values["name"] = values["name"].strip()
    return Duplex.model_validate({**current.model_dump(mode="json"), **values})


def _track_registers(before, after, identities, *, exclude_id=None):
    """Preserve authored nucleotide offsets through an identity-preserving move.

    This follows exact overhang/strand/domain correspondence; it never searches
    nearby geometry or chooses a replacement when an input has disappeared.
    """
    from backend.core.duplex import bp_to_offset, offset_to_bp

    identities = set(identities) & {
        end.overhang_id for edge in after.duplexes if edge.id != exclude_id
        for end in (edge.left, edge.right)
    }
    correspondence = {}
    for identity in sorted(identities):
        path = ["driver"]
        old = _domain(before, identity, path)
        new = _domain(after, identity, path)
        if old == new:
            continue
        old_owner = [(strand.id, i) for strand in before.strands for i, domain in enumerate(strand.domains)
                     if domain.overhang_id == identity]
        new_owner = [(strand.id, i) for strand in after.strands for i, domain in enumerate(strand.domains)
                     if domain.overhang_id == identity]
        ignored = {"helix_id", "start_bp", "end_bp", "direction"}
        if (old_owner != new_owner or abs(old.end_bp - old.start_bp) != abs(new.end_bp - new.start_bp)
                or old.model_dump(exclude=ignored) != new.model_dump(exclude=ignored)):
            raise DuplexReferenceError("Relocation cannot preserve the authored nucleotide selection",
                                       "overhang", identity, path)
        correspondence[identity] = (old, new)
    edges = []
    for edge in after.duplexes:
        changes = {}
        for side in ("left", "right"):
            end = getattr(edge, side)
            if edge.id == exclude_id or end.overhang_id not in correspondence:
                continue
            old, new = correspondence[end.overhang_id]
            a, b = bp_to_offset(old, end.start_bp), bp_to_offset(old, end.end_bp)
            if not 0 <= a <= b <= abs(old.end_bp - old.start_bp):
                raise DuplexReferenceError("Duplex register does not resolve to an ordered nucleotide selection",
                                           "duplex", edge.id, [side])
            changes[side] = end.model_copy(update={
                "start_bp": offset_to_bp(new, a), "end_bp": offset_to_bp(new, b)})
        edges.append(edge.model_copy(update=changes) if changes else edge)
    return after.copy_with(duplexes=edges)


def prepare_command(kind, design, values):
    """Capture backing selection inside the route's publication transaction."""
    if kind == "duplex-relax":
        from backend.core.part_duplex_relax_contract import prepare_command as prepare_relax
        return prepare_relax(design, values)
    values = dict(values)
    if kind == "duplex-sync-bindings":
        existing = {frozenset((edge.left.overhang_id, edge.right.overhang_id)) for edge in design.duplexes}
        selected = []
        for binding in design.overhang_bindings:
            pair = frozenset((binding.overhang_a_id, binding.overhang_b_id))
            if pair not in existing:
                selected.append(binding)
                existing.add(pair)
        identifier = identity_factory(values["history_seed"])
        values.update(binding_ids=[binding.id for binding in selected],
            duplex_ids=[identifier("duplex-sync", [str(i)]) for i in range(len(selected))],
            created_at=[binding.created_at for binding in selected])
        return values
    if kind == "duplex-connect":
        left, right = values["overhang_a_id"], values["overhang_b_id"]
    elif kind == "duplex-patch" and "driver" in values:
        body = PatchDuplexBody.model_validate({key: value for key, value in values.items()
            if key in PatchDuplexBody.model_fields})
        target = _patched(find_duplex(design, values["duplex_id"]), body)
        left, right = target.left.overhang_id, target.right.overhang_id
    else:
        return values
    values["binding_ids"] = [item.id for item in _pair_bindings(design, left, right)]
    return values


def create(design, params):
    from backend.core.duplex import smallest_unused_duplex_name

    body = CreateRequest.model_validate(params)
    _fresh(design.duplexes, body.duplex_id, "duplex")
    duplex = Duplex(id=body.duplex_id, created_at=body.created_at,
        name=smallest_unused_duplex_name(design), **body.model_dump(mode="json",
            include=set(CreateDuplexBody.model_fields)))
    validate_placement(design, duplex)
    return design.copy_with(duplexes=[*design.duplexes, duplex])


def connect(design, params):
    from backend.core.duplex import connect_register, longest_driver, relocate_duplex, smallest_unused_duplex_name

    body = ConnectRequest.model_validate(params)
    _fresh(design.duplexes, body.duplex_id, "duplex")
    pair = {body.overhang_a_id, body.overhang_b_id}
    if any({item.left.overhang_id, item.right.overhang_id} == pair for item in design.duplexes):
        raise HTTPException(409, detail="These overhangs are already connected by a duplex")
    for field in ("overhang_a_id", "overhang_b_id"):
        _domain(design, getattr(body, field), [field])
    try:
        left, right = connect_register(design, body.overhang_a_id, body.overhang_a_attach,
                                       body.overhang_b_id, body.overhang_b_attach)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    for end in (left, right):
        DuplexEndBody.model_validate(end.model_dump(mode="json"))
    duplex = Duplex(id=body.duplex_id, created_at=body.created_at,
        name=smallest_unused_duplex_name(design), left=left, right=right,
        driver=body.driver or longest_driver(design, left, right), allow_n_wildcard=body.allow_n_wildcard)
    validate_placement(design, duplex)
    linked = _bindings(design, body.binding_ids, left.overhang_id, right.overhang_id)
    updated = design.copy_with(duplexes=[*design.duplexes, duplex])
    if linked:
        return updated  # Existing bindings own relocation, including unbound bindings.
    _geometry_references(design, [("overhang_a_id", body.overhang_a_id), ("overhang_b_id", body.overhang_b_id)])
    identifier = identity_factory(body.history_seed)
    _fresh(design.forced_ligations, identifier("duplex-ligation", [duplex.id]), "forced_ligation")
    _fresh(design.cluster_transforms, identifier("duplex-cluster", [duplex.id]), "cluster")
    before_relocation = updated
    updated = relocate_duplex(updated, duplex, identity_seed=body.history_seed)
    updated = _track_registers(before_relocation, updated, pair, exclude_id=duplex.id)
    # The existing relocation moves the driven domain into the driver's bp
    # frame. Store its live register, as the nanoparticle Apply path does;
    # retaining the old coordinates can produce an out-of-domain saved edge.
    left, right = connect_register(updated, body.overhang_a_id, body.overhang_a_attach,
                                   body.overhang_b_id, body.overhang_b_attach)
    live = find_duplex(updated, duplex.id).model_copy(update={"left": left, "right": right})
    updated = updated.copy_with(duplexes=[live if item.id == live.id else item for item in updated.duplexes])
    for edge in updated.duplexes:
        if {edge.left.overhang_id, edge.right.overhang_id} & pair:
            validate_placement(updated, edge, ignore_id=edge.id)
    return updated


def patch(design, params):
    from backend.core.binding_relax import apply_bind_topology, compute_bind_topology, revert_bind_topology
    from backend.core.binding_drivers import apply_driver_to_joint

    body = PatchRequest.model_validate(params)
    current = find_duplex(design, body.duplex_id)
    candidate = _patched(current, body)
    if body.left is not None or body.right is not None:
        validate_placement(design, candidate, ignore_id=current.id)
    updated = design.copy_with(duplexes=[candidate if item.id == current.id else item for item in design.duplexes])
    if body.binding_ids is None:
        return updated
    linked = _bindings(design, body.binding_ids, candidate.left.overhang_id, candidate.right.overhang_id)
    driver = candidate.left.overhang_id if candidate.driver == "left" else candidate.right.overhang_id
    driven = candidate.right.overhang_id if candidate.driver == "left" else candidate.left.overhang_id
    updated = updated.copy_with(overhang_bindings=[item.model_copy(update={
        "driver_oh_id": driver, "driven_oh_id": driven}) if item.id in body.binding_ids else item
        for item in updated.overhang_bindings])
    if not linked or not linked[0].bound or not linked[0].prior_driven_topology:
        return updated  # Preserve metadata-only behavior, including bindingless driver edits.
    binding = _resolve(updated.overhang_bindings, linked[0].id, "overhang_binding", ["binding_ids", 0])
    if binding.target_joint_id:
        _resolve(updated.cluster_joints, binding.target_joint_id, "cluster_joint", ["binding_ids", 0])
    before_relocation = updated
    reverted = revert_bind_topology(updated, binding.prior_driven_topology)
    _geometry_references(reverted, [("driver", driver), ("driver", driven)])
    ligation_id = identity_factory(body.history_seed)("binding-driver-ligation", [binding.id])
    _fresh(reverted.forced_ligations, ligation_id, "forced_ligation")
    topology = compute_bind_topology(reverted, binding,
        driver_side="a" if driver == binding.overhang_a_id else "b", forced_ligation_id=ligation_id)
    updated = apply_bind_topology(reverted, topology)
    updated = updated.copy_with(overhang_bindings=[item.model_copy(update={
        "prior_driven_topology": topology.snapshot}) if item.id == binding.id else item
        for item in updated.overhang_bindings])
    updated = apply_driver_to_joint(updated, binding.target_joint_id) if binding.target_joint_id else updated
    updated = _track_registers(before_relocation, updated, {driver, driven})
    for edge in updated.duplexes:
        if {edge.left.overhang_id, edge.right.overhang_id} & {driver, driven}:
            validate_placement(updated, edge, ignore_id=edge.id)
    return updated


def delete(design, params):
    body = DeleteRequest.model_validate(params)
    find_duplex(design, body.duplex_id)
    # Existing Delete removes the edge only; unbind/restoration is a distinct action.
    return design.copy_with(duplexes=[item for item in design.duplexes if item.id != body.duplex_id])


def sync(design, params):
    from backend.core.duplex import smallest_unused_duplex_name, synthesize_duplex_from_binding

    body = SyncRequest.model_validate(params)
    subdomains = {}
    for overhang in design.overhangs:
        for subdomain in overhang.sub_domains:
            subdomains.setdefault(subdomain.id, []).append((overhang.id, subdomain))
    updated = design
    existing = {frozenset((edge.left.overhang_id, edge.right.overhang_id)) for edge in design.duplexes}
    for index, (binding_id, duplex_id, created_at) in enumerate(zip(body.binding_ids, body.duplex_ids, body.created_at)):
        path = ["binding_ids", index]
        binding = _resolve(design.overhang_bindings, binding_id, "overhang_binding", path)
        pair = frozenset((binding.overhang_a_id, binding.overhang_b_id))
        if pair in existing:
            raise DuplexReferenceError("Selected binding pair already has a duplex", "overhang_binding",
                                       binding_id, path, status=409)
        selected = {}
        for side in ("a", "b"):
            identity = getattr(binding, f"sub_domain_{side}_id")
            matches = subdomains.get(identity, [])
            if len(matches) != 1:
                raise DuplexReferenceError("Selected binding subdomain is missing or ambiguous", "subdomain",
                                           identity, path, missing=not matches)
            owner, subdomain = matches[0]
            if owner != getattr(binding, f"overhang_{side}_id"):
                raise DuplexReferenceError("Selected binding subdomain has a different overhang owner",
                                           "subdomain", identity, path)
            _domain(design, owner, path)
            selected[identity] = (owner, subdomain)
        length = min(subdomain.length_bp for _owner, subdomain in selected.values())
        if not 0 < length <= 50_000:
            raise DuplexReferenceError("Selected binding register exceeds the supported nucleotide budget",
                                       "overhang_binding", binding_id, path)
        if binding.target_joint_id:
            _resolve(design.cluster_joints, binding.target_joint_id, "cluster_joint", path)
        _fresh(updated.duplexes, duplex_id, "duplex", path=["duplex_ids", index])
        edge = synthesize_duplex_from_binding(design, binding, duplex_id=duplex_id,
                                              created_at=created_at, subdomain_lookup=selected)
        if edge is None:
            raise DuplexReferenceError("Selected binding has no supported register", "overhang_binding", binding_id, path)
        for end in (edge.left, edge.right):
            DuplexEndBody.model_validate(end.model_dump(mode="json"))
        edge = edge.model_copy(update={"name": smallest_unused_duplex_name(updated)})
        # Migration/sync has always retained mismatches for classification. Keep
        # that policy while enforcing live reference, bounds and occupancy rules.
        validate_placement(updated, edge, check_wc=False)
        updated = updated.copy_with(duplexes=[*updated.duplexes, edge])
        existing.add(pair)
    return updated


def relax(design, params):
    """Worker-only adapter around the existing direct relaxation algorithm."""
    from backend.core.part_duplex_relax_contract import (
        AUTHORING, DuplexRelaxContractError, native_source, validate_environment, validate_inputs,
    )
    from backend.core.direct_relax import relax_direct_binding
    from backend.core.part_numerical_runtime import digest

    command = validate_inputs(design, params)
    validate_environment(command)
    source = native_source(design)
    updated, _info = relax_direct_binding(source, command.driver_overhang_id, command.driven_overhang_id,
                                         joint_ids=command.joint_ids)
    validate_environment(command)
    outputs = {"overhangs", "cluster_transforms"}
    if any(getattr(updated, name) != getattr(design, name) for name in AUTHORING - outputs):
        raise DuplexRelaxContractError("Duplex relaxation changed unrelated authoring fields", code="builder_output_mismatch")
    for name in outputs:
        if sorted(item.id for item in getattr(updated, name)) != sorted(item.id for item in getattr(design, name)):
            raise DuplexRelaxContractError("Duplex relaxation changed output identities", code="builder_output_mismatch")
    try:
        digest(updated.model_dump(mode="json", include=outputs))
    except (TypeError, ValueError) as exc:
        raise DuplexRelaxContractError("Duplex relaxation produced non-finite pose data", code="builder_output_mismatch") from exc
    # The native solver emits incidental pose history. Preserve the input history
    # and let the feature transaction publish one versioned operation instead.
    return design.copy_with(**{name: getattr(updated, name) for name in outputs})


def build(kind, design, params):
    from backend.core.cluster_autodetect import with_default_cluster

    builder = {"duplex-create": create, "duplex-connect": connect,
               "duplex-patch": patch, "duplex-delete": delete, "duplex-sync-bindings": sync,
               "duplex-relax": relax}.get(kind)
    if builder is None:
        raise NotImplementedError(kind)
    updated = builder(design, params)
    # Response adapters historically add this placement umbrella silently.
    # Derive it inside the command so sparse sources replay identically.
    return with_default_cluster(updated, identity_factory=identity_factory(params["history_seed"]))
