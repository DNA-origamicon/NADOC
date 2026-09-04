"""
MD ensemble — fan out N independent NAMD production replicas from one equilibrated
structure to a compute cluster (Alpine/SLURM).

The scientifically-standard multi-seed ensemble: relax/equilibrate ONCE (the parent
:class:`~backend.core.md_job.MdJob`), then run N production replicas that share the
parent's equilibrated coordinates but each draw their OWN Maxwell-Boltzmann velocity
set at 300 K from a distinct NAMD ``seed`` (``reinitvels``).  Each replica is a child
``MdJob`` (``parent_job_id`` set, ``execution_target="alpine"``, its own
``ensemble_seed``) with its own production-only package, submitted as its own sbatch —
so the existing per-job SLURM poll loop (:func:`md_executor.poll_remote_jobs`) tracks
each replica independently and the panel renders them under the parent's expand chevron.

This module owns only the ENSEMBLE-specific bits: distinct-seed generation and building
a replica's production-only package from the parent's package.  Submission reuses
:func:`md_executor.submit_job` verbatim (one child at a time).  Conf generation reuses
the shared, parameterized builders in :mod:`backend.core.md_protocols`.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus
from backend.core.md_protocols import (
    PRODUCTION_DCD_FREQ,
    PRODUCTION_ENM_K,
    PRODUCTION_LANGEVIN_DAMPING,
    PRODUCTION_RECIPE_VERSION,
    SegmentSpec,
    build_production_conf,
    build_reseed_conf,
    package_npt_allowed,
    overrides_for_stage,
    protocol_fidelity,
    psf_atom_count,
    retarget_anchor_pdb,
    write_hmr_psf,
    write_production_enm,
)

logger = logging.getLogger(__name__)

_DEFAULT_BASE_SEED = 54321

#: Largest NAMD ``seed``.  NAMD stores it as a signed 32-bit int, so the usable range is
#: 1 .. 2^31-1.  Draws are held below the top so ``base + n_replicas`` cannot overflow.
NAMD_SEED_MAX = 2**31 - 1
_SEED_DRAW_CEILING = NAMD_SEED_MAX - 4096


def generate_seeds(base: int, n: int) -> list[int]:
    """N distinct, reproducible NAMD seeds for an ensemble (pure).

    Consecutive integers from ``base`` — NAMD seeds only need to differ to give
    independent PRNG streams (velocity draw + Langevin forces).  ``base`` is drawn
    fresh per ensemble by :func:`random_seed`; pass an explicit one only to reproduce
    a specific past run.
    """
    if n < 1:
        raise ValueError("n_replicas must be >= 1")
    return [int(base) + i for i in range(int(n))]


def random_seed(exclude: Iterable[int] = ()) -> int:
    """A fresh NAMD velocity seed, uniform in 1 .. ``_SEED_DRAW_CEILING``.

    Every production run draws its own — a fixed seed means two runs of the same
    structure share one velocity realisation and one Langevin force stream, so they are
    the SAME trajectory, not two samples of an ensemble.  When designs are compared
    against each other that also correlates their thermal histories, which is exactly the
    error a multi-replica comparison exists to avoid.

    Reproducibility is preserved by RECORDING, not by fixing: the drawn value lands in
    ``MdJob.ensemble_seed``, the manifest, and the segment's stage label, and can be
    replayed by passing it back explicitly.

    ``exclude`` (typically the seeds of a job's existing siblings) is never returned, so
    a fan-out cannot collide onto one trajectory.  Uses :mod:`secrets` rather than
    :mod:`random` so a run started from a freshly-forked worker cannot inherit a
    process-global RNG state that another worker already drew from.
    """
    taken = {int(s) for s in exclude}
    for _ in range(64):
        seed = secrets.randbelow(_SEED_DRAW_CEILING) + 1
        if seed not in taken:
            return seed
    # 64 collisions against a 2-billion-wide range is not chance; take the first free
    # value rather than looping forever.
    seed = secrets.randbelow(_SEED_DRAW_CEILING) + 1
    while seed in taken:
        seed = seed % _SEED_DRAW_CEILING + 1
    return seed


def replica_label(index: int, seed: int) -> str:
    """Human label for a replica row, e.g. ``"Replica 3 · seed 54324"`` (pure)."""
    return f"Replica {int(index) + 1} · seed {int(seed)}"


def _anchor_weight(pdb_line: str) -> float:
    """Column-B anchor weight of a PDB ATOM/HETATM line (0.0 when blank/unparsable)."""
    try:
        return float(pdb_line[60:66])
    except (ValueError, IndexError):
        return 0.0


def _link_or_copy(src: Path, dst: Path) -> None:
    """Hardlink ``src`` → ``dst`` (disk-free, same filesystem), copying on failure.

    Replica packages share the parent's large immutable structure files (PSF/PDB/
    forcefield); a hardlink avoids duplicating tens of MB per replica.  Replicas never
    rewrite these files, so the shared inode is safe.  Falls back to a full copy across
    filesystems or when linking is unsupported.  No-op if the destination exists.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def build_replica_package(
    parent: MdJob,
    child: MdJob,
    *,
    seed: int,
    index: int,
    total_steps: int,
    length_ns: float,
    timestep_fs: float,
    fast: bool,
    #: The two integrator axes the timestep used to imply.  ``None`` = follow ``fast``
    #: (which is only a NAME for 4 fs), so an untouched call is byte-identical to what it
    #: emitted before they existed.  Passing them is how a child runs, say, 2 fs WITHOUT
    #: rigid bonds — a combination exp51 measured and the spawn route could not express.
    rigid_bonds: Optional[str] = None,
    hmr: Optional[bool] = None,
    ready_checkpoint: str,
    workspace: Path,
    dcd_freq: int = PRODUCTION_DCD_FREQ,
    force_resident: Optional[bool] = None,
    enm_restraints: bool = False,
    enm_k: float = PRODUCTION_ENM_K,
    damping: float = PRODUCTION_LANGEVIN_DAMPING,
    stage_overrides: Optional[dict] = None,
    anchors_file: Optional[str] = None,
    #: Where to READ the marker PDB from.  Defaults to the parent package, but the
    #: production route now stages a child-local copy: writing into the shared parent
    #: package meant every new anchored launch overwrote the reference file that
    #: already-completed children still pointed at.
    anchors_src: "Optional[Path]" = None,
    anchor_k: Optional[float] = None,
    anchors_requested: Optional[list] = None,
    field: Optional[dict] = None,
    orientation_restraint: bool = False,
    orientation_force_constant: float = 500.0,
    force_nvt: bool = False,
) -> Path:
    """Build a production-only package for one ensemble replica; returns its package dir.

    Layout (everything staged — ``md_executor.stage_plan`` skips only ``output/`` and
    ``*.log``): the parent's ``{stem}.psf``/``.pdb``/``forcefield/``/``mgh_extrabonds.txt``
    (+ ``{stem}_hmr.psf`` for the fast path) hardlinked in; the parent's equilibrated
    ``output/{ready_checkpoint}.{coor,xsc}`` copied to package-root
    ``equilibrated.{coor,xsc}`` (so they upload); a **reseed** conf (manifest
    ``minimization`` slot) that reinitialises velocities from this replica's ``seed`` and
    writes ``output/{reseed}.{coor,vel,xsc}``; and a **production** conf reading that
    reseed checkpoint.  The manifest is production-only (no ``declash`` key, so
    ``generate_sbatch`` accepts it) with ``total_ns == length_ns``.

    ``anchors_file`` / ``field`` are the JOB's external forces.  They used to be dropped
    here: this builder called ``build_production_conf`` without either, and never staged
    the anchor PDB — so a relaxation prepared WITH anchors produced an UNANCHORED
    production child, and an E-field job's production child ran FIELD-FREE while its
    record still said otherwise.  (The sibling append route never had this hole; it reads
    both back out of the manifest.)  The caller passes them; ``None`` keeps the
    unanchored/field-free conf byte-identical to before.

    ``anchor_k`` (kcal/mol/Å², column B) switches the anchor from a hard ``fixedAtoms``
    pin to a **soft harmonic restraint** — see :func:`md_protocols.external_forces_block`.
    Because a soft restraint needs REFERENCE coordinates and the prep-time anchor PDB
    holds the idealised build pose, the file is re-pointed at this replica's equilibrated
    start (:func:`md_protocols.retarget_anchor_pdb`) rather than hardlinked; otherwise the
    restraint would pull the structure back to where the ladder moved it from.

    Mutates + saves ``child`` (name_stem, package_subdir, one production segment,
    ``status = queued``).  Pure-ish file IO; raises ``FileNotFoundError`` if the parent
    checkpoint coords are missing.
    """
    parent_pkg = parent.package_dir(workspace)
    manifest = json.loads((parent_pkg / "manifest.json").read_text())
    name_stem = manifest["name_stem"]
    box = tuple(float(x) for x in manifest["box_ang"])
    mgh_extrabonds = bool(manifest.get("mgh_extrabonds"))

    child.name_stem = name_stem
    child.package_subdir = parent.package_subdir
    child_pkg = child.package_dir(workspace)
    child_pkg.mkdir(parents=True, exist_ok=True)
    (child_pkg / "output").mkdir(exist_ok=True)

    # Topology snapshot: a production/ensemble child runs the parent's PSF/PDB, so it
    # shares the parent's frozen design.json.  Copy it into the child's job dir (mirrors
    # oxDNA's child spawn).  Without it the metrics/trajectory endpoints can't map P atoms
    # → base pairs and fall back to whatever design is loaded — or fail with a misleading
    # "no NAMD trajectory" even though the DCD is present.
    parent_snapshot = parent.job_dir(workspace) / "design.json"
    if parent_snapshot.exists():
        child.job_dir(workspace).mkdir(parents=True, exist_ok=True)
        shutil.copy2(parent_snapshot, child.job_dir(workspace) / "design.json")

    # ── Structure files (shared, immutable) ────────────────────────────────────
    for rel in (f"{name_stem}.psf", f"{name_stem}.pdb"):
        _link_or_copy(parent_pkg / rel, child_pkg / rel)

    # 4 fs needs a hydrogen-mass-repartitioned PSF.  It does NOT need the PARENT to have
    # built one: HMR is a pure mass edit of the PSF (coordinates and force field are
    # untouched), so it can be produced here from the structure the child already copied.
    # This used to require `(parent_pkg / hmr_name).exists()`, which silently downgraded a
    # requested 4 fs to 1 fs whenever the relaxation had not run in fast mode — letting the
    # RELAXATION's integrator dictate PRODUCTION's, which is backwards: the ladder's job is
    # to deliver equilibrated coordinates, and production is free to sample them at any
    # sanctioned timestep.  Reseeding (build_reseed_conf below) re-draws velocities at
    # temperature, so the mass change never inherits a checkpoint's old kinetic energy.
    hmr_downgrade_reason: Optional[str] = None
    hmr_build_failed = False
    hmr_name = f"{name_stem}_hmr.psf"
    # `fast` is only a NAME for 4 fs; HMR is its own axis since exp51.  An explicit
    # hmr=False at 4 fs is a legal, measured-but-warned choice (standard masses), and it
    # must NOT be treated as a failed repartition — only a PSF that cannot be built is
    # that, and only that downgrades the timestep below.
    use_fast = bool(fast) if hmr is None else bool(hmr)
    if use_fast:
        if (parent_pkg / hmr_name).exists():
            _link_or_copy(parent_pkg / hmr_name, child_pkg / hmr_name)
        else:
            # Build it here.  Fails CLOSED to the safe path rather than 500-ing the whole
            # production launch: write_hmr_psf raises on a PSF it cannot parse, and losing
            # the run over an unreadable topology would be worse than running it at 1 fs.
            try:
                write_hmr_psf(child_pkg / f"{name_stem}.psf", child_pkg / hmr_name)
            except (OSError, RuntimeError, ValueError, IndexError) as exc:
                (child_pkg / hmr_name).unlink(missing_ok=True)
                use_fast = False
                hmr_build_failed = True
                # LOUD.  A downgrade the user cannot see is the bug this whole area keeps
                # reproducing: a "4 fs" run that quietly delivers 1 fs looks like a
                # mysterious 3x throughput loss, not a fallback.  Recorded in the manifest
                # (surfaced by the panel) as well as the log.
                hmr_downgrade_reason = (
                    f"4 fs was requested but the hydrogen-mass-repartitioned PSF could not "
                    f"be built from {name_stem}.psf ({type(exc).__name__}: {exc}). The run "
                    f"was downgraded to the 1 fs conservative reference — it is NOT running "
                    f"at 4 fs."
                )
                logger.warning("[%s] %s", child.job_id, hmr_downgrade_reason)
    structure_psf = hmr_name if use_fast else None

    if mgh_extrabonds and (parent_pkg / "mgh_extrabonds.txt").exists():
        _link_or_copy(
            parent_pkg / "mgh_extrabonds.txt", child_pkg / "mgh_extrabonds.txt"
        )

    # Segid → NADOC chain map: the flexibility map / trajectory P-order path reads
    # this from the package dir (load_segid_chain_map).  Without it the replica falls
    # back to the reference-PDB P-order, which can't build the 5'-termini specs → the
    # 21 phosphate-less 5' bases render un-positioned/un-coloured.  Immutable, shared.
    if (parent_pkg / "charge_audit.json").exists():
        _link_or_copy(parent_pkg / "charge_audit.json", child_pkg / "charge_audit.json")

    # The graphene membrane is part of the simulated system, not merely preparation UI.
    # Carry its machine-readable descriptor into every production child just as we carry
    # the PSF/PDB.  Previously only graphene_fixed.pdb happened to survive through the
    # anchors path: NAMD could restrain the atoms, but the child manifest/reloaded UI said
    # there was no nanopore and downstream transport analysis lost its pore geometry.
    graphene_nanopore = manifest.get("graphene_nanopore")
    if graphene_nanopore and (parent_pkg / "graphene_nanopore.json").is_file():
        shutil.copy2(
            parent_pkg / "graphene_nanopore.json",
            child_pkg / "graphene_nanopore.json",
        )

    ff = parent_pkg / "forcefield"
    if ff.is_dir():
        for f in sorted(ff.rglob("*")):
            if f.is_file():
                _link_or_copy(f, child_pkg / "forcefield" / f.relative_to(ff))

    # ── Equilibrated start (root-level so it stages) ────────────────────────────
    # A production PARENT is a true CONTINUATION, not a fresh replica: carry its OWN
    # paired restart set (coor+vel+xsc) so production resumes with the endpoint's
    # constraint-consistent velocities. reinitvels on a warm NPT endpoint injects
    # force-uncorrelated velocities that overflow the startup RATTLE solve -> KINETIC=NaN
    # at step 0 (validated: the reseed also read the clashed final .coor; the paired
    # .restart.coor is clean). A relaxation parent stays a replica SPAWN (coords+box only).
    continuation = getattr(parent, "run_kind", "") == "production"
    if continuation:
        stage = (
            ("restart.coor", "equilibrated.coor"),
            ("restart.vel", "equilibrated.vel"),
            ("restart.xsc", "equilibrated.xsc"),
        )
    else:
        stage = (("coor", "equilibrated.coor"), ("xsc", "equilibrated.xsc"))
    for ext, dst_name in stage:
        src = parent_pkg / "output" / f"{ready_checkpoint}.{ext}"
        if not src.exists():
            raise FileNotFoundError(f"parent equilibrated checkpoint missing: {src}")
        # Copy (not link): the reseed reads these; keep them independent of the parent.
        shutil.copy2(src, child_pkg / dst_name)

    # ── Anchors (external forces) ──────────────────────────────────────────────
    # Staged AFTER the equilibrated checkpoint, because a soft anchor is re-referenced to
    # it.  A hard anchor is coordinate-independent (fixedAtoms marks atoms, it does not
    # restrain them TO anything), so it is hardlinked verbatim.
    n_anchor_atoms = 0
    if anchors_file:
        src_anchor = Path(anchors_src) if anchors_src else (parent_pkg / anchors_file)
        if not src_anchor.exists():
            raise FileNotFoundError(f"anchor file missing: {src_anchor}")
        dst_anchor = child_pkg / anchors_file
        if anchor_k is None:
            # COPY, never hardlink.  Unlike the PSF/PDB/forcefield this file is NOT
            # immutable: a later anchored launch rewrites its source in place, and a
            # hardlinked child would silently inherit the new selection and k — which is
            # exactly how a completed run's marker PDB came to disagree with the restraint
            # energy NAMD had logged for it.
            shutil.copy2(src_anchor, dst_anchor)
            n_anchor_atoms = sum(
                1
                for ln in src_anchor.read_text().splitlines()
                if ln.startswith(("ATOM", "HETATM")) and _anchor_weight(ln) > 0
            )
        else:
            from backend.core.md_shell_reprep import read_namd_coor  # noqa: PLC0415

            coords = read_namd_coor(child_pkg / "equilibrated.coor")
            n_anchor_atoms = retarget_anchor_pdb(
                src_anchor, dst_anchor, coords=coords, k=anchor_k
            )
        logger.info(
            "[%s] anchors: %d atom(s) %s",
            child.job_id,
            n_anchor_atoms,
            "fixed (fixedAtoms)"
            if anchor_k is None
            else f"restrained at k={anchor_k:g} kcal/mol/A^2 vs the equilibrated pose",
        )

    # ── Reseed (velocity reinit for a replica; velocity-PRESERVING for a continuation) ──
    # A carved cell (vacuum corners) must stay at constant volume — the parent package's
    # manifest is the record of how it was solvated.  The replica inherits that.
    npt_allowed = package_npt_allowed(parent_pkg) and not force_nvt
    reseed_name = f"{name_stem}_00_reseed"
    (child_pkg / f"{reseed_name}.conf").write_text(
        build_reseed_conf(
            reseed_name,
            name_stem,
            box,
            mgh_extrabonds,
            seed=seed,
            equil_base="equilibrated",
            structure_psf=structure_psf,
            preserve_velocities=continuation,
            npt=npt_allowed,
        )
    )

    steps = max(100, int(total_steps))
    # Drive the production integrator from ONE resolved timestep so the conf's dt and the
    # ns label can never diverge.  The ensemble path previously passed only ``fast`` to
    # build_production_conf, so a manual 2 fs replica silently emitted a 1 fs conf and ran
    # half its labelled simulated time.  4 fs needs the HMR PSF (``use_fast``); if 4 fs was
    # requested but no HMR PSF exists, fall back to the safe 1 fs reference — mirrors the
    # missing-PSF guard in routes_md._append_production_segments.
    # Elastic network retained through production, built from the coordinates this run
    # STARTS from (see md_protocols.write_production_enm — a prep-time network would drag
    # the structure back to the pre-ladder build).  Fails open: losing a production run
    # over an unbuildable network would be worse than running it unrestrained, but the
    # reason is recorded in the manifest rather than swallowed.
    enm_file: Optional[str] = None
    enm_error: Optional[str] = None
    if enm_restraints:
        try:
            enm_file = write_production_enm(
                child_pkg, name_stem, child_pkg / "equilibrated.coor", scale=enm_k
            )
        except (OSError, RuntimeError, ValueError) as exc:
            enm_error = (
                f"production elastic network could not be built "
                f"({type(exc).__name__}: {exc}); this run is UNRESTRAINED"
            )
            logger.warning("[%s] %s", child.job_id, enm_error)

    colvars_file: Optional[str] = None
    if orientation_restraint:
        from backend.core.md_shell_reprep import (  # noqa: PLC0415
            orientation_restraint_colvars,
            read_namd_coor,
            write_orientation_reference_xyz,
        )

        # NADOC writes the complete hydrogen-bearing DNA block first in both PSF and
        # PDB; solvent and ions are HETATM records after it.  Reference the equilibrated
        # checkpoint so the bias starts at zero torque.
        n_dna = sum(
            1
            for line in (child_pkg / f"{name_stem}.pdb").read_text().splitlines()
            if line.startswith("ATOM")
        )
        reference_name = "dna_orientation_reference.xyz"
        colvars_file = "dna_orientation.colvars"
        write_orientation_reference_xyz(
            child_pkg / reference_name,
            read_namd_coor(child_pkg / "equilibrated.coor"),
            n_dna,
        )
        (child_pkg / colvars_file).write_text(
            orientation_restraint_colvars(
                n_dna, reference_name, force_constant=orientation_force_constant
            )
        )

    # ONLY an unbuildable HMR PSF drops the timestep.  It used to be `not use_fast`, which
    # after exp51 would also fire for a deliberate hmr=False at 4 fs — silently running a
    # quarter of the requested simulated time for a combination the user chose on purpose.
    eff_timestep_fs = 1.0 if (timestep_fs == 4.0 and hmr_build_failed) else timestep_fs
    length_ns = steps * eff_timestep_fs / 1_000_000.0
    label_ns = f"{length_ns:g}".replace(".", "p")
    prod_name = f"{name_stem}_01_production_{label_ns}ns_k0"
    prod = SegmentSpec(
        name=prod_name,
        stage=f"{length_ns:g} ns production replica (seed {seed})",
        percent=100.0,
        steps=steps,
        temp=300.0,
        damping=damping,
        scale=None,
        npt=True,
        previous=reseed_name,
        reinit=False,
        dcd_freq=dcd_freq,
        min_c1_paired=0.90,
        min_wc_ref_relative=0.25,
    )
    # GPU-resident: the replica package is what the panel's Start-Production actually
    # builds, so it needs the same size gate + explicit override as every other conf
    # writer.  Without n_atoms this fell to "unknown" and forced resident ON, which is
    # why turning the Advanced-card dropdown off changed nothing for a production run.
    (child_pkg / f"{prod_name}.conf").write_text(
        build_production_conf(
            prod,
            name_stem,
            box,
            mgh_extrabonds,
            seed=seed,
            fast=use_fast,
            timestep_fs=eff_timestep_fs,
            # The third axis. Without it a child that asked for 2 fs with rigid bonds OFF
            # got `rigidBonds all` anyway, because the writer derived it from the timestep.
            rigid_bonds=("none" if hmr_build_failed else rigid_bonds),
            hmr=use_fast,
            structure_psf=structure_psf,
            n_atoms=psf_atom_count(child_pkg / f"{name_stem}.psf"),
            force_resident=force_resident,
            npt=npt_allowed,
            damping=damping,
            enm_file=enm_file,
            # Stage 0 of a production child is the velocity reseed (which takes no
            # overrides — it runs zero steps); the production stage itself is 1.
            overrides=overrides_for_stage(stage_overrides, 1),
            anchors_file=anchors_file,
            anchor_k=anchor_k,
            field=field,
            colvars_file=colvars_file,
        )
    )

    # ── Manifest (production-only; total_ns == length_ns) ───────────────────────
    child_manifest = {
        "nadoc_md_run_manifest_version": 1,
        "protocol": manifest.get("protocol"),
        "package_dir": str(child_pkg.resolve()),
        "name_stem": name_stem,
        # `files.anchors` must describe THIS package, not the parent's: a child can be
        # anchored when its parent was not (or vice versa), and the append route reads
        # this key back to keep an extended stage under the same forces.
        "files": {
            **manifest.get("files", {}),
            **({"anchors": anchors_file} if anchors_file else {"anchors": None}),
            **({"graphene_nanopore": "graphene_nanopore.json"} if graphene_nanopore else {}),
        },
        "box_ang": list(box),
        "mgh_extrabonds": mgh_extrabonds,
        "graphene_nanopore": graphene_nanopore,
        "anchor_groups": manifest.get("anchor_groups"),
        # The child's OWN external forces, so the run record states what it ran under
        # instead of leaving an analysis to assume "production = unrestrained".
        "field": field,
        "anchors": (
            {
                "requested": anchors_requested or [],
                "file": anchors_file,
                "n_atoms_anchored": n_anchor_atoms,
                "k_kcal_mol_a2": anchor_k,
                "mechanism": (
                    "fixedAtoms (fixedAtomsCol B); held immobile"
                    if anchor_k is None
                    else "harmonic restraints (constraints/consref/conskfile, conskcol B), "
                    "referenced to this replica's equilibrated coordinates"
                ),
            }
            if anchors_file
            else None
        ),
        # NO "declash" key — a production replica never declashes; generate_sbatch
        # rejects a declash manifest (its mid-chain rebuild can't run in a bare sbatch).
        "charge_audit": manifest.get("charge_audit"),
        # The parent's solvation record — padding, water shell, npt_allowed and the
        # box_check verdict.  A child re-uses the parent's cell verbatim (hardlinked
        # PSF/PDB, box_ang copied above), so the parent's verdict is EXACTLY the
        # child's verdict.  Dropping it made `_assert_cell_fits_a_free_run` read an
        # empty dict on every child and fall through its `fits_rotated=True` default:
        # prep measured that a turned solute overlaps its own image, recorded it, and
        # the one hop to the child threw the answer away.
        "solvation": manifest.get("solvation"),
        # Occupies the minimization slot but is a zero-step velocity reseed, not a
        # minimisation — hence the explicit label (md_protocols.minimization_slot).
        "minimization": {"name": reseed_name, "steps": 0, "stage": "Velocity reseed"},
        # What this production run actually restrained and how hard it was thermostatted —
        # both differ from the ladder, and both are things a methods section has to state.
        "production_recipe": {
            "version": PRODUCTION_RECIPE_VERSION,
            "langevin_damping": damping,
            "enm_restraints": bool(enm_file),
            "enm_k": enm_k if enm_file else None,
            "enm_file": enm_file,
            "enm_network": "base-ring, inter-residue, 8 A cutoff" if enm_file else None,
            "enm_built_from": "equilibrated checkpoint" if enm_file else None,
            "enm_error": enm_error,
            "orientation_restraint": bool(colvars_file),
            "orientation_force_constant_kcal_mol": (
                orientation_force_constant if colvars_file else None
            ),
            "orientation_reference": (
                "equilibrated checkpoint" if colvars_file else None
            ),
        },
        "stage_overrides": stage_overrides or {},
        # A production child's OWN delta from the published protocol — the parent's
        # block describes the ladder and cannot know what production ended up doing.
        "protocol_fidelity": protocol_fidelity(
            fast=use_fast,
            carved=not npt_allowed,
            padding_nm=float(
                ((manifest.get("solvation") or {}).get("padding_nm")) or 2.0
            ),
            charge_audit=manifest.get("charge_audit") or {},
            production_enm=bool(enm_file),
            stage_overrides=stage_overrides,
        ),
        "segments": [asdict(prod)],
        # total_ns_from_manifest = Σ(segment steps) × relax ts.  One production segment
        # at the production timestep → total_ns == length_ns (no production_extension,
        # which would double-count).
        "relax_protocol_settings": {"timestep_fs": eff_timestep_fs},
        "fast_relaxation": {"enabled": use_fast, "structure_psf": structure_psf},
        # The three integrator axes this child resolved to, in the same manifest keys the
        # prep path writes them under — so chaining a production off THIS job reads its
        # parent's real choice instead of falling back to the auto value for the timestep.
        "production_timestep_fs": eff_timestep_fs,
        "production_rigid_bonds": rigid_bonds,
        "production_hmr": use_fast,
        "ensemble": {
            "parent_job_id": parent.job_id,
            "seed": int(seed),
            "index": int(index),
            "reinit_velocities": True,
            "equilibrated_from": ready_checkpoint,
            "length_ns": length_ns,
            "steps": steps,
            "timestep_fs": eff_timestep_fs,
            # Non-null ⇒ the run is NOT at the timestep that was asked for, and says why.
            # Never let a downgrade be invisible: it presents as unexplained lost
            # throughput, which is far harder to diagnose than a refusal.
            "timestep_downgrade_reason": hmr_downgrade_reason,
        },
    }
    text = json.dumps(child_manifest, indent=2)
    (child_pkg / "manifest.json").write_text(text)
    (child_pkg / "nadoc_md_run.json").write_text(text)

    child.segments = [
        MdSegmentStatus(
            name=prod.name,
            stage=prod.stage,
            percent=prod.percent,
            steps=prod.steps,
            status="pending",
        )
    ]
    child.minimization = MdSegmentStatus(
        name=reseed_name,
        stage="Velocity reseed",
        percent=100.0,
        steps=0,
        status="pending",
    )
    child.current_segment_idx = 0
    child.status = MdStatus.queued
    child.error = None
    child.user_stopped = False
    child.save(workspace)
    return child_pkg
