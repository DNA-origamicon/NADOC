"""Join regeneration uses recorded sites and bridge identity, not preview state."""


def build(design, params):
    from backend.core.cluster_join import ClusterJoinRequest, propose_cluster_join
    from backend.core.cluster_join_free import (
        FreeClusterJoinRequest,
        propose_free_cluster_join,
    )
    from backend.core.cluster_reconcile import MutationReport

    values = {
        k: v
        for k, v in params.items()
        if k not in {"_proof_version", "bridge_identity_seed", "flexible_choices"}
    }
    # These guards protect live publication; the isolated candidate has its own
    # identity. Neither a preview hash nor the recorded revision supplies geometry.
    values.update(expected_design_id=design.id, expected_revision=0, preview_token=None)
    schema, builder = (
        (ClusterJoinRequest, propose_cluster_join)
        if "first" in values
        else (FreeClusterJoinRequest, propose_free_cluster_join)
    )
    updated, report = builder(
        design,
        schema.model_validate(values),
        identity_seed=params["bridge_identity_seed"],
    )
    from backend.core.part_flexible_choices import apply_flexible_choices

    updated = apply_flexible_choices(updated, params.get("flexible_choices"))
    return updated, MutationReport(
        new_helix_origins={
            b["helix_id"]: None for b in report["bridges"] if "helix_id" in b
        }
    )
