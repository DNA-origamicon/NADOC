"""Implicit-solvent (GBIS) NAMD package builder for the in-app job runner.

The explicit-solvent path (:mod:`backend.core.namd_solvate`) wraps the DNA in a
periodic TIP3P water box.  For a large single-layer origami that box can reach
~2M atoms — too big for a small GPU's VRAM (NAMD dies at ``buildTileLists``).

This module builds the *same* all-atom, hydrogen-complete DNA topology (via the
shared ``build_charmm_psfgen_topology``) but ships it **dry**: no water, no ions,
no periodic cell.  The stage configs run NAMD's Generalised Born Implicit Solvent
(GBIS), where the solvent is a dielectric continuum and salt enters as a Debye
``ionConcentration``.  Atom count drops ~6-7x (DNA only), so the same origami
that overflowed the card fits comfortably.

Trade-off (documented for the user): GBIS has **no explicit Mg²⁺**, so it captures
no divalent condensation / specific-site binding — it is a legitimate relaxation /
minimisation engine, not a magnesium-stability model.  For seed relaxation off an
oxDNA structure that is exactly the right tool; for final energetics use explicit.

The ENM restraint ladder, minimize/segment machinery, anchors and E-field are all
reused from :mod:`backend.core.md_protocols`; only the solvent model differs (the
``gbis=True`` branch in ``_common_header``).  Because there is no barostat in
implicit solvent, the ladder is NVT-only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from backend.core.md_charge import audit_psf
from backend.core.md_protocols import (
    IMPLICIT_GBIS_PROTOCOL,
    _min_conf,
    _round_up_to_cycle,
    _segment_conf,
    design_has_extra_bases,
    design_has_extensions,
    design_requires_extra_base_declash,
    identify_unpaired_residues,
    mgh_slow_release_segments,
    namd_efield_vector,
    psf_atom_count,
    write_aksimentiev_enm_files,
    write_anchor_restraints_pdb,
    write_restraints_pdb,
)
from backend.core.models import Design
from backend.core.namd_topology import build_charmm_psfgen_topology

import logging

logger = logging.getLogger(__name__)

# GBIS salt as a Debye screening concentration (mol/L).  0.15 M ≈ physiological;
# this replaces the explicit-path Na/Mg ion atoms (there are none in implicit).
_GBIS_ION_CONC_M = 0.15


def build_namd_gbis_package(
    design: Design,
    job_dir: Path,
    *,
    minimize_steps: int = 4_800,
    adaptive_minimization: bool = True,
    min_scale: float = 0.5,
    seed: int = 42,  # noqa: ARG001 — kept for signature parity with the solvate prep
    atomistic_model=None,
    progress=None,
    declash: bool = False,
    force_soft: bool = False,
    anchors: Optional[list] = None,
    anchor_atoms: Optional[list] = None,
    field: Optional[dict] = None,
    gbis_ion_conc_M: float = _GBIS_ION_CONC_M,
) -> tuple[str, str, list]:
    """Build a dry GBIS package + all stage configs in ``job_dir``.

    Mirrors :func:`md_protocols.prepare_mgh_slow_release` minus the GROMACS
    solvation: build the psfgen DNA topology, copy the force field, write the
    Aksimentiev base-ring ENM, and emit GBIS minimize + NVT segment confs.

    ``atomistic_model`` (optional) supplies the DNA starting coordinates — pass an
    oxDNA-relaxed model to seed NAMD from relaxed positions instead of ideal B-DNA
    (the topology is identical either way).

    Returns ``(package_subdir, name_stem, segments)`` relative to ``job_dir``.
    """
    # Lazy imports to avoid pulling namd_solvate's heavy module tail unless a GBIS
    # job actually runs (and to sidestep any import-order coupling).
    from backend.core.namd_solvate import _FF_DIR, _FF_FILES, _check_ff_files  # noqa: PLC0415

    _check_ff_files()
    minimize_steps = _round_up_to_cycle(minimize_steps)

    name = (design.metadata.name or "design").replace(" ", "_")
    name_stem = name

    # 1. Dry, hydrogen-complete DNA topology (same builder the explicit path uses
    #    in strict mode).  GBIS needs a full all-atom PSF with CHARMM radii.
    if progress is not None:
        progress("topology", None, "Building DNA topology (PSF/PDB)…")
    topology_build = build_charmm_psfgen_topology(
        design, atomistic_model=atomistic_model
    )
    dna_pdb = topology_build.pdb_text
    dna_psf = topology_build.psf_text

    dry_audit = audit_psf(
        dna_psf, require_dna_hydrogens=True, require_dna_residue_charge=True
    )
    if not dry_audit.passed:
        raise RuntimeError(
            "Dry DNA topology audit failed; cannot start implicit-solvent NAMD. "
            + "; ".join(dry_audit.errors)
        )

    # 2. Lay out the package directory.
    package_dir = job_dir / "package" / f"{name}_namd_gbis"
    (package_dir / "forcefield").mkdir(parents=True, exist_ok=True)
    (package_dir / "output").mkdir(exist_ok=True)
    (package_dir / f"{name_stem}.psf").write_text(dna_psf)
    (package_dir / f"{name_stem}.pdb").write_text(dna_pdb)
    for ff_file in _FF_FILES:
        ff_path = _FF_DIR / ff_file
        if ff_path.exists():
            (package_dir / "forcefield" / ff_file).write_bytes(ff_path.read_bytes())

    pdb_path = package_dir / f"{name_stem}.pdb"

    # 3. Base-ring ENM restraints (identical to the explicit ladder — the network
    #    is on DNA base-ring atoms, solvent-independent).
    if progress is not None:
        progress("enm", None, "Building elastic-network restraints…")
    write_restraints_pdb(pdb_path, package_dir / "restraints_dna_heavy.pdb")
    # Extra bases remain single-stranded even when a 1xT junction does not require
    # declash.  Keep every such residue (and extension tail) out of the ordinary ENM
    # so the standard ladder can relax it instead of pinning its seed geometry.
    exclude = None
    if design_has_extra_bases(design) or design_has_extensions(design):
        exclude = identify_unpaired_residues(package_dir / f"{name_stem}.psf", pdb_path)
    enm_report = write_aksimentiev_enm_files(
        pdb_path,
        package_dir,
        name_stem,
        exclude_residues=exclude or None,
        progress=progress,
    )

    # 4. Anchors (optional) — fixedAtoms marker PDB, GBIS honours it the same way.
    anchors_file: Optional[str] = None
    anchor_indices: dict = {}
    n_anchored_atoms = 0
    if anchors:
        from backend.core.namd_topology import (  # noqa: PLC0415
            requested_atom_names,
            resolve_anchor_atom_map,
        )

        # Each anchor may name its own atoms; anchor_atoms is the fallback for those
        # that don't.
        anchor_indices = resolve_anchor_atom_map(
            design,
            anchors,
            model=atomistic_model,
            full_topology=True,
            default_atoms=set(anchor_atoms) if anchor_atoms else None,
        )
        if anchor_indices:
            n_anchored_atoms = write_anchor_restraints_pdb(
                pdb_path, package_dir / "restraints_anchors.pdb", anchor_indices
            )
            anchors_file = "restraints_anchors.pdb"
            if not n_anchored_atoms:
                raise ValueError(
                    f"anchor atoms {requested_atom_names(anchor_indices)} matched no heavy "
                    f"atom in the {len(anchor_indices)} anchored residue(s)."
                )

    efield_vec = namd_efield_vector(field)
    if efield_vec is not None and anchors_file is None:
        logger.warning(
            "GBIS E-field prepared with no anchor (scopes %r resolved to no DNA "
            "residues) — the structure will drift down-field.",
            anchors,
        )

    # 5. Declash (auto for junctions with 2+ inserted bases, or designs carrying
    #    strand-extension ssDNA tails): minimise against an ss-excluded ENM so the
    #    inserted bases / tails relax out of clash.  A 1xT junction uses the standard
    #    ladder; it remains excluded from the ordinary ENM above.
    declash = (
        declash
        or design_requires_extra_base_declash(design)
        or design_has_extensions(design)
    )
    declash_enm_file: Optional[str] = None
    n_unpaired = 0
    if declash:
        ss = identify_unpaired_residues(package_dir / f"{name_stem}.psf", pdb_path)
        n_unpaired = len(ss)
        write_aksimentiev_enm_files(
            pdb_path,
            package_dir,
            f"{name_stem}_declash",
            scales=(min_scale,),
            exclude_residues=ss,
        )
        declash_enm_file = f"{name_stem}_declash_k{min_scale:g}.enm.extra"

    # 6. Segment ladder.  Implicit solvent has no barostat → NVT only.  A declash /
    #    force-soft design runs the soft (1 fs, flexible-bond) integrator.
    if progress is not None:
        progress("finalize", None, "Writing simulation configs…")
    # exp49 (2026-07-30) measured the assumption behind this directly: a 25 ps probe as
    # the FIRST dynamics after minimisation, on ideal builds carrying 2 / 24 / 60 inserted
    # crossover bases.  2 fs with rigidBonds all survived every one; only 4 fs + HMR blew
    # up.  So a declash design needs the GENTLE tier (2 fs, rigid), not the flexible-bond
    # 1 fs tier — which was costing 2x across the whole 19.2 ns ladder for protection it
    # never needed.  ``force_soft`` stays as the explicit escape hatch, and the runner
    # still rewrites any segment that actually fails RATTLE down to 1 fs.
    gentle_ladder = declash and not force_soft
    min_name, segments = mgh_slow_release_segments(
        name_stem,
        soft=force_soft,
        gentle=gentle_ladder,
        nvt_only=True,
        timestep_fs=2.0,
    )

    # 7. Confs.  ``box`` is unused under GBIS (no periodic cell) — pass a dummy.
    box = (0.0, 0.0, 0.0)
    (package_dir / f"{min_name}.conf").write_text(
        _min_conf(
            min_name,
            name_stem,
            box,
            False,
            minimize_steps,
            min_scale,
            enm_file=declash_enm_file,
            anchors_file=anchors_file,
            field=field,
            gbis=True,
            n_atoms=psf_atom_count(package_dir / f"{name_stem}.psf"),
            adaptive_minimization=adaptive_minimization,
        )
    )
    # _common_header carries the ionConcentration; patch it per requested salt.
    for spec in segments:
        (package_dir / f"{spec.name}.conf").write_text(
            _segment_conf(
                spec,
                name_stem,
                box,
                False,
                anchors_file=anchors_file,
                field=field,
                gbis=True,
            ).replace(
                "ionConcentration   0.15",
                f"ionConcentration   {gbis_ion_conc_M:g}",
            )
        )
    # Same salt patch for the minimize conf.
    min_conf_path = package_dir / f"{min_name}.conf"
    min_conf_path.write_text(
        min_conf_path.read_text().replace(
            "ionConcentration   0.15", f"ionConcentration   {gbis_ion_conc_M:g}"
        )
    )

    segment_dicts = [
        {
            "name": s.name,
            "stage": s.stage,
            "percent": s.percent,
            "steps": s.steps,
            "temp": s.temp,
            "damping": s.damping,
            "scale": s.scale,
            "npt": s.npt,
            "previous": s.previous,
            "reinit": s.reinit,
            "dcd_freq": s.dcd_freq,
            "min_c1_paired": s.min_c1_paired,
            "min_wc_ref_relative": s.min_wc_ref_relative,
            "extra_bonds_file": s.extra_bonds_file,
            "soft": s.soft,
            "gentle": s.gentle,
            "timestep_fs": s.timestep_fs,
        }
        for s in segments
    ]

    manifest = {
        "nadoc_md_run_manifest_version": 1,
        "protocol": IMPLICIT_GBIS_PROTOCOL,
        "package_dir": str(package_dir.resolve()),
        "name_stem": name_stem,
        "files": {
            "topology": f"{name_stem}.psf",
            "coordinates": f"{name_stem}.pdb",
            "forcefield_dir": "forcefield",
            "output_dir": "output",
            "restraints": "restraints_dna_heavy.pdb",
            **({"anchors": anchors_file} if anchors_file else {}),
        },
        "box_ang": None,
        "mgh_extrabonds": False,
        "solvent": {
            "model": "gbis_implicit",
            "generalised_born": True,
            "ion_concentration_M": gbis_ion_conc_M,
            "solvent_dielectric": 78.5,
            "note": (
                "Generalised Born implicit solvent — no explicit water or Mg²⁺. "
                "Relaxation/minimisation engine; not a magnesium-stability model."
            ),
        },
        "anchors": {
            "requested": anchors or [],
            "file": anchors_file,
            "n_residues": len(anchor_indices),
            "n_atoms_fixed": n_anchored_atoms,
            "mechanism": "fixedAtoms (fixedAtomsCol B)",
        },
        "field": (
            {
                "field_pN": float(
                    field.get("field_pN", field.get("force_pN", 0.0)) or 0.0
                ),
                "dir": [float(c) for c in field["dir"]],
                "efield_vector": list(efield_vec),
                "mechanism": "native NAMD eFieldOn/eField",
            }
            if efield_vec is not None
            else None
        ),
        "declash": declash,
        "declash_min_coor": f"output/{min_name}.coor" if declash else None,
        "n_unpaired_excluded": n_unpaired if declash else 0,
        "minimization": {
            "name": min_name,
            "steps": minimize_steps,
            "scale": min_scale,
            # Timeline label — see md_protocols.minimization_slot.
            "stage": f"Minimization ENM k={min_scale:g}",
            "restraint": "aksimentiev_base_ring_enm",
            "extra_bonds_file": f"{name_stem}_k{min_scale:g}.enm.extra",
        },
        "aksimentiev_enm": enm_report,
        "fast_relaxation": {
            "enabled": False,
            "note": "GBIS runs the standard CUDA path (no GPUresident).",
        },
        "segments": segment_dicts,
        "health_checks": "After every segment: 10%, 50%, and 100% of each stage.",
    }
    manifest_text = json.dumps(manifest, indent=2)
    (package_dir / "manifest.json").write_text(manifest_text)
    (package_dir / "nadoc_md_run.json").write_text(manifest_text)

    package_subdir = str(package_dir.relative_to(job_dir))
    return package_subdir, name_stem, segments


def prepare_implicit_gbis_namd(
    design: Design,
    job_dir: Path,
    *,
    minimize_steps: int = 4_800,
    atomistic_model=None,
    progress=None,
    declash: bool = False,
    force_soft: bool = False,
    anchors: Optional[list] = None,
    anchor_atoms: Optional[list] = None,
    field: Optional[dict] = None,
    # Accept-and-ignore the explicit-solvent kwargs so the shared prep call site
    # (routes_md) can pass one uniform kwarg set regardless of protocol.
    ion_conc_mM: float = 0.0,  # noqa: ARG001
    mg_conc_mM: float = 0.0,  # noqa: ARG001
    salt_mode: str = "custom",  # noqa: ARG001
    padding_nm: float = 1.2,  # noqa: ARG001
    box_mode: str = "rotation",  # noqa: ARG001 — implicit solvent has no cell
    # Cell-sizing intent: meaningless here — GBIS is implicit solvent with no periodic
    # cell, so there is no image for the solute to rotate into.
    free_ns: Optional[float] = None,  # noqa: ARG001
    fast: bool = False,  # noqa: ARG001 — GBIS forces standard CUDA
    seed: int = 42,  # noqa: ARG001
    # GBIS has no explicit-solvent box and cannot run GPU-resident (no implicit-solvent
    # path in resident mode), so both of these are inapplicable here — but the shared
    # prep call site in routes_md passes ONE uniform kwarg set for every protocol, so
    # they must still be accepted.  They were added to that call site by the
    # GPU-resident dropdown work without being added here, which broke every GBIS job
    # at prep with "unexpected keyword argument 'gpu_resident_mode'".
    # tests/test_prepare_signatures.py now pins this.
    gpu_resident_mode: str = "auto",  # noqa: ARG001
    production_timestep_fs: float = 4.0,  # noqa: ARG001
    # Accepted and ignored: implicit solvent has no GPU-resident path and no HMR PSF (the
    # repartitioned copy is written by the explicit-solvent prep), and this ladder pins its
    # own integrator.  routes_md passes one uniform kwarg set to every protocol, so these
    # must be accepted here even though they cannot apply — see tests/test_prepare_signatures.
    relax_timestep_fs: Optional[float] = None,  # noqa: ARG001
    relax_rigid_bonds: Optional[str] = None,  # noqa: ARG001
    relax_hmr: Optional[bool] = None,  # noqa: ARG001
    production_rigid_bonds: Optional[str] = None,  # noqa: ARG001
    production_hmr: Optional[bool] = None,  # noqa: ARG001
    devices: str = "0",  # noqa: ARG001 — no box to size
    # Recorded by the explicit path for its protocol_fidelity block; GBIS has no
    # published protocol to be faithful to, so it accepts-and-ignores.
    early_stop_relax: bool = False,  # noqa: ARG001
    adaptive_minimization: bool = True,
    # Per-stage hand edits.  Accepted-and-ignored for now: the GBIS ladder writes its
    # confs through its own emitter, so honouring them here would need the same
    # apply_conf_overrides pass the explicit path got.  Left undone deliberately rather
    # than half-done — the wizard only offers the editable table for the explicit
    # protocol, and silently dropping edits would be worse than not offering them.
    stage_overrides: Optional[dict] = None,  # noqa: ARG001
) -> tuple[str, str, list]:
    """Protocol entry point: prepare an implicit-solvent (GBIS) NAMD job.

    Salt: the explicit ``ion_conc_mM`` (NaCl) is mapped to the GBIS Debye
    ``ionConcentration`` when nonzero, else physiological 0.15 M is used.
    """
    ion_M = (
        (ion_conc_mM / 1000.0) if ion_conc_mM and ion_conc_mM > 0 else _GBIS_ION_CONC_M
    )
    return build_namd_gbis_package(
        design,
        job_dir,
        minimize_steps=minimize_steps,
        adaptive_minimization=adaptive_minimization,
        atomistic_model=atomistic_model,
        progress=progress,
        declash=declash,
        force_soft=force_soft,
        anchors=anchors,
        anchor_atoms=anchor_atoms,
        field=field,
        gbis_ion_conc_M=ion_M,
    )
