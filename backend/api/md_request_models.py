"""Validated MD job creation, production, and summary API contracts.

Kept separate from orchestration so consumers can inspect/validate requests
without importing job runners and route registration.
"""
from __future__ import annotations
from typing import Annotated, Literal, Optional
from pydantic import BaseModel, Field, field_validator
from backend.core.md_ensemble import NAMD_SEED_MAX
from backend.core.md_presets import DEFAULT_PRESET
from backend.core.md_protocols import EQUILIBRIUM_AWARE_PROTOCOL
from backend.core.namd_runner import default_threads

#: Upper bound on a single production run's length.  These are sanity rails, not a
#: policy on how long a run *should* be — microsecond-scale origami production is a
#: normal ask, and the previous 50M-step / 100 ns ceiling rejected it with a raw
#: pydantic 422 (an array of dicts, which the panel rendered as "[object Object]").
#: 1e9 steps is 4 µs at 4 fs and 2 µs at 2 fs, and stays well inside the 32-bit int
#: NAMD parses ``numsteps`` into.  What actually protects a long run is the disk
#: forecast + the periodic-cell rotation check, not an arbitrary step count.
MAX_PRODUCTION_STEPS = 1_000_000_000
MAX_PRODUCTION_NS = 10_000.0


# ── Request/response models ────────────────────────────────────────────────────


class CreateJobRequest(BaseModel):
    protocol: str = Field(
        EQUILIBRIUM_AWARE_PROTOCOL, description="Protocol preset name"
    )
    threads: int = Field(
        default_factory=default_threads,
        ge=1,
        description="NAMD +p thread count; defaults to half the logical CPUs",
    )
    devices: str = Field("0", description="CUDA device IDs (e.g. '0' or '0,1')")
    autostart: bool = Field(
        False, description="Start NAMD immediately after preparation"
    )
    seed: Optional[int] = Field(
        None,
        ge=1,
        le=NAMD_SEED_MAX,
        description="Base NAMD random seed for this job. The Job Wizard generates and "
        "displays one before creation; API callers may omit it and the server draws one. "
        "Relaxation stage i uses base+i, while the base itself is recorded on the job.",
    )
    salt_mode: str = Field(
        "screening",
        description="'screening' uses validated origami screening defaults; 'custom' uses Mg/NaCl fields",
    )
    # Advanced overrides (all optional)
    ion_conc_mM: float = Field(0.0, ge=0.0)
    mg_conc_mM: float = Field(12.5, ge=0.0)
    padding_nm: float = Field(1.2, gt=0.0)
    box_size_nm: Optional[tuple[
        Optional[Annotated[float, Field(gt=0, allow_inf_nan=False)]],
        Optional[Annotated[float, Field(gt=0, allow_inf_nan=False)]],
        Optional[Annotated[float, Field(gt=0, allow_inf_nan=False)]],
    ]] = Field(None, description="Initial X/Y/Z cell lengths in nm; null axes use calculated sizes.")
    box_mode: Literal["bbox", "rotation"] = Field(
        "rotation",
        description="Cell geometry chosen at solvation. 'rotation' is a cubic cell "
        "that remains safe at every solute orientation; 'bbox' is the smaller "
        "axis-aligned cell and is appropriate only while overall orientation is "
        "restrained or for short relaxation-only work.",
    )
    # Backward-compatible input for saved drafts and older API clients. It no longer
    # controls cell geometry; callers should send box_mode explicitly.
    production_ns_intent: Optional[float] = Field(None, gt=0.0, le=MAX_PRODUCTION_NS)
    minimize_steps: int = Field(4_800, ge=100)
    adaptive_minimization: bool = Field(
        True,
        description="Stop minimization after sustained energy convergence instead of "
        "always running the atom-scaled maximum. The configured minimization steps "
        "remain a hard ceiling; missing convergence data fails safe to the ceiling.",
    )
    declash: Optional[bool] = Field(
        None,
        description="Declash protocol: runs ONLY when explicitly requested (True). None "
        "(the default — every untouched wizard session) is OFF, same as an explicit "
        "False; it does not auto-detect from the design (RE-AUDIT CONCLUDED, "
        "2026-08-19). A design whose junctions insert 2+ extra bases (e.g. 2xT "
        "thymines) or that carries strand extensions is flagged as an advisory "
        "condition on this control instead of auto-applying declash. True forces the "
        "declash minimisation/gentle ladder on; it also blocks the early-stop "
        "accelerator on an Alpine submit, which a declash package refuses.",
    )
    force_soft: bool = Field(
        False,
        description="Run the WHOLE ladder with the soft integrator (rigidBonds none "
        "+ 1 fs), not just the first segment. The instability 'Fix' remedy "
        "sets this for a model that keeps blowing up rigid-bond RATTLE.",
    )
    fast: bool = Field(
        True,
        description="Fast relaxation (DEFAULT): hydrogen-mass repartitioning + 4 fs "
        "timestep + NAMD GPU-resident on the hard ladder (~4x NPT throughput "
        "on a capped box). Auto-disabled for soft/declash ladders. Same "
        "simulated ns per stage (step count halved), wall-clock ~4x shorter. "
        "Set false (or untick in the UI) if a very large design fails the "
        "first hard segment with a GPU out-of-memory error.",
    )
    relax_timestep_fs: Optional[float] = Field(
        None,
        description="RELAXATION LADDER timestep (fs): 4.0, 2.0 or 1.0. None → derived from "
        "`fast` (4.0 on, 2.0 off), which is the historical behaviour and where the "
        "per-stage soft/gentle tiers (1/2 fs) still apply as a ceiling. An EXPLICIT "
        "value here is a pin: honored verbatim on every stage, soft/gentle included, "
        "and returns a warning condition (not a refusal) if that is above the tier's "
        "measured-safe rate. A new production run starts from this resolved "
        "integrator but may override it.",
    )
    relax_rigid_bonds: Optional[str] = Field(
        None,
        description="RELAXATION LADDER bonds-to-hydrogen constraint: 'all' or 'none'. "
        "None → auto from the ladder timestep ('none' at 1 fs, 'all' above). "
        "Independent of the timestep since exp51 measured 1 fs + 'all' stable; "
        "'none' above 1 fs is a measured loss and is warned about, not blocked.",
    )
    relax_hmr: Optional[bool] = Field(
        None,
        description="RELAXATION LADDER hydrogen-mass repartitioning. None → auto (on only "
        "at 4 fs, where exp51 measured it load-bearing: 4 fs on standard masses "
        "fails RATTLE at 16.8 ps). Below 4 fs it is a measured LOSS in energy "
        "conservation, so it is never defaulted on.",
    )
    production_rigid_bonds: Optional[str] = Field(
        None,
        description="PRODUCTION RUN bonds-to-hydrogen constraint: 'all', 'none', or None "
        "for auto from `production_timestep_fs`. Recorded now, applied when "
        "production runs off this package.",
    )
    production_hmr: Optional[bool] = Field(
        None,
        description="PRODUCTION RUN hydrogen-mass repartitioning; None → auto (on only at "
        "4 fs). Recorded now, applied when production runs off this package.",
    )

    @field_validator("relax_timestep_fs")
    @classmethod
    def _sanctioned_relax_timestep(cls, v: Optional[float]) -> Optional[float]:
        if v is None:
            return None
        if float(v) not in (1.0, 2.0, 4.0):
            raise ValueError("relax_timestep_fs must be 1.0, 2.0, or 4.0")
        return float(v)

    @field_validator("relax_rigid_bonds", "production_rigid_bonds")
    @classmethod
    def _sanctioned_rigid_bonds(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s not in ("all", "none"):
            raise ValueError("rigid_bonds must be 'all' or 'none'")
        return s

    gpu_resident: Optional[str] = Field(
        None,
        description="NAMD GPU-resident mode for this run: 'auto' (DEFAULT — decided by "
        "solvated atom count against the measured crossover), 'on' (force it) "
        "or 'off' (force CUDA offload). Resident keeps integration + bonded "
        "forces on the GPU and is a LARGE-system win (3.2x at 3.14M atoms), "
        "but a LOSS below ~100k (both paths hit the same per-step floor and "
        "resident's setup is pure overhead — measured 0.88-0.97x at 32.5k). "
        "'on' is refused for GBIS, which NAMD cannot run in resident mode.",
    )

    @field_validator("gpu_resident")
    @classmethod
    def _sanctioned_gpu_resident(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s not in ("auto", "on", "off"):
            raise ValueError("gpu_resident must be 'auto', 'on', or 'off'")
        return s

    gpu_fallback_policy: Optional[str] = Field(
        None,
        description="What to do if the fastest GPU (resident) mode can't start on this "
        "structure: 'ask' (DEFAULT — pause and ask the user, so an unattended "
        "run stops & notifies rather than silently slowing) or 'auto_offload' "
        "(auto-accept the ~3x slower GPU mode). None → the NADOC_GPU_FALLBACK "
        "env default ('ask'). Stored on the job; the UI remembers it in "
        "localStorage.",
    )
    production_timestep_fs: float = Field(
        4.0,
        description="Integrator timestep (fs) for the PRODUCTION run: 4.0 (fast, HMR + "
        "GPUresident — the default; needs the fast relaxation ladder), 2.0 "
        "(rigidBonds all + GPUresident, no HMR — a manual medium path), or 1.0 "
        "(conservative reference, rigidBonds none). Only these three are allowed; "
        "2.0 is a deliberate manual choice, never auto-selected. See "
        "memory/feedback_namd_4fs_production_only.md.",
    )

    @field_validator("production_timestep_fs")
    @classmethod
    def _sanctioned_production_timestep(cls, v: float) -> float:
        if v not in (1.0, 2.0, 4.0):
            raise ValueError("production_timestep_fs must be 1.0, 2.0, or 4.0")
        return float(v)

    design_source_path: Optional[str] = Field(
        None,
        description="Workspace path of the part used to create this job",
    )
    oxdna_job_id: Optional[str] = Field(
        None,
        description="If set, seed the NAMD run from this completed oxDNA job's "
        "relaxed coordinates (its OWN design.json + latest last_conf) "
        "instead of ideal B-DNA.",
    )
    graphene_nanopore: bool = Field(
        False,
        description="Carry a deposited oxDNA surface into this seeded NAMD job as a "
        "graphene-nanopore build descriptor. Requires an oxDNA surface-deposition seed.",
    )
    two_electrodes: Optional[dict] = None
    graphene_only: bool = Field(
        False,
        description="Build a membrane/electrolyte control with no DNA. Requires "
        "graphene_nanopore; the pore is centered in an XY sheet at z=0.",
    )
    graphene_temperature_K: float = Field(298.15, ge=270, le=350, allow_inf_nan=False)
    graphene_charge_density_C_m2: float = Field(0.0, ge=-0.5, le=0.5, allow_inf_nan=False,
        description="Total fixed sheet charge per projected cell area; screening control only.")
    graphene_pore_diameter_nm: float = Field(
        2.1, ge=0.0, le=100.0,
        description="Diameter of the aligned graphene aperture in nm.",
    )
    graphene_surface_axis: Optional[str] = Field(
        None,
        description="Hard-surface face: -x, +x, -y, +y, -z, or +z. None inherits "
        "an oxDNA deposition plane, or defaults to -y for a fresh design.",
    )
    graphene_surface_offset_nm: float = Field(
        0.0, ge=0.0, le=100.0,
        description="Persistent outward displacement from the selected design face (nm).",
    )

    @field_validator("graphene_surface_axis")
    @classmethod
    def _valid_graphene_surface_axis(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in {"-x", "+x", "-y", "+y", "-z", "+z"}:
            raise ValueError("graphene_surface_axis must be -x, +x, -y, +y, -z, or +z")
        return v
    graphene_layers: int = Field(
        1, ge=1, le=6,
        description="Number of fixed graphene layers; additional layers extend away from DNA.",
    )
    graphene_layer_spacing_nm: float = Field(
        0.335, gt=0.1, le=1.0,
        description="Normal spacing between graphene layers in nm.",
    )
    graphene_atomistic_clearance_nm: float = Field(
        0.32, ge=0.0, le=2.0,
        description="Minimum DNA-heavy-atom to first-layer separation after backmapping (nm).",
    )
    graphene_water_clearance_nm: float = Field(
        0.30, ge=0.0, le=1.0,
        description="Remove water oxygens closer than this distance to a graphene site (nm).",
    )
    graphene_sheet_margin_nm: float = Field(
        1.5, ge=0.5, le=10.0,
        description="Graphene overhang beyond the DNA lateral extent (nm).",
    )
    mrdna_job_id: Optional[str] = Field(
        None,
        description="If set, seed the NAMD run from this completed FINE-stage mrDNA "
        "job's relaxed CG structure (its OWN design.json snapshot) instead "
        "of ideal B-DNA.  Mutually exclusive with oxdna_job_id.",
    )
    blade_job_id: Optional[str] = Field(
        None,
        description="If set, seed the NAMD run from this completed BLADE relax job's "
        "EXACT all-atom relaxed coordinates (its OWN design.json snapshot). "
        "Unlike the oxDNA/mrDNA seeds (reconstructed from a coarse-grained "
        "frame), BLADE is already atomistic, so the exact conformation is fed "
        "straight into solvation via solute_coords=. Forces full-topology "
        "(psfgen, with hydrogens) prep. Mutually exclusive with the others.",
    )
    vacuum_job_id: Optional[str] = Field(
        None,
        description="If set, seed solvation from this completed in-vacuo ENRG-MD "
        "pre-stage (Aksimentiev tutorial §3.2) — the tutorial's §3.3 starts "
        "from the vacuum run's last frame, not the idealised build. Normally "
        "set automatically by the standard preset rather than by hand.",
    )
    skip_vacuum_prestage: bool = Field(
        False,
        description="Skip the in-vacuo shape-relaxation pre-stage. It is on by default "
        "because the published protocol runs it, but it is measurably "
        "counter-productive below ~4 helices (a 2hb's solvation box GREW "
        "6.8%), so the UI asks first on small designs.",
    )
    execution_target: str = Field(
        "local",
        description="'local' runs NAMD as a local subprocess (default); 'alpine' "
        "tags the job for remote SLURM submission (submit via "
        "/md/jobs/{id}/submit-remote once prepared + connected).",
    )
    cluster_name: Optional[str] = Field(
        None,
        description="Cluster profile name for remote execution (default 'alpine').",
    )
    partition: Optional[str] = Field(
        None,
        description="Preferred SLURM partition, chosen in the Job Wizard's first step "
        "while the user could see live availability and wait times. Stored on "
        "the job so that context survives to submission — which can happen in a "
        "later session, long after the queue picture that motivated the choice. "
        "None → auto-pick at submit time.",
    )
    slurm_resources: Optional[dict] = Field(
        None,
        description="SLURM resources adjusted in the Job Wizard's first step alongside the "
        "partition (any of cores/gpus/mem_gb/walltime/qos). SPARSE: send only "
        "what the user actually changed. Anything omitted is re-derived at "
        "submit time from the built package's exact atom count, which is more "
        "accurate than the wizard's pre-solvation estimate.",
    )
    runpod_gpu_key: Optional[str] = Field(
        None,
        description="RunPod GPU type id chosen in the Job Wizard's first step from the ranked "
        "live table. A PREFERENCE, not a demand: the network volume pins the pod's "
        "datacenter, so a single named card frequently comes back 'no instances "
        "currently available'. It heads the priority list; same-value fallbacks "
        "follow. None → rank at launch time.",
    )
    runpod_budget_usd: Optional[float] = Field(
        None,
        gt=0,
        description="Spend cap for this job's pod, in USD. A BUDGET, not a duration — the "
        "kill-switch wall-clock is derived from the rate of the card actually "
        "obtained. Reaching it pauses for explicit user approval; a manual resume "
        "authorizes a fresh cap. "
        "None → the backend default.",
    )
    runpod_volume_id: Optional[str] = Field(
        None,
        description="RunPod network volume to mount. Carries the patched NAMD, the packages "
        "and every checkpoint, and pins the datacenter. None → the connected "
        "session's volume.",
    )
    runpod_estimated_cost_usd: Optional[float] = Field(None, ge=0)
    runpod_quoted_rate_usd_per_hour: Optional[float] = Field(None, ge=0)
    run_dir: Optional[str] = Field(
        None,
        description="Directory to write this run into (archive-from-birth). A NAMD run "
        "produces multi-GB trajectories; pointing it at a roomy volume (e.g. an "
        "external Archive drive) keeps them off a full system disk. The job's "
        "folder is created at <run_dir>/<job_id> and the app resolves it via the "
        "archive index. None → the default workspace location.",
    )
    anchors: Optional[list] = Field(
        None,
        description="Anchor scopes (shared oxDNA/CanDo picker format: overhang / cluster "
        "/ domain / strand / base) to hold immobile via NAMD fixedAtoms for the "
        "whole ladder. Each entry may carry its own `atoms` list to hold only "
        "those PDB atom names (null = all heavy atoms for that anchor); anchors "
        "with no `atoms` key fall back to `anchor_atoms`. A JOB-REQUEST "
        "annotation, never a Design edit; a selection that resolves to nothing "
        "leaves the run unanchored.",
    )
    surface_anchors: Optional[list] = Field(
        None,
        description="Anchor scopes attached to the NAMD hard surface. They are kept "
        "separate for provenance/UI but resolve to the same fixed-atom mechanism at "
        "their deposited coordinates. oxDNA surface anchors are mapped to ordinary "
        "fixed anchors when graphene_nanopore is not requested.",
    )
    anchor_atoms: Optional[list[str]] = Field(
        None,
        description="DEFAULT atom-name filter, for anchors that do not carry their own "
        '`atoms` list. e.g. ["C1\'"] pins one sugar carbon per base instead of '
        "all ~20 heavy atoms. Each entry of `anchors` may override this with its "
        "own `atoms` (null there means all heavy atoms for that anchor, and beats "
        "this default). None = all heavy atoms (hydrogens are never anchored). "
        "Names that match nothing are rejected rather than silently producing an "
        "unanchored run.",
    )
    anchor_k: Optional[float] = Field(
        0.02,
        gt=0.0,
        le=100.0,
        description="GPU-compatible harmonic force constant for DNA anchors during "
        "relaxation (kcal/mol/Å²). The default 0.02 damps global drift/tumbling "
        "without turning the selected atoms into immobile fixedAtoms.",
    )
    field: Optional[dict] = Field(
        None,
        description="Uniform electric field, shared cross-engine descriptor "
        "{'field_pN': <force per NUCLEOTIDE, pN>, 'dir': [x,y,z]} — the same "
        "per-nucleotide load oxDNA/LAMMPS apply per bead and CanDo applies per "
        "duplex node. Emitted as native NAMD eFieldOn/eField (q·E, exact: a DNA "
        "nucleotide carries -1 e). Requires >=1 anchor (an unanchored uniform "
        "force just streams the structure). A JOB-REQUEST annotation, never a "
        "Design edit.",
    )
    relax_preset: str = Field(
        DEFAULT_PRESET,
        description="Named relaxation protocol (backend/core/md_presets.py): "
        "'fast_shape' (vacuum ENRG-MD), 'standard' (Aksimentiev explicit "
        "MgCl2 + ENM ladder, the default), or 'full_physics' (solvent-first "
        "staged release). Supplies DEFAULTS only — any field the caller sets "
        "explicitly wins.",
    )
    early_stop_relax: bool = Field(
        True,
        description="Relaxation accelerator: skip a stage's remaining p50/p100 chunks "
        "once its first chunk shows an energy+WC plateau (multi-criteria, "
        "backend/core/md_cutoff.py). Never skips production/qualification "
        "stages. ON by default; the 'full_physics' preset turns it off, "
        "since a stage you intend to publish should not be truncated.",
    )
    draft: bool = Field(
        False,
        description="Create the job as an unprepared DRAFT (status='draft') instead of "
        "solvating immediately. Valid for native, graphene-only, and seeded jobs. "
        "The deferred build runs on POST /md/jobs/{id}/prepare when the user presses "
        "Run, so topology-changing surface choices are frozen exactly once.",
    )
    stage_overrides: dict = Field(
        default_factory=dict,
        description='Per-stage NAMD directive overrides, keyed by stage INDEX as a string (0 = minimisation, 1..N = the stages in order) plus "*" for every stage: {"*": {"langevinDamping": "2"}, "3": {"run": "50000"}}. "*" is merged first, so a per-stage entry refines it. A null value DELETES the directive. Directives that name the package\'s own files or outputs are refused — overriding one would detach the stage from its job rather than change the physics. Every override is recorded in the manifest and declared in its protocol_fidelity block, because a hand edit is a departure from every protocol by definition.',
    )
    seed_lattice_nm: "float | str | None" = Field(
        None,
        description="Pre-expand the lattice before building the seed, so the run starts "
        "at the interhelical spacing MD says the structure ends up at "
        "instead of spending relaxation swelling into it. null = build as "
        'designed (2.25 nm caDNAno lattice). "auto" = the measured relaxed '
        "spacing for this design's largest extra-base count, applied ONLY if "
        "it inserts extra bases. A float sets the centre-to-centre spacing in "
        "nm directly and skips that gate. Measured on 6hbx100: at TT inserts, "
        "2.25 -> 2.55 nm cuts steric contacts on the inserts by 58% AND "
        "relaxes the crossover bridges; with no inserts there is no slack to "
        "take up and the backbone only stretches. The saved design is never "
        "modified — a scaled copy feeds the seed. Recorded in manifest.json "
        "as seed_lattice_nm.",
    )
    allow_ring_pierced_seed: bool = Field(
        False,
        description="Build even when a covalent bond in the seed is threaded through "
        "a nucleotide ring. Off by default because this permanent defect cannot "
        "relax away and can turn into a severely stretched phosphodiester bond. "
        "Recorded in manifest.json either way.",
    )


class ProductionRequest(BaseModel):
    length_ns: Optional[float] = Field(None, gt=0.0, le=MAX_PRODUCTION_NS)
    steps: Optional[int] = Field(None, ge=100, le=MAX_PRODUCTION_STEPS)
    autostart: bool = Field(True)
    dcd_freq: Optional[int] = Field(
        None,
        ge=100,
        le=1_000_000,
        description="DCD trajectory output interval (steps). Defaults to PRODUCTION_DCD_FREQ "
        "(2500 = every 10 ps at 4 fs). The disk forecast reads this too, so a "
        "raised interval shrinks the predicted trajectory the same way it "
        "shrinks the real one.",
    )
    continue_from_production: bool = Field(False)
    allow_undersized_cell: bool = Field(
        False,
        description="Run even when the package's cell is too small for the solute to "
        "rotate freely. A relaxation package is sized for its short "
        "restrained ladder, so a long UNRESTRAINED run in it can walk the "
        "solute into its own periodic image and quietly corrupt the "
        "trajectory. Off by default; set it only if you know the run is "
        "short enough or the solute is effectively spherical.",
    )
    production_timestep_fs: Optional[float] = Field(
        None,
        description="Integrator timestep (fs) for THIS production run: 1.0, 2.0 or 4.0. "
        "Sending it PINS the choice — if the package cannot honour it the run "
        "fails with FAILURE_TIMESTEP_PINNED rather than quietly substituting a "
        "different one. Omit to inherit the value baked into the package "
        "manifest at prep time, or (absent that) the auto-derived default. "
        "Until this existed the timestep could only be chosen when the package "
        "was PREPARED, so changing the Advanced-card dropdown before starting "
        "production had no effect on the run at all.",
    )

    rigid_bonds: Optional[str] = Field(
        None,
        description="Bonds-to-hydrogen constraint for THIS production run: 'all', 'none', "
        "or omit to inherit the package's prep-time choice (and, failing that, "
        "the auto value for the timestep). Independent of the timestep since "
        "exp51; unsound combinations are warned about, never blocked.",
    )
    hmr: Optional[bool] = Field(
        None,
        description="Hydrogen-mass repartitioning for THIS production run. Omit to inherit "
        "the package's prep-time choice, else auto (on only at 4 fs). The HMR "
        "PSF is built on demand when it is missing.",
    )

    @field_validator("rigid_bonds")
    @classmethod
    def _sanctioned_prod_rigid_bonds(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s not in ("all", "none"):
            raise ValueError("rigid_bonds must be 'all' or 'none'")
        return s

    gpu_resident: Optional[str] = Field(
        None,
        description="GPU-resident mode for THIS production run: 'auto' (size gate), 'on' "
        "or 'off'. Omit to inherit the package's prep-time choice. Production "
        "used to hard-code resident ON for 2/4 fs regardless of size or of the "
        "Advanced-card dropdown.",
    )

    @field_validator("production_timestep_fs")
    @classmethod
    def _sanctioned_production_timestep(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and v not in (1.0, 2.0, 4.0):
            raise ValueError("production_timestep_fs must be 1.0, 2.0, or 4.0")
        return None if v is None else float(v)

    @field_validator("gpu_resident")
    @classmethod
    def _sanctioned_prod_gpu_resident(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip().lower()
        if s not in ("auto", "on", "off"):
            raise ValueError("gpu_resident must be 'auto', 'on', or 'off'")
        return s


class JobSummary(BaseModel):
    job_id: str
    design_name: str
    protocol: str
    status: str
    created_at: float
    n_segments: int
    current_segment_idx: int
    error: Optional[str]
    latest_health: Optional[dict]
