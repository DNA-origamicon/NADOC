import numpy as np


def test_empty_design_automatically_selects_graphene_control_protocol():
    from backend.api.routes_md import CreateJobRequest, _infer_graphene_only
    from backend.core.models import Design

    body = CreateJobRequest(graphene_nanopore=True)
    inferred = _infer_graphene_only(body, Design())
    assert inferred.graphene_only is True
    assert inferred.graphene_nanopore is True

    ordinary = _infer_graphene_only(CreateJobRequest(), Design())
    assert ordinary.graphene_only is False


def test_unsequenced_dna_is_not_mistaken_for_graphene_only():
    from types import SimpleNamespace
    from backend.api.routes_md import CreateJobRequest, _infer_graphene_only

    design = SimpleNamespace(strands=[SimpleNamespace(sequence=None)])
    inferred = _infer_graphene_only(CreateJobRequest(graphene_nanopore=True), design)
    assert inferred.graphene_only is False


def test_graphene_sheet_has_requested_hole_and_plane():
    from backend.core.namd_solvate import _graphene_pdb_atoms

    dna = "ATOM      1  P    DA A   1     -10.000 -10.000   5.000  1.00  0.00\n"
    spec = {
        "dir": [0, 0, 1], "position_nm": 0.0,
        "pore_center_nm": [0, 0, 0], "pore_diameter_nm": 2.1,
    }
    lines = _graphene_pdb_atoms(dna, spec)
    assert len(lines) > 100
    xyz = np.asarray([[float(x[30:38]) / 10, float(x[38:46]) / 10,
                       float(x[46:54]) / 10] for x in lines])
    assert np.max(np.abs(xyz[:, 2])) < 1e-6
    assert np.min(np.linalg.norm(xyz[:, :2], axis=1)) >= 1.05 - 1e-3
    assert all(x[72:76].strip().startswith("GR") for x in lines)


def test_graphene_over_9999_atoms_splits_segments_without_corrupting_pdb_columns():
    from backend.core.namd_solvate import _graphene_identity, _hetatm_record

    assert _graphene_identity(9998) == ("GR00", 9999)
    assert _graphene_identity(9999) == ("GR01", 1)
    segid, resid = _graphene_identity(10_000)
    line = _hetatm_record(10_001, "C", "GRP", "G", resid, 100.84, -42.062,
                          -120.7, segname=segid)
    assert float(line[30:38]) == 100.84
    assert float(line[38:46]) == -42.062
    assert float(line[46:54]) == -120.7
    assert line[72:76].strip() == "GR01"


def test_graphene_hydration_shell_removes_only_overlapping_waters():
    from backend.core.namd_solvate import (
        _Water, _exclude_waters_near_graphene, _hetatm_record,
    )

    graphene = _hetatm_record(1, "C", "GRP", "G", 1, 0, 0, 0, segname="GR00")
    near = _Water(0.10, 0, 0, 0.10, 0, 0, 0.10, 0, 0)
    far = _Water(0.40, 0, 0, 0.40, 0, 0, 0.40, 0, 0)
    kept, removed = _exclude_waters_near_graphene([near, far], graphene)
    assert kept == [far]
    assert removed == 1


def test_graphene_plane_moves_outside_atomistic_dna_protrusion():
    from backend.core.namd_solvate import _graphene_pdb_atoms

    dna = "ATOM      1  P    DA A   1       0.000  -2.000   0.000  1.00  0.00\n"
    spec = {"dir": [0, 1, 0], "pore_center_nm": [0, 0, 0],
            "pore_diameter_nm": 2.1}
    lines = _graphene_pdb_atoms(dna, spec)
    ys = np.asarray([float(line[38:46]) / 10 for line in lines])
    assert np.max(np.abs(ys - 0.12)) < 1e-6
    assert spec["atomistic_clearance_shift_nm"] == 0.12


def test_graphene_layers_extend_away_from_dna_with_requested_spacing():
    from backend.core.namd_solvate import _graphene_pdb_atoms

    dna = "ATOM      1  P    DA A   1       0.000   0.000   5.000  1.00  0.00\n"
    spec = {
        "dir": [0, 0, 1], "pore_center_nm": [0, 0, 0],
        "pore_diameter_nm": 2.1, "layers": 3, "layer_spacing_nm": 0.335,
    }
    lines = _graphene_pdb_atoms(dna, spec)
    zs = np.asarray([float(line[46:54]) / 10 for line in lines])

    assert np.allclose(sorted(np.unique(np.round(zs, 3))), [-0.67, -0.335, 0.0])
    assert spec["thickness_nm"] == 0.67


def test_graphene_only_sheet_builds_without_dna_and_tiles_xy_cell():
    from backend.core.namd_solvate import _graphene_pdb_atoms, _recenter_pdb_in_padded_box

    spec = {"dir": [0, 0, 1], "pore_center_nm": [0, 0, 0],
            "pore_diameter_nm": 2.1, "layers": 1}
    lines = _graphene_pdb_atoms("END\n", spec)
    assert lines
    pdb, box = _recenter_pdb_in_padded_box(
        "\n".join(lines) + "\nEND\n", 3.0, "bbox", (0.08, 0.08, 3.0),
    )
    xyz = np.asarray([[float(x[30:38]) / 10, float(x[38:46]) / 10,
                       float(x[46:54]) / 10] for x in pdb.splitlines()
                      if x.startswith("HETATM")])
    assert box[2] >= 6.0
    assert xyz[:, 0].min() < 0.1 and box[0] - xyz[:, 0].max() < 0.1
    assert xyz[:, 1].min() < 0.1 and box[1] - xyz[:, 1].max() < 0.1


def test_graphene_surface_axis_and_offset_select_requested_design_face():
    from backend.core.namd_solvate import _graphene_pdb_atoms

    dna = "\n".join([
        "ATOM      1  P    DA A   1     -10.000 -20.000 -30.000  1.00  0.00",
        "ATOM      2  P    DA A   2      40.000  50.000  60.000  1.00  0.00",
    ]) + "\n"
    for axis, coord_index, expected in (
        ("-x", 0, -1.5), ("+x", 0, 4.5),
        ("-y", 1, -2.5), ("+y", 1, 5.5),
        ("-z", 2, -3.5), ("+z", 2, 6.5),
    ):
        spec = {"surface_axis": axis, "surface_offset_nm": 0.5,
                "atomistic_clearance_nm": 0.32, "pore_diameter_nm": 2.1}
        lines = _graphene_pdb_atoms(dna, spec)
        coords = np.asarray([[float(line[30:38]) / 10, float(line[38:46]) / 10,
                              float(line[46:54]) / 10] for line in lines])
        assert np.allclose(coords[:, coord_index], expected, atol=1e-3)
        assert spec["surface_axis"] == axis
        assert spec["surface_offset_nm"] == 0.5
