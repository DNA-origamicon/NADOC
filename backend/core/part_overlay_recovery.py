"""Respect recorded topology boundaries when restoring authored cluster fields.

Pose deltas retain the established seek behavior. Membership/name/appearance
setters before a later payload are already incorporated in that payload and
must not overwrite its newer values (for example an inherited extruded helix).
No commands or validation are executed on this recovery path.
"""


def restore_authored_fields(design, snapshot):
    fields = {}
    for entry in design.feature_log:
        if entry.feature_type == "cluster_op" and entry.authored_fields:
            fields.setdefault(entry.cluster_id, set()).update(entry.authored_fields)
    if not fields:
        return design
    saved = {c.id: c for c in snapshot.cluster_transforms if c.id in fields}
    clusters = [
        c.model_copy(update={key: getattr(saved[c.id], key) for key in fields[c.id]})
        if c.id in saved
        else c
        for c in design.cluster_transforms
    ]
    return design.copy_with(cluster_transforms=clusters)


def after_payload(active, last):
    if not any(e.authored_fields for e in last.values()):
        return set()
    ids = set()
    for entry in reversed(active):
        if (
            entry.feature_type in {"snapshot", "routing-cluster"}
            and not entry.evicted
            and entry.post_state_gz_b64
        ):
            break
        if entry.feature_type == "cluster_op":
            ids.add(entry.cluster_id)
    return ids
