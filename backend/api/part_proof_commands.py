"""Audited versioned part replay contracts, separate from recovery dispatch."""
from backend.api.part_photoproduct_commands import KINDS as PHOTOPRODUCT_KINDS
from backend.api.part_refinement_commands import KINDS as REFINEMENT_KINDS
from backend.api.part_linker_commands import KINDS as LINKER_KINDS
from backend.api.part_crossover_moves import KINDS as MOVE_KINDS
from backend.api.part_cell_commands import KINDS as CELL_KINDS
from backend.api.part_annotation_commands import KINDS as ANNOTATION_KINDS
from backend.api.part_extension_commands import KINDS as EXTENSION_KINDS, UPSERT_VERSION as EXTENSION_UPSERT_VERSION
from backend.api.part_ligation_commands import KINDS as LIGATION_KINDS
from backend.api.part_auto_commands import KINDS as AUTO_KINDS
from backend.core.part_overlay_commands import GROUP_CREATE_VERSION, KINDS as OVERLAY_KINDS, proof_version_supported
from backend.core.part_dependencies import Dependencies, Resource
from backend.api.part_native_commands import LOOP_COMMANDS, SEQUENCE_COMMANDS, PATTERN_COMMANDS
from backend.api.part_structural_commands import KINDS as STRUCTURAL_KINDS
from backend.api.part_branch_commands import KINDS as BRANCH_KINDS
from backend.api.part_path_commands import KINDS as PATH_KINDS
from backend.api.part_section_commands import KINDS as SECTION_KINDS
from backend.api.part_connectivity_commands import KINDS as CONNECTIVITY_KINDS
from backend.api.part_joined_path_commands import KINDS as JOINED_PATH_KINDS
from backend.api.part_nanoparticle_commands import KINDS as NANOPARTICLE_KINDS
from backend.api.part_duplex_commands import KINDS as DUPLEX_KINDS
from backend.api.part_protein_commands import KINDS as PROTEIN_KINDS
from backend.api.part_protein_conjugation_commands import KINDS as PROTEIN_CONJUGATION_KINDS
from backend.api.part_thiol_commands import KINDS as THIOL_KINDS
from backend.api.part_aptamer_commands import KINDS as APTAMER_KINDS
from backend.api.part_element_copy_commands import KINDS as ELEMENT_COPY_KINDS
from backend.api.part_cadnano_commands import KINDS as CADNANO_KINDS
from backend.api.part_nanoparticle_connection_commands import KINDS as NP_CONNECTION_KINDS
from backend.api.part_connection_version_commands import is_pending_action
from backend.api.part_connection_application_commands import ACTION as CONNECTION_APPLY_ACTION
from backend.api.part_connection_composition_commands import ACTION as CONNECTION_COMPOSE_ACTION
from backend.api.part_connection_direct_commands import ACTION as CONNECTION_DIRECT_ACTION
from backend.api.part_connection_direct_composition import ACTION as CONNECTION_DIRECT_COMPOSE_ACTION
from backend.api.part_connection_disconnect import ACTION as CONNECTION_DISCONNECT_ACTION
from backend.core.part_group_organization import KINDS as GROUP_ORGANIZATION_KINDS


TOPOLOGY_MINOR_KINDS = frozenset({
    "nick", "nick-batch", "strand-end-resize", "domain-shift",
    "strand-delete", "strand-delete-batch", "domain-delete",
    "crossover-place", "crossover-place-batch",
})
EXTRUSION_COMMANDS = frozenset({"extrude-segment", "extrude-continuation", "extrude-deformed-continuation", "circle-segment", "extrude-frame"})
PROOF_SNAPSHOT_KINDS = (
    GROUP_ORGANIZATION_KINDS | NP_CONNECTION_KINDS | CADNANO_KINDS | ELEMENT_COPY_KINDS | APTAMER_KINDS | THIOL_KINDS
    | PROTEIN_CONJUGATION_KINDS | PROTEIN_KINDS | DUPLEX_KINDS | NANOPARTICLE_KINDS
    | JOINED_PATH_KINDS | CONNECTIVITY_KINDS | SECTION_KINDS | PATH_KINDS | BRANCH_KINDS
    | PHOTOPRODUCT_KINDS | REFINEMENT_KINDS | LINKER_KINDS | ANNOTATION_KINDS | AUTO_KINDS
    | EXTRUSION_COMMANDS | SEQUENCE_COMMANDS | PATTERN_COMMANDS | EXTENSION_KINDS
    | frozenset({"photoproduct-relax", "bundle-create", "sweep", "cluster-join", "strand-sequence",
                 "apply-loop-skips", "overhang-extrude", "overhang-sequence", "overhang-bulk", "cluster-paste", "cluster-dissolve", "placement-poses"})
)
PROOF_MINOR_KINDS = MOVE_KINDS | CELL_KINDS | LIGATION_KINDS | TOPOLOGY_MINOR_KINDS | LOOP_COMMANDS | STRUCTURAL_KINDS | frozenset({"joint-place", "joint-update", "joint-delete", "strand-patch"})
PROOF_VERSION = 1
PART_TOPOLOGY = Resource("part", "topology")


def _cluster_op_dependencies(params):
    """Read only bounded command metadata; the saved v1 builder stays unchanged.

    Domains have ordinal addresses within a strand, not stable identities. The
    owning strand plus the topology barrier covers reordering and changes to its
    helix mapping without looking up a Design. Explicit empty lists are writes
    to membership too. Saved pose rows carrying full authored membership are
    therefore conservative barriers even if the user only changed their pose.
    """
    from math import isfinite
    from backend.core.models import ClusterRigidTransform
    from backend.core.part_operation_input import validate_operation_input

    if type(params) is not dict:
        return Dependencies(known=False)
    try:
        validate_operation_input(params)
        if not proof_version_supported("cluster_op", params.get("_proof_version")):
            return Dependencies(known=False)
        identity = params.get("cluster_id")
        if type(identity) is not str or not identity:
            return Dependencies(known=False)
        # Reuse native field coercion, including legacy DomainRef integer input.
        # No source model, model dump, UUID allocation or native builder is used.
        fields = ("translation", "rotation", "pivot", "name", "helix_ids", "domain_ids", "color", "opacity")
        selected = ClusterRigidTransform.model_validate({
            "id": identity, **{field: params[field] for field in fields if field in params}})
        for field, length in (("translation", 3), ("rotation", 4), ("pivot", 3)):
            vector = getattr(selected, field)
            if len(vector) != length or not all(isfinite(value) for value in vector):
                return Dependencies(known=False)
        if (not isfinite(selected.opacity) or any(not hid for hid in selected.helix_ids)
                or any(not ref.strand_id or ref.domain_index < 0 for ref in selected.domain_ids)):
            return Dependencies(known=False)
    except ValueError:
        return Dependencies(known=False)
    cluster = Resource("cluster", identity)
    reads = {cluster}
    membership = "helix_ids" in params or "domain_ids" in params
    if membership:
        reads.add(PART_TOPOLOGY)
        reads.update(Resource("helix", hid) for hid in selected.helix_ids)
        reads.update(Resource("strand", ref.strand_id) for ref in selected.domain_ids)
    return Dependencies(frozenset(reads), frozenset({cluster}), barrier=membership)


def capabilities():
    from backend.core.feature_registry import part_replay_capabilities
    from backend.api.part_recipe_capabilities import editing_capabilities
    kinds = PROOF_MINOR_KINDS | PROOF_SNAPSHOT_KINDS | OVERLAY_KINDS
    return {**part_replay_capabilities(), **editing_capabilities(kinds), "proof_version": PROOF_VERSION,
            "proof_version_overrides": {"cluster_create": {"supported": [1, GROUP_CREATE_VERSION],
                                                            "authoring": GROUP_CREATE_VERSION},
                                        "extension-upsert": {"supported": [1, EXTENSION_UPSERT_VERSION],
                                                             "authoring": EXTENSION_UPSERT_VERSION}},
            "proof_commands": sorted(PROOF_MINOR_KINDS | PROOF_SNAPSHOT_KINDS | OVERLAY_KINDS),
            "group_organization": {"native_version": 1, "public_authoring": False,
                                   "history_container": "snapshot"},
            "proof_root_kinds": ["empty", "import"]}


def dependencies(kind, params):
    from backend.core.part_suppression import KIND, valid_definition
    if kind == KIND:
        return Dependencies(known=valid_definition(params, dependencies))
    from backend.core import part_frozen_topology as frozen
    if frozen.is_frozen(params):
        from backend.core.part_replay_cache import DEFORMATION_INDEPENDENT
        return (Dependencies(frozenset({PART_TOPOLOGY}), frozenset({PART_TOPOLOGY}), barrier=True)
                if kind in DEFORMATION_INDEPENDENT and frozen.valid_params(params) else Dependencies(known=False))
    if type(params) is dict and "_connection_organization" in params:
        from backend.api.part_connection_organization import split
        from backend.core.part_group_organization import ORGANIZATION
        try:
            inputs = split(kind, params)
        except ValueError:
            return Dependencies(known=False)
        inner = dependencies(kind, inputs)
        return Dependencies(inner.reads | {ORGANIZATION}, inner.writes | {ORGANIZATION},
                            known=inner.known, barrier=True, imported_sources=inner.imported_sources)
    if kind in EXTENSION_KINDS:
        from backend.api.part_extension_commands import dependencies as extension_dependencies
        return extension_dependencies(kind, params)
    if kind == "placement-poses":
        from backend.api.part_placement_pose_commands import dependencies as pose_dependencies
        return pose_dependencies(params)
    if kind in GROUP_ORGANIZATION_KINDS:
        from backend.core.part_group_organization import dependencies as organization_dependencies
        # Generated composition has not qualified the distinct namespaces yet.
        # Attribution is presentation metadata, as for the other native commands.
        if type(params) is not dict or "_generated_scope" in params:
            return Dependencies(known=False)
        return organization_dependencies(kind, {key: value for key, value in params.items()
                                               if key != "_generator"})
    if kind == "cluster_op":
        return _cluster_op_dependencies(params)
    if kind == "cluster-dissolve":
        from backend.core.part_group_dissolve import parse_command
        if type(params) is not dict or not 2 <= len(params) <= 3:
            return Dependencies(known=False)
        try:
            selected = parse_command({key: value for key, value in params.items() if key != "_generator"})
        except (ValueError, TypeError, AttributeError):
            return Dependencies(known=False)
        resources = frozenset({PART_TOPOLOGY, *(Resource("cluster", cid) for cid in selected)})
        return Dependencies(resources, resources, barrier=True)
    if not proof_version_supported(kind, params.get("_proof_version")):
        return Dependencies(known=False)
    if "_generated_scope" in params and (kind in NP_CONNECTION_KINDS or (
            kind == "overhang-bulk" and (is_pending_action(params)
                or params.get("action") in (CONNECTION_APPLY_ACTION, CONNECTION_COMPOSE_ACTION, CONNECTION_DIRECT_ACTION, CONNECTION_DIRECT_COMPOSE_ACTION, CONNECTION_DISCONNECT_ACTION))) or (
            kind == "nanoparticle-patch" and "thiol_version" in params
            and params.get("pending_connection_version_ids"))):
        return Dependencies(known=False)  # Compound scoped owner selection is not qualified yet.
    # Composition metadata belongs to the scope executor, not the underlying
    # strict command schema. Preserve source provenance during scoped admission.
    params = {key: value for key, value in params.items()
              if key not in {"_generated_scope", "_generator"}}
    if kind == "overhang-bulk" and params.get("action") == CONNECTION_DISCONNECT_ACTION:
        from backend.api.part_connection_disconnect import dependency_contract
        return dependency_contract(params, topology=PART_TOPOLOGY)
    if kind == "overhang-bulk" and params.get("action") == CONNECTION_DIRECT_COMPOSE_ACTION:
        from backend.api.part_connection_direct_composition import dependency_contract
        return dependency_contract(params, topology=PART_TOPOLOGY)
    if kind == "overhang-bulk" and params.get("action") == CONNECTION_DIRECT_ACTION:
        from backend.api.part_connection_direct_commands import dependency_contract
        return dependency_contract(params, topology=PART_TOPOLOGY)
    if kind == "overhang-bulk" and params.get("action") == CONNECTION_COMPOSE_ACTION:
        from backend.api.part_connection_composition_commands import dependency_contract
        return dependency_contract(params, topology=PART_TOPOLOGY)
    if kind == "overhang-bulk" and params.get("action") == CONNECTION_APPLY_ACTION:
        from backend.api.part_connection_application_commands import dependency_contract
        return dependency_contract(params, topology=PART_TOPOLOGY)
    if kind == "overhang-bulk" and is_pending_action(params):
        from backend.api.part_connection_version_commands import parse_command
        try:
            command = parse_command(params)
        except ValueError:
            return Dependencies(known=False)
        reads = {PART_TOPOLOGY, Resource("overhang", command.overhang_a_id),
                 Resource("overhang", command.overhang_b_id)}
        version = Resource("connection_version", command.version_id)
        if command.action != "connection-version-create":
            reads.add(version)
        affected = {Resource("connection_version", identity)
                    for identity in getattr(command, "affected_version_ids", ())}
        return Dependencies(frozenset(reads | affected), frozenset({PART_TOPOLOGY, version} | affected), barrier=True)
    if kind in NP_CONNECTION_KINDS:
        from backend.api.part_nanoparticle_connection_commands import parse_command
        try:
            command = parse_command(kind, params)
        except ValueError:
            return Dependencies(known=False)
        reads = {PART_TOPOLOGY, Resource("nanoparticle", command.nanoparticle_id),
                 Resource("nanoparticle_conjugation", command.conjugation_id),
                 Resource("strand", command.strand_id), Resource("overhang", command.overhang_id)}
        version = Resource("nanoparticle_connection_version", command.version_id)
        if kind != "nanoparticle-connection-version-create":
            reads.add(version)
        writes = {PART_TOPOLOGY, version}
        if "nanoparticle_application_version" in params:
            reads.add(Resource("overhang", command.handle_overhang_id))
            if command.prior_duplex_id is not None:
                reads.add(Resource("duplex", command.prior_duplex_id))
            reads.update(Resource("nanoparticle_connection_version", identity)
                         for identity in command.conflict_version_ids)
            if getattr(command, "duplex_id", None) is not None:
                writes.add(Resource("duplex", command.duplex_id))
        return Dependencies(frozenset(reads), frozenset(writes), barrier=True)
    if kind == "nanoparticle-patch" and "coating_version" in params:
        from backend.api.part_streptavidin_commands import resources
        try:
            contract = resources(kind, params)
        except ValueError:
            return Dependencies(known=False)
        sources = frozenset(Resource("input_source", source.sha256) for source in contract["sources"])
        particle = Resource("nanoparticle", params["nanoparticle_id"])
        return Dependencies(frozenset({PART_TOPOLOGY, particle}) | sources,
                            frozenset({PART_TOPOLOGY, particle}), barrier=True,
                            imported_sources=sources if contract["imports"] else frozenset())
    if kind in ELEMENT_COPY_KINDS:
        from backend.api.part_element_copy_commands import parse_command
        try:
            command = parse_command(kind, params)
        except ValueError:
            return Dependencies(known=False)
        reads, writes = {PART_TOPOLOGY}, {PART_TOPOLOGY}
        for resource, sources, outputs in (
            ("protein_attachment", command.protein_ids, command.protein_output_ids),
            ("nanoparticle", command.nanoparticle_ids, command.nanoparticle_output_ids),
        ):
            reads.update(Resource(resource, identity) for identity in sources)
            writes.update(Resource(resource, identity) for identity in outputs)
        return Dependencies(frozenset(reads), frozenset(writes), barrier=True)
    if kind in PROTEIN_KINDS | PROTEIN_CONJUGATION_KINDS | THIOL_KINDS | APTAMER_KINDS | CADNANO_KINDS:
        if kind in CADNANO_KINDS:
            from backend.api.part_cadnano_commands import resources
        elif kind in APTAMER_KINDS:
            from backend.api.part_aptamer_commands import resources
        elif kind in THIOL_KINDS:
            from backend.api.part_thiol_commands import resources
        elif kind in PROTEIN_CONJUGATION_KINDS:
            from backend.api.part_protein_conjugation_commands import resources
        else:
            from backend.api.part_protein_commands import resources
        try:
            contract = resources(kind, params)
        except ValueError:
            return Dependencies(known=False)
        sources = frozenset(Resource("input_source", source.sha256)
                            for source in contract["sources"])
        return Dependencies(frozenset({PART_TOPOLOGY}) | sources,
                            frozenset({PART_TOPOLOGY}), barrier=True,
                            imported_sources=sources if contract["imports"] else frozenset())
    if kind in DUPLEX_KINDS:
        from backend.api.part_duplex_commands import parse_command
        try:
            parse_command(kind, params)
        except ValueError:
            return Dependencies(known=False)
        return Dependencies(frozenset({PART_TOPOLOGY}), frozenset({PART_TOPOLOGY}), barrier=True)
    if kind in NANOPARTICLE_KINDS:
        from backend.api.part_nanoparticle_commands import parse_command, resources
        try:
            command = parse_command(kind, params)
            contract = resources(kind, params)
        except ValueError:
            return Dependencies(known=False)
        particle = Resource("nanoparticle", command.nanoparticle_id)
        sources = frozenset(Resource("input_source", source.sha256) for source in contract["sources"])
        reads = {PART_TOPOLOGY, particle}
        if kind == "nanoparticle-patch" and "thiol_version" in params:
            reads.update(Resource("nanoparticle_connection_version", identity)
                         for identity in command.pending_connection_version_ids)
        # Shared postprocessors can retry pending ligations. Retain the part
        # barrier until that interaction has a narrower proved write contract.
        return Dependencies(frozenset(reads) | sources,
                            frozenset({PART_TOPOLOGY, particle}), barrier=True,
                            imported_sources=sources if contract["imports"] else frozenset())
    if kind == "photoproduct-relax" or (kind == "photoproduct-create" and params.get("method") != "preflight"):
        if params.get("conversion_version") != 1:
            return Dependencies(known=False)
        from backend.core.part_cpd_contract import parse_command
        try:
            parse_command(kind, params)
        except ValueError:
            return Dependencies(known=False)
        return Dependencies(frozenset({PART_TOPOLOGY}), frozenset({PART_TOPOLOGY}), barrier=True)
    if kind == "overhang-bulk":
        from backend.api.part_overhang_commands import ACTIONS
        if type(params.get("action")) is not str or params["action"] not in ACTIONS:
            return Dependencies(known=False)
    if kind in OVERLAY_KINDS:
        if kind == "deformation":
            from backend.core.part_group_selection import has_part_group_targets, target_references
            try:
                if not has_part_group_targets(params.get("targets")):
                    return Dependencies(frozenset({PART_TOPOLOGY}), frozenset({PART_TOPOLOGY}), barrier=True)
                from backend.core.part_operation_input import validate_operation_input
                validate_operation_input(params)
                placements = params.get("cluster_ids", [])
                if type(placements) is not list or any(
                        type(identity) is not str or not 1 <= len(identity) <= 512 for identity in placements):
                    return Dependencies(known=False)
                reads = {PART_TOPOLOGY, *(Resource(*ref) for ref in target_references(params.get("targets"))),
                         *(Resource("cluster", identity) for identity in placements)}
            except (ValueError, TypeError, KeyError):
                return Dependencies(known=False)
            return Dependencies(frozenset(reads), frozenset({PART_TOPOLOGY}), barrier=True)
        return Dependencies(frozenset({PART_TOPOLOGY}), frozenset({PART_TOPOLOGY}), barrier=True)
    if kind == "bundle-create" and params.get("history_seed"):
        return Dependencies(writes=frozenset({PART_TOPOLOGY}), barrier=True)
    if kind in SECTION_KINDS | BRANCH_KINDS | PATTERN_COMMANDS | EXTRUSION_COMMANDS | (AUTO_KINDS - {"auto-break", "auto-merge"}) and not params.get("history_seed"):
        return Dependencies(known=False)
    if kind in PATTERN_COMMANDS and "_organization_copy" in params:
        from backend.api.pattern_features import CircularPatternBody, LinearPatternBody
        from backend.core.part_operation_input import validate_operation_input
        from backend.core.part_pattern_organization import parse_organization_copy
        try:
            validate_operation_input(params)
            copy = parse_organization_copy(params["_organization_copy"])
            if copy is None:
                return Dependencies(known=False)
            schema = CircularPatternBody if kind == "circular-pattern" else LinearPatternBody
            body = schema.model_validate(params)
            placements = [body.cluster_id] if kind == "circular-pattern" else body.cluster_ids
            reads = {PART_TOPOLOGY, *(Resource("cluster", identity) for identity in placements),
                     *(Resource("part_group", identity) for identity in copy.group_ids)}
        except (ValueError, TypeError):
            return Dependencies(known=False)
        return Dependencies(frozenset(reads), frozenset({PART_TOPOLOGY}), barrier=True)
    if kind == "auto-scaffold-connectivity-section" and not params.get("history_seed"):
        return Dependencies(known=False)
    if kind in {"photoproduct-create", "cluster-paste", "overhang-extrude", "nucleotide-transform", "nucleotide-transform-batch"} and not params.get("history_seed"):
        return Dependencies(known=False)
    if kind == "cluster-join" and (
        not params.get("bridge_identity_seed") or "flexible_choices" not in params
    ):
        return Dependencies(known=False)
    if kind == "sweep" and not params.get("sweep_id"):
        return Dependencies(known=False)
    if kind in (PROOF_SNAPSHOT_KINDS - {"bundle-create"}) | LOOP_COMMANDS:
        return Dependencies(frozenset({PART_TOPOLOGY}), frozenset({PART_TOPOLOGY}), barrier=True)
    if kind not in PROOF_MINOR_KINDS:
        return Dependencies(known=False)
    if kind == "crossover-place" and not params.get("crossover_id"):
        return Dependencies(known=False)
    if kind == "crossover-place-batch" and any(not p.get("crossover_id") for p in params.get("placements", [])):
        return Dependencies(known=False)
    if kind == "forced-ligation-create" and not params.get("_fl_id"):
        return Dependencies(known=False)
    if kind in TOPOLOGY_MINOR_KINDS | STRUCTURAL_KINDS | MOVE_KINDS | CELL_KINDS | LIGATION_KINDS | {"strand-patch"}:
        # Native routing can reconcile domains, overhangs and pending ligations.
        # Conservatively serialize these effects until narrower contracts exist.
        return Dependencies(frozenset({PART_TOPOLOGY}), frozenset({PART_TOPOLOGY}), barrier=True)
    joint = Resource("joint", params["joint_id"])
    if kind == "joint-place":
        # Placement replaces any existing joint on that cluster. Track that
        # ownership slot too, so replacement cannot appear independent.
        cluster = Resource("cluster", params["cluster_id"])
        slot = Resource("cluster-joint-slot", params["cluster_id"])
        return Dependencies(frozenset({cluster, slot}), frozenset({joint, slot}))
    return Dependencies(frozenset({joint}), frozenset({joint}))


def execute(kind, design, params):
    return _execute(kind, design, params, expensive=False)


def execute_long(kind, design, params):
    """Worker-only executor; numerical/source contracts still gate each solver."""
    return _execute(kind, design, params, expensive=True)


def _execute(kind, design, params, *, expensive):
    if not dependencies(kind, params).known:
        raise NotImplementedError("Command lacks a versioned proof contract")
    from backend.core.part_suppression import KIND
    if kind == KIND:
        return design
    from backend.core.positional_refs import resolve as resolve_positions
    params = resolve_positions(kind, params, design)
    if design.group_organization is not None:
        from backend.api.part_group_organization_gate import require_native_command
        require_native_command(kind, params)
    if "_connection_organization" in params:
        from backend.api.part_connection_organization import execute as organized_connection
        return organized_connection(kind, design, params,
            lambda k, d, p: _execute(k, d, p, expensive=expensive))
    if kind in GROUP_ORGANIZATION_KINDS:
        from backend.core.part_group_organization import build
        return build(kind, design, {key: value for key, value in params.items() if key != "_generator"})
    from backend.core.part_history_proof import ProofBudgetExceeded
    # Admission is explicit-operation-only; never scan models on normal edits.
    nucleotide_budget = sum(h.length_bp for h in design.helices)
    multiplier = params.get("instances", 1) * (params.get("instances2", 1) if params.get("two_dimensional") else 1)
    if nucleotide_budget * multiplier > 50_000:
        raise ProofBudgetExceeded("Recipe command exceeds proof nucleotide budget")
    if kind == "sweep":
        from math import dist
        points = params.get("points_nm", [])
        # Conservative input admission; native spline validation remains authoritative.
        if len(params.get("cells", [])) * sum(dist(a, b) for a, b in zip(points, points[1:])) > 8_000:
            raise ProofBudgetExceeded("Sweep exceeds proof path budget")
    if "_generated_scope" in params:
        from backend.api.generated_native_scope import execute as scoped_execute
        return scoped_execute(kind, design, params, lambda k, d, p: _execute(k, d, p, expensive=expensive))
    if "_generator" in params:
        # Match dependency/scoped admission: preserve the recorded annotation,
        # but never pass it into reference resolution or native command inputs.
        params = {key: value for key, value in params.items() if key != "_generator"}
    if "_frozen_legacy" in params:
        from backend.core.part_frozen_topology import build
        return build(kind, design, params)
    if kind == "placement-poses":
        from backend.api.part_placement_pose_commands import build
        # Like cluster_op, complete absolute overlays perform no topology retry
        # or reconciliation. The builder validates every owner before applying.
        return build(design, params)
    if kind == "extension-delete" or (kind == "extension-upsert"
                                      and params["_proof_version"] == EXTENSION_UPSERT_VERSION):
        from backend.api.part_extension_commands import build
        # V2 deliberately owns only terminal annotations. Existing v1 upserts
        # continue through native reconciliation/retry below, unchanged.
        return build(kind, design, params)
    from backend.api.part_command_references import validate_command_references
    validate_command_references(kind, design, params)
    from backend.api.part_connection_version_commands import is_metadata_command
    if is_metadata_command(kind, params):
        from backend.api.part_connection_version_commands import build
        from backend.core.photoproducts import stale_photoproduct_ids
        updated = build(design, params)
        if stale_photoproduct_ids(updated):
            raise ValueError("photoproduct_dependency")
        return updated
    if kind in OVERLAY_KINDS:
        from backend.core.part_overlay_commands import build
        return build(kind, design, params)
    if kind == "cluster-dissolve":
        from backend.core.part_group_dissolve import build
        return build(design, params)
    from backend.api.part_feature_commands import replay_minor, replay_snapshot
    from backend.core.cluster_reconcile import reconcile_cluster_membership
    from backend.core.lattice import retry_pending_ligations
    from backend.core.photoproducts import stale_photoproduct_ids
    from backend.core.part_group_lineage import KINDS as LINEAGE_KINDS, prepare_lineage, start_lineage, advance_lineage, apply_lineage
    lineage = prepare_lineage(design, kind, params) if kind in LINEAGE_KINDS else None
    lineage_trace = start_lineage(lineage)
    report = None
    if kind == "photoproduct-relax" or (kind == "photoproduct-create" and params.get("method") == "convert"):
        if not expensive:
            from backend.core.part_command_errors import CommandContractError
            from backend.core.part_cpd_contract import validate_inputs
            # A missing endpoint is actionable without constructing atoms or
            # initializing a numerical runtime. Cost admission must not hide it.
            validate_inputs(kind, design, params)
            raise CommandContractError("CPD regeneration requires an explicit bounded evaluation job",
                                       code="long_job_required")
        from backend.api.part_cpd_commands import build
        updated = build(kind, design, params)
    elif kind in EXTENSION_KINDS:
        from backend.api.part_extension_commands import build
        updated = build(kind, design, params)
    elif kind == "nick-batch":
        from backend.api.part_command_references import build_strict_nick_batch
        updated = build_strict_nick_batch(design, params)
    elif kind in ELEMENT_COPY_KINDS:
        from backend.api.part_element_copy_commands import build
        updated = build(kind, design, params)
    elif kind in CADNANO_KINDS:
        from backend.api.part_cadnano_commands import build
        from backend.core.part_input_sources import EmbeddedResolver
        updated = build(kind, design, params, resolver=EmbeddedResolver(design.input_sources))
    elif kind in APTAMER_KINDS:
        from backend.api.part_aptamer_commands import build
        from backend.core.part_input_sources import EmbeddedResolver
        updated = build(kind, design, params, resolver=EmbeddedResolver(design.input_sources))
    elif kind in NP_CONNECTION_KINDS:
        from backend.api.part_nanoparticle_connection_commands import build
        updated = build(kind, design, params)
    elif kind in THIOL_KINDS:
        from backend.api.part_thiol_commands import build
        updated = build(kind, design, params)
    elif kind in PROTEIN_CONJUGATION_KINDS:
        from backend.api.part_protein_conjugation_commands import build
        updated = build(kind, design, params)
    elif kind in PROTEIN_KINDS:
        from backend.api.part_protein_commands import build
        from backend.core.part_input_sources import EmbeddedResolver
        updated = build(kind, design, params, resolver=EmbeddedResolver(design.input_sources))
    elif kind in DUPLEX_KINDS:
        if kind == "duplex-relax" and not expensive:
            from backend.core.part_command_errors import CommandContractError
            from backend.core.part_duplex_relax_contract import validate_inputs
            validate_inputs(design, params)
            raise CommandContractError("Duplex relaxation requires an explicit bounded evaluation job",
                                       code="long_job_required")
        from backend.api.part_duplex_commands import build
        updated = build(kind, design, params)
    elif kind == "nanoparticle-patch" and "coating_version" in params:
        from backend.api.part_streptavidin_commands import build, validate_inputs
        from backend.core.part_input_sources import EmbeddedResolver
        resolver = EmbeddedResolver(design.input_sources)
        if not expensive:
            from backend.core.part_command_errors import CommandContractError
            validate_inputs(kind, design, params, resolver=resolver)
            raise CommandContractError("Coating regeneration requires an explicit bounded evaluation job",
                                       code="long_job_required")
        updated = build(kind, design, params, resolver=resolver)
    elif kind in NANOPARTICLE_KINDS:
        from backend.api.part_nanoparticle_commands import build
        from backend.core.part_input_sources import EmbeddedResolver
        updated = build(kind, design, params, resolver=EmbeddedResolver(design.input_sources))
    elif kind in BRANCH_KINDS:
        from backend.api.part_branch_commands import build
        updated = build(kind, design, params)
    elif kind in SECTION_KINDS:
        from backend.api.part_section_commands import build
        updated = build(kind, design, params)
    elif kind in CONNECTIVITY_KINDS:
        from backend.api.part_connectivity_commands import build
        updated = build(kind, design, params)
    elif kind in JOINED_PATH_KINDS:
        from backend.api.part_joined_path_commands import build
        updated = build(kind, design, params)
    elif kind in PATH_KINDS:
        from backend.api.part_path_commands import build
        updated = build(kind, design, params)
    elif kind in PHOTOPRODUCT_KINDS:
        from backend.api.part_photoproduct_commands import build
        updated = build(kind, design, params)
    elif kind in REFINEMENT_KINDS:
        from backend.api.part_refinement_commands import build
        updated = build(kind, design, params)
    elif kind == "cluster-paste":
        from backend.core.cluster_copy import paste_clusters
        from backend.core.cluster_reconcile import MutationReport
        updated, ids, _ = paste_clusters(design, params["cluster_ids"], (params["delta_row"], params["delta_col"]), identity_seed=params["history_seed"])
        report = MutationReport(new_helix_origins={hid: None for hid in ids})
    elif kind in LINKER_KINDS:
        from backend.api.part_linker_commands import build
        result = build(kind, design, params)
        updated, report = result if isinstance(result, tuple) else (result, None)
    elif kind == "overhang-bulk":
        if params.get("action") == CONNECTION_DISCONNECT_ACTION:
            from backend.api.part_connection_disconnect import build
            updated, report = build(design, params)
        elif params.get("action") == CONNECTION_DIRECT_COMPOSE_ACTION:
            from backend.api.part_connection_direct_composition import build
            updated, report = build(design, params)
        elif params.get("action") == CONNECTION_DIRECT_ACTION:
            from backend.api.part_connection_direct_commands import build
            updated, report = build(design, params)
        elif params.get("action") == CONNECTION_COMPOSE_ACTION:
            from backend.api.part_connection_composition_commands import build
            updated, report = build(design, params)
        elif params.get("action") == CONNECTION_APPLY_ACTION:
            from backend.api.part_connection_application_commands import build
            updated, report = build(design, params)
        else:
            from backend.api.part_overhang_commands import build
            updated = build(design, params)
    elif kind == "overhang-extrude":
        from backend.api.crud import _build_overhang_extrude, OverhangExtrudeRequest
        updated, report = _build_overhang_extrude(design, OverhangExtrudeRequest.model_validate(params))
    elif kind == "overhang-sequence":
        from backend.api.part_overhang_patch import build
        updated = build(design, params)
    elif lineage_trace is not None:
        from backend.api.part_resize_commands import build
        updated = build(kind, design, params, lineage=lineage_trace)
    elif kind in MOVE_KINDS:
        from backend.api.part_crossover_moves import build
        updated = build(kind, design, params)
    elif kind in CELL_KINDS:
        from backend.api.part_cell_commands import build
        updated = build(kind, design, params)
    elif kind in ANNOTATION_KINDS:
        from backend.api.part_transform_references import build_annotation_with_reference_diagnostics
        updated = build_annotation_with_reference_diagnostics(kind, design, params)
    elif kind == "apply-loop-skips":
        from backend.api.part_loop_commands import build
        updated = build(design)
    elif kind in {"strand-sequence", "strand-patch"}:
        from backend.api.part_strand_patch import build
        from backend.api.crud import StrandPatchRequest
        updated = build(design, params["strand_id"], StrandPatchRequest.model_validate(params))[0]
    elif kind in LIGATION_KINDS:
        from backend.api.part_ligation_commands import build
        updated = build(kind, design, params)
    elif kind in STRUCTURAL_KINDS:
        from backend.api.part_structural_commands import build
        updated = build(kind, design, params)
    elif kind in LOOP_COMMANDS:
        from backend.api.part_native_commands import build_loop
        updated = build_loop(kind, design, params)
    elif kind in SEQUENCE_COMMANDS:
        from backend.api.part_native_commands import build_sequence
        updated = build_sequence(kind, design, params)
    elif kind in PATTERN_COMMANDS:
        from backend.api.pattern_features import build_pattern
        from backend.core.cluster_reconcile import MutationReport
        updated, ids, _ = build_pattern(kind, design, params, id_seed=params["history_seed"])
        report = MutationReport(new_helix_origins={hid: None for hid in ids})
        lineage = prepare_lineage(updated, kind, params)
    elif kind == "cluster-join":
        from backend.api.part_join_command import build
        updated, report = build(design, params)
    elif kind in AUTO_KINDS:
        from backend.api.part_auto_commands import build
        updated = build(kind, design, params)
    elif kind in EXTRUSION_COMMANDS:
        from backend.api.part_extrusion_commands import build
        updated, report = build(kind, design, params)
    elif kind == "sweep":
        updated = replay_snapshot(kind, design, {k: v for k, v in params.items() if k != "_proof_version"})
    elif kind == "bundle-create":
        from backend.core.part_history_proof import ProofBudgetExceeded
        cells = params.get("cells", [])
        if len(cells) > 512 or len(cells) * abs(params.get("length_bp", 0)) > 50_000:
            raise ProofBudgetExceeded("Bundle exceeds proof work budget")
        updated = replay_snapshot(kind, design, params)
    else:
        updated = replay_minor(kind, design, params)
    lineage = advance_lineage(lineage, updated, trace=lineage_trace)
    updated = reconcile_cluster_membership(design, updated, report)
    if kind not in {"auto-break", "full-autostaple", "cluster-join"}:
        updated = retry_pending_ligations(design, updated)
    updated = apply_lineage(lineage, updated)
    if stale_photoproduct_ids(updated):
        raise ValueError("photoproduct_dependency")
    return updated
