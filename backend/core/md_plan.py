"""md_plan.py — the computed protocol plan behind the Job Wizard.

Every parameter a NAMD relaxation or production run will actually use, listed per stage,
with the difference from the previous stage, the conditions that skip or alter a stage,
and the retry policy the runner applies on a crash.  Pure: no disk, no FastAPI, no
network.  The API layer lives in ``backend/api/routes_md_plan.py``.

**How this stays honest.**  It would be easy — and wrong — to describe the protocol from a
hand-written table.  That table drifts: the memory notes said "12 ladder segments" for
months while the code built 20, and the docs said the ladder barostat was 200/100 fs when
it is 1000/500.  So this module does not describe anything.  It CALLS the real conf
writers (``_segment_conf``, ``_min_conf``, ``build_production_conf``) and parses their
output.  The plan *is* the conf.  A parameter can only appear here if NAMD will really
receive it, and a divergence is impossible by construction rather than by discipline.

Deliberately NOT done: extracting a shared "parameters for this segment" helper that both
the conf writer and this module consume.  ``build_production_conf`` and its callers carry
explicit byte-identical guarantees in their docstrings (the ensemble path depends on
them); routing them through an intermediate dict would put those at risk for no gain.

Two classes of value cannot be known before solvation, and are LABELLED rather than
guessed:

* *deferred* — the cell vectors, which ``namd_solvate`` computes from the solvated system;
  and ``minimize_steps``, which is a floor that scales to one step per 10 atoms.
* *conditional* — ``GPUresident``, gated on the solvated atom count.  Detected generically
  by emitting each stage twice (unknown vs. small atom count) and diffing, so a future
  size-gated directive is picked up without anyone remembering to add it here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional

from backend.core import md_protocols as _p
from backend.core.md_integrator import resident_decision
from backend.core.md_cutoff import CutoffParams
from backend.core.md_protocols import SegmentSpec

# ── What the diff ignores ─────────────────────────────────────────────────────
#: Per-segment bookkeeping — output paths and restart-chain filenames.  These differ on
#: EVERY stage by construction, so leaving them in would bury the physics under noise.
NOISE_KEYS = frozenset(
    {
        "outputname",
        "dcdfile",
        "xstfile",
        "veldcdfile",
        "forcedcdfile",
        "bincoordinates",
        "binvelocities",
        "extendedsystem",
        "coordinates",
        "structure",
    }
)

#: Resolved by ``namd_solvate`` from the solvated system, so a pre-prep plan cannot know
#: them.  Reported as ``deferred`` instead of being shown as zeros.
BOX_KEYS = frozenset(
    {
        "cellbasisvector1",
        "cellbasisvector2",
        "cellbasisvector3",
        "cellorigin",
    }
)

#: Directive ordering for display: the wizard groups rows so an integrator change is not
#: three screens away from the timestep it belongs to.  Anything unlisted falls into
#: "Other" in source order, so a new NAMD directive shows up rather than vanishing.
PARAM_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "Integrator",
        (
            "timestep",
            "rigidbonds",
            "rigidtolerance",
            "nonbondedfreq",
            "fullelectfrequency",
            "stepspercycle",
            "gpuresident",
            "minimize",
            "run",
        ),
    ),
    (
        "Electrostatics & solvent",
        (
            "pme",
            "pmegridspacing",
            "cutoff",
            "switching",
            "switchdist",
            "pairlistdist",
            "exclude",
            "onefourscaling",
            "gbis",
            "alphacutoff",
            "ionconcentration",
            "solventdielectric",
            "wrapall",
            "wrapwater",
        ),
    ),
    (
        "Thermostat & barostat",
        (
            "temperature",
            "langevin",
            "langevintemp",
            "langevindamping",
            "langevinhydrogen",
            "reinitvels",
            "margin",
            "usegrouppressure",
            "useflexiblecell",
            "useconstantarea",
            "langevinpiston",
            "langevinpistontarget",
            "langevinpistonperiod",
            "langevinpistondecay",
            "langevinpistontemp",
        ),
    ),
    (
        "Restraints & fixed atoms",
        (
            "extrabonds",
            "extrabondsfile",
            "constraints",
            "consref",
            "conskfile",
            "conskcol",
            "constraintscaling",
            "fixedatoms",
            "fixedatomsfile",
            "fixedatomscol",
            "efieldon",
            "efield",
            "colvars",
            "colvarsconfig",
        ),
    ),
    (
        "Output cadence",
        (
            "outputenergies",
            "xstfreq",
            "restartfreq",
            "binaryrestart",
            "dcdfreq",
            "veldcdfreq",
            "forcedcdfreq",
        ),
    ),
    (
        "Files & forcefield",
        (
            "paratypecharmm",
            "parameters",
            "seed",
        ),
    ),
)

_GROUP_OF: dict[str, str] = {key: group for group, keys in PARAM_GROUPS for key in keys}


def param_group(key: str) -> str:
    """Display group for a NAMD directive (pure).  Unknown directives group as "Other"."""
    return _GROUP_OF.get(key.lower(), "Other")


# ── Conf parsing ──────────────────────────────────────────────────────────────


def parse_conf_directives(conf_text: str) -> dict:
    """NAMD conf text → ``{directive.lower(): value}`` (pure).

    A directive that legitimately repeats (``parameters``, ``extraBondsFile``) collapses
    to a list, in file order — collapsing it to the last value would hide the ENM file
    behind the Mg extrabonds file, which is the single most important restraint fact in
    the ladder.  Comments and blank lines are dropped; a bare directive with no argument
    (NAMD accepts a few) maps to ``""``.
    """
    out: dict = {}
    for raw in conf_text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split(None, 1)
        key = parts[0].lower()
        value = parts[1].strip() if len(parts) > 1 else ""
        if key in out:
            prev = out[key]
            out[key] = (prev if isinstance(prev, list) else [prev]) + [value]
        else:
            out[key] = value
    return out


@dataclass(frozen=True)
class PlanContext:
    """Everything ``_segment_conf`` needs that is not the segment itself.

    ``box`` defaults to zeros: the plan runs BEFORE solvation, so there is no cell yet.
    The zero vectors are stripped from the emitted parameters (see :data:`BOX_KEYS`) and
    reported as deferred, rather than displayed as a 0 Å box.
    """

    name_stem: str = "design"
    box: tuple[float, float, float] = (0.0, 0.0, 0.0)
    mgh_extrabonds: bool = True
    fast: bool = False
    carved: bool = False
    fill_fraction: float = 1.0
    structure_psf: Optional[str] = None
    #: The two axes the timestep used to imply.  None = follow the segment's own tier, so
    #: an untouched plan is byte-identical to what it emitted before they existed.
    rigid_bonds: Optional[str] = None
    hmr: Optional[bool] = None
    #: The ladder's base timestep, so the preview's tiers CAP it rather than replace it.
    base_timestep_fs: Optional[float] = None
    anchors_file: Optional[str] = None
    field: Optional[dict] = None
    gbis: bool = False
    vacuum: bool = False
    colvars_file: Optional[str] = None
    capture_vel_force: bool = False
    n_atoms: Optional[int] = None
    force_resident: Optional[bool] = None
    minimize_steps: int = _p.MIN_STEPS_FLOOR
    no_enm: bool = False
    enm_file: Optional[str] = None
    min_scale: float = 0.5
    seed: int = 54321


def _strip(params: dict) -> dict:
    """Drop the pre-solvation-meaningless cell block."""
    return {k: v for k, v in params.items() if k not in BOX_KEYS}


def stage_parameters(
    spec: SegmentSpec, ctx: PlanContext, overrides: Optional[dict] = None
) -> dict:
    """Every directive ``_segment_conf`` would write for this segment (pure)."""
    return _strip(
        parse_conf_directives(
            _p._segment_conf(
                spec,
                ctx.name_stem,
                ctx.box,
                ctx.mgh_extrabonds,
                fast=ctx.fast,
                carved=ctx.carved,
                fill_fraction=ctx.fill_fraction,
                structure_psf=ctx.structure_psf,
                colvars_file=ctx.colvars_file,
                rigid_bonds=ctx.rigid_bonds,
                hmr=ctx.hmr,
                base_timestep_fs=ctx.base_timestep_fs,
                anchors_file=ctx.anchors_file,
                field=ctx.field,
                gbis=ctx.gbis,
                vacuum=ctx.vacuum,
                capture_vel_force=ctx.capture_vel_force,
                n_atoms=ctx.n_atoms,
                force_resident=ctx.force_resident,
                overrides=overrides,
            )
        )
    )


def minimization_parameters(
    min_name: str, ctx: PlanContext, overrides: Optional[dict] = None
) -> dict:
    """Every directive ``_min_conf`` would write for the minimisation step (pure)."""
    return _strip(
        parse_conf_directives(
            _p._min_conf(
                min_name,
                ctx.name_stem,
                ctx.box,
                ctx.mgh_extrabonds,
                ctx.minimize_steps,
                ctx.min_scale,
                enm_file=ctx.enm_file,
                no_enm=ctx.no_enm,
                anchors_file=ctx.anchors_file,
                field=ctx.field,
                gbis=ctx.gbis,
                vacuum=ctx.vacuum,
                overrides=overrides,
            )
        )
    )


def production_parameters(
    spec: SegmentSpec,
    ctx: PlanContext,
    *,
    timestep_fs: Optional[float] = None,
    start_checkpoint: Optional[str] = None,
    npt: bool = True,
    damping: float = _p.PRODUCTION_LANGEVIN_DAMPING,
    enm_file: Optional[str] = None,
    overrides: Optional[dict] = None,
) -> dict:
    """Every directive ``build_production_conf`` would write (pure)."""
    return _strip(
        parse_conf_directives(
            _p.build_production_conf(
                spec,
                ctx.name_stem,
                ctx.box,
                ctx.mgh_extrabonds,
                seed=ctx.seed,
                fast=ctx.fast,
                timestep_fs=timestep_fs,
                structure_psf=ctx.structure_psf,
                start_checkpoint=start_checkpoint,
                rigid_bonds=ctx.rigid_bonds,
                hmr=ctx.hmr,
                anchors_file=ctx.anchors_file,
                field=ctx.field,
                colvars_file=ctx.colvars_file,
                n_atoms=ctx.n_atoms,
                force_resident=ctx.force_resident,
                npt=npt,
                damping=damping,
                enm_file=enm_file,
                overrides=overrides,
            )
        )
    )


def reseed_parameters(
    reseed_name: str,
    ctx: PlanContext,
    *,
    npt: bool = True,
    preserve_velocities: bool = False,
) -> dict:
    """Every directive ``build_reseed_conf`` would write for the bridge stage (pure).

    The velocity reseed is a real conf the production child executes — a zero-step run
    that re-draws velocities from this run's own seed (or, for a true continuation,
    carries the parent's forward).  It was invisible in the plan, which meant the wizard
    showed the production run starting from a checkpoint it does not actually read.
    """
    return _strip(
        parse_conf_directives(
            _p.build_reseed_conf(
                reseed_name,
                ctx.name_stem,
                ctx.box,
                ctx.mgh_extrabonds,
                seed=ctx.seed,
                equil_base="equilibrated",
                structure_psf=ctx.structure_psf,
                preserve_velocities=preserve_velocities,
                npt=npt,
            )
        )
    )


def conditional_keys(spec: SegmentSpec, ctx: PlanContext, *, emit=None) -> dict:
    """Directives whose presence/value depends on the solvated atom count (pure).

    Emitted twice — "atom count unknown" and "atom count below every size gate" — and
    diffed.  Generic on purpose: today this finds ``GPUresident`` and nothing else, but a
    future size-gated directive is caught without anyone having to remember this file.
    Returns ``{key: reason}``; a key absent from one variant reads as ``"(absent)"``.

    Skipped entirely when the caller already knows the atom count, or has forced the
    resident mode by hand — then the value is a fact, not a condition.

    ``emit`` selects which conf writer to probe, so the production column gets the same
    treatment through ``build_production_conf`` rather than the ladder's writer.
    """
    if ctx.n_atoms is not None or ctx.force_resident is not None:
        return {}
    emit = emit or stage_parameters
    unknown = emit(spec, ctx)
    tiny = emit(spec, replace(ctx, n_atoms=0))
    reason = (
        f"depends on the solvated atom count, which solvation decides: GPU-resident mode "
        f"needs at least {_p._RESIDENT_MIN_ATOMS:,} atoms to be a measured win, and a "
        f"water-shell carve must fill at least {_p._RESIDENT_MIN_FILL:.0%} of its cell. "
        f"A one-cycle probe re-checks it on the real structure before the first fast "
        f"segment, and can still fall back."
    )
    return {
        k: reason
        for k in set(unknown) | set(tiny)
        if unknown.get(k, "(absent)") != tiny.get(k, "(absent)")
    }


# ── Diffing ───────────────────────────────────────────────────────────────────


def stage_diff(prev: Optional[dict], nxt: dict, *, ignore=NOISE_KEYS) -> dict:
    """``{directive: [old, new]}`` for everything that changed (pure).

    A directive present in only one of the two reads as ``"(absent)"`` on the other side —
    an ENM file appearing or the barostat block vanishing is exactly the kind of
    difference the wizard exists to show, and dropping it would be the worst possible
    omission.  ``prev=None`` (the first stage) yields ``{}``: nothing to differ from.
    """
    if prev is None:
        return {}
    keys = (set(prev) | set(nxt)) - set(ignore)
    out = {}
    for key in sorted(keys):
        old, new = prev.get(key, "(absent)"), nxt.get(key, "(absent)")
        if old != new:
            out[key] = [old, new]
    return out


#: The six directives where the relaxation ladder and the production run silently
#: disagree.  Each is a deliberate choice with a reason, but none of them was visible
#: anywhere before the wizard — a production run is NOT "the last ladder stage without
#: restraints", and that difference belongs on screen next to the two columns.
_ASYMMETRY_NOTES: dict[str, str] = {
    "fullelectfrequency": (
        "The ladder runs PME every other step at 2 fs (the tutorial's literal value); "
        "production evaluates it every step, because at 4 fs the literal 2 would put PME "
        "on an 8 fs interval, past the r-RESPA resonance limit. The PME INTERVAL is what "
        "matches the reference, not the number."
    ),
    "stepspercycle": (
        "Longer pairlist-rebuild cycle in the ladder (20) than in production (10)."
    ),
    "pairlistdist": (
        "The ladder carries 3.5 Å of pairlist buffer over the cutoff to survive its "
        "longer stepspercycle; production uses the tutorial's 12 Å."
    ),
    "langevinpistonperiod": (
        "The ladder uses the tutorial's soft 1000 fs piston; production runs a stiffer "
        "200 fs one. This is a NADOC choice, not the reference."
    ),
    "langevinpistondecay": (
        "Ladder 500 fs vs production 100 fs — the same stiffer-piston choice."
    ),
    "extrabondsfile": (
        "The elastic network is gone in production. The ladder's restraint ladder exists "
        "to hand over equilibrated coordinates; production is unrestrained (the Mg(H2O)6 "
        "extrabonds stay, because they hold the magnesium hydration shell together)."
    ),
}


def production_asymmetries(last_stage: dict, production: dict) -> list[dict]:
    """The known ladder-vs-production differences, annotated (pure).

    Only reports an entry when the two columns actually differ, so a future change that
    aligns them makes the row disappear instead of lying about it.
    """
    out = []
    for key, note in _ASYMMETRY_NOTES.items():
        old, new = last_stage.get(key, "(absent)"), production.get(key, "(absent)")
        if old != new:
            out.append({"key": key, "relaxation": old, "production": new, "note": note})
    return out


# ── Production segment construction (shared with the real path) ───────────────

#: How a production run is split into chunks.  Not a physics choice — it exists so a long
#: run has health checkpoints and can be resumed part-way.
PRODUCTION_CHUNKS: tuple[tuple[float, float], ...] = (
    (10.0, 0.10),
    (50.0, 0.40),
    (100.0, 0.50),
)

_PRODUCTION_TIER_LABEL = {4.0: "fast", 2.0: "medium", 1.0: "conservative"}


def production_stage_label(timestep_fs: float) -> str:
    """Human name for the integrator tier a production timestep selects (pure)."""
    return _PRODUCTION_TIER_LABEL.get(float(timestep_fs), "conservative")


def production_length_ns(total_steps: int, timestep_fs: float) -> float:
    """Simulated nanoseconds for a step count at a timestep (pure)."""
    return total_steps * timestep_fs / 1_000_000.0


def production_segment_spec(
    name_stem: str,
    *,
    stage_idx: int,
    pct: float,
    frac: float,
    total_steps: int,
    timestep_fs: float,
    previous: str,
    damping: float = _p.PRODUCTION_LANGEVIN_DAMPING,
    dcd_freq: Optional[int] = None,
) -> SegmentSpec:
    """One production chunk's SegmentSpec (pure).

    Shared by ``routes_md._append_production_segments`` (the path that really runs) and
    the wizard's plan, so the two cannot describe different runs.  Building the spec in
    two places is exactly the shape of LESSONS H16: a fix lands on one call site, the
    other keeps the old behaviour, and nothing catches it because both look right.
    """
    length_ns = production_length_ns(total_steps, timestep_fs)
    label_ns = f"{length_ns:g}".replace(".", "p")
    return SegmentSpec(
        name=f"{name_stem}_{stage_idx:02d}_production_{label_ns}ns_k0_p{int(pct)}",
        stage=f"{length_ns:g} ns {production_stage_label(timestep_fs)} production run",
        percent=pct,
        steps=max(100, int(round(total_steps * frac))),
        temp=300.0,
        # Defaults to the LITERATURE PRODUCTION coupling, not the ladder's equilibration
        # value — see md_protocols.PRODUCTION_LANGEVIN_DAMPING. Metadata for the manifest;
        # build_production_conf carries the same number into the conf.
        damping=damping,
        scale=None,
        npt=True,
        previous=previous,
        reinit=False,
        # The user's trajectory interval when they set one.  This used to be hardcoded to
        # PRODUCTION_DCD_FREQ while `ProductionRequest.dcd_freq` was validated, documented
        # AND used by the disk forecast — so the forecast and the run disagreed by exactly
        # the ratio the user had chosen.
        dcd_freq=int(dcd_freq) if dcd_freq else _p.PRODUCTION_DCD_FREQ,
        min_c1_paired=0.90,
        # Deliberately looser than the ladder's: an unrestrained run is EXPECTED to lose
        # some base pairing, and gating it at the ladder's threshold would flag every
        # healthy production run.
        min_wc_ref_relative=0.25,
    )


# ── The stage table ───────────────────────────────────────────────────────────


def _role_for(spec: SegmentSpec) -> str:
    # The settle stage is the one that holds the solute still while the barostat finds the
    # box size.  It is identified by its restraint reference — it used to hold the solute
    # with ``fixedAtoms``, which NAMD refuses under GPU-resident and warns against under
    # constant pressure.  ``fixed_atoms_file`` is still honoured so any future hard-pinned
    # stage classifies the same way.
    if spec.restraint_ref_file or spec.fixed_atoms_file:
        return "settle"
    if "production" in spec.name.lower():
        return "production"
    return "ladder"


def _stage_row(
    index: int,
    name: str,
    stage: str,
    role: str,
    *,
    steps: int,
    timestep_fs: float,
    params: dict,
    prev_params: Optional[dict],
    conditional: dict,
    spec: Optional[SegmentSpec] = None,
    protocol_params: Optional[dict] = None,
    accepts_overrides: bool = True,
) -> dict:
    return {
        "index": index,
        # Whether a hand edit on THIS stage reaches the conf that runs.  Every ladder and
        # production stage does; the production child's velocity-reseed bridge does not —
        # ``build_replica_package`` writes it without an overrides pass — so the table
        # renders it read-only rather than accepting an edit that would be dropped.
        "accepts_overrides": accepts_overrides,
        "name": name,
        "stage": stage,
        "role": role,
        "steps": steps,
        "timestep_fs": timestep_fs,
        # The number that matters and that nothing displayed before: simulated time is
        # steps x the timestep the segment ACTUALLY runs at, which is not always the
        # timestep the step count was sized for (see the declash note in the wizard).
        "ns": round(steps * timestep_fs / 1_000_000.0, 6),
        "percent": getattr(spec, "percent", 100.0),
        "scale": getattr(spec, "scale", None),
        "previous": getattr(spec, "previous", ""),
        "soft": bool(getattr(spec, "soft", False)),
        "gentle": bool(getattr(spec, "gentle", False)),
        "fixed_atoms_file": getattr(spec, "fixed_atoms_file", None),
        "restraint_ref_file": getattr(spec, "restraint_ref_file", None),
        "min_c1_paired": getattr(spec, "min_c1_paired", None),
        "min_wc_ref_relative": getattr(spec, "min_wc_ref_relative", None),
        "params": params,
        "diff_vs_previous": stage_diff(prev_params, params),
        "conditional_params": conditional,
        # {directive: protocol_value} for every directive a hand edit moved. Two DIFFERENT
        # highlights matter in the stage table and they answer different questions:
        # `diff_vs_previous` is "what changes as the ladder advances", and this is "where
        # have I departed from the protocol I picked" — which is the one a reviewer asks.
        "overridden": stage_diff(protocol_params, params) if protocol_params else {},
    }


def relaxation_stages(
    ctx: PlanContext,
    *,
    soft: bool = False,
    gentle: bool = False,
    nvt_only: bool = False,
    timestep_fs: Optional[float] = None,
    stage_overrides: Optional[dict] = None,
) -> list[dict]:
    """The full ordered stage table for a relaxation, minimisation included (pure).

    The ladder itself comes from ``mgh_slow_release_segments`` — the same call
    ``prepare_mgh_slow_release`` makes — so the stage COUNT is never a literal here.  A
    change to ``LADDER_CHUNK_PCTS`` or to the settle stage shows up in the wizard with no
    edit to this file.
    """
    # The caller's explicit ladder timestep wins; otherwise the historical fast-derived
    # 4/2 fs. The step counts are sized from THIS, so a 1 fs ladder reports the step count
    # it will really run rather than a 4 fs one's.
    ladder_dt = (
        float(timestep_fs) if timestep_fs is not None else (4.0 if ctx.fast else 2.0)
    )
    min_name, segments = _p.mgh_slow_release_segments(
        ctx.name_stem,
        soft=soft,
        gentle=gentle,
        nvt_only=nvt_only,
        timestep_fs=ladder_dt,
    )

    rows: list[dict] = []
    # Emitted TWICE for any stage the user has edited: once as the protocol writes it and
    # once with the edits on top. Diffing the two is what makes "you have departed from
    # this protocol here" a computed fact rather than a claim.
    min_ov = _p.overrides_for_stage(stage_overrides, 0)
    min_params = minimization_parameters(min_name, ctx, min_ov)
    rows.append(
        _stage_row(
            0,
            min_name,
            "Energy minimisation",
            "minimization",
            steps=ctx.minimize_steps,
            timestep_fs=0.0,
            params=min_params,
            prev_params=None,
            conditional={},
            protocol_params=minimization_parameters(min_name, ctx) if min_ov else None,
        )
    )

    prev_params = min_params
    for i, spec in enumerate(segments, start=1):
        ov = _p.overrides_for_stage(stage_overrides, i)
        params = stage_parameters(spec, ctx, ov)
        rows.append(
            _stage_row(
                i,
                spec.name,
                spec.stage,
                _role_for(spec),
                steps=spec.steps,
                # SAME call the conf writer makes, base included — this used to omit the base
                # and so reported 2 fs (and therefore double the ns) for a ladder whose confs
                # said 1 fs.  The "one source of truth" the docstring promises only holds if
                # both callers pass the same arguments.
                timestep_fs=_p.effective_timestep_fs(
                    spec, ctx.fast and not ctx.gbis and not ctx.vacuum, ladder_dt
                ),
                params=params,
                prev_params=prev_params,
                conditional=conditional_keys(spec, ctx),
                spec=spec,
                protocol_params=stage_parameters(spec, ctx) if ov else None,
            )
        )
        prev_params = params
    return rows


def production_stages(
    ctx: PlanContext,
    *,
    total_steps: int,
    timestep_fs: float,
    stage_idx: int = 1,
    previous: str = "equilibrated",
    npt: bool = True,
    damping: float = _p.PRODUCTION_LANGEVIN_DAMPING,
    enm_file: Optional[str] = None,
    stage_overrides: Optional[dict] = None,
) -> list[dict]:
    """The production chunk table (pure)."""

    def _emit(spec, c, ov=None):
        return production_parameters(
            spec,
            c,
            timestep_fs=timestep_fs,
            npt=npt,
            damping=damping,
            enm_file=enm_file,
            overrides=ov,
        )

    rows: list[dict] = []
    prev_params: Optional[dict] = None
    prev_name = previous
    for i, (pct, frac) in enumerate(PRODUCTION_CHUNKS):
        spec = production_segment_spec(
            ctx.name_stem,
            stage_idx=stage_idx,
            pct=pct,
            frac=frac,
            total_steps=total_steps,
            timestep_fs=timestep_fs,
            previous=prev_name,
            damping=damping,
        )
        ov = _p.overrides_for_stage(stage_overrides, i + 1)
        params = _emit(spec, ctx, ov)
        rows.append(
            _stage_row(
                i,
                spec.name,
                spec.stage,
                "production",
                steps=spec.steps,
                timestep_fs=timestep_fs,
                params=params,
                prev_params=prev_params,
                conditional=conditional_keys(spec, ctx, emit=_emit),
                spec=spec,
                protocol_params=_emit(spec, ctx) if ov else None,
            )
        )
        prev_params, prev_name = params, spec.name
    return rows


def replica_production_spec(
    ctx: PlanContext,
    *,
    total_steps: int,
    timestep_fs: float,
    previous: str,
    damping: float = _p.PRODUCTION_LANGEVIN_DAMPING,
    dcd_freq: Optional[int] = None,
) -> SegmentSpec:
    """The ONE production segment a production CHILD job runs (pure).

    Mirrors ``md_ensemble.build_replica_package`` line for line — the child package is a
    velocity reseed followed by a single unchunked production run, not the append route's
    10/40/50 % chunk ladder.  Two independent constructions is the shape of LESSONS H16,
    so the numbers here come from the same arithmetic the builder uses.
    """
    steps = max(100, int(total_steps))
    length_ns = production_length_ns(steps, timestep_fs)
    label_ns = f"{length_ns:g}".replace(".", "p")
    return SegmentSpec(
        name=f"{ctx.name_stem}_01_production_{label_ns}ns_k0",
        stage=f"{length_ns:g} ns production replica",
        percent=100.0,
        steps=steps,
        temp=300.0,
        damping=damping,
        scale=None,
        npt=True,
        previous=previous,
        reinit=False,
        dcd_freq=int(dcd_freq or _p.PRODUCTION_DCD_FREQ),
        min_c1_paired=0.90,
        min_wc_ref_relative=0.25,
    )


def replica_production_stages(
    ctx: PlanContext,
    *,
    total_steps: int,
    timestep_fs: float,
    npt: bool = True,
    damping: float = _p.PRODUCTION_LANGEVIN_DAMPING,
    enm_file: Optional[str] = None,
    dcd_freq: Optional[int] = None,
    continuation: bool = False,
    stage_overrides: Optional[dict] = None,
) -> list[dict]:
    """The stage table a production CHILD really runs: reseed bridge, then production.

    ``production_stages`` above describes the OTHER production path — the legacy route
    that appends chunked segments onto the parent job.  The wizard's Create button goes to
    ``POST /md/jobs/{parent}/production-run``, which builds a replica package, and that
    package has exactly two confs.  Showing three chunks there was a table of a run the
    user was not about to start, with a first column carrying 10 % of the step count.

    The override indices match the builder's: the reseed takes none (it runs zero steps
    and ``build_replica_package`` writes it without an overrides pass), and the production
    stage is slot ``1``.
    """
    reseed_name = f"{ctx.name_stem}_00_reseed"
    reseed_params = reseed_parameters(
        reseed_name, ctx, npt=npt, preserve_velocities=continuation
    )
    rows = [
        _stage_row(
            0,
            reseed_name,
            "Velocity continuation" if continuation else "Velocity reseed",
            "reseed",
            steps=0,
            timestep_fs=timestep_fs,
            params=reseed_params,
            prev_params=None,
            conditional={},
            accepts_overrides=False,
        )
    ]

    spec = replica_production_spec(
        ctx,
        total_steps=total_steps,
        timestep_fs=timestep_fs,
        previous=reseed_name,
        damping=damping,
        dcd_freq=dcd_freq,
    )

    def _emit(s, c, ov=None):
        return production_parameters(
            s,
            c,
            timestep_fs=timestep_fs,
            npt=npt,
            damping=damping,
            enm_file=enm_file,
            overrides=ov,
        )

    ov = _p.overrides_for_stage(stage_overrides, 1)
    params = _emit(spec, ctx, ov)
    rows.append(
        _stage_row(
            1,
            spec.name,
            spec.stage,
            "production",
            steps=spec.steps,
            timestep_fs=timestep_fs,
            params=params,
            prev_params=reseed_params,
            conditional=conditional_keys(spec, ctx, emit=_emit),
            spec=spec,
            protocol_params=_emit(spec, ctx) if ov else None,
        )
    )
    return rows


# ── Conditions, retries, deferred values ──────────────────────────────────────


def protocol_conditions(
    *,
    carved: bool,
    gbis: bool,
    force_soft: bool,
    gentle_ladder: bool,
    early_stop: bool,
    gpu_resident_mode: str,
    stages: list[dict],
    n_atoms: Optional[int] = None,
    fill_fraction: float = 1.0,
) -> list[dict]:
    """Everything that can skip, alter or repeat a stage (pure).

    Every number here is IMPORTED from the module that enforces it.  Retyping a threshold
    is how a UI ends up confidently displaying a limit the code stopped using.
    """
    cut = CutoffParams()
    out: list[dict] = []
    settle = next((s for s in stages if s["role"] == "settle"), None)
    first_gentle = next(
        (s for s in stages if s.get("gentle") and s["role"] != "settle"), None
    )

    if carved:
        out.append(
            {
                "id": "settle_skipped",
                "kind": "skip",
                "title": "The settle stage is not run",
                "detail": (
                    f"A water-shell carve leaves vacuum in the corners of the cell, so the "
                    f"whole ladder runs at constant volume. The {_p.SETTLE_STAGE_PS:g} ps "
                    f"fixed-DNA settle stage exists to let the barostat find the right box "
                    f"size before the structure starts moving — with no barostat there is "
                    f"nothing for it to settle, so it is skipped."
                ),
                "applies_to": [],
                "source": "md_protocols.mgh_slow_release_segments",
            }
        )
        out.append(
            {
                "id": "barostat_off",
                "kind": "forced",
                "title": "Constant volume (barostat off) for every stage",
                "detail": (
                    "Required, not merely allowed: a barostat would expel the vacuum from a "
                    "carved cell, collapsing it onto the solute until the DNA meets its own "
                    "periodic image. The box-size equilibration criterion is unavailable for "
                    "this run as a result."
                ),
                "applies_to": [s["name"] for s in stages if s["role"] == "ladder"],
                "source": "md_protocols._pressure_block",
            }
        )
    elif settle is not None:
        out.append(
            {
                "id": "settle_stage",
                "kind": "stage",
                "title": f"{_p.SETTLE_STAGE_PS:g} ps settle stage with every DNA atom fixed",
                "detail": (
                    "Solvation deliberately under-fills the box, which is why the cell shrinks "
                    "at all and why the box trace is the reference's equilibration monitor. "
                    "Pinning the solute while the cell finds its own size separates 'the water "
                    "is settling' from 'the structure is moving', so the ladder starts from a "
                    "box that already holds the right amount of water. It is not numbered, so "
                    "stages 01-04 mean the same thing whether or not it ran."
                ),
                "applies_to": [settle["name"]],
                "source": "Aksimentiev tutorial Note 4",
            }
        )

    if force_soft:
        out.append(
            {
                "id": "force_soft",
                "kind": "forced",
                "title": "Every stage runs the 1 fs flexible-bond integrator",
                "detail": (
                    "The whole ladder is pinned to rigidBonds none + 1 fs. This is the manual "
                    "escape hatch for a model that keeps failing rigid-bond RATTLE; it roughly "
                    "doubles the wall clock versus the 2 fs gentle tier."
                ),
                "applies_to": "all",
                "source": "CreateJobRequest.force_soft",
            }
        )
    elif gentle_ladder:
        out.append(
            {
                "id": "declash_gentle",
                "kind": "forced",
                "title": "Every stage runs the 2 fs gentle tier (declash)",
                "detail": (
                    "This design inserts two or more extra bases at one junction, carries "
                    "single-stranded extensions, or explicitly requested declash. A 1xT "
                    "junction alone does not select this tier. A 25 ps probe measured that 2 fs "
                    "with rigid bonds survives the longer inserted runs while 4 fs + "
                    "hydrogen-mass repartitioning can blow up, so the ladder uses the gentle "
                    "tier. A validated pre-relaxed seed suppresses the extra-base automatic "
                    "trigger."
                ),
                "applies_to": "all",
                "source": "md_protocols.prepare_mgh_slow_release",
            }
        )
    elif first_gentle is not None:
        out.append(
            {
                "id": "soft_start",
                "kind": "forced",
                "title": f"First moving stage runs at 2 fs: {first_gentle['name']}",
                "detail": (
                    "A freshly built ideal-B-DNA model usually has one residual local strain "
                    "that the restrained minimisation cannot relieve, and hitting it with the "
                    "full timestep on the very first dynamics steps trips a RATTLE constraint "
                    "failure. Only this one segment is slowed; every later stage reverts. It "
                    "lands on the first stage whose solute atoms actually MOVE, which is why "
                    "it is not the settle stage."
                ),
                "applies_to": [first_gentle["name"]],
                "source": "md_protocols.mgh_slow_release_segments",
            }
        )

    # GPU-resident, decided by the SAME function the confs use, so the reason shown here
    # is the reason the run will actually have.  The timestep is not one of its inputs
    # (exp52): production used to drop resident at 1 fs, discarding the user's own choice.
    mode = (gpu_resident_mode or "auto").lower()
    decision = resident_decision(
        n_atoms=n_atoms,
        force_resident={"on": True, "off": False}.get(mode),
        min_atoms=_p._RESIDENT_MIN_ATOMS,
        gbis=gbis,
        carved_fill=fill_fraction if carved else None,
        min_fill=_p._RESIDENT_MIN_FILL,
    )
    gpu_detail = (
        f"{'ON' if decision.on else 'OFF'} for this run — {decision.reason}. "
        f"GPU-resident changes WHERE integration runs, not what is computed, so it never "
        f"alters the physics; it is decided by system size and hard compatibility only. "
        f"Measured both ways on one system (exp52, 32.7k atoms): accepted and engaged at "
        f"every sanctioned timestep, 1.86-2.06x faster with it on — note that contradicts "
        f"the ~{_p._RESIDENT_MIN_ATOMS:,}-atom crossover on that hardware, so treat the "
        f"crossover as a per-machine default and override it when you have measured yours. "
        f"Two things override any choice because NAMD refuses them outright: implicit "
        f"solvent, and a carved cell below {_p._RESIDENT_MIN_FILL:.0%} fill (resident "
        f"under-counts its GPU exclusion buffers and dies at step 0). "
        f"A one-cycle probe re-checks the real structure before the first fast segment."
    )
    out.append(
        {
            # A user choice that cannot be honoured is a WARNING, not a footnote: it is the
            # one case where the control on screen and the run disagree.
            "id": "gpu_resident_gate",
            "kind": "warning" if decision.overridden else "conditional",
            "title": (
                f"GPU-resident: {mode} requested, {'on' if decision.on else 'off'} in "
                f"this run"
                if decision.overridden
                else f"GPU-resident mode: {mode}"
            ),
            "detail": gpu_detail,
            "applies_to": "all",
            "source": "CreateJobRequest.gpu_resident",
        }
    )

    if early_stop:
        out.append(
            {
                "id": "early_stop",
                "kind": "skip",
                "title": "Settled stages stop early",
                "detail": (
                    f"Once a stage's trajectory is flat in BOTH energy and base pairing, its "
                    f"remaining chunks are skipped and the restart files are carried forward. "
                    f"Both criteria must agree — energy alone plateaus while the structure is "
                    f"still rearranging. Thresholds over a {cut.window}-frame window, minimum "
                    f"{cut.min_frames} frames: potential energy drift < {cut.eps_pot_drift:.2%} "
                    f"and fluctuation < {cut.eps_pot_fluct:.2%}; volume drift < "
                    f"{cut.eps_vol_drift:.2%} and fluctuation < {cut.eps_vol_fluct:.2%}; "
                    f"base-pairing drift < {cut.eps_wc_drift:.2%} and fluctuation < "
                    f"{cut.eps_wc_fluct:.2%}. Never applied to a production stage."
                ),
                "applies_to": [s["name"] for s in stages if s["role"] == "ladder"],
                "source": "md_cutoff.should_early_stop_stage",
            }
        )
    else:
        out.append(
            {
                "id": "early_stop_off",
                "kind": "info",
                "title": "Every stage runs to its full length",
                "detail": (
                    "Early stopping is off, so no chunk is skipped even if the "
                    "trajectory has clearly settled. This is the right setting for a "
                    "run whose numbers are going in a paper."
                ),
                "applies_to": "all",
                "source": "CreateJobRequest.early_stop_relax",
            }
        )
    return out


def retry_policy() -> list[dict]:
    """What the runner does automatically when a stage crashes (pure).

    Bounded, and each bound is imported.  A user watching a job restart itself three times
    should be able to see that this is designed behaviour with a limit, not a loop.
    """
    from backend.core import namd_runner as _r  # noqa: PLC0415 — avoids an import cycle

    return [
        {
            "id": "retry_cell_shrink",
            "title": "Periodic cell became too small",
            "max_attempts": _r.MAX_CELL_SHRINK_RESUMES,
            "detail": (
                f"The barostat compressed the box past NAMD's patch grid. The piston is "
                f"softened {_r.PISTON_SOFTEN_FACTOR:g}x (longer period and decay, capped at "
                f"{_r._PISTON_MAX_PERIOD_FS:,} fs) and the stage resumes from its last "
                f"checkpoint, up to {_r.MAX_CELL_SHRINK_RESUMES} times. This is the "
                f"reference protocol's own Note 4 remedy. If the cell is COLLAPSING rather "
                f"than shrinking — vacuum in the box — it refuses to resume instead, "
                f"because softening the piston cannot fix a box with a hole in it."
            ),
        },
        {
            "id": "retry_host_oom",
            "title": "Ran out of pinned host memory",
            "max_attempts": _r.MAX_HOST_OOM_RESUMES,
            "detail": (
                f"GPU-resident mode pins host RAM, and this machine's pinnable pool is "
                f"small. Host memory is freed and the stage resumes from its checkpoint, "
                f"up to {_r.MAX_HOST_OOM_RESUMES} times."
            ),
        },
        {
            "id": "retry_instability",
            "title": "Rigid-bond constraint failure (atoms moving too fast)",
            "max_attempts": _r.MAX_INSTABILITY_RESUMES,
            "detail": (
                "Once, and only once: the failing stage and every later one drop to the "
                "1 fs flexible-bond integrator with GPU-resident turned off, and the "
                "crashed stage restarts FRESH from the last stable stage endpoint rather "
                "than from its own partial checkpoint. This is the automatic form of the "
                "manual 'run everything soft' setting. A stage that is already soft is not "
                "softened again, which is how the runner knows to stop retrying."
            ),
        },
        {
            "id": "gpu_probe",
            "title": "GPU-resident mode will not start",
            "max_attempts": 1,
            "detail": (
                "A one-cycle probe runs before the first fast segment. If resident mode "
                "cannot start on this structure, every conf is rewritten to the slower "
                "offload path (step counts and output cadences are doubled so the "
                "simulated time and frame count are unchanged). By default the job PAUSES "
                "and asks first, so an unattended run stops and notifies instead of "
                "silently running ~3x slower."
            ),
        },
    ]


def deferred_notes(
    *, minimize_steps: int, n_atoms: Optional[int], padding_nm: float
) -> list[dict]:
    """Values this plan cannot resolve until the system is solvated (pure)."""
    out: list[dict] = [
        {
            "key": "cellBasisVector",
            "title": "Periodic cell size",
            "detail": (
                "Computed during solvation from the solute's bounding box (or its "
                "rotation radius, for a package sized for a long unrestrained run) "
                "plus the padding below."
            ),
        }
    ]
    if n_atoms is None:
        out.append(
            {
                "key": "minimize",
                "title": f"Minimisation steps: at least {minimize_steps:,}",
                "detail": (
                    f"This is a FLOOR, not the value. Minimisation has to scale with the "
                    f"system — a flat count is safe on a small bundle and catastrophic on a "
                    f"large origami, which starts with enormous van der Waals energy "
                    f"concentrated at inserted bases and detonates well into dynamics. After "
                    f"solvation it becomes one step per {_p.MIN_STEPS_PER_ATOMS} atoms, "
                    f"rounded up (a 224,000-atom system would run "
                    f"{_p.minimize_steps_for_atoms(224_000, minimize_steps):,} steps)."
                ),
            }
        )
    out.append(
        {
            "key": "padding_nm",
            "title": f"Padding: {padding_nm:g} nm requested",
            "detail": (
                "Trimmed automatically if the resulting cell would not fit this "
                "machine — a smaller box is preferred over a water-shell carve, "
                "because a carve costs the barostat, and with it the settle stage and "
                "the box-size equilibration criterion."
            ),
        }
    )
    return out
