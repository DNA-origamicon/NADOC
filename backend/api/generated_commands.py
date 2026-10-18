"""Compile planned construction changes into NADOC's existing history operations.

Planning selects parameters. Native bend/cluster/rotation entries and Fine Routing
children remain usable by the ordinary editors and replay machinery.
"""

import uuid

from backend.api import state
from backend.core.models import (
    DeformationLogEntry,
    ClusterCreateLogEntry,
    ClusterOpLogEntry,
    MinorMutationLogEntry,
    RoutingClusterLogEntry,
    OverhangRotationLogEntry,
)
from backend.core.design_diff import encode_child_diff


def fine_routing(before, after, commands):
    current = before
    children = []
    from backend.api.part_proof_commands import execute
    for kind, label, params in commands:
        params = {**params, "_proof_version": 1}
        updated = execute(kind, current, params)
        a, r, m, size = encode_child_diff(current, updated)
        children.append(
            MinorMutationLogEntry(
                op_subtype=kind,
                label=label,
                params=params,
                diff_added_b64=a,
                diff_removed_b64=r,
                diff_modified_b64=m,
                diff_size_bytes=size,
            )
        )
        current = updated
    # Do not mask differences between the selected manual operations and planning.
    from backend.core.part_history_proof import AUTHORING_FIELDS
    mismatches = sorted(f for f in AUTHORING_FIELDS if getattr(current, f) != getattr(after, f))
    if mismatches:
        raise ValueError(f"Generated native commands disagree with planning: {mismatches}")
    pre, pre_size = state.encode_design_snapshot(before)
    post, post_size = state.encode_design_snapshot(after)
    return RoutingClusterLogEntry(
        children=children,
        pre_state_gz_b64=pre,
        pre_state_size_bytes=pre_size,
        post_state_gz_b64=post,
        post_state_size_bytes=post_size,
    )


def ordinary_entries(before, after, entry, key):
    """Replace compound generator labels with native, fully specified operations."""
    if entry.params.get("_proof_version") == 1:
        from backend.api.part_proof_commands import PROOF_MINOR_KINDS
        if entry.op_kind in PROOF_MINOR_KINDS:
            params = {k: v for k, v in entry.params.items() if k != "_generator"}
            return [fine_routing(before, after, [(entry.op_kind, entry.label, params)])]
        # Already executed against the composed input in GeneratedHistory.
        # Keep provenance outside the parameters understood by strict schemas.
        params = {k: v for k, v in entry.params.items() if k != "_generator"}
        return [entry.model_copy(update={"params": params})]
    if key == "section-profile":
        params = {"entries": entry.params["entries"]}
        return [fine_routing(before, after, [("strand-end-resize", "Size reinforcement spans", params)])]
    if key == "sweep":
        # SweepRequest forbids extra keys; this is a native authoring command.
        return [
            entry.model_copy(
                update={
                    "params": {
                        k: v for k, v in entry.params.items() if k != "_generator"
                    }
                }
            )
        ]
    if key == "prepare-handles":
        from backend.core.nanoparticle import replace_gold_nanosphere

        current = before
        entries = []
        for particle in after.nanoparticles:
            if particle.kind != "gold_nanosphere":
                continue
            updated = replace_gold_nanosphere(
                current, particle.id, pose=particle.pose.values
            )
            if updated == current:
                continue
            pre, pre_size = state.encode_design_snapshot(current)
            post, post_size = state.encode_design_snapshot(updated)
            params = {
                "nanoparticle_id": particle.id,
                "pose": particle.pose.values,
                "_generator": {
                    "version": 2,
                    "group_id": entry.params["_generator"]["group_id"],
                    "key": f"prepare-handle:{particle.id}",
                    "cluster_ids": [],
                },
            }
            entries.append(
                entry.model_copy(
                    update={
                        "id": str(uuid.uuid4()),
                        "op_kind": "nanoparticle-patch",
                        "label": "Move gold nanosphere",
                        "params": params,
                        "design_snapshot_gz_b64": pre,
                        "snapshot_size_bytes": pre_size,
                        "post_state_gz_b64": post,
                        "post_state_size_bytes": post_size,
                    }
                )
            )
            current = updated
        if current.helices != after.helices:
            raise ValueError(
                "Particle handles could not be restored with ordinary pose edits"
            )
        return entries
    if key == "curve-path":
        previous = {op.id for op in before.deformations}
        return [
            DeformationLogEntry(deformation_id=op.id, op_snapshot=op)
            for op in after.deformations
            if op.id not in previous
        ]
    if key.startswith("fit-overhang:"):
        old = {o.id: o for o in before.overhangs}
        changed = [
            o
            for o in after.overhangs
            if o.id in old and old[o.id].rotation != o.rotation
        ]
        rotations = OverhangRotationLogEntry(
            overhang_ids=[o.id for o in changed],
            rotations=[o.rotation for o in changed],
            labels=[o.label for o in changed],
        )
        # Duplex materialization is a standard derived consequence of rotating
        # a paired overhang. Record its ordinary cluster poses as well.
        cluster_entry = entry.model_copy(update={"op_kind": "cluster-pose"})
        return [
            *([rotations] if changed else []),
            *ordinary_entries(before, after, cluster_entry, "fit-clusters"),
        ]
    if entry.op_kind == "nick":
        params = {k: entry.params[k] for k in ("helix_id", "direction")}
        params["bp_index"] = entry.params.get("cut_bp_index", entry.params["bp_index"])
        return [
            fine_routing(
                before, after, [("nick", "Nick strand", params)]
            )
        ]
    if entry.op_kind == "cluster-pose":
        old = {c.id: c for c in before.cluster_transforms}
        result = []
        for cluster in after.cluster_transforms:
            if old.get(cluster.id) == cluster:
                continue
            if cluster.id not in old:
                result.append(
                    ClusterCreateLogEntry(
                        cluster_id=cluster.id,
                        cluster_snapshot=cluster.model_copy(
                            update={"rotation": [0, 0, 0, 1], "translation": [0, 0, 0]}
                        ),
                        name=cluster.name,
                        helix_ids=cluster.helix_ids,
                        domain_ids=cluster.domain_ids,
                    )
                )
            result.append(
                ClusterOpLogEntry(
                    cluster_id=cluster.id,
                    translation=cluster.translation,
                    rotation=cluster.rotation,
                    pivot=cluster.pivot,
                    authored_fields={k: cluster.model_dump(mode="json")[k]
                        for k in ("name", "helix_ids", "domain_ids", "color", "opacity")},
                )
            )
        return result
    if key == "curve-marks":
        commands = []
        for helix in after.helices:
            prior = {
                m.bp_index: m.delta for m in before.find_helix(helix.id).loop_skips
            }
            removed = set(prior) - {m.bp_index for m in helix.loop_skips}
            for bp in sorted(removed):
                commands.append(
                    (
                        "loop-skip-insert",
                        f"Remove loop/skip · helix {helix.id} bp {bp}",
                        dict(helix_id=helix.id, bp_index=bp, delta=0),
                    )
                )
            for mark in helix.loop_skips:
                if prior.get(mark.bp_index) == mark.delta:
                    continue
                params = dict(
                    helix_id=helix.id, bp_index=mark.bp_index, delta=mark.delta
                )
                commands.append(
                    (
                        "loop-skip-insert",
                        f"{'Loop' if mark.delta > 0 else 'Skip'} · helix {helix.id} bp {mark.bp_index}",
                        params,
                    )
                )
        return [fine_routing(before, after, commands)]
    labels = {
        "bundle": "Extrude segment",
        "scaffold": "Auto scaffold (seamed)",
        "autostaple": "Full autostaple",
        "curve-sequences": "Assign staple sequences",
        "attachment-sequences": "Assign staple sequences",
        "final-sequences": "Assign staple sequences",
    }
    params = dict(entry.params)
    # Version 2 is provenance only, not a bespoke feature editor/rebuild engine.
    meta = params["_generator"]
    params["_generator"] = {
        k: v
        for k, v in meta.items()
        if k in ("version", "group_id", "key", "cluster_ids")
    }
    params["_generator"]["version"] = 2
    if key == "bundle":
        params.update(
            plane="XY", offset_nm=0.0, strand_filter="both", ligate_adjacent=False
        )
    if key.startswith("handle:"):
        old = {c.id for c in before.nanoparticle_conjugations}
        conjugation = next(
            c for c in after.nanoparticle_conjugations if c.id not in old
        )
        params.update(
            nanoparticle_id=conjugation.nanoparticle_id,
            conjugation_id=conjugation.id,
            scheme=conjugation.scheme,
            count=1,
            attach_end=conjugation.attach_end,
        )
    if key.startswith("sequence:"):
        old = {o.id: o for o in before.overhangs}
        changed = next(o for o in after.overhangs if old.get(o.id) != o)
        params.update(overhang_id=changed.id, label=changed.label)
    if key.startswith("connect:"):
        version = next(
            v
            for v in after.nanoparticle_connection_versions
            if not any(
                old.id == v.id for old in before.nanoparticle_connection_versions
            )
        )
        params.update(version.model_dump(mode="json"))
    label = (
        "Move gold nanosphere"
        if key.startswith("fit:")
        else labels.get(key, entry.label)
    )
    return [entry.model_copy(update={"label": label, "params": params})]


def certify_entries(before, after, entries):
    """Promote compiled native rows only after complete independent comparison.

    Legacy asset/compound construction remains usable recovery data and is
    reported explicitly. Its snapshots never become native command inputs.
    """
    from backend.api.part_proof_commands import dependencies, execute
    from backend.core.part_overlay_commands import command_input, KINDS
    from backend.core.part_history_proof import AUTHORING_FIELDS
    from fastapi import HTTPException
    candidates = []
    for entry in entries:
        if entry.feature_type in KINDS:
            candidate = entry.model_copy(update={"proof_version": 1})
        elif entry.feature_type == "snapshot":
            candidate = entry.model_copy(update={"params": {
                **{k: v for k, v in entry.params.items() if k != "_generator"}, "_proof_version": 1}})
        elif entry.feature_type == "routing-cluster":
            candidate = entry
        else:
            return entries, "Legacy compound routing has no complete native inputs"
        for child in (candidate.children if candidate.feature_type == "routing-cluster" else [candidate]):
            kind, params = command_input(child)
            if not dependencies(kind, params).known:
                return entries, f"No complete native contract for {kind}"
        candidates.append(candidate)
    current = before.model_copy(deep=True)
    try:
        for candidate in candidates:
            for child in (candidate.children if candidate.feature_type == "routing-cluster" else [candidate]):
                kind, params = command_input(child)
                current = execute(kind, current, params)
    except (ValueError, HTTPException) as exc:
        return entries, f"Native command rejected planned inputs: {exc}"
    mismatches = sorted(f for f in AUTHORING_FIELDS if getattr(current, f) != getattr(after, f))
    if mismatches:
        return entries, f"Native effects differ in {', '.join(mismatches)}"
    return candidates, None
