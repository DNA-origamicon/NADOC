"""Native landmark and oxDNA particle frames share sites, never coordinates."""

from copy import deepcopy

import numpy as np
import pytest

from backend.core.deformation import deformed_nucleotide_arrays
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import LatticeType, LoopSkip, NucleotideTransform
from backend.core.native_full_placement import NativePlacementError
from backend.physics.native_oxdna import PHYSICAL_SOURCE, native_full_to_oxdna_geometry
from tests.test_native_full_placement import _changed_design

pytestmark = pytest.mark.native_placement


@pytest.mark.parametrize("kind", ["bend", "twist"])
@pytest.mark.parametrize("scoped", [False, True])
@pytest.mark.parametrize("lattice", [LatticeType.HONEYCOMB, LatticeType.SQUARE])
@pytest.mark.parametrize("compact", [False, True])
def test_native_converts_to_independent_calibrated_physical_sites(kind, scoped, lattice, compact,
                                                               native_placement_evidence):
    design = _changed_design(kind, scoped=scoped, lattice=lattice)
    helix = design.helices[0].model_copy(update={"loop_skips": [LoopSkip(bp_index=15, delta=2)]})
    design = design.copy_with(helices=[helix])
    native = _geometry_for_design(design, compact_skips=compact)
    before = deepcopy(native)
    physical = native_full_to_oxdna_geometry(design, native)
    # Independent original geometric-site projection, with no native serializer.
    expected = deformed_nucleotide_arrays(helix, design, compact_skips=compact)
    for field, array_field in [("backbone_position", "positions"), ("base_normal", "base_normals"),
                               ("axis_tangent", "axis_tangents")]:
        actual = np.asarray([record[field] for record in physical])
        wanted = expected[array_field]
        native_placement_evidence(field=field, kind=kind, scoped=scoped, lattice=lattice.value,
            compact_skips=compact, expected=wanted.tolist(), actual=actual.tolist(),
            max_displacement_nm=float(np.linalg.norm(actual-wanted, axis=1).max()))
        np.testing.assert_allclose(actual, wanted, rtol=0, atol=2e-12)
    assert native == before
    assert all(record["placement_source"] == PHYSICAL_SOURCE for record in physical)
    assert all("helical_site" not in record and "slab_position" not in record for record in physical)
    assert native_full_to_oxdna_geometry(design, physical) == physical


def test_residue_pose_transports_physical_site_and_preserves_partner():
    design = _changed_design("bend", scoped=True)
    baseline = native_full_to_oxdna_geometry(design, _geometry_for_design(design))
    pose = NucleotideTransform(kind="base", helix_id="h0", bp_index=15, direction="FORWARD",
        copy_k=0, pivot=[2, 1, -1], translation=[3, -7, 2], rotation=[0, 0, 1, 0])
    changed = design.copy_with(nucleotide_transforms=[pose])
    actual = native_full_to_oxdna_geometry(changed, _geometry_for_design(changed))
    rotation = np.diag([-1, -1, 1])
    for before, after in zip(baseline, actual, strict=True):
        if before["bp_index"] == 15 and before["direction"] == "FORWARD":
            expected = np.asarray(pose.pivot) + rotation @ (np.asarray(before["backbone_position"])-pose.pivot) + pose.translation
            np.testing.assert_allclose(after["backbone_position"], expected, rtol=0, atol=2e-12)
        else:
            assert before == after


@pytest.mark.parametrize("damage", ["missing_site", "stale_bead", "missing_source", "wrong_source", "nonfinite"])
def test_bad_native_metadata_cannot_be_exported_as_a_physical_frame(damage):
    design = _changed_design("bend")
    records = _geometry_for_design(design)
    if damage == "missing_site":
        del records[0]["helical_site"]
    elif damage == "stale_bead":
        records[0]["backbone_position"][0] += 0.1
    elif damage == "missing_source":
        del records[0]["placement_source"]
    elif damage == "wrong_source":
        records[0]["placement_source"] = "unknown-landmark"
    else:
        records[0]["helical_site"]["phase_roll_rad"] = float("nan")
    with pytest.raises(NativePlacementError):
        native_full_to_oxdna_geometry(design, records)


def test_authored_physical_fold_is_never_inferred_from_its_radius():
    design = _changed_design("bend")
    records = [{"helix_id": "h0", "bp_index": 0, "direction": "FORWARD",
                "backbone_position": [0.8491, 0, 0], "base_normal": [0, 1, 0],
                "axis_tangent": [0, 0, 1]}]
    assert native_full_to_oxdna_geometry(design, records)[0] is records[0]


@pytest.mark.parametrize("missing", ["extension_only", "absent_anchor", "physical_anchor"])
def test_native_extension_cannot_be_relabelled_without_its_native_anchor(missing):
    from backend.core.models import StrandExtension
    from backend.physics.oxdna_interface import extension_beads

    design = _changed_design("bend")
    design = design.copy_with(extensions=[StrandExtension(
        strand_id=design.strands[0].id, end="three_prime", sequence="TT")])
    geometry = _geometry_for_design(design)
    bead, anchor, _end = extension_beads(design)[0]
    key = lambda record: (record["helix_id"], record["bp_index"], record["direction"])
    if missing == "extension_only":
        geometry = [record for record in geometry if record["placement_source"] == "native-full-extension-v1"]
    elif missing == "absent_anchor":
        geometry = [record for record in geometry if key(record) != anchor]
    else:
        physical = native_full_to_oxdna_geometry(design, geometry)
        replacement = next(record for record in physical if key(record) == anchor)
        geometry = [replacement if key(record) == anchor else record for record in geometry]
    with pytest.raises(NativePlacementError, match="native anchor frame") as caught:
        native_full_to_oxdna_geometry(design, geometry)
    assert bead in caught.value.details["unconverted_extensions"]


@pytest.mark.parametrize("reverse", [False, True])
def test_prospective_complement_and_bridge_export_have_complete_source_sites(reverse):
    from backend.core.design_geometry import _emit_bridge_nucs, native_full_nucleotide_at
    from backend.core.models import Direction
    from tests.test_native_placement_linker import _bridge_fixture

    design = _changed_design("bend", scoped=True)
    direction = Direction.REVERSE if reverse else Direction.FORWARD
    anchor = native_full_nucleotide_at(design.helices[0], design, 17, direction)
    converted = native_full_to_oxdna_geometry(design, [anchor])
    expected = deformed_nucleotide_arrays(design.helices[0], design)
    index = np.flatnonzero((expected["bp_indices"] == 17) & (expected["directions"] == reverse))[0]
    np.testing.assert_allclose(converted[0]["backbone_position"], expected["positions"][index], rtol=0, atol=2e-12)

    bridge_design, records, *_ = _bridge_fixture(8, reverse, reverse)
    _emit_bridge_nucs(bridge_design, {}, records)
    bridges = [record for record in records if record["helix_id"] == "__lnk__bridge"]
    physical = native_full_to_oxdna_geometry(bridge_design, bridges)
    assert len(physical) == 16
    for native, record in zip(bridges, physical, strict=True):
        axis = np.asarray(native["helical_site"]["axis_point"])
        radial = np.asarray(record["backbone_position"]) - axis
        assert np.linalg.norm(radial) == pytest.approx(1.0, abs=2e-12)
        assert np.dot(radial, record["axis_tangent"]) == pytest.approx(0.0, abs=2e-12)
