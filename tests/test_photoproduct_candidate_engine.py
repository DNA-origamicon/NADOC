from __future__ import annotations

from pathlib import Path

import numpy as np

from backend.parameterization.photoproduct_candidate_engine import (
    _boundary_pdb,
    _minimum_nonbonded_heavy_ratio,
    _namd_config,
    _psfgen_script,
    _solution_namd_config,
)


def test_boundary_pdb_groups_all_atoms_by_residue_and_maps_charmm_names():
    atom_map = ["1:C7", "2:OP1", "1:HO5'", "2:HO3'"]
    elements = ["C", "O", "H", "H"]
    coordinates = np.arange(12, dtype=float).reshape(4, 3)
    lines = _boundary_pdb(atom_map, elements, coordinates).splitlines()
    atom_lines = [line for line in lines if line.startswith("ATOM")]

    assert [int(line[22:26]) for line in atom_lines] == [1, 1, 2, 2]
    assert [line[12:16].strip() for line in atom_lines] == [
        "C5M",
        "H5T",
        "O1P",
        "H3T",
    ]


def test_candidate_dynamics_is_ordinary_mass_two_fs(tmp_path):
    text = _namd_config(
        topology_psf=tmp_path / "product.psf",
        starting_coordinates=tmp_path / "output/min.coor",
        nucleic_parameters=tmp_path / "na.prm",
        lesion_parameters=tmp_path / "cpd.prm",
        output_stem=tmp_path / "output/dynamics",
        action="dynamics",
        steps=1000,
        dcd_path=tmp_path / "output/dynamics.dcd",
    )

    assert "binCoordinates" in text
    assert "rigidBonds all" in text
    assert "timestep 2.0" in text
    assert "run 1000" in text
    assert "hmr" not in text.lower()


def test_candidate_config_can_use_short_relative_archive_output_paths():
    text = _namd_config(
        topology_psf=Path("product.psf"),
        starting_coordinates=Path("output/min.coor"),
        nucleic_parameters=Path("/forcefield/na.prm"),
        lesion_parameters=Path("/forcefield/cpd.prm"),
        output_stem=Path("output/dynamics"),
        action="dynamics",
        steps=1000,
        dcd_path=Path("output/dynamics.dcd"),
    )

    assert "structure product.psf" in text
    assert "binCoordinates output/min.coor" in text
    assert "outputName output/dynamics" in text
    assert "dcdFile output/dynamics.dcd" in text


def test_candidate_psfgen_script_uses_the_selected_variant_patch(tmp_path):
    text = _psfgen_script(
        topology=tmp_path / "na.rtf",
        lesion_topology=tmp_path / "variant.rtf",
        pdb=tmp_path / "boundary.pdb",
        output_dir=tmp_path,
        product=True,
        patch_name="CPDVAR1",
    )

    assert "topology " + str(tmp_path / "variant.rtf") in text
    assert "patch CPDVAR1 D000:1 D000:2" in text
    assert "TCPDCS1" not in text


def test_candidate_solution_config_is_periodic_ordinary_mass_and_two_fs(tmp_path):
    text = _solution_namd_config(
        topology_psf=Path("product_solvated.psf"),
        starting_coordinates=Path("output/heat.coor"),
        nucleic_parameters=tmp_path / "na.prm",
        lesion_parameters=tmp_path / "cpd.prm",
        water_parameters=tmp_path / "water.str",
        ion_nbfix_parameters=tmp_path / "ions.str",
        output_stem=Path("output/dynamics"),
        box_nm=(4.0, 4.1, 4.2),
        action="dynamics",
        steps=50000,
        dcd_path=Path("output/dynamics.dcd"),
        previous_output=Path("output/heat"),
    )

    assert "PME yes" in text
    assert "cellBasisVector3 0.0 0.0 42.000000" in text
    assert "binCoordinates output/heat.coor" in text
    assert "binVelocities output/heat.vel" in text
    assert "extendedSystem output/heat.xsc" in text
    assert "rigidBonds all" in text
    assert "timestep 2.0" in text
    assert "run 50000" in text
    assert "hmr" not in text.lower()


def test_periodic_neighbor_audit_is_exact_and_honors_exclusions():
    coordinates = np.asarray(
        [
            [0.1, 0.1, 0.1],
            [9.9, 0.1, 0.1],
            [5.0, 5.0, 5.0],
            [5.8, 5.0, 5.0],
        ],
        dtype=float,
    )
    radii = {index: 1.0 for index in range(4)}
    ratio, pair = _minimum_nonbonded_heavy_ratio(
        coordinates,
        list(range(4)),
        radii,
        {frozenset((0, 1))},
        np.asarray([10.0, 10.0, 10.0, 90.0, 90.0, 90.0]),
    )

    assert pair == (2, 3)
    assert np.isclose(ratio, 0.4)
