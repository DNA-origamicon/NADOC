"""The full owned oxDNA archive retains saved upgrade proposals as metadata."""

import pytest

from tests.test_group_upgrade_draft_lifecycle import basis, proposal


def test_full_archive_keeps_exact_saved_group_upgrade_and_owns_its_actions():
    from backend.core.oxdna_preparation_inputs import capture_archive

    design = basis()
    design = design.copy_with(repair_draft=proposal(design))
    before = design.model_dump(mode="json")
    archived = capture_archive(design)
    assert archived.model_dump(mode="json") == before
    assert archived.repair_draft is not design.repair_draft
    assert archived.repair_draft.actions[0] is not design.repair_draft.actions[0]
    design.repair_draft.actions[0].expected_cluster_id = "changed-after-capture"
    assert archived.model_dump(mode="json") == before


def test_new_upgrade_action_does_not_permit_unreviewed_archival_fields():
    from backend.core.oxdna_preparation_inputs import UnsupportedPreparation, capture_archive

    design = basis()
    design = design.copy_with(repair_draft=proposal(design))
    design.repair_draft.actions[0].__dict__["candidate"] = {}
    with pytest.raises(UnsupportedPreparation):
        capture_archive(design)
