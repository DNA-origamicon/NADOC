"""Representative ordinary Move/Rotate display under production allowances."""
import pytest

from backend.api import part_transform_preview as native, part_transform_preview_dto as dto
from backend.api.part_deformation_preview_sessions import capture
from backend.core.design_geometry import _geometry_for_design
from backend.core.part_dna_comparison_codec import unpack_records
from tests.deformation_history_app import fixture


@pytest.mark.slow
@pytest.mark.parametrize("size", ["small", "large"])
def test_representative_transform_keeps_exact_native_poses_and_ownership(size):
    source = fixture(f"transform-{size}")
    prepared = native.prepare_from_capture(capture(source, preserve_entry_types=True), "selected-transform")
    before = prepared.copy_prefix().model_dump(mode="json")
    evaluated = native.evaluate(prepared, {"translation": [7, 2, 3]})
    packet = dto.prepare_display(prepared.display_prefix(), evaluated)
    assert prepared.copy_prefix().model_dump(mode="json") == before
    assert packet["before"]["component_version"] == 2
    assert packet["candidate"]["component_version"] == 2
    assert unpack_records(packet["candidate"]["nucleotides"]) == _geometry_for_design(evaluated.design)
    assert unpack_records(packet["before"]["nucleotides"]) == _geometry_for_design(prepared.copy_prefix())
    assert packet["candidate"]["nucleotides"]["count"] > (16000 if size == "large" else 900)
