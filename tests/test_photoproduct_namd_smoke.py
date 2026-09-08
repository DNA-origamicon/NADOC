from __future__ import annotations

import hashlib
import json

import numpy as np

import pytest

from backend.core.cpd_forcefield import CpdCapabilityError
from backend.core.dcd_fast import append_frame, write_header
from backend.core.namd_topology import charmm_atom_name
from backend.core.photoproduct_chemistry import load_chemical_definition
from backend.parameterization.photoproduct_namd_smoke import (
    audit_photoproduct_namd_smoke,
    prepare_photoproduct_namd_smoke,
)


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pdb_line(serial, name, resname, chain, resid, x, y, z, segid):
    return (
        f"ATOM  {serial:5d} {name:<4} {resname:>3} {chain:1}{resid:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}      {segid:>4}\n"
    )


def _package(tmp_path):
    package = tmp_path / "package"
    forcefield = package / "forcefield/photoproducts/test"
    forcefield.mkdir(parents=True)
    parameter = forcefield / "product.prm"
    parameter.write_text("* test parameter evidence\n")
    relative = "photoproducts/test/product.prm"
    packaged = {
        "schema": "nadoc.packaged-photoproduct-forcefield.v1",
        "timestep_fs": 2.0,
        "hmr_4fs_enabled": False,
        "lesions": [{"lesion_id": "one", "product": "TT-CPD"}],
        "assets": [
            {
                "kind": "parameters",
                "product_id": "tt-cpd-cis-syn",
                "relative_path": relative,
                "sha256": _sha(parameter),
            }
        ],
    }
    (package / "photoproduct_forcefield_manifest.json").write_text(json.dumps(packaged))
    (package / "manifest.json").write_text(json.dumps({"name_stem": "system"}))
    static = {
        "schema": "nadoc.photoproduct-static-topology-audit.v1",
        "passed": True,
        "lesions": [
            {
                "lesion_id": "one",
                "product_id": "tt-cpd-cis-syn",
                "endpoints": [
                    {"endpoint": 1, "segid": "D000", "resid": 1},
                    {"endpoint": 2, "segid": "D000", "resid": 2},
                ],
            }
        ],
    }
    (package / "charge_audit.json").write_text(
        json.dumps(
            {"topology_metadata": {"photoproduct_static_topology_audit": static}}
        )
    )
    definition = load_chemical_definition("TT-CPD", "cis-syn")
    source = {
        key: np.asarray(value, dtype=float)
        for key, value in definition["source_ring_coordinates_angstrom"].items()
    }
    required = {
        reference
        for center in definition["product_stereocenters"]
        for reference in [center["atom"], *center["signed_volume_reference_atoms"]]
    }
    for endpoint in (1, 2):
        n1 = source[f"{endpoint}:N1"]
        c6 = source[f"{endpoint}:C6"]
        direction = n1 - c6
        source[f"{endpoint}:C1'"] = n1 + direction / np.linalg.norm(direction) * 1.45
        required.add(f"{endpoint}:C1'")
    ordered = sorted(required, key=lambda key: (int(key[0]), key.split(":", 1)[1]))
    atoms = [
        (
            serial,
            charmm_atom_name(key.split(":", 1)[1]),
            int(key[0]),
            source[key],
        )
        for serial, key in enumerate(ordered, start=1)
    ]
    atoms.append((len(atoms) + 1, "OH2", 1, np.asarray([50.0, 0.0, 0.0])))
    psf_lines = ["PSF", "", f"{len(atoms):8d} !NATOM"]
    pdb_lines = []
    for serial, name, resid, xyz in atoms:
        water = serial == len(atoms)
        segid = "WT1" if water else "D000"
        resname = "TIP3" if water else "THY"
        psf_lines.append(
            f"{serial:8d} {segid} {resid} {resname} {name} CT 0.000000 12.0110 0"
        )
        pdb_lines.append(
            _pdb_line(
                serial,
                name,
                "HOH" if water else resname,
                "W" if water else "A",
                resid,
                *xyz,
                segid,
            )
        )
    (package / "system.psf").write_text("\n".join(psf_lines) + "\n")
    (package / "system.pdb").write_text("".join(pdb_lines) + "END\n")
    (package / "namd.conf").write_text(
        "\n".join(
            [
                "structure system.psf",
                "coordinates system.pdb",
                "paraTypeCharmm on",
                "parameters forcefield/par_all36_na.prm",
                f"parameters         forcefield/{relative}",
                "langevin on",
                "langevinTemp 0",
                "temperature 0",
                "timestep 1.0",
                "rigidBonds none",
                "outputName output/system",
                "minimize 2000",
                "run 0",
                "",
            ]
        )
    )
    return package, parameter, np.stack([record[3] for record in atoms])


def test_prepare_namd_smoke_is_staged_hash_linked_and_ordinary_mass(tmp_path):
    package, _parameter, _coordinates = _package(tmp_path)
    output = package / "cpd_smoke"
    plan = prepare_photoproduct_namd_smoke(package_dir=package, output_dir=output)
    assert plan["status"] == "prepared_not_run"
    assert plan["gate_effect"] == "none"
    assert plan["product_ids"] == ["tt-cpd-cis-syn"]
    assert plan["integrator"] == {"maximum_timestep_fs": 2.0, "hmr": False}
    assert [item["name"] for item in plan["stages"]] == [
        "00_load",
        "01_local_min",
        "02_global_min",
        "03_dynamics_2fs",
    ]
    assert plan["local_mobile_mask"]["fixed_atom_count"] == 1
    local = (output / "01_local_min.conf").read_text()
    global_min = (output / "02_global_min.conf").read_text()
    dynamics = (output / "03_dynamics_2fs.conf").read_text()
    assert "fixedAtomsFile     cpd_smoke/local_fixed.pdb" in local
    assert "minimize           500" in local
    assert "binCoordinates     output/01_local_min.coor" in global_min
    assert "minimize           1000" in global_min
    assert "binCoordinates     output/02_global_min.coor" in dynamics
    assert "rigidBonds         all" in dynamics
    assert "timestep           2.0" in dynamics
    assert "run                1000" in dynamics
    assert "_hmr.psf" not in dynamics
    assert "forcefield/photoproducts/test/product.prm" in dynamics


def test_prepare_namd_smoke_rejects_changed_packaged_parameter(tmp_path):
    package, parameter, _coordinates = _package(tmp_path)
    parameter.write_text("changed\n")
    with pytest.raises(CpdCapabilityError, match="hash mismatch"):
        prepare_photoproduct_namd_smoke(
            package_dir=package, output_dir=package / "cpd_smoke"
        )


def test_prepare_namd_smoke_requires_output_inside_package(tmp_path):
    package, _parameter, _coordinates = _package(tmp_path)
    with pytest.raises(ValueError, match="inside the package"):
        prepare_photoproduct_namd_smoke(
            package_dir=package, output_dir=tmp_path / "outside"
        )


def test_audit_namd_smoke_checks_real_frames_logs_bonds_and_chirality(tmp_path):
    package, _parameter, coordinates = _package(tmp_path)
    smoke_dir = package / "cpd_smoke"
    plan = prepare_photoproduct_namd_smoke(package_dir=package, output_dir=smoke_dir)
    output_dir = package / "output"
    output_dir.mkdir(exist_ok=True)
    for stage in plan["stages"]:
        (package / stage["log"]).write_text(
            "Info: NAMD 3.0.2 for Linux-x86_64-multicore-CUDA\n"
            "ENERGY: 0 1.0 2.0 3.0 4.0\n"
            "[Partition 0][Node 0] End of program\n"
        )
        for suffix in ("coor", "xsc"):
            (output_dir / f"{stage['name']}.{suffix}").write_bytes(
                f"{stage['name']} {suffix}\n".encode()
            )
    dcd_path = output_dir / "03_dynamics_2fs.dcd"
    with dcd_path.open("wb") as handle:
        write_header(
            handle,
            len(coordinates),
            2,
            nsavc=10,
            delta=0.002 / 0.04888821,
        )
        append_frame(handle, coordinates)
        append_frame(handle, coordinates)
    report = audit_photoproduct_namd_smoke(
        package_dir=package,
        smoke_plan_path=smoke_dir / "smoke_plan.json",
        output_path=smoke_dir / "namd_smoke_report.json",
    )
    assert report["schema"] == "nadoc.photoproduct-namd-smoke.v1"
    assert report["status"] == "passed"
    assert report["passed"] is True
    assert report["timestep_fs"] == pytest.approx(2.0)
    assert all(frame["chirality_passed"] for frame in report["frames"])
    assert report["engine"] == {"name": "NAMD", "version": "3.0.2"}
