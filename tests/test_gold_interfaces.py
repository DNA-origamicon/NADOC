"""Independent crystal, physical-unit and package contract checks for bare gold."""

import json
import math

import numpy as np
import pytest
from scipy.spatial import cKDTree

from backend.core import gold_geometry as geometry, gold_model as model
from backend.core.namd_gold_package import layout, dry_pair, config, pack, verify_package, sha
from backend.core.md_charge import parse_psf_atoms
from backend.core.namd_solvate import _Water, _FF_DIR
from backend.core.surface_transforms import RigidTransform


@pytest.mark.parametrize("facet,repeats,layers,expected", [("100", [10, 11], 4, 440), ("111", [10, 7], 6, 840)])
def test_crystal_neighbors_and_periodic_seams(facet, repeats, layers, expected):
    a = .40782
    xyz, g = geometry.slab(facet, repeats, layers, a)
    assert len(xyz) == expected
    assert np.array_equal(xyz, geometry.slab(facet, repeats, layers, a)[0])
    cell = [*g["lateral_nm"], 10.]
    tree = cKDTree(xyz, boxsize=cell)
    distances = tree.query(xyz, k=2)[0][:, 1]
    assert np.allclose(distances, a/math.sqrt(2), atol=1e-10)
    middle = np.isclose(xyz[:, 2], g["layer_spacing_nm"])
    counts = tree.query_ball_point(xyz[middle], a/math.sqrt(2)*1.001, return_length=True)
    assert np.all(counts == 13)  # twelve fcc neighbors plus self, including seams


def test_particle_inversion_and_coordination():
    xyz, g = geometry.nanoparticle(.85, .40782)
    assert len(xyz) == 141
    assert np.max(np.linalg.norm(xyz, axis=1)) <= .85
    assert np.allclose(np.mean(xyz, axis=0), 0, atol=1e-15)
    assert len(cKDTree(xyz).query_ball_point([0, 0, 0], .40782/math.sqrt(2)*1.001)) == 13
    assert g["shape"] == "fcc_spherical_cut"


def test_transform_preserves_joint_cell_geometry():
    xyz, _ = geometry.nanoparticle(.85, .40782)
    t = RigidTransform(((0, -1, 0), (1, 0, 0), (0, 0, 1)), (3, 4, 5))
    data = geometry.transformed_geometry(xyz, np.eye(3)*5, t)
    assert np.allclose(t.inverse().points(data["positions_nm"]), xyz)
    assert np.allclose(data["cell_vectors_nm"], [[0, 5, 0], [-5, 0, 0], [0, 0, 5]])


@pytest.mark.parametrize("partner", ["NAUI", "OT", "HT", "SOD", "CLA"])
def test_pair_minimum_sigma_and_force(partner):
    eps, rmin = model.pair_parameters(partner)
    energy, force = model.pair_energy_force(rmin, partner)
    assert energy == pytest.approx(-eps)
    assert force == pytest.approx(0)
    assert model.pair_energy_force(rmin/2**(1/6), partner)[0] == pytest.approx(0, abs=1e-12)
    r, h = 1.13*rmin, 1e-5
    numeric = -(model.pair_energy_force(r+h, partner)[0]-model.pair_energy_force(r-h, partner)[0])/(2*h)
    assert model.pair_energy_force(r, partner)[1] == pytest.approx(numeric, rel=1e-8)
    assert model.pair_energy_force(10*model.contact_distance_nm(partner), partner)[0] == pytest.approx(6.)


def test_electrolyte_audit_detects_overwritten_cufix():
    text = (_FF_DIR/"toppar_water_ions_cufix.str").read_text()
    model.validate_electrolyte(text)
    with pytest.raises(ValueError, match="CUFIX override"):
        model.validate_electrolyte(text.replace("3.74075", "3.68075"))


def test_psf_gold_has_mass_neutrality_and_no_bonds():
    xyz, _ = geometry.nanoparticle(.85, .40782)
    psf, pdb = dry_pair(xyz)
    atoms = parse_psf_atoms(psf)
    assert len(atoms) == len(xyz) == len([r for r in pdb.splitlines() if r.startswith("HETATM")])
    assert all(a.mass == 196.96657 and a.charge == 0 and a.atomtype == "NAUI" for a in atoms)
    assert "0 !NBOND" in psf and "0 !NNB" in psf


def test_whole_water_contact_and_zero_salt():
    # Valid waters lie far from a metal atom; one oxygen contact is deliberately invalid.
    water = _Water(1., 1., 1., 1.08, 1., 1., 1., 1.08, 1.)
    clash = _Water(.01, 0, 0, .09, 0, 0, .01, .08, 0)
    retained, na, cl, info = pack([water]*101+[clash], np.array([[0., 0, 0]]), [3.]*3,
                                 {"kind": "nanoparticle"}, 0., 17, 6.)
    assert len(retained) == 101 and na == cl == []
    assert info["retained_before_ions"] == 101


def test_boundary_and_restart_contracts():
    _, cell, g = layout({"kind": "nanoparticle", "radius_nm": .85})
    m = {"cell_nm": cell, "geometry": g, "temperature_K": 298.15, "seed": 17, "mobility": "fixed"}
    text = config(m, restart="probe", first_step=1230)
    assert "GPUresident on" in text and "GPUAtomMigration off" in text
    assert "slab" not in text and "gpuGlobal" not in text and "tclForces" not in text
    assert "firsttimestep 1230" in text and "binvelocities output/probe.vel" in text
    assert "COMmotion yes" in text
    assert "COMmotion yes" not in config(m)
    assert "\ntemperature " not in text
    m["slab_gpu"] = {}
    with pytest.raises(ValueError, match="Slab correction"):
        config(m)


@pytest.mark.parametrize("spec", [{"kind": "nanoparticle", "vacuum_factor": 3},
                                  {"kind": "slab", "radius_nm": 1},
                                  {"kind": "slab", "facet": "110"},
                                  {"kind": "wall"}, {"kind": "slab", "charge": 1}])
def test_unsupported_geometry_fails(spec):
    with pytest.raises(ValueError):
        layout(spec)


def test_unsupported_model_timestep_and_restart_fail():
    with pytest.raises(ValueError):
        model.specification("generic_gold")
    with pytest.raises(ValueError):
        model.pair_parameters("MG")
    with pytest.raises(ValueError):
        config({}, timestep_fs=4.)
    with pytest.raises(ValueError):
        config({}, restart="../elsewhere")


def test_asset_tampering_fails(tmp_path):
    path = tmp_path/"system.psf"
    path.write_text("original")
    m = {"gold_model": model.specification(), "geometry": {"kind": "nanoparticle"},
         "asset_sha256": {"system.psf": sha(path)}}
    (tmp_path/"manifest.json").write_text(json.dumps(m))
    assert verify_package(tmp_path) == m
    path.write_text("changed")
    with pytest.raises(ValueError, match="asset changed"):
        verify_package(tmp_path)
