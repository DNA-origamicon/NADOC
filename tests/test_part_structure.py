"""Finite, geometry-free structural checks on independently owned models."""

from copy import deepcopy

import pytest

from backend.core.lattice_frame_model import LatticeFrame
from backend.core.models import ClusterRigidTransform, Design, Helix, Vec3
from backend.core.part_structure import MAX_ID_CHARS, assess_structure


def source():
    return Design(cluster_transforms=[ClusterRigidTransform(id="placement", helix_ids=["h"])],
                  lattice_frames=[LatticeFrame(id="frame", placement_cluster_id="placement")],
                  helices=[Helix(id="h", axis_start=Vec3(x=0, y=0, z=0),
                                 axis_end=Vec3(x=0, y=0, z=1), length_bp=3,
                                 lattice_frame_id="frame", grid_pos=(0, 0))])


def test_valid_frame_ownership_is_structural_only_and_does_not_mutate_or_serialize(monkeypatch):
    design = source()
    before = deepcopy(design)

    def forbidden(*args, **kwargs):
        raise AssertionError("Structural checking must not serialize, reparse, or derive geometry")

    for name in ("model_dump", "model_dump_json", "model_validate", "model_validate_json"):
        monkeypatch.setattr(Design, name, forbidden)
    monkeypatch.setattr("backend.core.geometry.nucleotide_positions_arrays", forbidden)
    report = assess_structure(design)
    assert report == {"scope": "part_structural_references", "version": 1, "status": "valid",
                      "complete": True, "scientific_integrity_checked": False,
                      "checked_counts": {"clusters": 1, "frames": 1, "helices": 1},
                      "observed_errors": 0, "issues": []}
    assert design == before


@pytest.mark.parametrize("unframed", [False, True])
def test_no_frame_designs_do_not_gain_implicit_placement_or_cell_requirements(unframed):
    design = Design()
    if unframed:
        design = design.copy_with(helices=[source().helices[0].model_copy(
            update={"lattice_frame_id": None, "grid_pos": None})])
    assert assess_structure(design)["status"] == "valid"


def test_missing_owner_reports_exact_frame_and_reference_without_a_fake_command_path():
    design = source().copy_with(cluster_transforms=[])
    before = deepcopy(design)
    report = assess_structure(design)
    assert report["status"] == "invalid" and report["complete"]
    assert report["issues"] == [{"code": "missing_reference",
        "model_path": ["lattice_frames", 0, "placement_cluster_id"],
        "resource": {"kind": "lattice_frame", "identity": "frame"},
        "reference": {"kind": "cluster", "identity": "placement"}}]
    assert report["observed_errors"] == 1
    assert design == before


@pytest.mark.parametrize("field,kind,reference_kind", [
    ("cluster_transforms", "cluster", "cluster"),
    ("lattice_frames", "lattice_frame", "lattice_frame"),
    ("helices", "helix", None),
])
def test_duplicate_identities_are_not_silently_last_wins(field, kind, reference_kind):
    design = source()
    values = getattr(design, field)
    design = design.copy_with(**{field: [*values, values[0].model_copy(deep=True)]})
    report = assess_structure(design)
    assert report["status"] == "invalid"
    duplicate = report["issues"][0]
    assert duplicate == {"code": "duplicate_identity", "model_path": [field, 1, "id"],
        "resource": {"kind": kind, "identity": values[0].id}, "first_model_path": [field, 0, "id"]}
    ambiguous = [issue for issue in report["issues"] if issue["code"] == "ambiguous_reference"]
    assert len(ambiguous) == (0 if reference_kind is None else 1)
    if ambiguous:
        assert ambiguous[0]["reference"]["kind"] == reference_kind


def test_missing_frame_and_cell_are_independent_typed_errors():
    design = source()
    design = design.copy_with(helices=[design.helices[0].model_copy(
        update={"lattice_frame_id": "missing", "grid_pos": None})])
    report = assess_structure(design)
    assert report["status"] == "invalid"
    assert report["issues"] == [
        {"code": "missing_reference", "model_path": ["helices", 0, "lattice_frame_id"],
         "resource": {"kind": "helix", "identity": "h"},
         "reference": {"kind": "lattice_frame", "identity": "missing"}},
        {"code": "missing_lattice_cell", "model_path": ["helices", 0, "grid_pos"],
         "resource": {"kind": "helix", "identity": "h"}},
    ]


def test_item_limit_is_checked_before_indexing_or_checkpointing_individual_records():
    calls = []
    report = assess_structure(source(), max_items=2, checkpoint=lambda: calls.append(True))
    assert report["status"] == "incomplete" and not report["complete"]
    assert report["limit"] == {"code": "structure_item_limit", "maximum": 2}
    assert report["checked_counts"] == {"clusters": 0, "frames": 0, "helices": 0}
    assert calls == [True]
    assert assess_structure(source(), max_items=3)["status"] == "valid"


@pytest.mark.parametrize("maximum", [0, 1])
def test_issue_cap_never_labels_observed_errors_valid_or_overflows_the_issue_list(maximum):
    design = source().copy_with(cluster_transforms=[], lattice_frames=[])
    design = design.copy_with(helices=[design.helices[0].model_copy(update={"grid_pos": None})])
    before = deepcopy(design)
    report = assess_structure(design, max_issues=maximum)
    assert report["status"] == "incomplete" and not report["complete"]
    assert report["observed_errors"] == maximum + 1
    assert len(report["issues"]) == maximum
    assert report["limit"] == {"code": "structure_issue_limit", "maximum": maximum}
    assert design == before


def test_exact_issue_cap_is_complete_when_no_diagnostic_was_omitted():
    report = assess_structure(source().copy_with(cluster_transforms=[]), max_issues=1)
    assert report["status"] == "invalid" and report["complete"]
    assert "limit" not in report


@pytest.mark.parametrize("location", ["id", "reference"])
def test_oversized_identities_are_refused_before_hashing(location):
    class UnhashableText(str):
        def __hash__(self):
            raise AssertionError("Oversized identity was hashed")

    design = source()
    # Exact strings are the persisted contract. A long actual str exercises the
    # byte/work bound; the subclass separately exercises fail-closed shape.
    value = "x" * (MAX_ID_CHARS + 1)
    if location == "id":
        design = design.copy_with(cluster_transforms=[design.cluster_transforms[0].model_copy(update={"id": value})])
    else:
        design = design.copy_with(lattice_frames=[design.lattice_frames[0].model_copy(update={"placement_cluster_id": value})])
    report = assess_structure(design)
    assert report["status"] == "incomplete" and not report["complete"]
    assert report["limit"]["code"] == "structure_identity_limit"
    assert value not in repr(report)
    design = source().copy_with(cluster_transforms=[source().cluster_transforms[0].model_copy(update={"id": UnhashableText("p")})])
    assert assess_structure(design)["status"] == "invalid"


def test_checkpoint_cancellation_is_not_converted_to_a_successful_partial_report():
    class Cancelled(BaseException):
        pass

    design, calls = source(), []
    before = deepcopy(design)

    def checkpoint():
        calls.append(True)
        if len(calls) == 4:
            raise Cancelled()

    with pytest.raises(Cancelled):
        assess_structure(design, checkpoint=checkpoint)
    assert design == before


@pytest.mark.parametrize("parameter,value", [("max_items", -1), ("max_items", True),
                                            ("max_issues", -1), ("max_issues", 1.5)])
def test_invalid_allowances_are_programmer_errors(parameter, value):
    with pytest.raises(ValueError, match="nonnegative integers"):
        assess_structure(source(), **{parameter: value})


def test_unsupported_collection_shape_is_explicitly_incomplete():
    report = assess_structure(source().copy_with(lattice_frames=()))
    assert report["status"] == "incomplete" and not report["complete"]
    assert report["limit"] == {"code": "structure_input_shape", "model_path": ["lattice_frames"]}
