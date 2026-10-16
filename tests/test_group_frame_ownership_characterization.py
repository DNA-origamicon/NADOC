"""ISSUE-106: characterize an invalid legacy output, not desired grouping behavior.

This target stays separate from the deformation-retarget acceptance dossier.
Saved v1 output stays unchanged. New v2 grouping has a separate successful
roundtrip/replay acceptance suite; explicit verification flags this old defect.
"""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.api import part_proof_commands
from backend.core.models import ClusterCreateLogEntry, ClusterRigidTransform, Design
from backend.core.part_history_contract import assess_part_history
from tests.test_part_deformation_preview import _append, native_source


def test_legacy_all_members_group_dangles_lattice_frame_placement_owner():
    source = native_source()
    source = source.copy_with(feature_log=source.feature_log[:-1], deformations=[])
    assert Design.model_validate_json(source.model_dump_json()) == source
    placement_id = source.lattice_frames[0].placement_cluster_id
    assert any(group.id == placement_id and group.is_default for group in source.cluster_transforms)
    group = ClusterRigidTransform(id=str(uuid4()), name="All helices",
        helix_ids=[helix.id for helix in source.helices])
    candidate = _append(source, ClusterCreateLogEntry(cluster_id=group.id, name=group.name,
        helix_ids=group.helix_ids, cluster_snapshot=group, proof_version=1))
    assert candidate.lattice_frames == source.lattice_frames
    assert placement_id not in {group.id for group in candidate.cluster_transforms}
    with pytest.raises(ValidationError, match="lattice frame placement cluster is missing"):
        Design.model_validate_json(candidate.model_dump_json())
    # Reproduction succeeds, while structural closure correctly refuses an
    # overall verified/editable result. Old authored inputs are not upgraded.
    report = assess_part_history(candidate, execute=part_proof_commands.execute,
                                 dependencies=part_proof_commands.dependencies)
    assert report["status"] == "failed", report
    assert report["reproducibility_status"] == "verified"
    assert report["structure"]["status"] == "invalid"
