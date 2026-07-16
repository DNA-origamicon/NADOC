"""
MD Protocol Presets — config generation for managed NAMD jobs.

Currently implements one preset:

  mgh_slow_release
    MGH explicit-solvent package (Mg-hexahydrate, TIP3P, CHARMM36/CUFIX)
    → Aksimentiev-style ENM minimization and long NPT equilibration
    → ENM ladder k=0.5 → 0.1 → 0.01 → k=0 handoff
    Health gates after every segment:
    C1' paired fraction ≥ 90%
    WC ref-relative ≥ 80% during ENM stages and ≥ 75% during k=0 handoff

Each segment runs to 10%, 50%, or 100% of its stage length so health checks
are frequent early in each new temperature or k setting.
"""

from __future__ import annotations

import io
import json
import logging
import math
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from scipy.spatial import cKDTree

logger = logging.getLogger(__name__)

from backend.core.models import Design


LEGACY_PROTOCOL = "mgh_slow_release"
EQUILIBRIUM_AWARE_PROTOCOL = "equilibrium_aware_namd"
# Implicit-solvent (Generalised Born) relaxation — no water box, fits small GPUs.
# Builder lives in backend.core.namd_gbis (kept out of this god-file).
IMPLICIT_GBIS_PROTOCOL = "implicit_gbis_namd"
SUPPORTED_PROTOCOLS = {LEGACY_PROTOCOL, EQUILIBRIUM_AWARE_PROTOCOL, IMPLICIT_GBIS_PROTOCOL}
# MUST match _common_header's "stepspercycle" — NAMD FATALs at startup if a
# minimize/run count is not a multiple of it.  (benchmark_runner.NAMD_STEPS_PER_CYCLE too.)
AKSIMENTIEV_STEPS_PER_CYCLE = 20


# ── Electric field (NAMD native eFieldOn / eField) ────────────────────────────
#
# NAMD applies ``F_i = q_i · eField`` to EVERY atom, where ``q_i`` is the atom's CHARMM
# partial charge; ``eField`` is in kcal·mol⁻¹·Å⁻¹·e⁻¹ and the resulting force in
# kcal·mol⁻¹·Å⁻¹.  The net force on a nucleotide is therefore ``(Σ_i q_i)·eField``.
#
# The cross-engine descriptor is force-per-NUCLEOTIDE in pN — exactly what oxDNA puts on
# each bead (a ``string`` force, ``OXDNA_FORCE_PN``), LAMMPS puts on each bead
# (``fix addforce``) and CanDo puts on each duplex axis node (×2 backbones,
# ``FEM_FIELD_CHARGES_PER_NODE``).  NAMD's bridge needs NO effective-charge fudge: an
# INTERNAL DNA nucleotide carries a net −1 e by force-field construction (its one
# phosphate), the same charge ``namd_solvate._count_dna_charge`` counts (one P per
# nucleotide) to neutralise the box.  So the eField that delivers ``field_pN`` to an
# internal nucleotide is exact, not calibrated.
#
# TERMINI (measured, not assumed — see tests/test_namd_efield.py): psfgen patches strand
# ends with 5TER/3TER hydroxyls, so a strand's FIRST residue carries −0.47 e and its LAST
# −0.53 e (CHARMM36 partial charges; they sum to −1.00, i.e. one phosphate's worth).  A
# strand of N nucleotides therefore carries −(N−1) e — exactly its phosphate count.  So
# NAMD applies slightly LESS total force than oxDNA's uniform per-bead ``field_pN``
# (deficit = N_strands/N_nucleotides: ~2 % on a real origami, ~12 % on an 8-mer).  This is
# NAMD being right and oxDNA approximating: a 5'-OH terminus genuinely has no phosphate.
# Do not "fix" it by rescaling eField — that would corrupt the internal per-nucleotide
# load, which is the quantity the engines actually share.
#
# Sign: the backbone charge is NEGATIVE, so the emitted eField points ANTIPARALLEL to the
# force direction the user asked for (``project_oxdna_efield`` GOTCHA: "force on the
# negative backbone is antiparallel to E").
#
# Physicality caveat — NAMD is the only engine here with explicit solvent, so eField also
# pushes the ions and polarises the water (real electrophoresis/electroosmosis, which
# oxDNA/CanDo/LAMMPS cannot represent).  The *applied load on the DNA* is identical to the
# other engines; the *response* additionally carries counterion drag.  That is a feature —
# it is why NAMD is the gold reference — but it means a NAMD-vs-oxDNA deflection delta is
# a physical difference, not necessarily a disagreement.
#
# Manning condensation is therefore NOT folded in (unlike the frontend's V/m helper's
# ``q_eff ≈ 0.25 e``): in explicit solvent the condensed counterions are actual particles
# that screen the field themselves.  Applying the bare −1 e is the physically correct
# driving force AND the cross-engine-comparable one.
_KCAL_J = 4184.0                     # J per kcal (thermochemical)
_AVOGADRO = 6.02214076e23            # mol⁻¹ (SI exact)
#: 1 kcal·mol⁻¹·Å⁻¹ expressed in pN (≈ 69.4769).
KCAL_MOL_A_IN_PN: float = _KCAL_J / _AVOGADRO / 1e-10 * 1e12
#: CHARMM net charge of an INTERNAL DNA nucleotide (its one phosphate), in units of e.
#: Strand termini are 5TER/3TER hydroxyls (−0.47 / −0.53 e); see the note above.
NAMD_DNA_CHARGE_PER_NUCLEOTIDE_E: float = -1.0


def namd_efield_vector(field: Optional[dict]) -> Optional[tuple[float, float, float]]:
    """NAMD ``eField`` vector delivering the shared per-nucleotide load, or ``None``.

    ``field`` mirrors the shared oxDNA descriptor ``{"field_pN": <force per NUCLEOTIDE,
    pN>, "dir": [x, y, z]}`` (``force_pN`` — the persisted oxDNA job spelling — is also
    accepted).  ``dir`` need not be a unit vector.

    Returns the vector in NAMD's units (kcal·mol⁻¹·Å⁻¹·e⁻¹) such that

        ``NAMD_DNA_CHARGE_PER_NUCLEOTIDE_E · eField · KCAL_MOL_A_IN_PN == field_pN · dir̂``

    i.e. every nucleotide feels exactly ``field_pN`` along ``dir``.  ``None`` / empty /
    zero magnitude / zero direction → ``None`` (an exact no-op, mirroring
    ``fem_solver.assemble_field_force``).

    Three-Layer Law: the field is a JOB-REQUEST annotation, read here only; it never
    touches topology.
    """
    if not field:
        return None
    mag_pn = float(field.get("field_pN", field.get("force_pN", 0.0)) or 0.0)
    dx, dy, dz = (float(c) for c in (field.get("dir") or (0.0, 0.0, 0.0)))
    dnorm = math.sqrt(dx * dx + dy * dy + dz * dz)
    if mag_pn == 0.0 or dnorm <= 1e-12:
        return None
    # F = q·E  ⇒  E = F / q.  q < 0, so E is antiparallel to the requested force.
    scale = mag_pn / (KCAL_MOL_A_IN_PN * NAMD_DNA_CHARGE_PER_NUCLEOTIDE_E * dnorm)
    return (dx * scale, dy * scale, dz * scale)


def _efield_lines(field: Optional[dict]) -> list[str]:
    """The ``eFieldOn``/``eField`` conf directives for a field spec (empty when absent)."""
    vec = namd_efield_vector(field)
    if vec is None:
        return []
    return [
        "eFieldOn           on\n",
        "eField             {:.8g} {:.8g} {:.8g}\n".format(*vec),
    ]


def external_forces_block(anchors_file: Optional[str], field: Optional[dict]) -> str:
    """The ``fixedAtoms`` + ``eField`` directives — the ONE emitter every conf writer uses.

    Anchors hold selected nucleotides completely fixed (Dirichlet-style).  They are
    orthogonal to the ramped all-DNA harmonic restraint: NAMD allows only one
    ``conskfile``, already spent on the slow-release restraint, so anchors ride the
    independent ``fixedAtoms`` mechanism and persist across the whole ladder while the
    restraint ramps to zero.

    Caveat (NPT): fixed atoms are not rescaled by the barostat and add no virial, so a
    LARGE fixed region biases the pressure; for a small end-anchor (the field use case)
    this is negligible.  Caveat (GPU): NAMD 3 refuses ``eField`` under *multi-GPU*
    ``GPUresident`` ("EField is not compatible with multi-GPU GPUresident"); single-GPU
    is fine, and the API rejects a multi-device field job up front.
    """
    lines: list[str] = []
    if anchors_file:
        lines.append("fixedAtoms         on\n")
        lines.append(f"fixedAtomsFile     {anchors_file}\n")
        lines.append("fixedAtomsCol      B\n")
    lines.extend(_efield_lines(field))
    return "".join(lines)


# ── Segment spec ──────────────────────────────────────────────────────────────

@dataclass
class SegmentSpec:
    name:     str              # output name prefix, e.g. "B_tube_01_050K_NVT_k5_p10"
    stage:    str              # human stage label, e.g. "50K NVT k=5.0"
    percent:  float            # 10, 50, or 100
    steps:    int              # MD steps in this segment
    temp:     float            # target temperature (K)
    damping:  float            # Langevin damping (ps^-1)
    scale:    Optional[float]  # restraint k (kcal/mol/Å²); None = unrestrained
    npt:      bool             # True if barostat is on
    previous: str              # output name of the preceding segment (or min)
    reinit:   bool = False     # True → reinitvels + temperature instead of vel continuation
    dcd_freq: int  = 20000     # DCD frame output interval (steps)
    min_c1_paired: float = 0.90
    min_wc_ref_relative: float = 0.85
    extra_bonds_file: Optional[str] = None
    soft: bool = False  # True → rigidBonds none + 1 fs (declash designs with
    #        residual single-stranded contacts that crash RATTLE)


# ── NAMD conf template ────────────────────────────────────────────────────────

# A whole ``GPUresident ...`` directive line (with its trailing newline).  NADOC's
# confs bake ``GPUresident on`` into the fast (HMR + 4 fs) segments because the
# local pipeline is GPU-resident; a CPU / regular-multicore NAMD build FATALs on it
# ("GPUresident not supported on regular multicore builds").
_GPU_RESIDENT_LINE_RE = re.compile(
    r"^[ \t]*GPUresident\b.*\r?\n?", re.IGNORECASE | re.MULTILINE
)


def strip_gpu_resident(conf_text: str) -> str:
    """Remove any ``GPUresident`` directive from a NAMD conf, for a CPU/multicore run.

    GPUresident (NAMD 3 CUDASOAintegrate) is valid only on a GPU-resident build; a
    regular multicore build aborts at startup.  Idempotent; a no-op when the directive
    is absent (e.g. the gentle ``_p10`` warmup confs never had it).

    ⚠️ Stripping GPUresident ALONE is not enough to keep a fast conf stable: the 4 fs
    timestep survives only under GPUresident's GPU constraint solver.  Without it, the
    CPU RATTLE path blows up on the first step ("Constraint failure in RATTLE algorithm
    for atom N") — measured on a 1.44M-atom GT_corner_v2 run.  Use
    ``downgrade_gpu_resident()`` when you need a RUNNABLE non-GPU-resident fast conf.
    """
    return _GPU_RESIDENT_LINE_RE.sub("", conf_text)


# Step-count / output-cadence keys that must be rescaled when the timestep changes, so
# the segment covers the SAME simulated time and writes the same frames-per-ns.
_STEP_SCALED_KEYS = ("run", "outputEnergies", "xstFreq", "restartfreq", "dcdFreq")
_TIMESTEP_RE = re.compile(r"^([ \t]*timestep[ \t]+)([0-9.]+)", re.IGNORECASE | re.MULTILINE)


def downgrade_gpu_resident(conf_text: str, factor: int = 2) -> str:
    """Make a fast (HMR + 4 fs + GPUresident) conf runnable WITHOUT GPU-resident mode.

    GPU-resident pins a large host buffer; on a host with a small pinned-memory pool
    (WSL2 caps it at ~1 GB) ``cudaMallocHost`` fails at startup for big systems —
    measured: fine at 756k atoms, fails at 971k, and GT_corner_v2's 1.44M-atom relax
    package fails outright.  See [[LESSONS]] K6.

    This ALSO divides the timestep by *factor* and MULTIPLIES every step-count/output-
    frequency key by it — the segment therefore covers the SAME simulated time and writes
    the same number of frames, just in twice as many (cheaper) steps.  HMR, ``rigidBonds
    all``, the PSF, PME, cutoffs and the barostat are untouched, so the physics is
    unchanged; only integrator throughput moves.

    The timestep halving is a CONSERVATIVE choice, not a hard requirement.  It was added
    because a 4 fs offload run once died with an instant "Constraint failure in RATTLE".
    That is NOT a general property of 4 fs on the offload path: with the HMR PSF and a
    relaxed starting structure, 4 fs + ``rigidBonds all`` + offload is stable — measured
    2026-07-12 on the carved 6hbx100_90deg, 60k steps (240 ps) from the p10 checkpoint,
    T flat at 298-299 K, zero RATTLE failures, 18.8 ns/day.  The original blow-up was
    almost certainly a *strained* start, not the timestep.  Carved packages are therefore
    written at 4 fs directly (see ``_segment_conf``'s ``carved`` guard) and never come
    through here.  This path now only serves the pinned-OOM case (K6), where halving is
    cheap insurance on systems large enough to have hit that limit.

    Pure + idempotent-safe: returns *conf_text* unchanged if it has no GPUresident line.
    """
    if not _GPU_RESIDENT_LINE_RE.search(conf_text):
        return conf_text

    text = strip_gpu_resident(conf_text)

    def _scale_ts(m: re.Match[str]) -> str:
        ts = float(m.group(2)) / factor
        # keep an integer-looking value integer ("4" -> "2", not "2.0")
        return f"{m.group(1)}{int(ts) if ts == int(ts) else ts}"

    text = _TIMESTEP_RE.sub(_scale_ts, text, count=1)

    for key in _STEP_SCALED_KEYS:
        pat = re.compile(rf"^([ \t]*{key}[ \t]+)(\d+)\b", re.IGNORECASE | re.MULTILINE)
        text = pat.sub(lambda m: f"{m.group(1)}{int(m.group(2)) * factor}", text)
    return text


# Directives a resume conf must re-specify (dropped from the original, re-emitted to
# point at the checkpoint + run only the remaining steps).  Mirrors the local
# runner's `_RESUME_DROP` (namd_runner) so remote resume matches local behaviour.
_RESUME_DROP = frozenset({
    "binCoordinates", "binVelocities", "extendedSystem", "temperature",
    "reinitvels", "firsttimestep", "dcdFile", "xstFile", "run",
})


def build_remote_resume_conf(
    conf_text: str,
    *,
    segment_name: str,
    restart_step: int,
    total_steps: int,
    cont_index: int = 1,
) -> str:
    """Rewrite a segment conf to RESUME from its NAMD checkpoint on the cluster (pure).

    A short-walltime remote run times out MID-segment; the segment's
    ``output/<name>.restart.{coor,vel,xsc}`` (written every ``restartfreq`` steps) is
    the checkpoint.  This drops the original coordinate/velocity/box/run directives
    and re-emits them pointing at those restart files, continues the step counter with
    ``firsttimestep``, runs only the REMAINING steps, and writes trajectory frames to a
    fresh ``output/<name>.cont<k>.dcd`` so the partial trajectory is preserved.
    ``outputName`` is untouched, so the final ``output/<name>.{coor,vel,xsc}`` land
    where the next segment expects them.

    Reads the restart files directly (NAMD reads them fully at startup, before the run
    overwrites them, so there is no read/write aliasing).  Port of the local runner's
    ``_write_resume_conf`` — kept pure (no file IO) since remote resume ships text.
    """
    remaining = int(total_steps) - int(restart_step)
    if remaining <= 0:
        raise ValueError(
            f"resume step {restart_step} is at/past the segment total {total_steps}"
        )
    kept = [
        line for line in conf_text.splitlines()
        if (line.split()[0] if line.split() else "") not in _RESUME_DROP
    ]
    kept += [
        f"binCoordinates     output/{segment_name}.restart.coor",
        f"binVelocities      output/{segment_name}.restart.vel",
        f"extendedSystem     output/{segment_name}.restart.xsc",
        f"dcdFile            output/{segment_name}.cont{cont_index}.dcd",
        f"xstFile            output/{segment_name}.cont{cont_index}.xst",
        f"firsttimestep      {int(restart_step)}",
        # NAMD 3's Tcl `run` has no `upto`; firsttimestep already advances the label,
        # so run only the remaining steps.  restart_step is a multiple of restartfreq
        # (itself a multiple of stepspercycle), so the remainder stays cycle-aligned.
        f"run                {remaining}",
    ]
    return "\n".join(kept) + "\n"


# 4 fs is the ONLY sanctioned PRODUCTION timestep (HMR + rigidBonds all fast path).  The
# single long-standing exception is the explicit 1.0 fs conservative-reference run
# (rigidBonds none, no HMR) — a deliberately-requested accuracy mode, NOT a stability
# workaround.  Any intermediate value (2 / 2.5 / 3 / 3.5 fs) is the banned "lower the
# timestep to dodge a RATTLE clash" anti-pattern: the fix for a 4 fs instability is to remove
# the offending clash (e.g. oxDNA-seed the extra bases), never to lower production dt.  Lower
# dt is legitimate ONLY in ramp/anneal/relaxation stages, which do not pass through here.
# See memory/feedback_namd_4fs_production_only.md.
PRODUCTION_TIMESTEP_FS = 4.0
_CONSERVATIVE_REFERENCE_DT_FS = 1.0


def require_sanctioned_production_timestep(dt_fs: float) -> float:
    """Enforce the 4 fs-only production rule; return ``dt_fs`` if it is allowed.

    Raises ``ValueError`` for any production timestep that is neither the 4.0 fs fast path
    nor the explicit 1.0 fs conservative-reference path.  This is a hard guard against
    silently shipping a sub-4 fs production run as a workaround for a local clash/instability.
    """
    if dt_fs not in (PRODUCTION_TIMESTEP_FS, _CONSERVATIVE_REFERENCE_DT_FS):
        raise ValueError(
            f"production timestep {dt_fs:g} fs is not sanctioned: 4.0 fs is the only "
            f"acceptable production dt (or the explicit 1.0 fs conservative-reference path). "
            f"Lower dt is allowed ONLY in ramp/anneal/relaxation. Fix the clash (oxDNA-seed "
            f"the design), do not lower the production timestep. See "
            f"memory/feedback_namd_4fs_production_only.md"
        )
    return dt_fs


def build_production_conf(
    spec: "SegmentSpec",
    name_stem: str,
    box: tuple[float, float, float],
    mgh_extrabonds: bool,
    *,
    seed: int = 54321,
    fast: bool = False,
    structure_psf: Optional[str] = None,
    start_checkpoint: Optional[str] = None,
    anchors_file: Optional[str] = None,
    field: Optional[dict] = None,
) -> str:
    """Unrestrained NPT production conf, continuing from a prior checkpoint (pure).

    Shared by the local production path (``routes_md._conservative_production_conf``,
    which delegates here with the defaults → byte-identical output) and the Alpine
    ensemble path, which passes a per-replica ``seed`` and ``start_checkpoint`` (the
    reseed step's output name) so each replica draws its own Langevin/velocity RNG
    stream while reading the same equilibrated coordinates.

    ``fast`` = the HMR + ``rigidBonds all`` + 4 fs + GPUresident throughput mode (see
    ``routes_md._production_fast_plan``); ``structure_psf`` overrides the PSF (the HMR
    PSF for fast runs).  ``start_checkpoint`` overrides ``spec.previous`` as the source
    of ``binCoordinates``/``binVelocities``/``extendedSystem`` (default None keeps
    ``spec.previous`` — the local segment-chain behaviour).
    """
    bx, by, bz = box
    cx, cy, cz = bx / 2, by / 2, bz / 2
    extras = "extraBonds         on\nextraBondsFile     mgh_extrabonds.txt\n" if mgh_extrabonds else ""
    # Fast mode = the fast-relaxation win applied to unrestrained production.  The
    # HMR PSF (non-water hydrogens x3) lets ``rigidBonds all`` run stably at a 4 fs
    # timestep; ``GPUresident on`` keeps integration + bonded forces on the GPU;
    # light multiple-timestepping (fullElectFrequency 2) skips a PME evaluation
    # every other step.  Together ~10x throughput vs the 1 fs / rigidBonds none /
    # CPU-integrated conservative path (1.3 -> >16 ns/day).  Electrostatics (PME
    # grid, cutoff, barostat coupling) are LEFT IDENTICAL to the conservative run,
    # so the production ensemble is unchanged — only integrator/throughput knobs
    # move.  GPUresident is sound here because the solvated box is capped (no
    # covalent bond wraps the periodic image).
    if fast:
        psf = structure_psf or f"{name_stem}.psf"
        rigid, ts, gpu_line = "all", 4.0, "GPUresident        on\n"
        # fullElectFrequency 1 at 4 fs → reciprocal PME every 4 fs, matching the
        # Aksimentiev reference (2 fs x 2).  fullElect 2 here would be PME every
        # 8 fs, past the r-RESPA resonance-stability limit (~4 fs) — and it only
        # bought ~0.7 ns/day.  stepspercycle 10 → 40 fs pairlist rebuild.
        nbf, fef, spc = 1, 1, 10
    else:
        psf = f"{name_stem}.psf"
        rigid, ts, gpu_line = "none", 1.0, ""
        nbf, fef, spc = 1, 1, 10
    require_sanctioned_production_timestep(ts)  # 4 fs-only rule (or explicit 1 fs reference)
    prev = start_checkpoint or spec.previous
    # Anchors + E-field carry into the unrestrained run — where a field's deflection
    # actually develops.  Dropping them here would silently un-anchor the field job and
    # let the uniform force stream the whole structure across the box (COM drift).
    # Default (None, None) → "" so the ensemble path stays byte-identical.
    ext_forces = external_forces_block(anchors_file, field)
    # Scale the I/O cadences to the RUN, not to a 250k-atom local job (see
    # _production_output_freqs): the hardcoded outputEnergies 100 / restartfreq 1000
    # were pure overhead on a 1.9M-atom GPU-resident run — a GPU->host energy pull every
    # 100 steps, and 90 MB of restart files to a NETWORK filesystem every 1000.
    prod_e, prod_r = _production_output_freqs(spec.steps, cycle=spc)
    return f"""\
structure          {psf}
coordinates        {name_stem}.pdb

seed               {seed}
paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
{extras}
cellBasisVector1   {bx:.3f}  0.000    0.000
cellBasisVector2   0.000    {by:.3f}  0.000
cellBasisVector3   0.000    0.000    {bz:.3f}
cellOrigin         {cx:.3f}   {cy:.3f}   {cz:.3f}

wrapAll            on
wrapWater          on
exclude            scaled1-4
oneFourScaling     1.0
switching          on
switchdist         10.0
cutoff             12.0
pairlistdist       14.0
PME                yes
PMEGridSpacing     1.0
rigidBonds         {rigid}
rigidTolerance     1.0e-8
timestep           {ts:g}
nonbondedFreq      {nbf}
fullElectFrequency {fef}
stepspercycle      {spc}
{gpu_line}langevin           on
langevinTemp       300
langevinDamping    5
langevinHydrogen   off
useGroupPressure   yes
useFlexibleCell    no
useConstantArea    no
langevinPiston     on
langevinPistonTarget  1.01325
langevinPistonPeriod  200.0
langevinPistonDecay   100.0
langevinPistonTemp 300
outputEnergies     {prod_e}
xstFreq            {prod_e}
restartfreq        {prod_r}
binaryrestart      yes
constraints        off
{ext_forces}outputName         output/{spec.name}
dcdFile            output/{spec.name}.dcd
dcdFreq            {spec.dcd_freq}
xstFile            output/{spec.name}.xst
binCoordinates     output/{prev}.coor
binVelocities      output/{prev}.vel
extendedSystem     output/{prev}.xsc
run                {spec.steps}
"""


def build_reseed_conf(
    reseed_name: str,
    name_stem: str,
    box: tuple[float, float, float],
    mgh_extrabonds: bool,
    *,
    seed: int,
    equil_base: str = "equilibrated",
    structure_psf: Optional[str] = None,
) -> str:
    """Velocity-reseed bridge conf for an ensemble replica (pure).

    Reads the shared equilibrated coordinates + box from PACKAGE-ROOT files
    (``{equil_base}.coor`` / ``{equil_base}.xsc`` — staged, unlike ``output/``),
    assigns a fresh Maxwell-Boltzmann velocity set at 300 K from this replica's
    ``seed`` (``reinitvels``), and writes ``output/{reseed_name}.{coor,vel,xsc}`` with a
    zero-step run — coordinates are preserved exactly, only the velocities differ per
    replica.  It occupies the manifest ``minimization`` slot so the production segment
    (which reads ``output/{reseed_name}``) chains from it via the standard sbatch.
    """
    bx, by, bz = box
    cx, cy, cz = bx / 2, by / 2, bz / 2
    extras = "extraBonds         on\nextraBondsFile     mgh_extrabonds.txt\n" if mgh_extrabonds else ""
    psf = structure_psf or f"{name_stem}.psf"
    return f"""\
structure          {psf}
coordinates        {name_stem}.pdb

seed               {seed}
paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
{extras}
cellBasisVector1   {bx:.3f}  0.000    0.000
cellBasisVector2   0.000    {by:.3f}  0.000
cellBasisVector3   0.000    0.000    {bz:.3f}
cellOrigin         {cx:.3f}   {cy:.3f}   {cz:.3f}

wrapAll            on
wrapWater          on
exclude            scaled1-4
oneFourScaling     1.0
switching          on
switchdist         10.0
cutoff             12.0
pairlistdist       14.0
PME                yes
PMEGridSpacing     1.0
rigidBonds         none
rigidTolerance     1.0e-8
timestep           1.0
nonbondedFreq      1
fullElectFrequency 1
stepspercycle      10
langevin           on
langevinTemp       300
langevinDamping    5
langevinHydrogen   off
useGroupPressure   yes
useFlexibleCell    no
useConstantArea    no
langevinPiston     on
langevinPistonTarget  1.01325
langevinPistonPeriod  200.0
langevinPistonDecay   100.0
langevinPistonTemp 300
outputEnergies     100
xstFreq            1000
restartfreq        1000
binaryrestart      yes
constraints        off
outputName         output/{reseed_name}
binCoordinates     {equil_base}.coor
extendedSystem     {equil_base}.xsc
temperature        300
reinitvels         300
run                0
"""


def _common_header(
    name_stem: str,
    box: tuple[float, float, float],
    _mgh_extrabonds: bool,
    *,
    rigid_bonds: str = "all",
    timestep: float = 2.0,
    gpu_resident: bool = False,
    structure_psf: Optional[str] = None,
    gbis: bool = False,
    gbis_ion_conc_M: float = 0.15,
    output_freq: int = 9_600,
    restart_freq: Optional[int] = None,
) -> str:
    bx, by, bz = box
    cx, cy, cz = bx / 2, by / 2, bz / 2
    # GPU-resident (NAMD 3 "GPUresident on") keeps integration + bonded forces on
    # the GPU for a large throughput win.  It requires a UNIFORMLY FILLED cell:
    # NAMD sizes its GPU tile/exclusion buffers from the cell-average density, so a
    # cell with vacuum in it silently under-counts exclusions and dies at step 0 with
    # "Low global CUDA exclusion count!".  A water-shell carve (water_shell_nm > 0) on
    # a concave design is exactly that case — see the ``carved`` guard in
    # _segment_conf and [[water-shell-carve]].
    gpu_line = "GPUresident        on\n" if gpu_resident else ""

    # Electrostatics/solvent block.  Two mutually exclusive modes:
    #   • Explicit water (default): a periodic capped box + PME long-range sum.
    #   • Implicit solvent (gbis=True): Generalised Born, NO water box and NO PME
    #     — the solvent is a dielectric continuum, so there are no cell vectors,
    #     no wrapping, and salt enters as a Debye ionConcentration.  This drops
    #     the atom count ~6-7x (DNA only) so a large origami fits a small GPU's
    #     VRAM at buildTileLists (the explicit box overflows an 8 GB card).  The
    #     longer 16 Å cutoff is standard for GBIS (Born-radius accuracy).
    if gbis:
        solvent_block = (
            f"# Implicit solvent (Generalised Born) — no water box, no PME\n"
            f"gbis               on\n"
            f"alphaCutoff        14.0\n"
            f"ionConcentration   {gbis_ion_conc_M:g}\n"
            f"solventDielectric  78.5\n"
            f"\n"
            f"cutoff             16.0\n"
            f"switching          on\n"
            f"switchdist         14.0\n"
            f"pairlistdist       18.0\n"
            f"exclude            scaled1-4\n"
            f"oneFourScaling     1.0\n"
        )
    else:
        solvent_block = (
            f"cellBasisVector1   {bx:.3f}  0.000    0.000\n"
            f"cellBasisVector2   0.000    {by:.3f}  0.000\n"
            f"cellBasisVector3   0.000    0.000    {bz:.3f}\n"
            f"cellOrigin         {cx:.3f}   {cy:.3f}   {cz:.3f}\n"
            f"\n"
            f"wrapAll            off\n"
            f"wrapWater          off\n"
            f"\n"
            f"PME                yes\n"
            f"PMEGridSpacing     1.5\n"
            f"\n"
            f"cutoff             10.0\n"
            f"switching          on\n"
            f"switchdist         8.0\n"
            # 3.5 A of pairlist buffer over the cutoff (was 2.0) so the list survives the
            # longer stepspercycle below.  Deliberately NO explicit ``margin``: an explicit
            # margin crashes NAMD's GPU tile-list kernel on any build WITHOUT the K2 patch,
            # and the 3080 Ti box does not have the patched NAMD_3.0.2p1 built yet.  It is
            # also not a measured win here — the 18.8 ns/day carved-offload result was
            # obtained with no margin.  See test_no_explicit_margin_in_configs.
            f"pairlistdist       13.5\n"
            f"exclude            scaled1-4\n"
            f"oneFourScaling     1.0\n"
        )
    return f"""\
structure          {structure_psf or f"{name_stem}.psf"}
coordinates        {name_stem}.pdb

paraTypeCharmm     on
parameters         forcefield/par_all36_na.prm
parameters         forcefield/toppar_water_ions_cufix.str
parameters         forcefield/par_stub_ions_nbfix.str
{solvent_block}
rigidBonds         {rigid_bonds}
rigidTolerance     1.0e-8

langevin           on
langevinHydrogen   off

timestep           {timestep:g}
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      20
{gpu_line}
outputEnergies     {output_freq}
xstFreq            {output_freq}
restartfreq        {restart_freq or output_freq}
binaryrestart      yes
"""


def _segment_conf(
    spec: SegmentSpec,
    name_stem: str,
    box: tuple[float, float, float],
    mgh_extrabonds: bool,
    *,
    minimize_steps: int = 0,
    fast: bool = False,
    carved: bool = False,
    structure_psf: Optional[str] = None,
    colvars_file: Optional[str] = None,
    anchors_file: Optional[str] = None,
    field: Optional[dict] = None,
    gbis: bool = False,
) -> str:
    # Soft integrator: flexible H bonds + 1 fs timestep.  Needed for declashed
    # designs whose residual single-stranded contacts crash rigid-bond RATTLE.
    # Fast mode (HMR + 4 fs) applies only to hard segments — it is incompatible
    # with the soft integrator's flexible bonds.  GBIS runs the standard CUDA path
    # (GPUresident does not support implicit solvent), so fast is off for an
    # implicit ladder.
    fast = fast and not spec.soft and not gbis
    rigid_bonds = "none" if spec.soft else "all"
    timestep = 1.0 if spec.soft else (4.0 if fast else 2.0)
    # The HMR PSF (heavy hydrogens) is valid ONLY with rigid bonds, so soft
    # segments fall back to the unmodified PSF; only the hard, fast segments use it.
    eff_psf = structure_psf if fast else None
    # GPU-resident is a SEPARATE axis from fast.  A water-shell carve leaves vacuum
    # in the cell, and NAMD 3 GPU-resident under-counts exclusions in a sparse cell
    # ("Low global CUDA exclusion count!", fatal at step 0 — measured: it needs
    # >=~90% water fill; even an 80%-filled cell dies).  A carved package therefore
    # keeps HMR + rigidBonds all + 4 fs but runs the standard CUDA-offload path
    # (nonbonded + PME still on the GPU), which is unaffected and, because the carve
    # removes ~4x the atoms, is still the faster of the two.
    gpu_resident = fast and not carved
    lines = [
        _common_header(
            name_stem, box, mgh_extrabonds, rigid_bonds=rigid_bonds, timestep=timestep,
            gpu_resident=gpu_resident, structure_psf=eff_psf, gbis=gbis,
            # From THIS chunk's length, so the frame count survives a timestep change.
            output_freq=_output_freq(spec.steps),
            # ...but the RESTART cadence is a DIFFERENT question. It is crash insurance,
            # not a sampling rate, and tying it to the frame count gave 9.5-11.8 min
            # between writes on the long chunks — so a dead pod cost that much compute.
            # See _RESTART_EVERY_STEPS: the optimum is ~3 min, and both extremes cost real
            # money.
            restart_freq=_restart_freq(spec.steps),
        )
    ]
    lines.append(f"outputName         output/{spec.name}\n")
    lines.append(f"dcdFile            output/{spec.name}.dcd\n")
    lines.append(f"dcdFreq            {spec.dcd_freq}\n")
    lines.append(f"xstFile            output/{spec.name}.xst\n")

    if spec.reinit or not spec.previous:
        lines.append(f"temperature        {spec.temp:g}\n")
    lines.append(f"langevinTemp       {spec.temp:g}\n")
    lines.append(f"langevinDamping    {spec.damping:g}\n")

    if spec.npt and not gbis:
        lines.append("useGroupPressure   yes\n")
        lines.append("useFlexibleCell    no\n")
        lines.append("useConstantArea    no\n")
        lines.append("langevinPiston     on\n")
        lines.append("langevinPistonTarget  1.01325\n")
        lines.append("langevinPistonPeriod  1000.0\n")
        lines.append("langevinPistonDecay   500.0\n")
        lines.append(f"langevinPistonTemp {spec.temp:g}\n")
    else:
        lines.append("langevinPiston     off\n")

    if mgh_extrabonds or spec.extra_bonds_file:
        lines.append("extraBonds         on\n")
        if mgh_extrabonds:
            lines.append("extraBondsFile     mgh_extrabonds.txt\n")
    if spec.extra_bonds_file:
        lines.append(f"extraBondsFile     {spec.extra_bonds_file}\n")

    if spec.scale is not None and not spec.extra_bonds_file:
        lines.append("constraints        on\n")
        lines.append("consref            restraints_dna_heavy.pdb\n")
        lines.append("conskfile          restraints_dna_heavy.pdb\n")
        lines.append("conskcol           B\n")
        lines.append(f"constraintScaling  {spec.scale:g}\n")
    else:
        lines.append("constraints        off\n")

    # Anchors + uniform E-field (native NAMD q·E).  Both ride the whole ladder: while the
    # slow-release restraint is still stiff the structure barely moves, and the deflection
    # develops smoothly as k → 0 — a quasi-static ramp into the tethered-arm regime rather
    # than a shock at the release segment.
    lines.append(external_forces_block(anchors_file, field))

    if spec.previous:
        lines.append(f"binCoordinates     output/{spec.previous}.coor\n")
        if not spec.reinit:
            lines.append(f"binVelocities      output/{spec.previous}.vel\n")
        lines.append(f"extendedSystem     output/{spec.previous}.xsc\n")
    if spec.reinit:
        lines.append(f"reinitvels         {spec.temp:g}\n")

    # Colvars (e.g. a weak DNA centre-of-mass restraint for carved-shell NVT
    # production — keeps the DNA off the vacuum corners without touching internal
    # dynamics).  Enabled only when a config file is supplied.
    if colvars_file:
        lines.append("colvars            on\n")
        lines.append(f"colvarsConfig      {colvars_file}\n")

    if minimize_steps:
        lines.append(f"minimize           {minimize_steps}\n")
    if spec.steps:
        lines.append(f"run                {spec.steps}\n")
    return "".join(lines)


def _min_conf(
    min_name: str,
    name_stem: str,
    box: tuple[float, float, float],
    mgh_extrabonds: bool,
    minimize_steps: int,
    scale: float,
    *,
    enm_file: Optional[str] = None,
    no_enm: bool = False,
    anchors_file: Optional[str] = None,
    field: Optional[dict] = None,
    gbis: bool = False,
) -> str:
    # enm_file overrides the default {name_stem}_k{scale}.enm.extra — used by the
    # declash protocol to minimise against an ss-excluded network.  Minimisation
    # (and the soft first segment it feeds) stays on the unmodified PSF + standard
    # CUDA; the HMR PSF only enters at the first hard, rigid-bond fast segment.
    #
    # ``no_enm`` drops the base-ring ENM entirely from the minimisation (the Mg
    # extrabonds stay).  Used by the oxDNA-seeded path: the seed backmap carries
    # duplex base clashes at crossover junctions (ring atoms down to ~0.3 A), and
    # an ENM built from those coords pins the clashes as its reference — a stiff
    # k0.5 restraint then stores that clash energy and dumps it catastrophically
    # when the ladder relaxes to k0.1 (70x over the velocity limit).  Minimising
    # WITHOUT the ENM lets the clashes open, after which the runner rebuilds the
    # ENM from the declashed coords (rebuild_declashed_references) so it never
    # encodes the clash again.  See PIPELINE_4FS_EXTRA_BASES.md.
    enm = enm_file or f"{name_stem}_k{scale:g}.enm.extra"
    lines = [_common_header(name_stem, box, mgh_extrabonds, rigid_bonds="none", gbis=gbis)]
    lines.append(f"outputName         output/{min_name}\n")
    lines.append(f"dcdFile            output/{min_name}.dcd\n")
    lines.append("dcdFreq            0\n")
    lines.append(f"xstFile            output/{min_name}.xst\n")
    lines.append("temperature        0\n")
    lines.append("langevinTemp       0\n")
    lines.append("langevinDamping    5\n")
    lines.append("langevinPiston     off\n")
    lines.append("extraBonds         on\n")
    if mgh_extrabonds:
        lines.append("extraBondsFile     mgh_extrabonds.txt\n")
    if not no_enm:
        lines.append(f"extraBondsFile     {enm}\n")
    lines.append("constraints        off\n")
    lines.append(external_forces_block(anchors_file, field))
    lines.append(f"minimize           {minimize_steps}\n")
    return "".join(lines)


# ── Restraints PDB ────────────────────────────────────────────────────────────

def write_restraints_pdb(pdb_path: Path, dst_path: Path) -> None:
    """Write restraints_dna_heavy.pdb with B=1.0 for DNA heavy atoms, B=0 for rest.

    NAMD reads the B-factor column (cols 61-66) as the per-atom constraint
    scaling factor via conskcol B.  DNA heavy atoms get B=1; hydrogens and
    solvent get B=0 (unconstrained).
    """
    lines = []
    for raw in pdb_path.read_text().splitlines(keepends=True):
        if raw.startswith("ATOM"):
            atom_name = raw[12:16].strip()
            value = 0.0 if atom_name.startswith("H") else 1.0
            raw = _set_bfactor(raw, value)
        elif raw.startswith("HETATM"):
            raw = _set_bfactor(raw, 0.0)
        lines.append(raw)
    dst_path.write_text("".join(lines))


def write_anchor_restraints_pdb(
    pdb_path: Path, dst_path: Path, anchored_indices: "set[int]"
) -> int:
    """Write a fixedAtoms marker PDB: B=1.0 for the heavy atoms of the anchored DNA
    residues, B=0 for everything else (hydrogens, solvent, and every non-anchored
    DNA atom).  NAMD reads col B via ``fixedAtomsCol B`` and holds the B=1 atoms
    immobile — the Dirichlet-style "held" analogue of the oxDNA trap / CanDo BC.

    ``anchored_indices`` is the 0-based residue-ordinal set from
    :func:`backend.core.namd_topology.resolve_anchor_residue_indices`.  Residues are
    counted positionally by contiguity (a boundary at any change of
    ``(chain, resid, resname)`` or a ``TER`` record) — the same walk
    :func:`backend.core.md_protocols._parse_base_ring_residues` uses — because psfgen's
    ``writepdb`` blanks the segid column and the 1-char chain aliases past 62 strands, so
    residues are only addressable by their order (which matches
    :func:`~backend.core.namd_topology.built_pdb_residue_keys`).  Returns the number of
    atoms marked fixed."""
    n_marked = 0
    lines = []
    res_idx = -1
    prev_id: tuple[str, str, str] | None = None
    for raw in pdb_path.read_text().splitlines(keepends=True):
        if raw.startswith("TER"):
            prev_id = None  # force a residue boundary at every chain terminus
            lines.append(raw)
            continue
        if raw.startswith("ATOM"):
            ident = (raw[21:22].strip(), raw[22:26].strip(), raw[17:21].strip())
            if ident != prev_id:
                res_idx += 1
                prev_id = ident
            atom_name = raw[12:16].strip()
            fixed = res_idx in anchored_indices and not atom_name.startswith("H")
            if fixed:
                n_marked += 1
            raw = _set_bfactor(raw, 1.0 if fixed else 0.0)
        elif raw.startswith("HETATM"):
            raw = _set_bfactor(raw, 0.0)
        lines.append(raw)
    dst_path.write_text("".join(lines))
    return n_marked


def _set_bfactor(line: str, value: float) -> str:
    if not line.endswith("\n"):
        line = line + "\n"
    if len(line) < 67:
        line = line.rstrip("\n").ljust(66) + "\n"
    return f"{line[:60]}{value:6.2f}{line[66:].rstrip()}\n"


# ── Aksimentiev-style ENM extraBonds ─────────────────────────────────────────

BASE_RING_ATOMS = {"N1", "C2", "N3", "C4", "C5", "C6", "N7", "C8", "N9"}
DNA_RESNAMES = {"ADE", "DA", "THY", "DT", "GUA", "DG", "CYT", "DC"}


@dataclass
class _BaseResidue:
    key: tuple[str, str, str]
    atoms: list[tuple[int, str, np.ndarray]] = field(default_factory=list)

    @property
    def com(self) -> np.ndarray:
        return np.mean([pos for _idx, _name, pos in self.atoms], axis=0)


def _parse_base_ring_residues(pdb_path: Path) -> list[_BaseResidue]:
    """Group base-ring atoms into residues by file *contiguity*.

    A residue boundary is any change in the per-atom identity tuple
    ``(segid, chain, resid, resname)`` relative to the previous atom line, plus
    every ``TER`` record.  This is robust at large strand counts where the PDB
    chain column (1 char) and segid column (4 chars) both alias: ``_chain_char``
    cycles every 62 strands and resids are not globally unique, so two
    physically distant residues can share ``(chain, resid, resname)``.  The
    earlier global-dict keying merged every such collision into one residue —
    corrupting its centre-of-mass and base-ring atom list — for ~half the
    residues of a 224-strand design.  Contiguity grouping never merges
    non-adjacent residues, so each physical base keeps its own ENM node and
    atom ordinals (which index NAMD's atom order) stay exact.
    """
    residues: list[_BaseResidue] = []
    current: _BaseResidue | None = None
    prev_id: tuple[str, str, str, str] | None = None
    atom_ordinal = 0
    for line in pdb_path.read_text(errors="replace").splitlines():
        if line.startswith("TER"):
            prev_id = None  # force a residue boundary at every chain terminus
            current = None
            continue
        if not line.startswith("ATOM  "):
            continue
        atom_ordinal += 1
        atom = line[12:16].strip()
        resn = line[17:21].strip()
        chain = line[21:22].strip()
        resid = line[22:26].strip()
        segid = line[72:76].strip()
        atom_id = (segid, chain, resid, resn)
        if atom_id != prev_id:
            current = _BaseResidue(key=(chain, resid, resn))
            residues.append(current)
            prev_id = atom_id
        if "H" in atom or atom in {"P", "O1P", "O2P"} or "'" in atom:
            continue
        if atom not in BASE_RING_ATOMS or resn not in DNA_RESNAMES:
            continue
        try:
            pos = np.array([
                float(line[30:38]),
                float(line[38:46]),
                float(line[46:54]),
            ], dtype=float)
        except ValueError:
            continue
        assert current is not None  # set on first ATOM after every boundary
        current.atoms.append((atom_ordinal - 1, atom, pos))
    return [res for res in residues if res.atoms]


def write_aksimentiev_enm_files(
    pdb_path: Path,
    package_dir: Path,
    name_stem: str,
    *,
    base_k: float = 0.5,
    scales: tuple[float, ...] = (0.5, 0.1, 0.01),
    cut_ang: float = 8.0,
    min_ang: float = 0.0,
    progress=None,
    exclude_residues: "set[tuple[str, str]] | None" = None,
) -> dict[str, object]:
    """Write tutorial-style base-ring ENM extraBonds files for all k scales.

    Restraints connect base-ring atoms of DIFFERENT residues within ``cut_ang``.
    A single atom-level KD-tree query finds them in C — the previous
    residue-COM-prefilter + Python atom double-loop was both ~10× slower on large
    designs AND buggy: when the PDB's 1-char chain column collided across many
    strands (>62), two physical residues merged under one key, their centroid
    landed far away, and the 30 Å COM prefilter silently dropped their valid
    restraints.  Working on absolute atom positions avoids that entirely.

    ``exclude_residues`` is a set of (chain_id, resid) keys whose base-ring atoms
    are dropped from the network — used to leave single-stranded / inserted bases
    unrestrained so they can relax out of steric clash (declash protocol).
    """
    residues = _parse_base_ring_residues(pdb_path)
    if exclude_residues:
        residues = [r for r in residues if (r.key[0], r.key[1]) not in exclude_residues]
    if not residues:
        raise RuntimeError(f"No DNA base-ring atoms found for ENM generation in {pdb_path}")

    # Flatten every base-ring atom into parallel arrays (position, global 0-based
    # atom index, owning-residue index).  One atom-level KD-tree query then finds
    # ALL atom pairs within cut_ang in C — replacing the old O(residue_pairs × 81)
    # Python double-loop (142M numpy.dot calls for a 5.7k-base origami → ~5 min).
    pos_list: list[np.ndarray] = []
    gidx_list: list[int] = []
    rid_list: list[int] = []
    for ri, res in enumerate(residues):
        for idx, _name, pos in res.atoms:
            pos_list.append(pos)
            gidx_list.append(idx)
            rid_list.append(ri)
    positions = np.asarray(pos_list, dtype=float)
    gidx = np.asarray(gidx_list, dtype=np.int64)
    rid  = np.asarray(rid_list, dtype=np.int64)

    pairs = cKDTree(positions).query_pairs(cut_ang, output_type="ndarray")
    if len(pairs):
        # Keep only INTER-residue pairs (matches the old loop, which only paired
        # atoms across distinct residues — never within a base ring).
        pairs = pairs[rid[pairs[:, 0]] != rid[pairs[:, 1]]]

    if len(pairs):
        _pd = np.linalg.norm(positions[pairs[:, 0]] - positions[pairs[:, 1]], axis=1)
        if min_ang > 0.0:
            # Never restrain a sub-physical inter-residue ring contact.  When the ENM is
            # rebuilt from a declashed-but-imperfect structure (topologically-locked
            # crossover-junction overlaps a no-ENM minimise can't fully open), pairs can
            # sit at ~2.1 A — far below the legit WC/stacking floor (~2.85 A).  Pinning
            # those makes the ENM fight the steric separation and a 4 fs step trips
            # "atoms moving too fast".  Dropping them lets the soft segment relax the
            # residue apart; the ~500/1.08M bonds lost are negligible for framework
            # stiffness.  See the 24hb k0.5 hand-off investigation.
            keep = _pd >= min_ang
            pairs = pairs[keep]
            _pd = _pd[keep]

    if len(pairs):
        ga = gidx[pairs[:, 0]]
        gb = gidx[pairs[:, 1]]
        lo = np.minimum(ga, gb)               # canonical (a ≤ b) bond ordering
        hi = np.maximum(ga, gb)
        dists = _pd
    else:
        lo = hi = np.empty(0, dtype=np.int64)
        dists = np.empty(0, dtype=float)

    n_bonds = int(len(lo))
    if progress is not None:
        progress("enm", 0.5, "Writing elastic-network restraint files…")
    a_str = [f"{int(a):10d}{int(b):10d}" for a, b in zip(lo.tolist(), hi.tolist())]
    d_str = [f"{d:10.3g}\n" for d in dists.tolist()]

    files: dict[str, int] = {}
    for ki, k in enumerate(scales):
        if progress is not None:
            progress("enm", 0.5 + 0.5 * (ki / max(1, len(scales))),
                     "Writing elastic-network restraint files…")
        filename = f"{name_stem}_k{k:g}.enm.extra"
        path = package_dir / filename
        k_col = f"{f'{k:.6g}':>10s}"
        with path.open("w") as handle:
            # Chunked writes: build line blocks so we never hold a full ~470 MB
            # string nor pay a syscall per restraint.
            for start in range(0, n_bonds, 200_000):
                end = min(start + 200_000, n_bonds)
                handle.write("".join(
                    f"bond{a_str[i]}{k_col}{d_str[i]}" for i in range(start, end)
                ))
        files[filename] = n_bonds

    report = {
        "schema": "nadoc.aksimentiev_enm.v1",
        "source_pdb": str(pdb_path),
        "n_residues_with_base_atoms": len(residues),
        "n_base_atoms": int(len(positions)),
        "n_restraints_per_file": n_bonds,
        "base_k_kcal_mol_A2": base_k,
        "scales": list(scales),
        "cut_ang": cut_ang,
        "base_atoms": sorted(BASE_RING_ATOMS),
        "files": files,
    }
    (package_dir / f"{name_stem}_aksimentiev_enm.report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    return report


# ── Declash protocol (single-stranded / inserted-base designs) ────────────────
#
# Designs with extra single-stranded bases at crossovers (e.g. "2xT" — two
# unpaired thymines per junction) are built with those bases in steric clash:
# the geometric layer threads their backbone through the cramped inter-helix gap,
# overlapping neighbouring-helix backbones.  Pinning them with the base-ring ENM
# stores that strain and breaks marginal duplex pairs once dynamics starts, so
# relaxation fails the health gate.
#
# The declash protocol: (1) leave the single-stranded bases OUT of the ENM so
# they can relax out of clash during minimisation; (2) rebuild the ENM ladder,
# heavy-atom restraints and the C1'/WC health reference from the declashed
# coordinates (so the structure is judged against its own relaxed geometry, not
# the clashed build); (3) run the ladder with the soft integrator (rigidBonds
# none + 1 fs) because residual single-stranded contacts crash rigid-bond RATTLE.

_DECLASH_BUILD_PDB_SUFFIX = "_build.pdb"  # backup of the original (clashed) build PDB
_C1_NO_PARTNER_ANG = 10.8  # C1'-C1' beyond this (no cross-seg partner) ⇒ unpaired


def identify_unpaired_residues(
    psf_path: Path, pdb_path: Path, *, full_segid: bool = False
) -> set[tuple[str, str]]:
    """Return (chain_id, resid) of DNA residues with no Watson-Crick partner.

    A residue is "unpaired" (single-stranded) if its C1' atom has no
    cross-segment C1' neighbour within _C1_NO_PARTNER_ANG Å — i.e. it is not
    part of a duplex.  Chain id is taken as the last character of the PSF segid
    (DNAA→A … DNAI→I), matching the PDB chain column.

    ``full_segid=True`` returns the FULL segid (e.g. "D01C") instead of its last
    character — the key format ``write_hmr_psf(heavy_residues=…)`` and
    ``extra_base_segid_resids`` match against the PSF's NATOM segid token, where
    last-char keys would alias many segids.
    """
    import MDAnalysis as mda  # noqa: PLC0415
    from scipy.spatial import cKDTree  # noqa: PLC0415

    u = mda.Universe(str(psf_path), str(pdb_path))
    c1 = u.select_atoms("name C1' C1X")
    if not len(c1):
        return set()
    pos = c1.positions
    seg = c1.segids
    resid = c1.resids
    tree = cKDTree(pos)
    ss: set[tuple[str, str]] = set()
    for k in range(len(pos)):
        nbrs = [
            m
            for m in tree.query_ball_point(pos[k], 11.0)
            if m != k and seg[m] != seg[k]
        ]
        mind = min((float(np.linalg.norm(pos[k] - pos[m])) for m in nbrs), default=99.0)
        if mind > _C1_NO_PARTNER_ANG:
            chain = str(seg[k]) if full_segid else str(seg[k])[-1]
            ss.add((chain, str(int(resid[k]))))
    return ss


def write_declashed_pdb(coor_path: Path, src_pdb: Path, dst_pdb: Path) -> int:
    """Write dst_pdb = src_pdb with coordinates replaced by a NAMD .coor file.

    Overwrites only the coordinate columns (31-54) of each ATOM/HETATM line,
    preserving record type, chain, resid and atom order so that downstream
    ENM atom-ordinals and health pair-building stay byte-consistent.  Returns
    the number of atoms rewritten.
    """
    import struct  # noqa: PLC0415

    raw = coor_path.read_bytes()
    n = struct.unpack("<i", raw[:4])[0]
    xyz = np.frombuffer(raw[4 : 4 + n * 24], dtype="<f8").reshape(n, 3)

    out: list[str] = []
    ai = 0
    for line in src_pdb.read_text().splitlines(keepends=True):
        if line.startswith(("ATOM", "HETATM")):
            x, y, z = xyz[ai]
            ai += 1
            line = f"{line[:30]}{x:8.3f}{y:8.3f}{z:8.3f}{line[54:]}"
        out.append(line)
    if ai != n:
        raise RuntimeError(
            f"Atom count mismatch: PDB has {ai} ATOM/HETATM lines, .coor has {n}"
        )
    dst_pdb.write_text("".join(out))
    return ai


# ── Hydrogen Mass Repartitioning ──────────────────────────────────────────────

_HMR_WATER_RESNAMES = {"TIP3", "TIP3P", "TIP4", "SPC", "SPCE", "HOH", "WAT"}


def _base_name_stem(package_dir: Path) -> str:
    """Return the base topology stem from a solvated package (e.g. "B_tube").

    The package ships both "{stem}.psf" and the derived "{stem}_hmr.psf" (fast-mode
    heavy-hydrogen topology), so the base stem is the one whose name does NOT end in
    "_hmr".  An unfiltered glob is filesystem-order-dependent and can otherwise pick
    the _hmr sibling, breaking every "{name_stem}.pdb" lookup downstream.
    """
    psf_files = list(package_dir.glob("*.psf"))
    if not psf_files:
        raise RuntimeError(f"No .psf file found in {package_dir}")
    base = [p for p in psf_files if not p.stem.endswith("_hmr")]
    if not base:
        raise RuntimeError(f"No base (non-_hmr) .psf file found in {package_dir}")
    return base[0].stem


def write_hmr_psf(
    src_psf: Path,
    dst_psf: Path,
    factor: float = 3.0,
    heavy_residues: "set[tuple[str, str]] | None" = None,
    heavy_factor: float = 8.0,
) -> int:
    """Write dst_psf = src_psf with non-water hydrogen masses scaled by ``factor``.

    Hydrogen Mass Repartitioning lets the dynamics run at a 4 fs timestep with
    ``rigidBonds all`` (a ~2x throughput win) by moving mass from the fast X-H
    stretch onto the hydrogen: each non-water H goes 1.008 -> 3.024 amu (factor 3)
    and the donated mass (2.016 amu) is subtracted from its single bonded heavy
    partner, conserving total mass exactly.  Water is left untouched (already
    rigid; repartitioning it would perturb solvent density).

    ``heavy_residues`` — a set of ``(segid, resid)`` keys (full segid, resid as str)
    whose atoms are made HEAVIER instead of HMR-lightened: they skip repartitioning and
    every atom mass is scaled by ``heavy_factor`` (from physical).  Use it for the
    single-stranded / dangling crossover extra bases.  Even with a clean seed they blow a
    4 fs step at step 0: their fast heavy-atom torsional/librational modes (sugar pucker,
    glycosidic, thymine-methyl rotation) are NOT frozen by ``rigidBonds`` (only X-H
    stretches are), and HMR *lightens* those carbons (thymine C5M CH3 -> ~6 amu) making it
    WORSE — the failure gets monotonically worse with more HMR.  A heavy-atom mode has
    frequency w = sqrt(k/m), so raising the mass slows it; scaling the dangling bases by
    ~8x drops those modes below the 4 fs stability limit (empirically converts a
    deterministic step-0 blow-up into survival, with the failure moving off the extra
    bases entirely).  This is thermodynamically FREE — mass drops out of the
    configurational partition function, so every equilibrium/fluctuation observable (the
    inter-helix stiffness the campaign measures) is UNCHANGED; only the extra bases'
    kinetics slow (a minor sampling-rate cost, not a bias, and they are not the measured
    DOF).  0xT (no dangling bases) needs no heavy set.  ``heavy_factor`` is tunable —
    validate/tune it on a full-ladder run.  See NAMD_4FS_RATTLE_RESEARCH.md.

    Only the mass token of each atom record is rewritten, at its original column
    width, so atom ordering and every other field stay byte-for-byte intact.
    Returns the number of hydrogens repartitioned.
    """
    heavy_residues = heavy_residues or set()
    lines = src_psf.read_text().splitlines()

    def _find(tag: str) -> int:
        for i, l in enumerate(lines):
            if tag in l:
                return i
        raise RuntimeError(f"{tag} not found in {src_psf}")

    natom_i = _find("!NATOM")
    n_atoms = int(lines[natom_i].split()[0])
    nbond_i = _find("!NBOND")
    n_bonds = int(lines[nbond_i].split()[0])

    mass = [0.0] * (n_atoms + 1)            # 1-based
    resname = [""] * (n_atoms + 1)
    heavy = [False] * (n_atoms + 1)         # dangling extra bases: mass scaled UP, no HMR
    span: list[Optional[tuple[int, int, int, int]]] = [None] * (n_atoms + 1)
    for k in range(n_atoms):
        li = natom_i + 1 + k
        toks = list(re.finditer(r"\S+", lines[li]))
        aid = int(toks[0].group())
        resname[aid] = toks[3].group()       # atomid seg resid resname name type charge MASS
        if heavy_residues and (toks[1].group(), toks[2].group()) in heavy_residues:
            heavy[aid] = True
        m = toks[7]
        mass[aid] = float(m.group())
        span[aid] = (li, m.start(), m.end(), m.end() - m.start())

    neigh: list[list[int]] = [[] for _ in range(n_atoms + 1)]
    read, li = 0, nbond_i + 1
    while read < n_bonds:
        nums = lines[li].split()
        for j in range(0, len(nums), 2):
            a, b = int(nums[j]), int(nums[j + 1])
            neigh[a].append(b)
            neigh[b].append(a)
            read += 1
        li += 1

    def _is_h(aid: int) -> bool:
        return 0.9 <= mass[aid] <= 1.5

    heavy_delta: dict[int, float] = {}
    n_hmr = 0
    for aid in range(1, n_atoms + 1):
        if not _is_h(aid) or resname[aid] in _HMR_WATER_RESNAMES or heavy[aid]:
            continue
        parents = [p for p in neigh[aid] if not _is_h(p)]
        if len(parents) != 1:                # ion-model H bonded to >1 heavy: skip
            continue
        new_h = mass[aid] * factor
        heavy_delta[parents[0]] = heavy_delta.get(parents[0], 0.0) + (new_h - mass[aid])
        mass[aid] = new_h
        n_hmr += 1
    for aid, d in heavy_delta.items():
        mass[aid] -= d
    # Dangling extra bases: uniform mass scale-UP on their (physical) atoms — slows their
    # fast heavy-atom modes below the 4 fs limit.  Applied AFTER HMR; a heavy residue's
    # atoms were skipped by the HMR loop (its H never donated, its heavy atoms received no
    # delta — DNA H are intra-residue), so they are still at physical mass here.
    if heavy_residues and heavy_factor != 1.0:
        for aid in range(1, n_atoms + 1):
            if heavy[aid] and resname[aid] not in _HMR_WATER_RESNAMES:
                mass[aid] *= heavy_factor

    out = list(lines)
    for aid in range(1, n_atoms + 1):
        sp = span[aid]
        if sp is None:
            continue
        li, s, e, w = sp
        out[li] = out[li][:s] + f"{mass[aid]:.4f}".rjust(w) + out[li][e:]
    dst_psf.write_text("\n".join(out) + "\n")
    return n_hmr


# Inter-residue ring pairs closer than this in the declashed structure are residual,
# topologically-locked clashes (a no-ENM minimise can't fully open crossover-junction
# overlaps), NOT legit WC/stacking contacts (those bottom out ~2.85 A).  The rebuilt ENM
# drops them so it never pins a sub-physical distance that a 4 fs step blows up on.
_ENM_DECLASH_MIN_REF_ANG = 2.8


def rebuild_declashed_references(
    package_dir: Path,
    name_stem: str,
    min_coor: Path,
    *,
    scales: tuple[float, ...] = (0.5, 0.1, 0.01),
    min_ang: float = _ENM_DECLASH_MIN_REF_ANG,
) -> dict[str, object]:
    """After the declash minimisation, re-anchor every reference to the relaxed coords.

    1. Back up the original build PDB to ``{name_stem}_build.pdb`` and overwrite
       ``{name_stem}.pdb`` with the declashed coordinates from ``min_coor``.
    2. Re-detect single-stranded residues and rebuild the ENM ladder
       ``{name_stem}_k*.enm.extra`` (ss-excluded) + ``restraints_dna_heavy.pdb``
       from the declashed geometry.

    Idempotent: if the build-PDB backup already exists the rebuild is skipped
    (so a resumed job does not re-overwrite).  Returns a small report dict.
    """
    pdb_path = package_dir / f"{name_stem}.pdb"
    psf_path = package_dir / f"{name_stem}.psf"
    build_pdb = package_dir / f"{name_stem}{_DECLASH_BUILD_PDB_SUFFIX}"

    if build_pdb.exists():
        return {"rebuilt": False, "reason": "already declashed (build backup present)"}

    pdb_path.replace(build_pdb)  # preserve original clashed build
    n_atoms = write_declashed_pdb(min_coor, build_pdb, pdb_path)

    ss = identify_unpaired_residues(psf_path, pdb_path)
    enm_report = write_aksimentiev_enm_files(
        pdb_path,
        package_dir,
        name_stem,
        scales=scales,
        min_ang=min_ang,
        exclude_residues=ss,
    )
    write_restraints_pdb(pdb_path, package_dir / "restraints_dna_heavy.pdb")
    return {
        "rebuilt": True,
        "n_atoms": n_atoms,
        "n_unpaired_excluded": len(ss),
        "enm_restraints_per_file": enm_report.get("n_restraints_per_file"),
    }


def design_has_extra_bases(design: "Design") -> bool:
    """True if the design inserts single-stranded bases at any junction.

    Covers both crossover ``extra_bases`` (e.g. "TT") and forced-ligation
    ``extra_bases`` — the same sources `_build_extra_base_atoms` builds from.
    Such designs are built with the inserted bases in steric clash, so the
    declash protocol is enabled automatically for them.
    """
    if any(
        getattr(xo, "extra_bases", None) for xo in getattr(design, "crossovers", [])
    ):
        return True
    return any(
        getattr(fl, "extra_bases", None)
        for fl in getattr(design, "forced_ligations", [])
    )


def design_has_extensions(design: "Design") -> bool:
    """True if the design carries any strand extension that contributes real DNA.

    Only SEQUENCE-bearing extensions count: a modification-only extension (a
    fluorophore or biotin with no ``sequence``) is not DNA and builds no residue.

    Extension tails are single-stranded, unpaired, and seeded on a geometric arc
    poking radially out of the duplex, so — exactly like crossover extra bases — they
    can start in steric contact with a neighbouring helix.  The declash protocol
    handles them for free once enabled: ``identify_unpaired_residues`` is purely
    geometric (C1′–C1′ > 10.8 Å ⇒ unpaired), so tail residues are auto-detected as
    single-stranded, kept out of the ENM, and relaxed with the soft integrator.
    """
    return any(getattr(e, "sequence", None) for e in getattr(design, "extensions", []))


# ── Box extraction ────────────────────────────────────────────────────────────

def parse_box_from_namd_conf(conf_text: str) -> tuple[float, float, float]:
    """Extract cellBasisVector diagonal as (bx, by, bz) in Å.

    Expects orthogonal box where off-diagonal elements are zero.
    """
    bx = by = bz = 0.0
    for line in conf_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("cellBasisVector1"):
            parts = stripped.split()
            if len(parts) >= 2:
                bx = float(parts[1])
        elif stripped.startswith("cellBasisVector2"):
            parts = stripped.split()
            if len(parts) >= 3:
                by = float(parts[2])
        elif stripped.startswith("cellBasisVector3"):
            parts = stripped.split()
            if len(parts) >= 4:
                bz = float(parts[3])
    if bx == 0.0 or by == 0.0 or bz == 0.0:
        raise ValueError(f"Could not parse box from NAMD conf (got {bx}, {by}, {bz})")
    return (bx, by, bz)


# ── mgh_slow_release segment sequence ────────────────────────────────────────

def _scale_label(scale: Optional[float]) -> str:
    if scale is None:
        return "unrestrained"
    s = f"{scale:g}"
    return s.replace(".", "p")


# The relaxation early-stop evaluator refuses to judge a plateau on fewer than
# ``CutoffParams.min_frames`` (20) ENERGY frames — "insufficient data" fails SAFE to
# "run the whole thing". Aim comfortably above that.
_ENERGY_FRAMES_PER_CHUNK = 30


# A restart write is ~90 MB (coor+vel, 1.9M atoms) pushed SYNCHRONOUSLY to the network
# volume, so it is not free — but it is the only thing standing between a dead pod and
# lost compute. The interval is a genuine optimum, not a preference:
#
#     wasted fraction   = w / T          (w = write cost, T = interval)
#     expected loss     = T / 2          per pod death
#     minimise 3600*w/T + lambda*T/2  ->  T* = sqrt(w / (lambda/2))
#
# With w ~ 1 s and the OBSERVED pod-death rate on RunPod (2 pods lost in ~10 h, so
# lambda ~ 0.2/h): T* ~ 190 s ~ 3 min, i.e. ~5,000 steps at 35.5 ms/step. Overhead 0.56%.
#
# ⚠️ Note this is a fixed STEP COUNT, not a fraction of the run. Write size scales with
# atoms and so does step time, so a fixed step count holds the overhead fraction roughly
# CONSTANT across system sizes. The old `steps // 50` rule was wrong in both directions:
# 9.5 min between writes on a long run (we lost 27,000 steps to a dead pod that way) and
# seconds on a short one.
_RESTART_EVERY_STEPS = 5_000


def _restart_freq(steps: int, cycle: int = AKSIMENTIEV_STEPS_PER_CYCLE) -> int:
    """Crash insurance, NOT a sampling rate. See _RESTART_EVERY_STEPS."""
    r = min(max(cycle, _RESTART_EVERY_STEPS), max(cycle, steps // 4))
    return max(cycle, r - (r % cycle))


def _production_output_freqs(steps: int, cycle: int = 10) -> tuple[int, int]:
    """``(energy_freq, restart_freq)`` for an unrestrained PRODUCTION run.

    Both were hardcoded — ``outputEnergies 100`` and ``restartfreq 1000`` — and on a
    1.9M-atom GPU-resident run both are pure overhead with ZERO effect on the trajectory:

      * ``outputEnergies 100`` forces a GPU->host energy reduction every 100 steps. In
        GPU-resident mode the whole point is that the data never leaves the card; this
        drags it back 13,750 times over a 1.375M-step run, and prints 13,750 energy
        frames nobody reads. Scale it: ~400 frames is plenty to watch progress and spot
        a blow-up.

      * ``restartfreq`` is the crash-insurance dial, and BOTH extremes cost real money —
        see _RESTART_EVERY_STEPS above. Rented GPUs die (host failure, reclaim, an
        over-broad reap); the restart file is what makes that a 3-minute loss instead of
        a 5-hour one.
    """
    e = max(cycle, steps // 400)
    r = min(max(cycle, _RESTART_EVERY_STEPS), max(cycle, steps // 4))
    return (max(cycle, e - (e % cycle)), max(cycle, r - (r % cycle)))


def _output_freq(steps: int, cycle: int = AKSIMENTIEV_STEPS_PER_CYCLE) -> int:
    """ENERGY/DCD print interval giving ~30 frames for a chunk of ``steps``, whatever
    the timestep.

    This used to be a hardcoded 9600 STEPS, and that silently broke relaxation
    early-stop the moment ``fast`` was enabled. The chunk step-counts are derived from a
    target simulated TIME, so doubling the timestep (2 fs -> 4 fs, the `fast` path)
    HALVES every chunk's step count for the same physics — while a step-denominated
    print interval kept firing just as often per step, i.e. HALF as often per
    nanosecond. A p10 chunk went from 25 ENERGY frames to 12, under the evaluator's
    min_frames=20, so `energy_plateaued` returned False for every p10 in the ladder and
    no p10 could ever bridge. The accelerator was still *emitted*, still *ran*, and
    still reported HOLD every time — a silent 4x cost increase with no error anywhere.

    Deriving the cadence from the chunk's own length makes the frame count invariant
    under timestep, which is what the evaluator actually cares about.
    """
    f = max(cycle, steps // _ENERGY_FRAMES_PER_CHUNK)
    return max(cycle, f - (f % cycle))      # NAMD wants a multiple of stepspercycle


def _display_dcd_freq(steps: int) -> int:
    """Write sparse frames for multi-ns relaxation without filling the disk.

    Same cadence as the ENERGY print: Tier-A early-stop reads a WC base-pairing series
    off THIS trajectory, so a chunk whose DCD is too sparse can't be judged either.
    """
    return _output_freq(steps)


def _round_up_to_cycle(steps: int, cycle: int = AKSIMENTIEV_STEPS_PER_CYCLE) -> int:
    """NAMD minimize/run steps must be divisible by stepspercycle."""
    if steps <= 0:
        return steps
    remainder = steps % cycle
    return steps if remainder == 0 else steps + (cycle - remainder)


def mgh_slow_release_segments(
    name_stem: str,
    *,
    soft: bool = False,
    nvt_only: bool = False,
    timestep_fs: float = 2.0,
) -> tuple[str, list[SegmentSpec]]:
    """Return (min_name, segments) for the mgh_slow_release protocol.

    The minimization name is returned separately because it needs a distinct
    conf/output name that the first warmup segment continues from.

    Default stages mirror the Aksimentiev tutorial shape:
      minimization: ENM k=0.5 + MGHH, 4800 steps by default
      NPT stages: 300 K, ENM k=0.5 -> 0.1 -> 0.01, 4.8 ns each
      handoff: 300 K, k=0, 4.8 ns

    ``soft=True`` (declash protocol) runs every stage with the soft integrator
    (rigidBonds none + 1 fs) so residual single-stranded contacts do not crash
    rigid-bond RATTLE.

    ``nvt_only=True`` forces every stage to run with the barostat off.  This is
    required when the package was built with a water-shell carve: the carved cell
    has vacuum corners, and an NPT piston would compress the box until the DNA
    overlaps its own periodic image.  Stage names keep their ``NPT`` label (to
    preserve manifest/resume continuity) but the cell is held fixed.
    """
    min_name = f"{name_stem}_00_min_enm_k0p5"

    # Each stage targets 4.8 ns of relaxation.  Step count scales inversely with
    # the timestep so fast mode (4 fs) keeps the same simulated time (1.2M steps)
    # rather than doubling it — fast mode is a wall-clock win, not a science change.
    stage_steps = int(round(2_400_000 * (2.0 / timestep_fs)))
    npt_ladder = [
        (0.5,  stage_steps, "300K_NPT_ENM_k0p5"),
        (0.1,  stage_steps, "300K_NPT_ENM_k0p1"),
        (0.01, stage_steps, "300K_NPT_ENM_k0p01"),
        (None, stage_steps, "300K_NPT_MGHH_only"),
    ]

    # Percentages and their fraction of total steps
    pcts = [(10.0, 0.10), (50.0, 0.40), (100.0, 0.50)]  # steps at 10%, then +40%, then +50%

    segments: list[SegmentSpec] = []
    stage_idx = 1
    previous = min_name

    for scale, total_steps, label in npt_ladder:
        stage_str = (
            "300K NPT k=0"
            if scale is None
            else f"300K NPT ENM k={scale}"
        )
        for i, (pct, frac) in enumerate(pcts):
            seg_steps = _round_up_to_cycle(max(100, int(total_steps * frac)))
            seg_name = f"{name_stem}_{stage_idx:02d}_{label}_p{int(pct)}"
            segments.append(
                SegmentSpec(
                    name=seg_name,
                    stage=stage_str,
                    percent=pct,
                    steps=seg_steps,
                    temp=300.0,
                    damping=5.0,
                    scale=scale,
                    npt=not nvt_only,
                    previous=previous,
                    reinit=False,
                    dcd_freq=_display_dcd_freq(seg_steps),
                    min_wc_ref_relative=0.75 if scale is None else 0.80,
                    extra_bonds_file=None
                    if scale is None
                    else f"{name_stem}_k{scale:g}.enm.extra",
                    soft=soft,
                )
            )
            previous = seg_name
        stage_idx += 1

    # Soft start: a freshly built ideal-B-DNA model often has one residual local
    # strain the ENM minimisation can't fully relieve (the ENM pins the global
    # shape).  Hitting it with 2 fs + rigidBonds all on the very first dynamics
    # steps trips a RATTLE "Constraint failure".  Run just the FIRST segment with
    # the soft integrator (rigidBonds none + 1 fs) so the strained atom relaxes
    # safely; every later segment reverts to fast 2 fs rigid dynamics.  (When the
    # whole ladder is already soft — declash designs — this is a no-op.)
    if segments and not soft:
        segments[0].soft = True

    return min_name, segments


# ── Full job preparation ──────────────────────────────────────────────────────

def prepare_mgh_slow_release(
    design: Design,
    job_dir: Path,
    *,
    protocol: str = LEGACY_PROTOCOL,
    ion_conc_mM: float = 0.0,
    mg_conc_mM: float = 12.5,
    salt_mode: str = "custom",
    padding_nm: float = 1.2,
    water_shell_nm: float = 0.0,
    minimize_steps: int = 4_800,
    min_scale: float = 0.5,
    require_full_topology: bool = False,
    seed: int = 42,
    atomistic_model=None,
    progress=None,
    declash: bool = False,
    force_soft: bool = False,
    fast: bool = False,
    pre_declashed: bool = False,
    anchors: Optional[list] = None,
    field: Optional[dict] = None,
) -> tuple[str, str, list[SegmentSpec]]:
    """Build the solvated package and all stage configs in job_dir.

    ``atomistic_model`` (optional) is a pre-built heavy-atom model supplying the
    DNA starting coordinates — pass an oxDNA-relaxed model (Phase-2 NAMD seed)
    to start NAMD from relaxed positions instead of ideal B-DNA.

    Calls build_namd_solvated_package (GROMACS solvation step, ~60-120 s).
    Extracts the ZIP to job_dir/package/, then writes:
      - restraints_dna_heavy.pdb
      - {min_name}.conf
      - one .conf per segment
      - manifest.json

    Declash (auto-enabled when the design inserts extra bases at crossovers, or
    forced via ``declash=True``): the minimisation runs against an ss-excluded
    ENM so the inserted bases relax out of clash, the runner re-anchors all
    references to the declashed coordinates after minimisation (see
    ``rebuild_declashed_references``), and the ladder runs with the soft
    integrator.

    Returns (package_subdir, name_stem) relative to job_dir.
    """
    from backend.core.namd_solvate import build_namd_solvated_package  # noqa: PLC0415

    minimize_steps = _round_up_to_cycle(minimize_steps)

    water_shell_nm = water_shell_nm or 0.0
    carve_shell = water_shell_nm > 0

    zip_bytes = build_namd_solvated_package(
        design,
        padding_nm      = padding_nm,
        ion_conc_mM     = ion_conc_mM,
        mg_conc_mM      = mg_conc_mM,
        mg_hexahydrate  = True,
        require_full_topology = require_full_topology,
        seed            = seed,
        atomistic_model = atomistic_model,
        water_shell_nm  = water_shell_nm if carve_shell else None,
        progress        = progress,
    )

    # Extract ZIP — inner folder is "{name}_namd_solvated/"
    pkg_root = job_dir / "package"
    pkg_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        zf.extractall(pkg_root)

    # Discover the extracted subfolder
    inner_dirs = [p for p in pkg_root.iterdir() if p.is_dir()]
    if not inner_dirs:
        raise RuntimeError("ZIP extraction produced no subdirectory.")
    package_dir = inner_dirs[0]       # e.g. package/B_tube_namd_solvated/

    # Derive file stem from the BASE {stem}.psf.  The package also ships a derived
    # "{stem}_hmr.psf" (heavy-hydrogen topology for fast mode), so an unfiltered
    # glob can pick that up first (glob order is filesystem-dependent) and make
    # name_stem "{stem}_hmr" — then every downstream "{name_stem}.pdb" lookup opens
    # a nonexistent "{stem}_hmr.pdb".  Exclude the _hmr sibling explicitly.
    name_stem = _base_name_stem(package_dir)

    # Parse box from the generated namd.conf
    namd_conf_path = package_dir / "namd.conf"
    box = parse_box_from_namd_conf(namd_conf_path.read_text())

    mgh_extrabonds = (package_dir / "mgh_extrabonds.txt").exists()

    # Write restraint references and Aksimentiev-style ENM files.
    if progress is not None:
        progress("enm", None, "Building elastic-network restraints…")
    pdb_path = package_dir / f"{name_stem}.pdb"
    write_restraints_pdb(pdb_path, package_dir / "restraints_dna_heavy.pdb")
    # Exclude single-stranded crossover extra bases from the LADDER ENM so they relax to
    # their true conformation rather than being pinned into a stretched backbone bond.
    # Without this, an oxDNA-SEEDED FAST (4 fs) ladder restrains the seeded inserts and the
    # minimiser stretches ~14 C4'-C5' bonds to ~2 A — enough to trip a 4 fs RATTLE step.
    # (The un-seeded declash path hid this behind its soft 1 fs integrator; ss inserts
    # should never be ENM-pinned there either, so the exclusion is correct for both.)
    _ladder_enm_exclude: "set[tuple[str, str]]" = set()
    if design_has_extra_bases(design) or declash:
        _ladder_enm_exclude = identify_unpaired_residues(
            package_dir / f"{name_stem}.psf", pdb_path)
    enm_report = write_aksimentiev_enm_files(
        pdb_path, package_dir, name_stem,
        exclude_residues=_ladder_enm_exclude or None, progress=progress)

    # Anchors (optional): resolve the shared anchor scopes to DNA residues and write a
    # fixedAtoms marker PDB the whole ladder reads.  A JOB-REQUEST annotation resolved
    # read-only from the topology — never a Design edit (Three-Layer Law).  A selection
    # that resolves to nothing (stale / ssDNA-only) leaves the run unanchored.
    anchors_file: Optional[str] = None
    anchor_indices: set = set()
    n_anchored_atoms = 0
    if anchors:
        from backend.core.namd_topology import resolve_anchor_residue_indices  # noqa: PLC0415
        # full_topology must match how the package {stem}.pdb was built (psfgen when
        # require_full_topology, else export_pdb) so the residue ordinals line up.
        anchor_indices = resolve_anchor_residue_indices(
            design, anchors, model=atomistic_model, full_topology=require_full_topology)
        if anchor_indices:
            n_anchored_atoms = write_anchor_restraints_pdb(
                pdb_path, package_dir / "restraints_anchors.pdb", anchor_indices)
            anchors_file = "restraints_anchors.pdb"

    # E-field (optional): a uniform native NAMD q·E body force, also a JOB-REQUEST
    # annotation.  A field with no anchor just streams the whole box (COM drift).
    efield_vec = namd_efield_vector(field)
    if efield_vec is not None and anchors_file is None:
        # An unanchored uniform q·E body force just streams the whole box (COM drift).
        # Anchors are recommended but no longer required — the UI warns; the run proceeds.
        logger.warning(
            "NAMD E-field prepared with no anchor (requested scopes %r resolved to no DNA "
            "residues) — the structure will drift down-field (COM drift).", anchors)

    # Declash: minimise against an ss-excluded ENM so inserted single-stranded
    # bases relax out of clash.  References are rebuilt from the declashed coords
    # by the runner after minimisation (rebuild_declashed_references).  Enabled
    # automatically whenever the design inserts extra bases at crossovers (they
    # are built clashed) or carries strand extensions (free ssDNA tails seeded on a
    # geometric arc); the explicit flag can force it on otherwise.
    #
    # ``pre_declashed`` OVERRIDES the extra-base auto-enable: an oxDNA-SEEDED structure
    # (build_namd_seed) already has its extra bases at relaxed, non-clashing
    # positions with healthy backbone bonds, so the soft declash ladder — and the
    # 1 fs / no-HMR / no-fast penalty it forces — is unnecessary.  Seeding is
    # precisely what lets an extra-base design run the 4 fs fast ladder (the
    # geometric-guess build could not: its stacked sugars minimised into a ~3.1 A
    # C4'-C5' bond that is fatal to a 4 fs RATTLE step). See the 24hb 4 fs
    # investigation + backend/core/oxdna_seed.py.
    declash = (declash
               or (design_has_extra_bases(design) and not pre_declashed)
               or design_has_extensions(design))
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

    # oxDNA-SEEDED extra-base designs (pre_declashed) skip the soft declash ladder
    # above, but their backmap still carries DUPLEX base clashes at crossover junctions
    # (inter-residue ring atoms down to ~0.3 A) that the seed-built ENM would pin as its
    # reference.  A stiff k0.5 ENM masks the stored clash energy; relaxing to k0.1 dumps
    # it (70x over the velocity limit) and NAMD dies.  Fix: minimise WITHOUT the base-ring
    # ENM (no_enm below) so the duplex declashes, then have the runner rebuild the ENM from
    # the declashed minimise coords (rebuild_declashed_references) — all WITHOUT dropping to
    # the soft 1 fs ladder, which is exactly what pre_declashed preserves.  This is a
    # DISTINCT trigger from ``declash`` above (which is coupled to soft_ladder/fast).  See
    # PIPELINE_4FS_EXTRA_BASES.md + the 24hb k0.1 investigation.
    rebuild_enm_from_min = bool(pre_declashed and design_has_extra_bases(design))

    # Create output dir
    if progress is not None:
        progress("finalize", None, "Writing simulation configs…")
    (package_dir / "output").mkdir(exist_ok=True)

    # Fast mode: HMR PSF + 4 fs + GPU-resident on the hard ladder (~4x in NPT).
    # Disabled for the soft integrator (HMR / 4 fs need rigid bonds), so a declash
    # / force-soft ladder always runs the classic 2 fs standard-CUDA path.
    soft_ladder = declash or force_soft
    fast = fast and not soft_ladder

    # Build segment list.  A water-shell carve leaves vacuum corners, so the
    # whole ladder must run NVT (barostat off) — an NPT piston would collapse the
    # cell onto the DNA's periodic image.  Fast mode halves the step count (4 fs)
    # to hold each stage at its 4.8 ns relaxation target.
    min_name, segments = mgh_slow_release_segments(
        name_stem, soft=soft_ladder, nvt_only=carve_shell,
        timestep_fs=4.0 if fast else 2.0,
    )

    # The HMR PSF enters at the first hard, rigid-bond segment; minimisation and
    # the soft strain-relief first segment keep the unmodified PSF.
    structure_psf: Optional[str] = None
    n_hmr = 0
    if fast:
        hmr_psf = package_dir / f"{name_stem}_hmr.psf"
        n_hmr = write_hmr_psf(package_dir / f"{name_stem}.psf", hmr_psf)
        structure_psf = hmr_psf.name

    # Write minimization conf
    (package_dir / f"{min_name}.conf").write_text(
        _min_conf(
            min_name,
            name_stem,
            box,
            mgh_extrabonds,
            minimize_steps,
            min_scale,
            enm_file=declash_enm_file,
            no_enm=rebuild_enm_from_min,
            anchors_file=anchors_file,
            field=field,
        )
    )

    # Write segment confs
    for spec in segments:
        (package_dir / f"{spec.name}.conf").write_text(
            _segment_conf(spec, name_stem, box, mgh_extrabonds,
                          fast=fast, carved=carve_shell, structure_psf=structure_psf,
                          anchors_file=anchors_file, field=field)
        )

    charge_audit = {}
    charge_audit_path = package_dir / "charge_audit.json"
    if charge_audit_path.exists():
        charge_audit = json.loads(charge_audit_path.read_text())

    segment_dicts = [
        {
            "name":     s.name,
            "stage":    s.stage,
            "percent":  s.percent,
            "steps":    s.steps,
            "temp":     s.temp,
            "damping":  s.damping,
            "scale":    s.scale,
            "npt":      s.npt,
            "previous": s.previous,
            "reinit":   s.reinit,
            "dcd_freq": s.dcd_freq,
            "min_c1_paired": s.min_c1_paired,
            "min_wc_ref_relative": s.min_wc_ref_relative,
            "extra_bonds_file": s.extra_bonds_file,
            "soft": s.soft,
        }
        for s in segments
    ]

    # Write manifest for human inspection and NADOC trajectory reload.
    manifest = {
        "nadoc_md_run_manifest_version": 1,
        "protocol":    protocol,
        "package_dir": str(package_dir.resolve()),
        "name_stem":   name_stem,
        "files": {
            "topology": f"{name_stem}.psf",
            "coordinates": f"{name_stem}.pdb",
            "base_config": "namd.conf",
            "forcefield_dir": "forcefield",
            "output_dir": "output",
            "charge_audit": "charge_audit.json",
            "restraints": "restraints_dna_heavy.pdb",
            **({"anchors": anchors_file} if anchors_file else {}),
        },
        "box_ang":     list(box),
        "mgh_extrabonds": mgh_extrabonds,
        "anchors": {
            "requested": anchors or [],
            "file": anchors_file,
            "n_residues": len(anchor_indices),
            "n_atoms_fixed": n_anchored_atoms,
            "mechanism": "fixedAtoms (fixedAtomsCol B); held immobile across the ladder",
        },
        # The E-field as launched.  ``efield_vector`` is the NAMD-unit vector actually
        # written into every conf; the production-stage writers read it back from here so
        # an extended run keeps the same field (and the same anchors) as the ladder.
        "field": (
            {
                "field_pN": float(field.get("field_pN", field.get("force_pN", 0.0)) or 0.0),
                "dir": [float(c) for c in field["dir"]],
                "efield_vector": list(efield_vec),
                "efield_units": "kcal/mol/A/e",
                "charge_per_nucleotide_e": NAMD_DNA_CHARGE_PER_NUCLEOTIDE_E,
                "terminal_charge_note": (
                    "internal nucleotides carry -1 e (one phosphate) and feel exactly "
                    "field_pN; 5TER/3TER hydroxyl termini carry -0.47/-0.53 e, so a strand "
                    "feels -(N-1) e worth of force (its phosphate count)"
                ),
                "mechanism": "native NAMD eFieldOn/eField (q·E on every charged atom)",
            }
            if efield_vec is not None
            else None
        ),
        "declash": declash,
        "declash_min_coor": (
            f"output/{min_name}.coor" if (declash or rebuild_enm_from_min) else None),
        "n_unpaired_excluded": n_unpaired if declash else 0,
        # Seeded extra-base path: minimise ran WITHOUT the ENM (no_enm) to open the seed
        # backmap's duplex clashes; the runner rebuilds the ENM from the declashed coords
        # so k0.1 no longer releases stored clash energy.  Decoupled from ``declash``
        # (which forces the soft 1 fs ladder) — this keeps the fast 4 fs ladder.
        "rebuild_enm_from_min": rebuild_enm_from_min,
        "salt": {
            "mode": salt_mode,
            "nacl_mM": ion_conc_mM,
            "mgcl2_mM": mg_conc_mM,
            "note": "screening mode uses neutralizing Na+ plus 12.5 mM MgCl2/MGH and no extra bulk NaCl",
        },
        "equilibrium_aware": {
            "requires_full_dna_topology": require_full_topology,
            "requires_dna_hydrogens": require_full_topology,
            "requires_neutral_final_psf": require_full_topology,
            "current_package_passed": bool(
                charge_audit.get("production_ready")
                if charge_audit else not require_full_topology
            ),
        },
        "charge_audit": charge_audit,
        "minimization": {
            "name":  min_name,
            "steps": minimize_steps,
            "scale": min_scale,
            # Seeded extra-base path minimises with NO base-ring ENM so the seed
            # backmap's duplex clashes can open (the ENM is rebuilt from these coords).
            "restraint": (
                "mgh_only_no_enm" if rebuild_enm_from_min else "aksimentiev_base_ring_enm"),
            "extra_bonds_file": (
                None if rebuild_enm_from_min
                else declash_enm_file or f"{name_stem}_k{min_scale:g}.enm.extra"),
        },
        "aksimentiev_enm": enm_report,
        "fast_relaxation": {
            "enabled": fast,
            "hydrogens_repartitioned": n_hmr,
            "structure_psf": structure_psf,
            "gpu_resident": fast,
            "timestep_fs": 4.0 if fast else 2.0,
            "note": "HMR (non-water H x3) + GPUresident + 4 fs on the hard ladder; "
                    "capped box only, ~4x NPT throughput vs standard CUDA 2 fs.",
        },
        "relax_protocol_settings": {
            "stage_length_steps": 2_400_000,
            "stage_length_ns_at_2fs": 4.8,
            "timestep_fs": 4.0 if fast else 2.0,
            "temperature_k": 300.0,
            "langevin_damping_ps_inv": 5.0,
            "pme_grid_spacing_ang": 1.5,
            "switch_cut_pairlist_ang": [8.0, 10.0, 12.0],
            "piston_period_decay_fs": [1000.0, 500.0],
            "output_frequency_steps": 9600,
        },
        "segments": segment_dicts,
        "health_checks": "After every segment: 10%, 50%, and 100% of each stage.",
    }
    manifest_text = json.dumps(manifest, indent=2)
    (package_dir / "manifest.json").write_text(manifest_text)
    (package_dir / "nadoc_md_run.json").write_text(manifest_text)

    # Relative subdir for MdJob
    package_subdir = str(package_dir.relative_to(job_dir))
    return package_subdir, name_stem, segments


def prepare_equilibrium_aware_namd(
    design: Design,
    job_dir: Path,
    **kwargs,
) -> tuple[str, str, list[SegmentSpec]]:
    """Prepare the strict one-button production workflow.

    This wraps the same Mg slow-release ladder, but requires a complete DNA
    topology with hydrogens and a neutral final PSF before any job can queue.
    """
    return prepare_mgh_slow_release(
        design,
        job_dir,
        protocol=EQUILIBRIUM_AWARE_PROTOCOL,
        require_full_topology=True,
        **kwargs,
    )


def segments_from_manifest(manifest_path: Path) -> tuple[str, list[SegmentSpec]]:
    """Reconstruct segment list from an existing manifest.json (for resume)."""
    import json  # noqa: PLC0415

    data = json.loads(manifest_path.read_text())
    min_name = data["minimization"]["name"]
    segments = [
        SegmentSpec(
            name=s["name"],
            stage=s["stage"],
            percent=s["percent"],
            steps=s["steps"],
            temp=s["temp"],
            damping=s["damping"],
            scale=s["scale"],
            npt=s["npt"],
            previous=s["previous"],
            reinit=s.get("reinit", False),
            dcd_freq=s.get("dcd_freq", 20000),
            min_c1_paired=s.get("min_c1_paired", 0.90),
            min_wc_ref_relative=s.get("min_wc_ref_relative", 0.85),
            extra_bonds_file=s.get("extra_bonds_file"),
            soft=s.get("soft", False),
        )
        for s in data["segments"]
    ]
    return min_name, segments
