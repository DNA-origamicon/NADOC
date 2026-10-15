"""Versioned, fail-closed proof boundary for standard-part history.

Recovery snapshots and diffs are never evidence of command reproducibility.
Only explicitly versioned command contracts participate in proof replay.
Imported source state remains distinct from native editable construction.
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PartRecipeRoot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int = Field(default=1, ge=1)
    kind: Literal["empty", "import"] = "empty"
    lattice_type: Literal["HONEYCOMB", "SQUARE"] = "HONEYCOMB"
    initial_name: str = "Untitled"
    source_json: str | None = Field(default=None, max_length=1_000_000)
    source_sha256: str | None = None


# Conservative whole-field ownership: nested authoring data is compared in
# full. A new Design field must receive an explicit role before verification.
_AUTHORING = """
dimensions lattice_frames helices strands lattice_type metadata deformations
cluster_transforms nucleotide_transforms cluster_joints cluster_join_constraints
overhangs overhang_connections overhang_bindings connection_versions duplexes
flexible_segment_marks flexible_connections protein_assets protein_attachments
nanoparticles nanoparticle_conjugations nanoparticle_connection_versions
tm_settings extensions staple_groups photoproduct_junctions crossovers
crossover_constraints forced_ligations
""".split()
_PRESENTATION = """
plate_layout representation_overrides view_volumes annotations annotations_enabled
visibility_state camera_poses animations
""".split()
_PHYSICAL = "chain_sim_projects loadouts atomistic_reference active_loadout_id last_editable_loadout_id".split()
_HISTORY = "feature_log feature_log_cursor feature_log_sub_cursor recipe_root".split()
FIELD_ROLES = MappingProxyType({
    **dict.fromkeys(_AUTHORING, "authoring"),
    **dict.fromkeys(_PRESENTATION, "presentation"),
    **dict.fromkeys(_PHYSICAL, "physical"),
    **dict.fromkeys(_HISTORY, "history"),
    "input_sources": "input_source",
    "repair_draft": "repair_draft",
    "id": "document_identity",
})


def create_empty_part(name, lattice_type):
    """Record provenance only at the explicit new-empty-document boundary."""
    from backend.core.models import Design, DesignMetadata
    return Design(
        metadata=DesignMetadata(name=name), lattice_type=lattice_type,
        recipe_root=PartRecipeRoot(initial_name=name, lattice_type=lattice_type),
    )


def assess_part_history(design, *, max_entries=2000, execute=None, dependencies=None, checkpoint=None):
    """Read-only coverage/proof result for an already isolated Design.

Never invokes the recovery evaluator, decompresses a snapshot, changes IDs,
or silently treats an unsupported command as an import. No certificate is
persisted. API callers bind the result to the captured session/revision.
"""
    from backend.core.part_history_proof import assess
    return assess(design, max_entries=max_entries, execute=execute,
                  dependencies=dependencies, checkpoint=checkpoint)
