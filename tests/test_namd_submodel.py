"""Software contracts for derived PSF cropping and fixed-shell execution."""

import asyncio
import json

import pytest

from backend.core.namd_submodel import crop_topology, finalize_package, sections
from backend.core.namd_topology import CharmmTopologyBuild


def toy_topology():
    # A parser fixture, not an authored NADOC structure or force-field model.
    atoms = [f"{i:8d} D000 {i} ADE P P -1.000 30.974 0" for i in range(1, 9)]
    psf = (
        "PSF\n\n1 !NTITLE\n REMARKS parser fixture\n\n8 !NATOM\n"
        + "\n".join(atoms)
        + "\n\n7 !NBOND\n1 2 2 3 3 4 4 5 5 6 6 7 7 8\n1 !NPHI\n2 3 4 5\n0 !NNB\n"
        + "0 " * 8
        + "\n"
    )
    pdb = (
        "\n".join(
            f"ATOM  {i:5d}  P   ADE A{i:4d}    {i * 10:8.3f}{0:8.3f}{0:8.3f}{1:6.2f}{0:6.2f}      D000 P"
            for i in range(1, 9)
        )
        + "\nEND\n"
    )
    return CharmmTopologyBuild(pdb_text=pdb, psf_text=psf, metadata={})


BOX = dict(
    min_corner=[3.9, -0.1, -0.1],
    max_corner=[4.1, 0.1, 0.1],
    rotation=[0, 0, 0, 1],
    shell_nm=0,
)


def test_zero_shell_keeps_complete_mobile_bonded_support():
    source = toy_topology()
    cropped, receipt = crop_topology(source, BOX)
    assert receipt["mobile_source_indices"] == [3]
    assert receipt["retained_source_indices"] == [1, 2, 3, 4]
    assert receipt["mobile_output_indices"] == [2]
    assert sections(cropped.psf_text)["NBOND"][0] == 3
    assert list(map(int, " ".join(sections(cropped.psf_text)["NPHI"][1]).split())) == [
        1,
        2,
        3,
        4,
    ]
    # Preserve source positions, charges and atom identities; only serials change.
    assert [s.split()[1:] for s in sections(cropped.psf_text)["NATOM"][1]] == [
        s.split()[1:] for s in sections(source.psf_text)["NATOM"][1][1:5]
    ]
    assert receipt["cut_bonds_source_indices"] == [[0, 1], [4, 5]]


def test_shell_expands_context_and_empty_box_fails():
    _, receipt = crop_topology(toy_topology(), {**BOX, "shell_nm": 2})
    assert receipt["retained_source_indices"] == [1, 2, 3, 4, 5]
    with pytest.raises(ValueError, match="selects no"):
        crop_topology(
            toy_topology(),
            {**BOX, "min_corner": [20, 20, 20], "max_corner": [21, 21, 21]},
        )


def test_fixed_shell_precedes_adaptive_loop_and_preserves_other_pins(tmp_path):
    cropped, receipt = crop_topology(toy_topology(), BOX)
    (tmp_path / "submodel.json").write_text(json.dumps(receipt))
    (tmp_path / "toy.pdb").write_text(cropped.pdb_text)
    (tmp_path / "manifest.json").write_text("{}")
    conf = tmp_path / "relax.conf"
    conf.write_text("GPUresident on\nlangevinPiston on\nwhile {1} {\n minimize 20\n}\n")
    finalize_package(tmp_path, "toy")
    text = conf.read_text()
    assert text.index("fixedAtoms on") < text.index("while")
    assert "GPUresident on" not in text and "langevinPiston on" not in text
    marker = tmp_path / "submodel_fixed.pdb"
    flags = [
        float(s[60:66]) for s in marker.read_text().splitlines() if s.startswith("ATOM")
    ]
    assert flags == [1, 1, 0, 1]
    finalize_package(tmp_path, "toy")
    assert conf.read_text() == text
    assert (
        json.loads((tmp_path / "manifest.json").read_text())["submodel_execution"][
            "fixed_atoms"
        ]
        == 3
    )


def test_selection_rebuilds_unstarted_job_and_freezes_started_job(
    tmp_path, monkeypatch
):
    from backend.api import routes_md
    from backend.api.simulation_submodel import SubmodelSelection, read_selection
    from backend.core.md_job import new_job, MdStatus

    job = new_job("test", "equilibrium_aware_namd", "test", "package")
    job.save(tmp_path)
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    monkeypatch.setattr(routes_md, "_load_job", lambda _: job)
    (job.job_dir(tmp_path) / "design.json").write_text("source snapshot")
    asyncio.run(routes_md.put_md_submodel(job.job_id, SubmodelSelection(box=BOX)))
    assert job.status == MdStatus.draft
    assert (job.job_dir(tmp_path) / "design.json").read_text() == "source snapshot"
    assert read_selection(job.job_dir(tmp_path))["box"]["shell_nm"] == 0
    job.status = MdStatus.running
    with pytest.raises(Exception, match="frozen"):
        asyncio.run(
            routes_md.put_md_submodel(
                job.job_id, SubmodelSelection(box={**BOX, "shell_nm": 1})
            )
        )
    # Visibility remains editable without changing the simulated region.
    asyncio.run(
        routes_md.put_md_submodel(
            job.job_id, SubmodelSelection(box={**BOX, "visible": False})
        )
    )


def test_solvated_psf_reflow_is_lossless_and_readable_by_analysis(tmp_path):
    import MDAnalysis as mda
    from backend.core.namd_submodel import canonical_bonded_lines

    source = (
        toy_topology()
        .psf_text.replace(
            "1 !NPHI",
            "5 !NTHETA\n1 2 3 2 3 4\n3 4 5 4 5 6 5 6 7\n\n1 !NPHI",
        )
        .replace("0 !NNB", "0 !NIMPHI\n\n0 !NNB")
    )
    canonical = canonical_bonded_lines(source)
    before, after = sections(source), sections(canonical)
    for key in ("NBOND", "NTHETA", "NPHI"):
        assert before[key][0] == after[key][0]
        assert " ".join(before[key][1]).split() == " ".join(after[key][1]).split()
    path = tmp_path / "toy.psf"
    path.write_text(canonical)
    universe = mda.Universe(str(path))
    assert len(universe.atoms) == 8
    assert len(universe.bonds) == 7
    assert len(universe.angles) == 5
    assert len(universe.dihedrals) == 1
    assert canonical_bonded_lines(canonical) == canonical


def test_fixed_shell_resource_budget_keeps_all_atoms_and_rejects_resident(tmp_path):
    from backend.core.namd_resources import configuration_memory

    (tmp_path / "toy.psf").write_text("100000 !NATOM\n")
    conf = tmp_path / "run.conf"
    conf.write_text("structure toy.psf\nGPUresident off\nrun 100\n")
    baseline = configuration_memory(conf, fallback_box=[150] * 3, detailed=False)
    atom = toy_topology().pdb_text.splitlines()[0]
    (tmp_path / "fixed.pdb").write_text(
        (atom[:60] + "  1.00" + atom[66:] + "\n") * 100000
    )
    conf.write_text(
        "structure toy.psf\nGPUresident off\nfixedAtoms on\nfixedAtomsFile fixed.pdb\nfixedAtomsCol B\nfixedAtomsForces off\nlangevinPiston off\nrun 100\n"
    )
    estimate = configuration_memory(conf, fallback_box=[150] * 3, detailed=False)
    assert estimate.atoms == 100000
    assert estimate.ram_mib > baseline.ram_mib
    assert estimate.gpu_mib > baseline.gpu_mib
    conf.write_text(conf.read_text().replace("GPUresident off", "GPUresident on"))
    with pytest.raises(ValueError, match="offload"):
        configuration_memory(conf, fallback_box=[150] * 3, detailed=False)


def test_prepared_cell_center_uses_source_translation_not_whole_design_center(tmp_path):
    source = toy_topology()
    cropped, receipt = crop_topology(source, BOX)
    (tmp_path / "submodel_source").mkdir()
    (tmp_path / "submodel_source/full.pdb").write_text(source.pdb_text)
    (tmp_path / "submodel.json").write_text(json.dumps(receipt))
    translated = "\n".join(
        line[:30] + f"{float(line[30:38]) + 10:8.3f}" + line[38:]
        if line.startswith("ATOM")
        else line
        for line in cropped.pdb_text.splitlines()
    )
    (tmp_path / "toy.pdb").write_text(translated)
    (tmp_path / "manifest.json").write_text(json.dumps({"box_ang": [100, 100, 100]}))
    finalize_package(tmp_path, "toy")
    saved = json.loads((tmp_path / "submodel.json").read_text())
    assert saved["source_to_package_translation_nm"] == [1, 0, 0]
    assert saved["source_cell_center_nm"] == [4, 5, 5]


def test_legacy_display_only_selection_cannot_start_full_package(tmp_path):
    from backend.api.md_submodel import require_prepared_selection
    from backend.api.simulation_submodel import SubmodelSelection, save_selection
    from backend.core.md_job import new_job
    from fastapi import HTTPException

    job = new_job("test", "equilibrium_aware_namd", "test", "package")
    job.save(tmp_path)
    require_prepared_selection(job, tmp_path)
    save_selection(job.job_dir(tmp_path), SubmodelSelection(box=BOX))
    with pytest.raises(HTTPException, match="does not match"):
        require_prepared_selection(job, tmp_path)
    package = job.package_dir(tmp_path)
    package.mkdir(parents=True, exist_ok=True)
    # Normalized API defaults are part of the persisted receipt.
    box = SubmodelSelection(box=BOX).model_dump(mode="json")["box"]
    (package / "submodel.json").write_text(json.dumps({"box": box}))
    require_prepared_selection(job, tmp_path)
    save_selection(
        job.job_dir(tmp_path), SubmodelSelection(box={**box, "visible": False})
    )
    require_prepared_selection(job, tmp_path)
    save_selection(job.job_dir(tmp_path), SubmodelSelection(box={**box, "shell_nm": 3}))
    with pytest.raises(HTTPException, match="does not match"):
        require_prepared_selection(job, tmp_path)


def test_sequence_deferred_preparation_preserves_saved_region(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from backend.api import routes_md
    from backend.api.simulation_submodel import SubmodelSelection, save_selection
    from backend.core.md_job import new_job

    job = new_job("test", "equilibrium_aware_namd", "test", "")
    job.prep_params = {"submodel": None}
    job.awaiting_sequence = True
    job.save(tmp_path)
    save_selection(job.job_dir(tmp_path), SubmodelSelection(box=BOX))
    design = SimpleNamespace(metadata=SimpleNamespace(name="test"))
    monkeypatch.setattr(routes_md, "_workspace", lambda: tmp_path)
    monkeypatch.setattr(
        routes_md.design_state,
        "get_or_404",
        lambda: SimpleNamespace(without_reference_geometry=lambda: design),
    )
    monkeypatch.setattr(routes_md, "_sequence_problem", lambda _: None)
    monkeypatch.setattr(routes_md, "design_size_factor", lambda _: 1)
    captured = {}

    def prepare(body, **kwargs):
        captured["box"] = body.submodel.model_dump(mode="json")
        return kwargs["existing_job"]

    monkeypatch.setattr(routes_md, "_spawn_prep_job", prepare)
    routes_md._prepare_sequence_deferred_job(job, autostart=False)
    assert captured["box"] == SubmodelSelection(box=BOX).model_dump(mode="json")["box"]


def test_submodel_production_writer_defaults_to_one_not_relaxation_damping(tmp_path):
    import re
    from backend.core.md_protocols import SegmentSpec, build_production_conf

    cropped, receipt = crop_topology(toy_topology(), BOX)
    (tmp_path / "submodel.json").write_text(json.dumps(receipt))
    (tmp_path / "toy.pdb").write_text(cropped.pdb_text)
    spec = SegmentSpec(
        name="production",
        stage="production",
        percent=100,
        steps=1000,
        temp=300,
        damping=5,
        scale=None,
        npt=False,
        previous="relax",
        reinit=False,
        dcd_freq=100,
        timestep_fs=4,
    )
    conf = tmp_path / "production.conf"
    conf.write_text(
        build_production_conf(
            spec,
            "toy",
            (100, 100, 100),
            False,
            timestep_fs=4,
            force_resident=False,
            npt=False,
        )
    )
    finalize_package(tmp_path, "toy")
    assert re.search(r"^langevinDamping\s+1$", conf.read_text(), re.M)
    assert re.search(r"^timestep\s+4$", conf.read_text(), re.M)


def test_uniform_shell_preserves_core_stage_restraints_and_legacy_recipe(tmp_path):
    cropped, receipt = crop_topology(toy_topology(), {**BOX, "shell_nm": 3})
    boundary = receipt["shell_boundary"]
    assert boundary["fixed_output_indices"] == [0, 6]
    assert boundary["restrained_output_indices"] == [1, 2, 4, 5]
    (tmp_path / "submodel.json").write_text(json.dumps(receipt))
    (tmp_path / "toy.pdb").write_text(cropped.pdb_text)
    lines = cropped.pdb_text.splitlines()
    (tmp_path / "stage.pdb").write_text(
        "\n".join(
            s[:60] + "  2.00" + s[66:] if s.startswith("ATOM") else s for s in lines
        )
    )
    conf = tmp_path / "relax.conf"
    conf.write_text(
        "constraints on\nconsref stage.pdb\nconskfile stage.pdb\nconskcol B\nconstraintScaling 0.5\nrun 100\n"
    )
    finalize_package(tmp_path, "toy")
    weights = [
        float(s[60:66])
        for s in (tmp_path / "submodel_restraints_relax.pdb").read_text().splitlines()
        if s.startswith("ATOM")
    ]
    assert weights == [1, 0.1, 0.1, 1, 0.1, 0.1, 1]
    first = conf.read_text()
    finalize_package(tmp_path, "toy")
    assert conf.read_text() == first
    receipt.pop("shell_boundary")
    receipt["version"] = 1
    (tmp_path / "submodel.json").write_text(json.dumps(receipt))
    conf.write_text("constraints off\nrun 100\n")
    finalize_package(tmp_path, "toy")
    assert "constraints off" in conf.read_text()
    flags = [
        float(s[60:66])
        for s in (tmp_path / "submodel_fixed.pdb").read_text().splitlines()
        if s.startswith("ATOM")
    ]
    assert flags == [1, 1, 1, 0, 1, 1, 1]


def test_uniform_production_shell_references_parent_checkpoint(tmp_path):
    import struct
    import numpy as np

    cropped, receipt = crop_topology(toy_topology(), {**BOX, "shell_nm": 3})
    (tmp_path / "submodel.json").write_text(json.dumps(receipt))
    (tmp_path / "toy.pdb").write_text(cropped.pdb_text)
    coords = np.arange(21, dtype=np.float64).reshape(7, 3)
    (tmp_path / "equilibrated.coor").write_bytes(struct.pack("i", 7) + coords.tobytes())
    conf = tmp_path / "production.conf"
    conf.write_text(
        "constraints off\nbincoordinates equilibrated.coor\nbinvelocities equilibrated.vel\ntimestep 4\nlangevinDamping 1\nrun 100\n"
    )
    finalize_package(tmp_path, "toy")
    lines = [
        s
        for s in (tmp_path / "submodel_restraints_production.pdb")
        .read_text()
        .splitlines()
        if s.startswith("ATOM")
    ]
    for i in receipt["shell_boundary"]["restrained_output_indices"]:
        assert [float(lines[i][k : k + 8]) for k in (30, 38, 46)] == coords[i].tolist()
        assert float(lines[i][60:66]) == 0.1
    assert float(lines[3][60:66]) == 0  # Core is free during production.
    assert "binvelocities equilibrated.vel" in conf.read_text()
    assert "timestep 4" in conf.read_text()


def test_uniform_merge_preserves_small_effective_core_coefficients():
    from backend.core.namd_submodel_boundary import coefficient_field

    for value in (0, 0.1, 0.02 * 0.1, 0.00001, 100):
        field = coefficient_field(value)
        assert len(field) == 6
        assert float(field) == pytest.approx(value, rel=1e-12, abs=0)
    with pytest.raises(ValueError, match="Cannot preserve"):
        coefficient_field(123.456789)
