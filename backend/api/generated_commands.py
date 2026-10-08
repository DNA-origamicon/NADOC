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
from backend.core.loop_skip_calculator import apply_loop_skips


def fine_routing(before, after, commands):
    current = before
    children = []
    for kind, label, params, operation in commands:
        updated = operation(current)
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
    assert current.helices == after.helices and current.strands == after.strands
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
                before, after, [("nick", "Nick strand", params, lambda d: after)]
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
                )
            )
        return result
    if key == "curve-marks":
        commands = []
        for helix in after.helices:
            prior = {
                m.bp_index: m.delta for m in before.find_helix(helix.id).loop_skips
            }
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
                        lambda d, hid=helix.id, mark=mark: apply_loop_skips(
                            d, {hid: [mark]}
                        ),
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
