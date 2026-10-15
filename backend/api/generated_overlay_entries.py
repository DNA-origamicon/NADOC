"""Keep generated grouping/pose inputs in the ordinary editable overlay schema."""

from backend.core.models import ClusterCreateLogEntry, ClusterOpLogEntry
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_overlay_commands import build, command_input
from backend.core.part_scope_references import namespace_design

KINDS = frozenset({"cluster_create", "cluster_op"})


def entry_for(kind, before, after, params, *, group, retained, identity, scoped):
    """Map a proven authored overlay definition, never a recovery snapshot."""
    authored = build(kind, before, params)
    if any(getattr(authored, field) != getattr(after, field) for field in AUTHORING_FIELDS):
        raise ValueError("Generated overlay differs from its authored inputs")
    mapped = namespace_design(authored, group, retained) if scoped else authored
    source_id = params["cluster"]["id"] if kind == "cluster_create" else params["cluster_id"]
    target_id = source_id if not scoped or source_id in retained else f"gen_{group}_{source_id}"
    cluster = next(cluster for cluster in mapped.cluster_transforms if cluster.id == target_id)
    common = {"id": identity, "cluster_id": target_id, "proof_version": 1}
    if kind == "cluster_create":
        entry = ClusterCreateLogEntry(**common, cluster_snapshot=cluster,
            name=cluster.name, helix_ids=cluster.helix_ids, domain_ids=cluster.domain_ids)
    else:
        fields = {key: getattr(cluster, key) for key in params
                  if key in {"name", "helix_ids", "domain_ids", "color", "opacity"}}
        fields = {key: [ref.model_dump(mode="json") for ref in value]
                  if key == "domain_ids" else value for key, value in fields.items()}
        entry = ClusterOpLogEntry(**common, translation=cluster.translation,
            rotation=cluster.rotation, pivot=cluster.pivot, authored_fields=fields)
    return entry, command_input(entry)[1]
