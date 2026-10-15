"""Audited versioned part replay contracts, separate from recovery dispatch."""
from backend.core.part_dependencies import Dependencies, Resource


PROOF_MINOR_KINDS = frozenset({"joint-place", "joint-update", "joint-delete"})
PROOF_VERSION = 1
PART_TOPOLOGY = Resource("part", "topology")


def capabilities():
    from backend.core.feature_registry import part_replay_capabilities
    return {**part_replay_capabilities(), "proof_version": PROOF_VERSION,
            "proof_commands": sorted(PROOF_MINOR_KINDS | {"bundle-create"}),
            "proof_root_kinds": ["empty", "import"]}


def dependencies(kind, params):
    if type(params.get("_proof_version")) is not int or params["_proof_version"] != PROOF_VERSION:
        return Dependencies(known=False)
    if kind == "bundle-create" and params.get("history_seed"):
        return Dependencies(writes=frozenset({PART_TOPOLOGY}))
    if kind not in PROOF_MINOR_KINDS:
        return Dependencies(known=False)
    joint = Resource("joint", params["joint_id"])
    if kind == "joint-place":
        # Placement replaces any existing joint on that cluster. Track that
        # ownership slot too, so replacement cannot appear independent.
        cluster = Resource("cluster", params["cluster_id"])
        slot = Resource("cluster-joint-slot", params["cluster_id"])
        return Dependencies(frozenset({cluster, slot, PART_TOPOLOGY}), frozenset({joint, slot}))
    return Dependencies(frozenset({joint, PART_TOPOLOGY}), frozenset({joint}))


def execute(kind, design, params):
    if not dependencies(kind, params).known:
        raise NotImplementedError("Command lacks a versioned proof contract")
    from backend.api.part_feature_commands import replay_minor, replay_snapshot
    from backend.core.cluster_reconcile import reconcile_cluster_membership
    from backend.core.lattice import retry_pending_ligations
    from backend.core.photoproducts import stale_photoproduct_ids
    if kind == "bundle-create":
        from backend.core.part_history_proof import ProofBudgetExceeded
        cells = params.get("cells", [])
        if len(cells) > 512 or len(cells) * abs(params.get("length_bp", 0)) > 50_000:
            raise ProofBudgetExceeded("Bundle exceeds proof work budget")
        updated = replay_snapshot(kind, design, params)
    else:
        updated = replay_minor(kind, design, params)
    updated = reconcile_cluster_membership(design, updated)
    updated = retry_pending_ligations(design, updated)
    if stale_photoproduct_ids(updated):
        raise ValueError("photoproduct_dependency")
    return updated
