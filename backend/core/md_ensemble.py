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
import os
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus
from backend.core.md_protocols import (
    PRODUCTION_DCD_FREQ,
    SegmentSpec,
    build_production_conf,
    build_reseed_conf,
    psf_atom_count,
    write_hmr_psf,
)

_DEFAULT_BASE_SEED = 54321


def generate_seeds(base: int, n: int) -> list[int]:
    """N distinct, reproducible NAMD seeds for an ensemble (pure).

    Consecutive integers from ``base`` — NAMD seeds only need to differ to give
    independent PRNG streams (velocity draw + Langevin forces).  ``base`` defaults to
    the 54321 used by the single-run production path so replica 0 matches it.
    """
    if n < 1:
        raise ValueError("n_replicas must be >= 1")
    return [int(base) + i for i in range(int(n))]


def replica_label(index: int, seed: int) -> str:
    """Human label for a replica row, e.g. ``"Replica 3 · seed 54324"`` (pure)."""
    return f"Replica {int(index) + 1} · seed {int(seed)}"


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
    ready_checkpoint: str,
    workspace: Path,
    dcd_freq: int = PRODUCTION_DCD_FREQ,
    force_resident: Optional[bool] = None,
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
    hmr_name = f"{name_stem}_hmr.psf"
    use_fast = bool(fast)
    if use_fast:
        if (parent_pkg / hmr_name).exists():
            _link_or_copy(parent_pkg / hmr_name, child_pkg / hmr_name)
        else:
            # Build it here.  Fails CLOSED to the safe path rather than 500-ing the whole
            # production launch: write_hmr_psf raises on a PSF it cannot parse, and losing
            # the run over an unreadable topology would be worse than running it at 1 fs.
            try:
                write_hmr_psf(child_pkg / f"{name_stem}.psf", child_pkg / hmr_name)
            except (OSError, RuntimeError, ValueError, IndexError):
                (child_pkg / hmr_name).unlink(missing_ok=True)
                use_fast = False
    structure_psf = hmr_name if use_fast else None

    if mgh_extrabonds and (parent_pkg / "mgh_extrabonds.txt").exists():
        _link_or_copy(parent_pkg / "mgh_extrabonds.txt", child_pkg / "mgh_extrabonds.txt")

    # Segid → NADOC chain map: the flexibility map / trajectory P-order path reads
    # this from the package dir (load_segid_chain_map).  Without it the replica falls
    # back to the reference-PDB P-order, which can't build the 5'-termini specs → the
    # 21 phosphate-less 5' bases render un-positioned/un-coloured.  Immutable, shared.
    if (parent_pkg / "charge_audit.json").exists():
        _link_or_copy(parent_pkg / "charge_audit.json", child_pkg / "charge_audit.json")

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
        stage = (("restart.coor", "equilibrated.coor"),
                 ("restart.vel", "equilibrated.vel"),
                 ("restart.xsc", "equilibrated.xsc"))
    else:
        stage = (("coor", "equilibrated.coor"), ("xsc", "equilibrated.xsc"))
    for ext, dst_name in stage:
        src = parent_pkg / "output" / f"{ready_checkpoint}.{ext}"
        if not src.exists():
            raise FileNotFoundError(f"parent equilibrated checkpoint missing: {src}")
        # Copy (not link): the reseed reads these; keep them independent of the parent.
        shutil.copy2(src, child_pkg / dst_name)

    # ── Reseed (velocity reinit for a replica; velocity-PRESERVING for a continuation) ──
    reseed_name = f"{name_stem}_00_reseed"
    (child_pkg / f"{reseed_name}.conf").write_text(
        build_reseed_conf(
            reseed_name, name_stem, box, mgh_extrabonds,
            seed=seed, equil_base="equilibrated", structure_psf=structure_psf,
            preserve_velocities=continuation,
        )
    )

    steps = max(100, int(total_steps))
    # Drive the production integrator from ONE resolved timestep so the conf's dt and the
    # ns label can never diverge.  The ensemble path previously passed only ``fast`` to
    # build_production_conf, so a manual 2 fs replica silently emitted a 1 fs conf and ran
    # half its labelled simulated time.  4 fs needs the HMR PSF (``use_fast``); if 4 fs was
    # requested but no HMR PSF exists, fall back to the safe 1 fs reference — mirrors the
    # missing-PSF guard in routes_md._append_production_segments.
    eff_timestep_fs = 1.0 if (timestep_fs == 4.0 and not use_fast) else timestep_fs
    length_ns = steps * eff_timestep_fs / 1_000_000.0
    label_ns = f"{length_ns:g}".replace(".", "p")
    prod_name = f"{name_stem}_01_production_{label_ns}ns_k0"
    prod = SegmentSpec(
        name=prod_name,
        stage=f"{length_ns:g} ns production replica (seed {seed})",
        percent=100.0,
        steps=steps,
        temp=300.0,
        damping=5.0,
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
            prod, name_stem, box, mgh_extrabonds,
            seed=seed, fast=use_fast, timestep_fs=eff_timestep_fs,
            structure_psf=structure_psf,
            n_atoms=psf_atom_count(child_pkg / f"{name_stem}.psf"),
            force_resident=force_resident,
        )
    )

    # ── Manifest (production-only; total_ns == length_ns) ───────────────────────
    child_manifest = {
        "nadoc_md_run_manifest_version": 1,
        "protocol": manifest.get("protocol"),
        "package_dir": str(child_pkg.resolve()),
        "name_stem": name_stem,
        "files": manifest.get("files", {}),
        "box_ang": list(box),
        "mgh_extrabonds": mgh_extrabonds,
        # NO "declash" key — a production replica never declashes; generate_sbatch
        # rejects a declash manifest (its mid-chain rebuild can't run in a bare sbatch).
        "charge_audit": manifest.get("charge_audit"),
        "minimization": {"name": reseed_name, "steps": 0},
        "segments": [asdict(prod)],
        # total_ns_from_manifest = Σ(segment steps) × relax ts.  One production segment
        # at the production timestep → total_ns == length_ns (no production_extension,
        # which would double-count).
        "relax_protocol_settings": {"timestep_fs": eff_timestep_fs},
        "fast_relaxation": {"enabled": use_fast, "structure_psf": structure_psf},
        "ensemble": {
            "parent_job_id": parent.job_id,
            "seed": int(seed),
            "index": int(index),
            "reinit_velocities": True,
            "equilibrated_from": ready_checkpoint,
            "length_ns": length_ns,
            "steps": steps,
            "timestep_fs": eff_timestep_fs,
        },
    }
    text = json.dumps(child_manifest, indent=2)
    (child_pkg / "manifest.json").write_text(text)
    (child_pkg / "nadoc_md_run.json").write_text(text)

    child.segments = [
        MdSegmentStatus(
            name=prod.name, stage=prod.stage, percent=prod.percent,
            steps=prod.steps, status="pending",
        )
    ]
    child.current_segment_idx = 0
    child.status = MdStatus.queued
    child.error = None
    child.user_stopped = False
    child.save(workspace)
    return child_pkg
