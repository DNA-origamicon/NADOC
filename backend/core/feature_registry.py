"""Standard-part command replay contracts, independent of session state.

These are legacy command executors, not certificates of complete reproducibility
or editability. Snapshots/diffs can restore many more kinds. Assembly contracts
are deliberately outside this registry until the deferred assembly track.
"""
from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True)
class ReplaySpec:
    module: str
    builder: str
    schema: str | None = None
    adapter: str = "design_request"
    parameter_keys: tuple[str, ...] = ()


_CRUD = "backend.api.crud"
_JOINTS = "backend.api.routes_cluster_joints"

# Module/name references are resolved by the API adapter. The core never imports
# API modules, calls routes, or reads the current session.
PART_SNAPSHOT_COMMANDS = MappingProxyType({
    "sweep": ReplaySpec("backend.core.sweep", "build_sweep", "SweepRequest"),
    "bundle-create": ReplaySpec(_CRUD, "_build_bundle", "BundleRequest", "bundle"),
    "extrude-segment": ReplaySpec(_CRUD, "_build_extrude_segment", "BundleSegmentRequest", "reconcile"),
    "extrude-continuation": ReplaySpec(_CRUD, "_build_extrude_continuation", "BundleContinuationRequest", "reconcile"),
    "extrude-deformed-continuation": ReplaySpec(_CRUD, "_build_extrude_deformed_continuation", "BundleDeformedContinuationRequest", "reconcile"),
    "overhang-extrude": ReplaySpec(_CRUD, "_build_overhang_extrude", "OverhangExtrudeRequest", "first"),
})

PART_MINOR_COMMANDS = MappingProxyType({
    "nick": ReplaySpec(_CRUD, "_build_nick", "NickRequest"),
    "nick-batch": ReplaySpec(_CRUD, "_build_nick_batch", "NickBatchRequest"),
    "crossover-place": ReplaySpec(_CRUD, "_build_place_crossover", "PlaceCrossoverRequest", "first"),
    "crossover-place-batch": ReplaySpec(_CRUD, "_build_place_crossover_batch", "PlaceCrossoverBatchRequest", "first"),
    "strand-end-resize": ReplaySpec(_CRUD, "_build_strand_end_resize", "StrandEndResizeRequest"),
    "domain-shift": ReplaySpec(_CRUD, "_build_domain_shift", "DomainShiftRequest"),
    "strand-delete": ReplaySpec(_CRUD, "_build_delete_strand", parameter_keys=("strand_id",)),
    "strand-delete-batch": ReplaySpec(_CRUD, "_build_delete_strands_batch", "StrandBatchDeleteRequest"),
    "domain-delete": ReplaySpec(_CRUD, "_build_delete_domain", parameter_keys=("strand_id", "domain_index")),
    "helix-delete": ReplaySpec("backend.api.part_feature_commands", "delete_helix"),
    "crossover-delete": ReplaySpec("backend.api.part_feature_commands", "delete_crossover"),
    "joint-place": ReplaySpec(_JOINTS, "_build_add_joint"),
    "joint-update": ReplaySpec(_JOINTS, "_build_update_joint"),
    "joint-delete": ReplaySpec(_JOINTS, "_build_delete_joint"),
})


def part_replay_capabilities():
    """Expose actual executor availability without implying a verified recipe."""
    return {
        "scope": "part",
        "version": 1,
        "snapshot_commands": sorted(PART_SNAPSHOT_COMMANDS),
        "minor_commands": sorted(PART_MINOR_COMMANDS),
        "certifies_history": False,
    }
