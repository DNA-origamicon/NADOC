"""Compile independent joined sections into ordinary editable native features."""

from copy import deepcopy
from uuid import UUID, uuid4, uuid5

import numpy as np
from scipy.spatial.transform import Rotation

from backend.api.generated_branch_steps import _execute_recorded
from backend.core.part_overlay_commands import GROUP_CREATE_VERSION


def build_joined_sections(design, summary, history, *, history_seed=None):
    """Author sparse seeds, grouping, placement and optional numeric paths."""
    from backend.api.part_joined_path_commands import compile_path_params
    from backend.api.part_section_commands import compile_seed_params
    from backend.core.models import ClusterRigidTransform

    if summary.get("branch_geometry") != "join" or not summary.get("join_sections"):
        raise ValueError("Joined construction requires independent section inputs")
    summary = deepcopy(summary)
    namespace = UUID(str(history_seed)) if history_seed is not None else uuid4()
    old_ids = [spec["id"] for spec in summary["join_sections"]]
    if len(set(old_ids)) != len(old_ids):
        raise ValueError("Joined section identities must be distinct")
    identities = {old: str(uuid5(namespace, f"section-cluster:{i}"))
                  for i, old in enumerate(old_ids)}
    # Keep planning section names available to report consumers after assigning
    # ordinary authored cluster identities. The caller's summary is untouched.
    summary["join_section_cluster_ids"] = identities
    for spec in summary["join_sections"]:
        spec["id"] = identities[spec["id"]]
    for field in ("join_crossbars", "join_arms", "join_attachments"):
        for spec in summary.get(field, []):
            if spec["cluster_id"] not in identities:
                raise ValueError("Joined plan references an unavailable section")
            spec["cluster_id"] = identities[spec["cluster_id"]]
    for index, spec in enumerate(summary["join_sections"]):
        prior = {helix.id for helix in design.helices}
        params = compile_seed_params(spec, index, uuid5(namespace, f"section-seed:{index}"))
        design = _execute_recorded(design, history, "independent-section-seed",
            f"Create independent section {index + 1}", params, f"branch-seed:{index}")
        helices = [helix for helix in design.helices if helix.id not in prior]
        cluster = ClusterRigidTransform(id=spec["id"],
            name="Middle stem" if index == 0 else f"Particle crossbar {index}",
            helix_ids=[helix.id for helix in helices])
        if history:
            # Overlay entries retain real UUIDs and map only typed membership.
            # Later scoped recipes explicitly retain this ordinary cluster ID.
            history.source_ids.add(cluster.id)
        design = _execute_recorded(design, history, "cluster_create",
            f"Group independent section {index + 1}",
            {"cluster": cluster.model_dump(mode="json"), "_proof_version": GROUP_CREATE_VERSION},
            f"branch-group:{index}")
        xy = np.mean([helix.axis_start.to_array() for helix in helices], axis=0)
        xy[2] = 0
        rotation = Rotation.from_quat(spec["rotation"]).as_matrix()
        pose = {"cluster_id": cluster.id, "rotation": spec["rotation"],
                "translation": (np.asarray(spec["position"]) - rotation @ xy).tolist(),
                "pivot": cluster.pivot, "_proof_version": 1}
        design = _execute_recorded(design, history, "cluster_op",
            f"Position independent section {index + 1}", pose, f"branch-pose:{index}")
        if spec.get("path") is not None or spec.get("path_recipe") is not None:
            params = compile_path_params(spec, index, cluster.helix_ids)
            design = _execute_recorded(design, history, "joined-crossbar-path",
                f"Curve particle crossbar {index}", params, f"joined-path:{index}")
    return design, summary


def route_joined_sections(design, summary, history):
    """Route each authored group, then persist each chosen ordinary Join input."""
    from backend.api.generated_branch_steps import encode_fork_curvature
    from backend.api.part_proof_commands import execute
    from backend.api.part_section_commands import route
    from backend.core.cluster_reconcile import reconcile_cluster_membership
    from backend.core.curved_rod_generator import physical_scaffold_nt
    from backend.core.joined_branches import BranchBudgetError, _attach_arm, _attach_crossbar
    from backend.core.lattice import retry_pending_ligations
    from backend.core.part_flexible_choices import capture_flexible_choices

    def check_budget(current):
        if physical_scaffold_nt(current) > summary.get("routing_budget", summary.get("scaffold_size", 8064)):
            raise BranchBudgetError("The routed Join branches exceed the scaffold budget.")

    for index, spec in enumerate(summary["join_sections"]):
        params = {"cluster_id": spec["id"], "lattice_column_offset": 1000 * index,
                  "history_seed": str(uuid4()), "_proof_version": 1}
        before = design
        design, routing = route(design, params)
        if not routing.valid:
            raise ValueError("An independent Join branch could not be routed.")
        design = retry_pending_ligations(before, reconcile_cluster_membership(before, design))
        if history:
            history.record(before, design, "auto-scaffold-bounded-section",
                f"Route independent section {index + 1}", params, f"branch-scaffold:{index}")
    if summary.get("join_curved"):
        design = encode_fork_curvature(design, history, "joined-route-curvature")
    check_budget(design)
    reports = []
    for index, spec in enumerate(summary.get("join_crossbars", summary.get("join_arms", []))):
        identity = str(uuid4())
        attach = _attach_crossbar if summary.get("join_curved") else _attach_arm
        proposed, body, report = attach(design, spec, identity_seed=identity,
                                       fixed_cluster_id=summary["join_sections"][0]["id"])
        params = {**body, "bridge_identity_seed": identity,
                  "flexible_choices": capture_flexible_choices(proposed), "_proof_version": 1}
        before = design
        design = execute("cluster-join", design, params)
        check_budget(design)
        if history:
            history.record(before, design, "cluster-join", f"Join particle crossbar {index + 1}",
                params, f"branch-join:{index}")
        reports.append(report)
    if len(design.scaffolds()) != 1:
        raise ValueError("Join branches did not form one scaffold.")
    summary.update(join_count=len(reports), bridge_pair_counts=[r["connection_count"] for r in reports],
        connector_nt=sum(r["added_connector_nt"] for r in reports),
        max_connector_nt=max((b["extra_bases"] for r in reports for b in r["bridges"]), default=0))
    return design, routing
