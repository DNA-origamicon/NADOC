"""Real deposited G4s must remain real, editable native DNA across projections."""

import numpy as np
import pytest

from backend.core.aptamer import import_aptamer, template_content
from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.lattice import resize_strand_ends
from backend.core.models import Design


@pytest.mark.parametrize("pid,length", [("148D", 15), ("1C35", 15), ("2HY9", 26)])
def test_templates_roundtrip_and_atom_coordinate_identity(pid, length):
    original = import_aptamer(template_content(pid), pid)
    design = Design.model_validate_json(original.model_dump_json())
    assert design.strands[0].id == original.strands[0].id
    assert len(design.strands[0].sequence) == length
    assert len(design.strands[0].domains) == 1
    assert not design.strands[0].is_reference
    geometry = _geometry_for_design(design, measured_positioning=True)
    assert len(geometry) == length
    assert sum(n["is_five_prime"] for n in geometry) == 1
    assert {n["strand_id"] for n in geometry} == {design.strands[0].id}
    atoms = build_atomistic_model(design).atoms
    for site in design.helices[0].native_residues:
        source = site.atoms
        projected = [a for a in atoms if a.bp_index == site.bp_index]
        for atom in projected:
            if atom.name in source:
                np.testing.assert_allclose(
                    [atom.x, atom.y, atom.z], source[atom.name].to_array(), atol=1e-10
                )
        np.testing.assert_allclose(
            geometry[site.bp_index]["backbone_position"], source["C1'"].to_array()
        )


def test_native_sites_move_with_cluster_in_both_representations():
    design = import_aptamer(template_content("148D"))
    design.cluster_transforms[0].translation = [3, -4, 2]
    design.cluster_transforms[0].rotation = [0, 0, 1, 0]
    g = _geometry_for_design(design)
    a = build_atomistic_model(design).atoms
    for site in design.helices[0].native_residues:
        expected = site.atoms["C1'"].to_array() * [-1, -1, 1] + [3, -4, 2]
        np.testing.assert_allclose(g[site.bp_index]["backbone_position"], expected)
        atom = next(a for a in a if a.bp_index == site.bp_index and a.name == "C1'")
        np.testing.assert_allclose([atom.x, atom.y, atom.z], expected)


def test_both_ends_resize_keeps_core_sequence_geometry_and_id():
    design = import_aptamer(template_content("148D"))
    strand = design.strands[0]
    hid = design.helices[0].id
    grown = resize_strand_ends(
        design,
        [
            dict(strand_id=strand.id, helix_id=hid, end="5p", delta_bp=-3),
            dict(strand_id=strand.id, helix_id=hid, end="3p", delta_bp=4),
        ],
    )
    assert grown.strands[0].id == strand.id
    assert grown.strands[0].sequence == "NNN" + strand.sequence + "NNNN"
    geometry = _geometry_for_design(grown)
    assert len(geometry) == 22
    assert np.isfinite(
        [[a.x, a.y, a.z] for a in build_atomistic_model(grown).atoms]
    ).all()
    for nuc in geometry:
        if 0 <= nuc["bp_index"] < 15:
            np.testing.assert_allclose(
                nuc["backbone_position"],
                design.helices[0]
                .native_residues[nuc["bp_index"]]
                .atoms["C1'"]
                .to_array(),
            )
    by_bp = {n["bp_index"]: np.array(n["backbone_position"]) for n in geometry}
    # Attachment tails now follow B-DNA slots so antiparallel binders form a
    # duplex; their terminal step is the same on both sides of the native core.
    step = np.linalg.norm(by_bp[-1] - by_bp[0])
    assert 0.5 < step < 0.8
    assert np.linalg.norm(by_bp[15] - by_bp[14]) == pytest.approx(step)
    restored = resize_strand_ends(
        grown,
        [
            dict(strand_id=strand.id, helix_id=hid, end="5p", delta_bp=3),
            dict(strand_id=strand.id, helix_id=hid, end="3p", delta_bp=-4),
        ],
    )
    assert restored.strands[0].sequence == strand.sequence


def test_ter_and_insertion_codes_preserve_distinct_strands():
    lines = [l for l in template_content("148D").splitlines() if l.startswith("ATOM")]
    text = "\n".join(lines + ["TER"] + lines)
    design = import_aptamer(text)
    assert len(design.strands) == 2
    assert len({s.id for s in design.strands}) == 2
    assert len(_geometry_for_design(design)) == 30
    # Each source residue gets a distinct insertion code even with shared resSeq.
    inserted = "\n".join(
        l[:22] + "   1" + chr(64 + int(l[22:26])) + l[27:] for l in lines
    )
    assert len(import_aptamer(inserted).strands[0].sequence) == 15


def test_broken_backbone_and_missing_frame_fail_without_dropping_residues():
    text = template_content("148D")
    lines = [
        l
        for l in text.splitlines()
        if not (l.startswith("ATOM") and int(l[22:26]) == 3)
    ]
    with pytest.raises(ValueError, match="Broken DNA backbone"):
        import_aptamer("\n".join(lines))
    with pytest.raises(ValueError, match="Incomplete DNA residue"):
        import_aptamer("\n".join(l for l in text.splitlines() if "C1'" not in l))


def test_api_import_merge_undo_and_resize():
    from backend.api import state
    from backend.api.routes_design_interchange import (
        AptamerImportRequest,
        import_aptamer_design,
    )
    from backend.api.crud import (
        StrandEndResizeRequest,
        StrandEndResizeEntry,
        strand_end_resize,
    )

    state.load_design(None)
    state.clear_history()
    try:
        result = import_aptamer_design(AptamerImportRequest(template_id="148D"))
        first = result["design"]["strands"][0]
        result = import_aptamer_design(AptamerImportRequest(template_id="2HY9"))
        assert len(result["design"]["strands"]) == 2
        assert result["design"]["strands"][0]["id"] == first["id"]
        result = strand_end_resize(
            StrandEndResizeRequest(
                entries=[
                    StrandEndResizeEntry(
                        strand_id=first["id"],
                        helix_id=first["domains"][0]["helix_id"],
                        end="3p",
                        delta_bp=3,
                    )
                ]
            )
        )
        assert result["partial_geometry"]
        assert len(result["nucleotides"]) == 18
        assert result["design"]["strands"][0]["sequence"].endswith("NNN")
        state.undo()
        assert len(state.get_design().strands) == 2
        state.undo()
        assert len(state.get_design().strands) == 1
        state.redo()
        assert len(state.get_design().strands) == 2
    finally:
        state.load_design(None)
        state.clear_history()


def test_coarse_axis_projection_traces_fold_and_extended_ends():
    from backend.core.deformation import deformed_helix_axes

    design = import_aptamer(template_content("148D"))
    axis = deformed_helix_axes(design)[0]
    points = [n["backbone_position"] for n in _geometry_for_design(design)]
    np.testing.assert_allclose(axis["samples"], points)
    assert len(axis["samples"]) == 15
    design.cluster_transforms[0].translation = [1, 2, 3]
    np.testing.assert_allclose(
        deformed_helix_axes(design)[0]["samples"], np.array(points) + [1, 2, 3]
    )


def test_native_oligo_complex_does_not_require_a_scaffold():
    from backend.core.validator import validate_design

    design = import_aptamer(template_content("148D"))
    assert validate_design(design).passed
