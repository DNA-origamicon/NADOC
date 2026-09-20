"""Small, reproducible CHARMM topology and controlled DCD frames (not MD evidence)."""

import json
from types import SimpleNamespace

import MDAnalysis as mda
import numpy as np
import pytest

from backend.core.lattice import make_bundle_design, make_nick
from backend.core.namd_topology import build_charmm_psfgen_topology
from backend.core.sequences import (
    assign_custom_scaffold_sequence,
    assign_staple_sequences,
)
from tests.conftest import SIX_HB_CELLS, EIGHTEEN_HB_CELLS


def build_md_fixture(
    folder, *, many_strands=False, cells=SIX_HB_CELLS, length_bp=28, nick_every=4
):
    folder.mkdir(parents=True, exist_ok=True)
    design = make_bundle_design(cells, length_bp=length_bp, name="generated_md")
    for strand in design.scaffolds():
        design, _, _ = assign_custom_scaffold_sequence(
            design, ("ACGT" * ((length_bp + 3) // 4))[:length_bp], strand_id=strand.id
        )
    design = assign_staple_sequences(design)
    if many_strands:
        # More than 62 strands exercise the single-character PDB chain collision.
        for strand in list(design.strands):
            domain = strand.domains[0]
            direction = 1 if domain.end_bp > domain.start_bp else -1
            for bp in range(
                domain.start_bp + (nick_every - 1) * direction,
                domain.end_bp,
                nick_every * direction,
            ):
                design = make_nick(design, domain.helix_id, bp, domain.direction)
        assert len(design.strands) > 62
    built = build_charmm_psfgen_topology(design)
    psf, ref = folder / "generated_md.psf", folder / "generated_md.pdb"
    psf.write_text(built.psf_text)
    ref.write_text(built.pdb_text)
    (folder / "charge_audit.json").write_text(json.dumps(built.metadata))
    design_path = folder / "design.json"
    design_path.write_text(design.model_dump_json())
    output = folder / "output"
    output.mkdir()
    dcd = output / "generated.dcd"
    universe = mda.Universe(str(psf), str(ref))
    reference = universe.atoms.positions.copy()
    with mda.Writer(str(dcd), universe.atoms.n_atoms) as writer:
        for frame in range(12):
            # Small deterministic internal motion plus a periodic translation.
            universe.atoms.positions = (
                reference
                + np.sin(np.arange(len(reference))[:, None] * 0.1 + frame) * 0.01
                + frame * 0.2
            )
            universe.dimensions = [
                *np.maximum(100, np.ptp(reference, axis=0) + 40),
                90,
                90,
                90,
            ]
            writer.write(universe.atoms)
    return SimpleNamespace(
        design=design, folder=folder, psf=psf, ref=ref, dcd=dcd, design_path=design_path
    )


@pytest.fixture(scope="module")
def generated_md(tmp_path_factory):
    return build_md_fixture(tmp_path_factory.mktemp("generated_md"))


@pytest.fixture(scope="module")
def generated_manystrand_md(tmp_path_factory):
    return build_md_fixture(
        tmp_path_factory.mktemp("generated_manystrand_md"), many_strands=True
    )


@pytest.fixture(scope="module")
def generated_solvated_md(tmp_path_factory, generated_md):
    """Real solvation/ionization, controlled rigid-water motion, no MD claim."""
    import io
    import zipfile
    from backend.core.namd_solvate import build_namd_solvated_package

    folder = tmp_path_factory.mktemp("generated_solvated_md")
    data = build_namd_solvated_package(
        generated_md.design,
        padding_nm=1.5,
        mg_conc_mM=10,
        mg_hexahydrate=True,
        require_full_topology=True,
        devices="cpu",
    )
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        archive.extractall(folder)
    psf = next(folder.rglob("generated_md.psf"))
    ref = psf.with_suffix(".pdb")
    audit = json.loads((psf.parent / "charge_audit.json").read_text())
    universe = mda.Universe(str(psf), str(ref))
    reference = universe.atoms.positions.copy()
    solvent = universe.select_atoms("resname TIP3")
    # gmx solvate seeds SPC coordinates. Construct ideal TIP3P water for the
    # rigid-water imaging oracle; a native constrained run would do this on startup.
    water = reference[solvent.indices].reshape(-1, 3, 3).copy()
    u = water[:, 1] - water[:, 0]
    u /= np.linalg.norm(u, axis=1)[:, None]
    v = water[:, 2] - water[:, 0]
    v -= np.sum(v * u, axis=1)[:, None] * u
    v /= np.linalg.norm(v, axis=1)[:, None]
    angle = np.deg2rad(104.52)
    water[:, 1] = water[:, 0] + 0.9572 * u
    water[:, 2] = water[:, 0] + 0.9572 * (np.cos(angle) * u + np.sin(angle) * v)
    reference[solvent.indices] = water.reshape(-1, 3)
    dcd = psf.parent / "generated.dcd"
    with mda.Writer(str(dcd), universe.atoms.n_atoms) as writer:
        for frame in range(3):
            universe.atoms.positions = reference.copy()
            # Translate whole water molecules; preserve their internal geometry.
            solvent.positions += frame * np.array([0.8, 0.3, -0.4])
            universe.dimensions = [
                *(np.array(audit["ionization"]["box_nm"]) * 10),
                90,
                90,
                90,
            ]
            writer.write(universe.atoms)
    return SimpleNamespace(
        design=generated_md.design,
        folder=psf.parent,
        psf=psf,
        ref=ref,
        dcd=dcd,
        audit=audit,
    )


@pytest.fixture(scope="module")
def generated_gromacs(tmp_path_factory, generated_md):
    """Fresh native GROMACS minimization plus controlled XTC reader frames."""
    import io
    import re
    import subprocess
    import zipfile
    from backend.core.gromacs_package import build_gromacs_package, _find_gmx
    from backend.core.pdb_export import export_pdb

    folder = tmp_path_factory.mktemp("generated_gromacs")
    design = generated_md.design
    with zipfile.ZipFile(io.BytesIO(build_gromacs_package(design))) as archive:
        archive.extractall(folder)
    package = next(folder.glob("*_gromacs"))
    # This fixture needs a bounded native EM, not an equilibration campaign.
    mdp = package / "em.mdp"
    mdp.write_text(
        re.sub(r"^nsteps\s*=.*$", "nsteps = 200", mdp.read_text(), flags=re.M)
    )
    gmx = _find_gmx()
    for args in (
        [
            gmx,
            "grompp",
            "-f",
            "em.mdp",
            "-c",
            "conf.gro",
            "-p",
            "topol.top",
            "-o",
            "em.tpr",
        ],
        [gmx, "mdrun", "-deffnm", "em", "-nt", "1"],
    ):
        result = subprocess.run(
            args, cwd=package, capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-4000:]
    pdb = package / "input_nadoc.pdb"
    pdb.write_text(export_pdb(design))
    u = mda.Universe(str(package / "em.gro"))
    reference = u.atoms.positions.copy()
    with mda.Writer(str(package / "view_whole.xtc"), u.atoms.n_atoms) as writer:
        for frame in range(101):
            u.atoms.positions = reference + frame * 0.01
            writer.write(u.atoms)
    return SimpleNamespace(
        design=design, folder=package, pdb=pdb, gro=package / "em.gro"
    )


@pytest.fixture(scope="module")
def generated_large_md(tmp_path_factory):
    return build_md_fixture(
        tmp_path_factory.mktemp("generated_large_md"),
        many_strands=True,
        cells=EIGHTEEN_HB_CELLS,
        length_bp=200,
        nick_every=100,
    )
