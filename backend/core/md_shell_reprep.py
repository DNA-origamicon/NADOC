"""Water-shell re-preparation for NVT production (reuse a completed relaxation).

A curved / elongated origami wastes most of an orthogonal solvation box on empty
water (the box encloses the arc; the concave side and corners are bulk).  The
water-shell carve (``namd_solvate._carve_water_shell``) removes water beyond N Å
of the DNA, cutting atom count ~2-5x — but a carved cell has vacuum corners, so
it must run **NVT** (an NpT piston would collapse the corners onto the periodic
image) and the DNA needs a weak centre-of-mass restraint so it cannot diffuse
into a corner over a long unrestrained run.

This module owns the two *novel* pieces of that pipeline:

- :func:`read_namd_coor` — parse a NAMD binary ``.coor`` restart into an (N,3)
  array, so the relaxed DNA coordinates from a completed job's checkpoint can seed
  the re-solvation (via ``build_namd_solvated_package(atomistic_model=…)``) instead
  of ideal B-DNA.  Re-solvating (rather than deleting water in place) keeps ion
  neutrality exact: the tested solvation path re-ionises from the carved solvent
  volume, whereas an in-place water delete would strand bulk Cl-/Mg2+ in vacuum.

- :func:`com_restraint_colvars` — emit a Colvars config that harmonically pins the
  DNA centre of mass (all its atoms) to a fixed point along each axis, leaving
  every internal degree of freedom free.  Prevents whole-body drift toward a
  vacuum corner without perturbing conformational dynamics.

The solvation reuse, segment protocol, and endpoint wiring live with the existing
prep/runner code; this module stays a small, pure, independently-tested unit.
"""

from __future__ import annotations

import dataclasses
import struct
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from backend.core.atomistic import AtomisticModel


def read_namd_coor(path: str | Path) -> np.ndarray:
    """Read a NAMD binary coordinate/restart file into an ``(N, 3)`` float64 array.

    NAMD's ``namdbin`` format is a 4-byte integer atom count followed by ``3*N``
    little-endian ``float64`` (x, y, z per atom).  Endianness is auto-detected by
    checking which interpretation makes the count consistent with the file size
    (``4 + N*24`` bytes).
    """
    data = Path(path).read_bytes()
    if len(data) < 4:
        raise ValueError(f"{path}: too short to be a NAMD .coor ({len(data)} bytes)")
    for endian in ("<", ">"):
        n = struct.unpack(endian + "i", data[:4])[0]
        if n > 0 and len(data) == 4 + n * 24:
            arr = np.frombuffer(
                data, dtype=np.dtype(endian + "f8"), count=3 * n, offset=4
            )
            return arr.reshape(n, 3).astype(np.float64)
    raise ValueError(
        f"{path}: not a NAMD binary .coor (size {len(data)} inconsistent with any atom count)"
    )


def stamp_relaxed_dna_model(
    model: "AtomisticModel",
    coor_ang: np.ndarray,
    *,
    guard: bool = True,
) -> "AtomisticModel":
    """Return a copy of ``model`` with its DNA atom coordinates replaced by the
    relaxed positions from a NAMD checkpoint.

    ``model`` is a fresh ``build_atomistic_model(design)`` — its atoms are the DNA
    heavy atoms in the SAME order that built the solvated PSF, so the DNA occupies
    the leading ``len(model.atoms)`` rows of the full-system checkpoint (DNA ``ATOM``
    records precede water/ion ``HETATM`` in every NADOC package).  Row ``i`` of the
    checkpoint therefore maps to ``model.atoms[i]``.

    The model stores coordinates in **nm**; a NAMD ``.coor`` is in **Å**, so the
    stamped values are divided by 10.  Topology (bonds, per-atom metadata) is
    untouched — only positions move — so the result can seed
    ``build_namd_solvated_package(atomistic_model=…)`` to re-solvate the *relaxed*
    (e.g. curved) DNA with a fresh water shell.

    With ``guard`` (default), the leading DNA block must be strictly smaller than
    the full checkpoint bounding box on every axis; otherwise the DNA-first ordering
    assumption is violated (a whole-box span means the leading rows are not the DNA)
    and we raise rather than silently stamp garbage.
    """
    n = len(model.atoms)
    if coor_ang.shape[0] < n:
        raise ValueError(
            f"checkpoint has {coor_ang.shape[0]} atoms, fewer than the {n} DNA model atoms"
        )
    if guard and coor_ang.shape[0] > n:
        full_span = coor_ang.max(0) - coor_ang.min(0)
        dna_span = coor_ang[:n].max(0) - coor_ang[:n].min(0)
        if not bool(np.all(dna_span < full_span * 0.95)):
            raise ValueError(
                "leading checkpoint block spans the full box on some axis — the "
                "DNA-first atom-order assumption is violated"
            )
    dna_nm = coor_ang[:n] / 10.0  # Å → nm
    atoms = [
        dataclasses.replace(
            a, x=float(dna_nm[i, 0]), y=float(dna_nm[i, 1]), z=float(dna_nm[i, 2])
        )
        for i, a in enumerate(model.atoms)
    ]
    from backend.core.atomistic import AtomisticModel  # noqa: PLC0415

    return AtomisticModel(atoms=atoms, bonds=list(model.bonds))


def _dna_com_ang(pdb_path: Path) -> tuple[tuple[float, float, float], int]:
    """Return (COM Å, n_dna) for the DNA of a NADOC solvated package.

    DNA is written as ``ATOM`` records (solvent/ions as ``HETATM``), so counting
    ``ATOM`` records gives the exact DNA atom count in the *built* PSF (hydrogens
    included) — the count the Colvars ``atomNumbersRange 1-N`` restraint needs and
    the frame its centre must reference."""
    xs = ys = zs = 0.0
    k = 0
    for line in pdb_path.read_text().splitlines():
        if not line.startswith("ATOM"):
            continue
        xs += float(line[30:38])
        ys += float(line[38:46])
        zs += float(line[46:54])
        k += 1
    if k == 0:
        raise ValueError(f"{pdb_path}: no ATOM records for DNA COM")
    return (xs / k, ys / k, zs / k), k


def prepare_shell_nvt_production(
    design,
    job_dir: Path,
    *,
    water_shell_nm: float = 1.5,
    ion_conc_mM: float = 0.0,
    mg_conc_mM: float = 12.5,
    padding_nm: float = 1.2,
    minimize_steps: int = 4800,
    equil_steps: int = 500_000,
    prod_steps: int = 12_500_000,
    com_force_constant: float = 1.0,
    dcd_freq: int = 5000,
    anchors: list | None = None,
    field: dict | None = None,
) -> dict:
    """Re-solvate a design with a water shell and write an NVT production protocol
    into ``job_dir``.

    Pipeline (mirrors the Aksimentiev pre-production recipe):
      DNA build → re-solvate with an ``water_shell_nm`` shell + 12 mM Mg (reuse
      ``prepare_mgh_slow_release`` with ``require_full_topology=True`` — psfgen adds
      hydrogens + CHARMM patches and neutralises exactly, HMR PSF, ENM, minimisation
      conf, box) → **minimise** → **restrained equilibration** (DNA position-
      restrained, NVT, soft 1 fs) → **NVT production** (HMR 4 fs, GPU-resident) with a
      weak DNA centre-of-mass Colvars restraint so the unrestrained DNA cannot drift
      onto the shell's vacuum corners.

    Seeded from the **design build**, NOT the completed job's checkpoint: (1) a
    psfgen PSF interleaves hydrogens, so the heavy-atom model's atom order does not
    line up with the checkpoint rows; (2) the MD-relaxed coordinates have drifted /
    spread in the periodic cell, so their bounding box (hence the re-solvation box)
    is *larger* than the compact design build — the design build carves smaller.  The
    design-build strain is instead relieved by the restrained equilibration below.

    The carved cell has vacuum corners so every stage is NVT (no barostat) — density
    is set by the equilibration at the fixed carved volume.

    Returns a dict of the built package facts (subdir, name_stem, carved atom count,
    segment names) for logging / manifest.
    """
    import json  # noqa: PLC0415
    from dataclasses import asdict  # noqa: PLC0415

    from backend.core import md_protocols as P  # noqa: PLC0415

    job_dir = Path(job_dir)

    def _psf_natom(psf_path: Path) -> int:
        for line in psf_path.read_text().splitlines():
            if "!NATOM" in line:
                return int(line.split()[0])
        return 0

    # Re-solvate with the shell.  require_full_topology=True → psfgen (hydrogens +
    # CHARMM patches + exact neutralisation); fast=True writes the HMR PSF;
    # water_shell_nm>0 auto-forces nvt_only and ion counts from the carved volume.
    subdir, name_stem, _ladder = P.prepare_mgh_slow_release(
        design,
        job_dir,
        protocol=P.EQUILIBRIUM_AWARE_PROTOCOL,
        ion_conc_mM=ion_conc_mM,
        mg_conc_mM=mg_conc_mM,
        padding_nm=padding_nm,
        water_shell_nm=water_shell_nm,
        minimize_steps=minimize_steps,
        require_full_topology=True,
        fast=True,
        # Anchors + E-field must go through prepare, not be spliced in afterwards: the
        # carve RE-SOLVATES, so the fixedAtoms marker PDB has to be rebuilt against the
        # carved system's PDB (a marker from an earlier package would have the wrong atom
        # count and NAMD requires fixedAtomsFile to match `structure` atom-for-atom).
        anchors=anchors,
        field=field,
    )
    package_dir = job_dir / subdir
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    box = tuple(float(x) for x in manifest["box_ang"])
    min_name = manifest["minimization"]["name"]
    mgh_extrabonds = bool(manifest.get("mgh_extrabonds"))
    hmr_psf = f"{name_stem}_hmr.psf"
    carved_atoms = _psf_natom(package_dir / f"{name_stem}.psf")

    # Colvars: pin the DNA COM (built-frame) so it can't drift to a vacuum corner.
    # n_dna is the DNA atom count in the BUILT (hydrogen-bearing) PSF.
    com, n_dna = _dna_com_ang(package_dir / f"{name_stem}.pdb")
    colvars_name = "com_restraint.colvars"
    (package_dir / colvars_name).write_text(
        com_restraint_colvars(n_dna, com, force_constant=com_force_constant)
    )

    # 4. Short segment protocol.  Equil: DNA position-restrained, NVT, soft 1 fs
    #    (the known first-dynamics RATTLE guard for carved cells).  Production:
    #    NVT, HMR 4 fs, unrestrained + the COM colvars.
    equil = P.SegmentSpec(
        name=f"{name_stem}_seq01_solvent_equil",
        stage="solvent equilibration (DNA position-restrained, NVT)",
        percent=100.0,
        steps=equil_steps,
        temp=300.0,
        damping=5.0,
        scale=1.0,
        npt=False,
        previous=min_name,
        reinit=True,
        dcd_freq=dcd_freq,
        min_c1_paired=0.0,
        min_wc_ref_relative=0.0,
        soft=True,
    )
    prod: list = []
    prev = equil.name
    for pct, frac in ((10.0, 0.10), (50.0, 0.40), (100.0, 0.50)):
        prod.append(
            P.SegmentSpec(
                name=f"{name_stem}_seq02_production_k0_p{int(pct)}",
                stage="shell NVT production (COM-restrained, HMR 4 fs)",
                percent=pct,
                steps=max(100, int(round(prod_steps * frac))),
                temp=300.0,
                damping=5.0,
                scale=None,
                npt=False,
                previous=prev,
                reinit=False,
                dcd_freq=dcd_freq,
                min_c1_paired=0.90,
                min_wc_ref_relative=0.25,
                soft=False,
            )
        )
        prev = prod[-1].name

    # Anchors + E-field, as prepare_mgh_slow_release just resolved them for the CARVED
    # system (it wrote restraints_anchors.pdb against the re-solvated PDB above).  These
    # confs replace the ladder's, so dropping either here would silently un-anchor /
    # de-energise the re-prepped run — exactly where an anchored field run lives on a
    # small GPU.
    anchors_file = (manifest.get("files") or {}).get("anchors")
    field = manifest.get("field") or None

    (package_dir / f"{equil.name}.conf").write_text(
        P._segment_conf(
            equil,
            name_stem,
            box,
            mgh_extrabonds,
            fast=False,
            anchors_file=anchors_file,
            field=field,
        )
    )
    for p in prod:
        (package_dir / f"{p.name}.conf").write_text(
            P._segment_conf(
                p,
                name_stem,
                box,
                mgh_extrabonds,
                fast=True,
                structure_psf=hmr_psf,
                colvars_file=colvars_name,
                anchors_file=anchors_file,
                field=field,
            )
        )

    # 5. Rewrite the manifest segment list to the short protocol (keep minimisation,
    #    box, HMR, ENM references the runner/health path already wrote).
    manifest["segments"] = [asdict(equil)] + [asdict(p) for p in prod]
    manifest["shell_production"] = {
        "water_shell_nm": water_shell_nm,
        "carved_atoms": carved_atoms,
        "n_dna_atoms": n_dna,
        "com_restraint_kcal_mol_A2": com_force_constant,
        "com_center_ang": list(com),
        "equil_steps": equil_steps,
        "prod_steps": prod_steps,
        "ensemble": "NVT (carved shell has vacuum corners; density set at fixed carved volume)",
        "seeded_from": "design_build",
    }
    text = json.dumps(manifest, indent=2)
    manifest_path.write_text(text)
    (package_dir / "nadoc_md_run.json").write_text(text)

    return {
        "package_subdir": subdir,
        "name_stem": name_stem,
        "carved_atoms": carved_atoms,
        "n_dna_atoms": n_dna,
        "box_ang": list(box),
        "segments": [s["name"] for s in manifest["segments"]],
        "min_name": min_name,
        "com_center_ang": list(com),
    }


def com_restraint_colvars(
    n_dna_atoms: int,
    center: tuple[float, float, float],
    *,
    force_constant: float = 1.0,
) -> str:
    """Colvars config: harmonically pin the DNA centre of mass to ``center``.

    The DNA atoms are assumed to be serials ``1..n_dna_atoms`` — true for every
    NADOC solvated package, which writes DNA ``ATOM`` records before the water/ion
    ``HETATM`` records.  One ``distanceZ`` colvar per axis (x, y, z) measures the
    COM's displacement from ``center`` along that axis; a harmonic with
    ``centers 0`` restores it.  Only the *collective* COM is restrained — every
    internal coordinate is untouched — so conformational dynamics run free while
    whole-body translation toward a vacuum corner is suppressed.

    ``force_constant`` is in kcal/mol/Å² (distanceZ is in Å).  ~1 is gentle for a
    COM of ~10^5 atoms: a 1 Å drift costs ~1 kcal/mol.
    """
    if n_dna_atoms < 1:
        raise ValueError("n_dna_atoms must be >= 1")
    cx, cy, cz = center
    axes = {"x": "(1.0, 0.0, 0.0)", "y": "(0.0, 1.0, 0.0)", "z": "(0.0, 0.0, 1.0)"}
    lines: list[str] = []
    for name, axis in axes.items():
        lines.append(
            f"colvar {{\n"
            f"    name dna_com_{name}\n"
            f"    distanceZ {{\n"
            f"        main {{ atomNumbersRange 1-{n_dna_atoms} }}\n"
            f"        ref  {{ dummyAtom ({cx:.3f}, {cy:.3f}, {cz:.3f}) }}\n"
            f"        axis {axis}\n"
            f"    }}\n"
            f"}}"
        )
    for name in ("x", "y", "z"):
        lines.append(
            f"harmonic {{\n"
            f"    name restrain_com_{name}\n"
            f"    colvars dna_com_{name}\n"
            f"    centers 0.0\n"
            f"    forceConstant {force_constant:g}\n"
            f"}}"
        )
    return "\n".join(lines) + "\n"


def orientation_restraint_colvars(
    n_dna_atoms: int,
    reference_file: str,
    *,
    force_constant: float = 500.0,
) -> str:
    """Restrain only the DNA's best-fit rigid-body orientation.

    ``reference_file`` contains the production-start coordinates of the same
    ``1..n_dna_atoms`` group.  The quaternion identity is therefore the pose at
    handoff, rather than the ideal pre-relaxation build.  Colvars projects the
    quaternion force back over the group while leaving its internal coordinates
    free.  Quaternion coordinates are dimensionless, so ``force_constant`` has
    units of kcal/mol (the 500 kcal/mol default is the Colvars manual example).
    """
    if n_dna_atoms < 3:
        raise ValueError("orientation restraint needs at least 3 DNA atoms")
    if not str(reference_file).strip():
        raise ValueError("reference_file must not be blank")
    if force_constant <= 0:
        raise ValueError("force_constant must be > 0")
    return (
        "colvar {\n"
        "    name dna_orientation\n"
        "    orientation {\n"
        f"        atoms {{ atomNumbersRange 1-{n_dna_atoms} }}\n"
        f"        refPositionsFile {reference_file}\n"
        "    }\n"
        "}\n"
        "harmonic {\n"
        "    name restrain_dna_orientation\n"
        "    colvars dna_orientation\n"
        "    centers (1.0, 0.0, 0.0, 0.0)\n"
        f"    forceConstant {force_constant:g}\n"
        "}\n"
    )


def write_orientation_reference_xyz(
    path: str | Path, coordinates_ang: np.ndarray, n_dna_atoms: int
) -> None:
    """Write a high-precision DNA-only XYZ reference from a NAMD checkpoint."""
    coords = np.asarray(coordinates_ang, dtype=float)
    if coords.ndim != 2 or coords.shape[1] != 3 or coords.shape[0] < n_dna_atoms:
        raise ValueError("checkpoint coordinates do not contain the requested DNA group")
    if n_dna_atoms < 3 or not np.isfinite(coords[:n_dna_atoms]).all():
        raise ValueError("orientation reference coordinates must be finite and non-empty")
    lines = [str(n_dna_atoms), "NADOC production-start DNA orientation reference"]
    lines.extend(
        f"X {x:.10f} {y:.10f} {z:.10f}" for x, y, z in coords[:n_dna_atoms]
    )
    Path(path).write_text("\n".join(lines) + "\n")
