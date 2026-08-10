"""routes_md_plan.py — ``POST /md/protocol-plan``, the Job Wizard's source of truth.

One endpoint that answers "what will this job actually run?" WITHOUT preparing anything:
no solvation, no disk writes, no job record.  It resolves the request exactly the way
``POST /md/jobs`` will (same preset merge, same forced overrides), then hands the resolved
settings to ``backend/core/md_plan.py``, which builds the stage table by calling the real
NAMD conf writers and parsing what they emit.

The point of the separation: this file knows about HTTP, presets and existing jobs;
``md_plan`` knows about NAMD and nothing else.  Neither one contains a hand-written table
of protocol parameters, which is the failure mode the wizard exists to end.

Lives outside ``routes_md.py`` on purpose — that module is already past 4,500 lines and is
an active carve-up target.
"""

from __future__ import annotations

import json
from dataclasses import replace
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import Field

from backend.api import state as design_state
from backend.api.routes_md import (
    CreateJobRequest,
    ProductionRequest,
    production_fast_plan,
    production_seed_checkpoint,
    resolve_relax_preset,
)
from backend.core import md_plan
from backend.core import md_presets
from backend.core import md_protocols as _p
from backend.core.md_integrator import integrator_warnings, resolve_integrator
from backend.core.md_job import MdJob, MdStatus

router = APIRouter()

#: Fields whose value the SERVER decides, whatever the caller sends.  Listed here so the
#: wizard can grey them out and say why, instead of offering a control that silently does
#: nothing — which is how a job ended up promising explicit MgCl2 and running with none.
_FORCED_BY_SALT_MODE = ("ion_conc_mM", "mg_conc_mM")

#: What screening mode pins them to (mirrors routes_md's own override at prep time).
_SCREENING_VALUES = {"ion_conc_mM": 0.0, "mg_conc_mM": 12.5}

#: The run length a production plan assumes when the caller has not chosen one.
#: ``ProductionRequest.length_ns`` falls back to 1 ns, which is a sane API default and a
#: useless one for a form: the wizard would preview a 1 ns run while its own control read
#: 100.  Stated here, returned in ``defaults``, and used by the wizard as the value it
#: shows — so the preview and the control can never disagree, and an untouched length
#: honestly reports itself as a default rather than as the user's choice.
WIZARD_DEFAULT_PRODUCTION_NS = 100.0


class ProtocolPlanRequest(CreateJobRequest):
    """A job request, plus what the plan needs that a job request does not carry.

    Subclasses ``CreateJobRequest`` so ``model_fields_set`` — which is how provenance is
    computed — means exactly what it means on the real create path.
    """

    kind: str = Field("relaxation", description="'relaxation' or 'production'")
    parent_job_id: Optional[str] = Field(
        None, description="Production only: the relaxation job to seed from."
    )
    length_ns: Optional[float] = Field(
        None, gt=0.0, description="Production run length."
    )
    steps: Optional[int] = Field(None, ge=100, description="Production step count.")
    dcd_freq: Optional[int] = Field(
        None, ge=100, description="Production DCD interval."
    )
    allow_undersized_cell: bool = Field(
        False,
        description="Production only: proceed despite a cell too small to let the "
        "structure rotate freely.",
    )
    enm_restraints: str = Field(
        "auto",
        description="Production only: keep an elastic network through the run "
        "('auto' | 'on' | 'off').",
    )
    orientation_restraint: bool = Field(
        False, description="Production only: restrain overall DNA orientation."
    )
    orientation_force_constant: float = Field(
        500.0, gt=0.0, le=100000.0,
        description="Quaternion harmonic force constant in kcal/mol."
    )
    langevin_damping: Optional[float] = Field(
        None, gt=0.0, description="Production only: Langevin coupling, ps^-1."
    )
    seed: Optional[int] = Field(
        None,
        ge=1,
        description="Production only: pin the NAMD velocity seed to reproduce a past run. "
        "Omit and one is drawn when the job is created.",
    )
    stage_overrides: dict = Field(
        default_factory=dict,
        description="Per-stage NAMD directive overrides, keyed by stage index (and '*'). "
        "Applied to the emitted confs, so the stage table shows the run as "
        "edited and marks every cell that departs from the protocol.",
    )
    n_atoms_hint: Optional[int] = Field(
        None,
        ge=1,
        description="Solvated atom count, when the caller already knows it (an existing "
        "package, or a disk estimate). Resolves the values this plan would "
        "otherwise have to report as deferred.",
    )


#: Which KIND OF RUN each request field governs.  The wizard groups its controls by this,
#: because "does this setting affect the ladder or the production run?" was unanswerable
#: from the flat list — `production_timestep_fs` sat between two relaxation settings and
#: looked like it changed the ladder.  Anything unlisted is "both" (or neither, e.g.
#: bookkeeping), which is the safe default: it stays in the shared group.
FIELD_SCOPE: dict[str, str] = {
    # The relaxation ladder only.
    "relax_preset": "relaxation",
    "relax_timestep_fs": "relaxation",
    "relax_rigid_bonds": "relaxation",
    "relax_hmr": "relaxation",
    "fast": "relaxation",
    "force_soft": "relaxation",
    "declash": "relaxation",
    "early_stop_relax": "relaxation",
    "early_stop_tier": "relaxation",
    "allow_catenated_seed": "relaxation",
    "minimize_steps": "relaxation",
    "protocol": "relaxation",
    # Everything else — solvation, chemistry, hardware — is shared by both, because the
    # cell and the PSF a relaxation builds are the ones production inherits verbatim.
}


def _integrator_conditions(resolved: CreateJobRequest) -> list[dict]:
    """Every measured objection to the relaxation integrator combination.

    The ladder's base timestep still falls back to `fast` when the caller has not chosen
    one, so this reports on what the confs will actually carry rather than on the raw
    request.  Warnings only — see md_integrator.
    """
    ladder_dt = (
        float(resolved.relax_timestep_fs)
        if resolved.relax_timestep_fs is not None
        else (4.0 if resolved.fast else 2.0)
    )
    if resolved.force_soft:
        ladder_dt = 1.0
    return integrator_warnings(
        resolve_integrator(ladder_dt, resolved.relax_rigid_bonds, resolved.relax_hmr),
        scope="relaxation",
    )


def _provenance(body: ProtocolPlanRequest, resolved: CreateJobRequest) -> dict:
    """Where every effective value came from (pure-ish; reads only the two requests).

    Four sources, in precedence order: what the caller sent (``user``), what the preset
    filled in (``preset``), the field's own default (``default``), and what the server
    overrides regardless (``forced`` / ``derived``).  Without this the wizard would show a
    number with no way to tell whether changing it does anything.
    """
    explicit = set(body.model_fields_set)
    preset = md_presets.get_preset(getattr(resolved, "relax_preset", None))
    out: dict = {}
    for name in CreateJobRequest.model_fields:
        value = getattr(resolved, name, None)
        if name in explicit:
            source, reason = "user", ""
        elif name in preset.defaults:
            source = "preset"
            reason = f"set by the {preset.label} preset"
        else:
            source, reason = "default", ""
        out[name] = {"value": value, "provenance": source, "reason": reason}

    # Locked fields are the preset's, whatever the caller sent — report them as forced so
    # the wizard renders them read-only WITH the reason, rather than offering a control
    # that silently does nothing.
    for name in preset.locked:
        if name in out:
            out[name] = {
                "value": preset.defaults.get(name),
                "provenance": "forced",
                "reason": (
                    f"the {preset.label} protocol owns this setting — changing it "
                    f"would make the protocol's name untrue, so it is not offered "
                    f"as a choice here"
                ),
            }

    if preset.defaults.get("protocol"):
        out["protocol"] = {
            "value": resolved.protocol,
            "provenance": "derived",
            "reason": (
                f"derived from the {preset.label} preset — protocol is never "
                f"selected separately, because a protocol that disagrees with its "
                f"preset is a job that promises one physics and runs another"
            ),
        }

    if (resolved.salt_mode or "").lower() == "screening":
        for name in _FORCED_BY_SALT_MODE:
            sent = getattr(body, name, None) if name in explicit else None
            out[name] = {
                "value": _SCREENING_VALUES[name],
                "provenance": "forced",
                "reason": (
                    "screening mode pins the ionic conditions to the validated "
                    "origami defaults: magnesium neutralises the backbone as "
                    "Mg(H2O)6 and there is no sodium. Switch salt mode to custom "
                    "to set these."
                ),
                **({"overridden_from": sent} if sent is not None else {}),
            }

    if resolved.force_soft and resolved.fast:
        out["fast"] = {
            "value": False,
            "provenance": "forced",
            "reason": (
                "the soft integrator cannot use hydrogen-mass repartitioning or a "
                "4 fs timestep, so forcing every stage soft turns fast mode off"
            ),
        }
    return out


def _design_flags() -> dict:
    """Design facts that change the protocol, if a design is loaded (never raises)."""
    try:
        design = design_state.get_or_404()
    except Exception:  # noqa: BLE001 — no design loaded is a normal wizard state
        return {
            "known": False,
            "extra_bases": False,
            "extra_base_declash": False,
            "extensions": False,
        }
    try:
        return {
            "known": True,
            "extra_bases": bool(_p.design_has_extra_bases(design)),
            "extra_base_declash": bool(_p.design_requires_extra_base_declash(design)),
            "extensions": bool(_p.design_has_extensions(design)),
        }
    except Exception:  # noqa: BLE001 — a malformed design must not break the preview
        return {
            "known": False,
            "extra_bases": False,
            "extra_base_declash": False,
            "extensions": False,
        }


def _relaxation_plan(body: ProtocolPlanRequest, resolved: CreateJobRequest) -> dict:
    carved = float(resolved.water_shell_nm or 0.0) > 0.0
    gbis = resolved.protocol == md_presets.IMPLICIT_PROTOCOL
    flags = _design_flags()
    # Mirrors prepare_mgh_slow_release: 2+xT junctions and free single-stranded tails
    # turn on declash automatically.  A 1xT junction stays on the standard ladder.
    declash = bool(
        resolved.declash or flags["extra_base_declash"] or flags["extensions"]
    )
    force_soft = bool(resolved.force_soft)
    gentle_ladder = declash and not force_soft
    # The ladder's base timestep: explicit if chosen, else the historical fast-derived
    # 4/2 fs.  `fast` is now only the NAME for "the base timestep is 4 fs" — mirrors
    # prepare_mgh_slow_release so the preview and the run agree.
    ladder_dt = (
        float(resolved.relax_timestep_fs)
        if resolved.relax_timestep_fs is not None
        else (4.0 if resolved.fast else 2.0)
    )
    fast = (ladder_dt >= 4.0) and not force_soft

    ctx = md_plan.PlanContext(
        name_stem="design",
        fast=fast,
        # The two decoupled axes, so the stage table shows what the confs will really
        # carry.  Without these the table kept reporting the auto values while the job
        # ran the chosen ones.
        rigid_bonds=resolved.relax_rigid_bonds,
        hmr=resolved.relax_hmr,
        base_timestep_fs=ladder_dt,
        # An HMR ladder names the repartitioned PSF; the plan runs before solvation, so
        # this is the name the package WILL have.
        structure_psf=(
            "design_hmr.psf"
            if resolve_integrator(
                ladder_dt, resolved.relax_rigid_bonds, resolved.relax_hmr
            ).hmr
            else None
        ),
        carved=carved,
        gbis=gbis,
        minimize_steps=int(resolved.minimize_steps),
        n_atoms=body.n_atoms_hint,
        force_resident={"on": True, "off": False}.get(
            str(resolved.gpu_resident or "auto").lower()
        ),
        anchors_file="anchors_fixed.pdb" if resolved.anchors else None,
        field=resolved.field or None,
    )
    try:
        stages = md_plan.relaxation_stages(
            ctx,
            soft=force_soft,
            gentle=gentle_ladder,
            nvt_only=carved,
            timestep_fs=ladder_dt,
            stage_overrides=body.stage_overrides or None,
        )
    except ValueError as exc:  # a protected directive — say which, do not 500
        raise HTTPException(400, str(exc)) from exc
    conditions = md_plan.protocol_conditions(
        carved=carved,
        gbis=gbis,
        force_soft=force_soft,
        gentle_ladder=gentle_ladder,
        early_stop=bool(resolved.early_stop_relax),
        gpu_resident_mode=str(resolved.gpu_resident or "auto"),
        stages=stages,
        n_atoms=body.n_atoms_hint,
    )
    # Will the full water box fit this machine?  A pre-flight ESTIMATE, reported and never
    # acted on: prep no longer carves on the user's behalf (that silently turned one
    # experiment into another), so this is the only thing standing between a too-large box
    # and an OOM at segment 1.  `source` names the control, so the wizard renders it as a
    # warning icon against Water shell carve rather than only in the list.
    if not carved and body.n_atoms_hint:
        try:
            from backend.core.md_optimize import probe_hardware  # noqa: PLC0415

            hw = probe_hardware(str(resolved.devices or "0"))
            cap = hw.get("atom_cap")
            if cap and body.n_atoms_hint > cap:
                conditions.append(
                    {
                        "id": "water_box_will_not_fit",
                        "kind": "warning",
                        "title": "The full water box may not fit this machine",
                        "detail": (
                            f"This system is about {body.n_atoms_hint:,} atoms and the "
                            f"pre-flight estimates room for roughly {cap:,} on the selected "
                            f"compute target. NADOC does NOT shrink the water for you — it "
                            f"used to, and a carve is a different experiment (vacuum corners "
                            f"force constant volume, which deletes the settle stage and the "
                            f"box-size equilibration criterion). Set a Water shell carve "
                            f"yourself if you want one, reduce the padding, seed from a "
                            f"coarse-grained relaxation, or run it anyway — the estimate is "
                            f"not a measurement and NAMD will answer the memory question "
                            f"itself at the first segment, before real compute is spent."
                        ),
                        "applies_to": "all",
                        "source": "CreateJobRequest.water_shell_nm",
                    }
                )
        except Exception:  # noqa: BLE001, S110
            # A forecast must never break the preview.
            pass

    if not resolved.allow_water_shell_carve and not carved:
        # A POLICY, not a verdict — deliberately not "blocking".
        #
        # This plan cannot know whether the design fits: that needs a solvation profile
        # (~26 s on a small bundle), far too expensive for an endpoint re-requested on
        # every keystroke. The fit check belongs to the pre-flight at launch, which
        # already runs it and already asks. Marking this blocking made the wizard refuse
        # to create ANY literature run, fitting or not — the opposite of the intent.
        conditions.append(
            {
                "id": "carve_refused",
                "kind": "forced",
                "title": "A water-shell carve is not allowed for this protocol",
                "detail": (
                    "The water is never trimmed to fit the hardware under this "
                    "protocol, and that is not overridable here. A carved cell has no "
                    "bulk phase for the published ionic condition to be a concentration "
                    "OF, no barostat, and therefore neither the fixed-DNA settle stage "
                    "nor the box-size trace the reference uses to judge equilibration — "
                    "it would be a different experiment wearing this protocol's name. "
                    "If the full box turns out not to fit your GPU, you are WARNED at "
                    "launch and can run it anyway (the estimate is not a measurement); "
                    "an out-of-memory failure lands at the first segment, before real "
                    "compute is spent. Cheaper routes: lower the water padding, seed "
                    "from an oxDNA or mrDNA relaxation so the all-atom leg is short, run "
                    "it on RunPod or the cluster, or pick a protocol that permits a "
                    "carve."
                ),
                "applies_to": "all",
                "source": "CreateJobRequest.allow_water_shell_carve",
            }
        )

    # Both scopes' integrator objections, stated as conditions so each one lands against
    # the control that caused it (their `source` names the request field).
    conditions = list(conditions) + _integrator_conditions(resolved)
    warnings: list[str] = []
    if gbis:
        warnings.append(
            "Implicit-solvent stages keep the explicit ladder's NAMES (they say NPT and "
            "MGHH) so a resumed job stays continuous, but the configs below are what "
            "really runs: constant volume, no water box, no magnesium."
        )
    if declash and not flags["known"]:
        warnings.append(
            "No design is loaded, so this preview assumes the declash setting you sent "
            "rather than reading the design's extra bases and extensions."
        )
    return {
        "stages": stages,
        # Which kind of run each setting governs, so the wizard can group its controls
        # instead of presenting one flat list in which a production-only field sits
        # between two ladder fields.
        "field_scopes": dict(FIELD_SCOPE),
        "conditions": conditions,
        "retries": md_plan.retry_policy(),
        "deferred": md_plan.deferred_notes(
            minimize_steps=int(resolved.minimize_steps),
            n_atoms=body.n_atoms_hint,
            padding_nm=float(resolved.padding_nm),
        ),
        "warnings": warnings,
        "design": flags,
        "declash": declash,
    }


def _load_parent(parent_id: str) -> MdJob:
    from backend.api.routes_md import _load_job  # noqa: PLC0415 — avoids a cycle

    return _load_job(parent_id)


def _production_plan(body: ProtocolPlanRequest, resolved: CreateJobRequest) -> dict:
    if not body.parent_job_id:
        raise HTTPException(
            400,
            "A production plan needs parent_job_id — the relaxation "
            "whose equilibrated coordinates it starts from.",
        )
    parent = _load_parent(body.parent_job_id)
    if parent.status != MdStatus.completed:
        raise HTTPException(
            400,
            "Production seeds from a COMPLETED relaxation; this one has not finished.",
        )

    spec, seed_warning, seed_reason = production_seed_checkpoint(parent)
    if spec is None:
        raise HTTPException(
            400, seed_reason or "No equilibrated checkpoint is available."
        )

    # Only the fields the caller EXPLICITLY set may reach the resolver: `resolved` carries
    # a preset-merged value for every field, and passing an unset production axis through
    # would look explicit and defeat the manifest's prep-time choice, which is what a
    # production child is supposed to inherit.
    explicit = set(body.model_fields_set)
    req = ProductionRequest(
        length_ns=(
            body.length_ns
            if body.length_ns is not None
            else (None if body.steps is not None else WIZARD_DEFAULT_PRODUCTION_NS)
        ),
        steps=body.steps,
        dcd_freq=body.dcd_freq,
        production_timestep_fs=(
            resolved.production_timestep_fs
            if "production_timestep_fs" in explicit
            else None
        ),
        rigid_bonds=(
            resolved.production_rigid_bonds
            if "production_rigid_bonds" in explicit
            else None
        ),
        hmr=(resolved.production_hmr if "production_hmr" in explicit else None),
        gpu_resident=(resolved.gpu_resident if "gpu_resident" in explicit else None),
    )
    plan = production_fast_plan(parent, req)

    # Continuing a PRODUCTION run is a different act from sampling off a relaxation, and
    # almost every sentence this endpoint emits has to know which: a continuation carries
    # the parent's velocities forward (so it extends one trajectory rather than drawing an
    # independent sample), and its parent's manifest is production-only, so the chemistry
    # has to be read from the relaxation the whole chain descends from.
    chained = parent.run_kind == "production"
    package_dir = parent.package_dir(_workspace_dir())
    try:
        manifest = json.loads((package_dir / "manifest.json").read_text())
    except (OSError, ValueError):
        manifest = {}
    name_stem = manifest.get("name_stem") or "design"
    carved = bool((manifest.get("solvation") or {}).get("carved"))
    ladder_fast = bool((manifest.get("fast_relaxation") or {}).get("enabled"))
    # The child runs the parent's PSF verbatim, so the solvated atom count is a FACT here,
    # not something solvation has yet to decide. Reading it turns GPU-resident from a
    # "conditional" cell into a resolved one — the relaxation plan cannot do this because
    # its package does not exist yet.
    n_atoms = body.n_atoms_hint or _p.psf_atom_count(package_dir / f"{name_stem}.psf")

    from backend.api.routes_md import _production_restraint_plan  # noqa: PLC0415

    restraints = _production_restraint_plan(
        parent, body.enm_restraints, body.langevin_damping
    )
    # The file does not exist until the child package is built (it is rebuilt from the
    # equilibrated checkpoint), but the plan has to SHOW that production will carry one —
    # the whole point is that the restraint row differs from the ladder's.
    enm_file = (
        f"{name_stem}_prod_k{_p.PRODUCTION_ENM_K:g}.enm.extra"
        if restraints["enm_restraints"]
        else None
    )

    ctx = md_plan.PlanContext(
        name_stem=name_stem,
        fast=bool(plan.get("fast")),
        carved=carved,
        mgh_extrabonds=bool(manifest.get("mgh_extrabonds", True)),
        structure_psf=(
            f"{name_stem}_hmr.psf" if plan.get("hmr", plan.get("fast")) else None
        ),
        rigid_bonds=plan.get("rigid_bonds"),
        hmr=plan.get("hmr"),
        n_atoms=n_atoms,
        force_resident=plan.get("force_resident"),
        # The velocity seed the reseed conf carries. A pinned seed is a real number; an
        # unpinned one is drawn at launch, so the table shows the placeholder and the
        # `deferred` note below says where the real one comes from.
        seed=int(body.seed) if body.seed is not None else md_plan.PlanContext.seed,
        # This is the filename the replica builder writes at launch. Feeding it through
        # the real conf writer makes tab 3 show `colvars on` + `colvarsConfig`, exactly
        # as the production conf will contain them.
        colvars_file=(
            "dna_orientation.colvars" if body.orientation_restraint else None
        ),
    )
    timestep_fs = float(plan["timestep_fs"])
    # The stage table of the run this wizard is about to CREATE.  `production_stages` (the
    # 10/40/50 % chunk ladder) belongs to the other production route — the legacy one that
    # appends segments onto the parent job.  `POST /md/jobs/{parent}/production-run` builds
    # a replica package, and that package is a velocity reseed plus ONE production conf.
    stages = md_plan.replica_production_stages(
        ctx,
        total_steps=int(plan["total_steps"]),
        timestep_fs=timestep_fs,
        npt=not carved,
        damping=restraints["damping"],
        enm_file=enm_file,
        dcd_freq=plan.get("dcd_freq"),
        continuation=chained,
        stage_overrides=body.stage_overrides or None,
    )

    # The column to diff against: the parent's own recorded segment, put back through the
    # SAME conf writer that produced it, so "what changes when I go to production" is a
    # real comparison and not two differently-derived descriptions.
    #
    # WHICH writer depends on what that segment was.  A relaxation stage came from
    # `_segment_conf`; the last stage of a PRODUCTION parent came from
    # `build_production_conf`, and running it back through the ladder's writer would
    # describe the run being continued with a conf that never existed — inventing
    # differences (the restraint block, the piston, the pairlist) that are artefacts of
    # the wrong emitter rather than real changes.
    source_ctx = md_plan.PlanContext(
        name_stem=name_stem,
        fast=ladder_fast,
        carved=carved,
        mgh_extrabonds=ctx.mgh_extrabonds,
        n_atoms=n_atoms,
    )
    if chained:
        parent_recipe = manifest.get("production_recipe") or {}
        source_ctx = replace(
            ctx,
            colvars_file=(
                "dna_orientation.colvars"
                if parent_recipe.get("orientation_restraint")
                else None
            ),
        )
        source_params = md_plan.production_parameters(
            spec,
            source_ctx,
            timestep_fs=spec.timestep_fs or timestep_fs,
            npt=not carved,
            damping=float(
                parent_recipe.get("langevin_damping") or _p.PRODUCTION_LANGEVIN_DAMPING
            ),
            enm_file=parent_recipe.get("enm_file"),
        )
    else:
        source_params = md_plan.stage_parameters(spec, source_ctx)

    conditions: list[dict] = []
    if seed_warning:
        conditions.append(
            {
                "id": "seed_checkpoint",
                "kind": "warning",
                "title": f"Starting from {spec.name}",
                "detail": seed_warning,
                "applies_to": [spec.name],
                "source": "routes_md._production_ready_checkpoint",
            }
        )
    else:
        conditions.append(
            {
                "id": "seed_checkpoint",
                "kind": "info",
                "title": (
                    f"Continuing {spec.name}"
                    if chained
                    else f"Starting from {spec.name}"
                ),
                # The single most consequential sentence on this screen, and it is the OPPOSITE
                # in the two cases. Off a relaxation, only coordinates and cell carry over and
                # velocities are redrawn, so each run is an independent sample. Off a
                # production, the velocities carry too — this EXTENDS one trajectory, and
                # treating two legs of it as two samples would double-count.
                "detail": (
                    (
                        "Coordinates, cell AND velocities carry over from this stage, so this run "
                        "extends that trajectory rather than sampling a new one. Its frames are "
                        "correlated with the parent's — treat the pair as one longer run, not as "
                        "two independent replicas. To get an independent sample instead, start "
                        "from the relaxation this chain descends from."
                    )
                    if chained
                    else (
                        "Coordinates and cell come from this stage; velocities are drawn fresh "
                        "at 300 K with this run's own random seed, so several productions off "
                        "one relaxation are independent samples."
                    )
                ),
                "applies_to": [spec.name],
                "source": "md_ensemble.build_replica_package",
            }
        )
    if chained:
        # `_completed_production_checkpoint` has no health gate at all, unlike the
        # relaxation path — it takes the last completed production segment with a full
        # restart set on disk, healthy or not. Say so rather than implying it was vetted.
        last_health = next(
            (h for h in reversed(parent.health_samples) if h.segment == spec.name), None
        )
        ok = last_health is None or last_health.passed
        conditions.append(
            {
                "id": "chain_source_health",
                "kind": "info" if ok else "warning",
                "title": (
                    "The run being continued passed its last health check"
                    if ok
                    else "The run being continued FAILED its last health check"
                ),
                "detail": (
                    (
                        "Base pairing and C1'-C1' distances were within gate at the last sample "
                        "of this segment. Continuing from it carries that structure forward."
                        if last_health is not None
                        else "No health sample was recorded for this segment, so nothing vouches for "
                        "the structure being continued. Continuing is still allowed — the "
                        "checkpoint is on disk and complete — but check the trajectory before "
                        "reading anything off the extension."
                    )
                    if ok
                    else (
                        f"Its last sample read C1' paired {last_health.c1_paired_fraction:.0%} "
                        f"(gate {spec.min_c1_paired:.0%}). A continuation inherits that "
                        f"structure verbatim, so the extension starts from a structure that has "
                        f"already degraded — the extra nanoseconds will not recover it."
                    )
                ),
                "applies_to": [spec.name],
                "source": "routes_md._completed_production_checkpoint",
            }
        )
    if plan.get("timestep_warning"):
        conditions.append(
            {
                "id": "timestep_warning",
                "kind": "warning",
                "title": "Timestep advisory",
                "detail": plan["timestep_warning"],
                # Sourced to the CONTROL, not to the function that raised it: this is the one
                # link the wizard has between a condition and a settings field, and a source
                # naming a Python function renders nowhere near the dropdown it is about.
                "applies_to": "all",
                "source": "CreateJobRequest.production_timestep_fs",
            }
        )
    conditions.append(
        {
            "id": "timestep_independence",
            "kind": "info",
            "title": f"Production timestep: {timestep_fs:g} fs",
            "detail": (
                "The relaxation never constrains this. A ladder exists to hand over "
                "equilibrated coordinates; once it has, production may run at any "
                "sanctioned timestep — 4 fs (the default, hydrogen-mass repartitioned), "
                "2 fs (rigid bonds, standard masses) or 1 fs (the conservative "
                "reference). Anything in between is refused outright."
            ),
            "applies_to": "all",
            "source": "CreateJobRequest.production_timestep_fs",
        }
    )
    conditions.append(
        {
            "id": "production_restraints",
            "kind": "info" if restraints["enm_restraints"] else "warning",
            "title": (
                "An elastic network is retained through production"
                if restraints["enm_restraints"]
                else "This production is genuinely unrestrained"
            ),
            "detail": (
                (
                    "Rebuilt from the equilibrated coordinates this run starts from — never from "
                    "the pre-relaxation build, which would pull the structure back to it. "
                    f"k = {_p.PRODUCTION_ENM_K:g} kcal/mol/A^2 on base-ring atoms within 8 A. "
                    "Note the published productions use a DENSER network (all non-hydrogen pairs "
                    "within 5 A), so this is the same restraint constant on a sparser network. "
                    f"Chosen because {restraints['enm_reason']}."
                )
                if restraints["enm_restraints"]
                else (
                    "The Aksimentiev-group 200+ ns origami productions a run like this would be "
                    "compared against are NOT unrestrained — they retain a network at "
                    f"k = {_p.PRODUCTION_ENM_K:g} throughout. Sampling a template-built structure "
                    "with none at all gives a measurably softer ensemble: more breathing, more "
                    "terminal fraying, larger RMSD drift. "
                    f"Chosen because {restraints['enm_reason']}."
                )
            ),
            "applies_to": "all",
            "source": "ProductionRunRequest.enm_restraints",
        }
    )
    conditions.append(
        {
            "id": "orientation_restraint",
            "kind": "info" if body.orientation_restraint else "warning",
            "title": (
                "Overall rotational diffusion is restrained"
                if body.orientation_restraint
                else "Overall rotational diffusion is free"
            ),
            "detail": (
                f"A Colvars quaternion harmonic (k = {body.orientation_force_constant:g} "
                "kcal/mol) holds the DNA near its equilibrated production-start pose. "
                "The best-fit rigid rotation is restrained; internal deformation remains free."
                if body.orientation_restraint
                else "The origami may tumble. The solvent cell must accommodate every orientation, "
                "which can dominate the water count for rods and plates."
            ),
            "applies_to": "all",
            "source": "ProductionRunRequest.orientation_restraint",
        }
    )
    conditions.append(
        {
            "id": "production_damping",
            "kind": "info",
            "title": f"Langevin coupling {restraints['damping']:g} ps⁻¹",
            "detail": (
                "The ladder runs at 5 ps⁻¹ — strong coupling while a template-built "
                "structure dumps strain. Production runs weak, because at 5 the "
                "dynamics are overdamped and every time-dependent measurement "
                "(diffusion, relaxation and correlation times, breathing kinetics) is "
                "scaled by something unrelated to the system. Equilibrium averages are "
                "unaffected either way."
            ),
            "applies_to": "all",
            "source": "ProductionRunRequest.langevin_damping",
        }
    )
    conditions.append(
        _box_fit_condition(
            parent,
            float(plan["length_ns"]),
            bool(body.allow_undersized_cell),
            orientation_restrained=bool(body.orientation_restraint),
        )
    )
    if carved:
        conditions.append(
            {
                "id": "carved_nvt",
                "kind": "forced",
                "title": "Constant volume (the package was solvated with a water-shell carve)",
                "detail": (
                    "The cell contains vacuum, so a barostat would collapse it onto the "
                    "structure. Production runs NVT for the same reason the ladder did."
                ),
                "applies_to": "all",
                "source": "md_protocols.build_production_conf",
            }
        )

    # The run stage, not the reseed bridge — every "vs the relaxation" comparison is about
    # the segment that integrates.
    run_stage = next((s for s in stages if s["role"] == "production"), stages[-1])
    choice = resolve_integrator(
        float(plan.get("timestep_fs") or 4.0), plan.get("rigid_bonds"), plan.get("hmr")
    )

    return {
        "stages": stages,
        "run_stage_index": run_stage["index"],
        # Whether this run EXTENDS its parent (velocities carry) or samples independently
        # off a relaxation. Almost every label the wizard writes branches on it.
        "continuation": chained,
        "seed_checkpoint": {
            "name": spec.name,
            "stage": spec.stage,
            "warning": seed_warning or "",
        },
        # The stage this run continues, whatever kind it is. Called `last_relax_stage`
        # until a production could be a parent — at which point the name was a lie on
        # every chained plan.
        "source_stage": {
            "name": spec.name,
            "stage": spec.stage,
            "kind": "production" if chained else "relaxation",
            "params": source_params,
        },
        # `production_asymmetries` annotates the LADDER-vs-production differences. In a
        # chain both columns are productions, so those differences do not exist — and its
        # one note that could still fire (`extrabondsfile`) is written in ladder terms and
        # would misdescribe a network the continuation deliberately dropped.
        "asymmetries": (
            []
            if chained
            else md_plan.production_asymmetries(source_params, run_stage["params"])
        ),
        "comparison": md_plan.stage_diff(source_params, run_stage["params"]),
        "timestep_plan": {
            "timestep_fs": timestep_fs,
            "total_steps": int(plan["total_steps"]),
            "length_ns": float(plan["length_ns"]),
            "fast": bool(plan.get("fast")),
            "warning": plan.get("timestep_warning") or "",
        },
        # What this run takes from its parent rather than choosing. Every one of these is
        # fixed the moment the package was solvated, so the wizard shows them as facts
        # about the run being continued instead of offering controls that do nothing.
        "inherited": _inherited_from_parent(
            parent, manifest, spec, n_atoms=n_atoms, chained=chained
        ),
        "limits": {"max_steps": _max_steps(), "max_ns": _max_ns()},
        "defaults": {
            "length_ns": WIZARD_DEFAULT_PRODUCTION_NS,
            "dcd_freq": _p.PRODUCTION_DCD_FREQ,
        },
        "field_scopes": dict(FIELD_SCOPE),
        "production_request": _production_provenance(
            body, plan, restraints, choice, manifest=manifest, chained=chained
        ),
        "conditions": conditions + integrator_warnings(choice, scope="production"),
        "retries": md_plan.retry_policy(),
        "deferred": _production_deferred(body, chained=chained),
        "warnings": [w for w in (seed_warning, plan.get("timestep_warning")) if w],
    }


def _inherited_from_parent(
    parent: MdJob,
    manifest: dict,
    spec,
    *,
    n_atoms: Optional[int],
    chained: bool = False,
) -> dict:
    """The facts a production child takes verbatim from the run it continues.

    Read-only by construction: the child hardlinks the parent's PSF/PDB and copies its
    cell, so re-solvating is not on the table.  Surfacing them is what makes "continue off
    this run" a statement the user can check rather than one they have to trust.

    A chained production's own manifest is production-only — no ``relax_preset``, no
    solvation block, no ion concentrations — so the chemistry is read from the ROOT
    relaxation the whole chain descends from.  Reading the immediate parent's blindly is
    what made a chained plan report "protocol: unrecorded" and blank ion concentrations.
    """
    from backend.api.routes_md import root_relaxation  # noqa: PLC0415

    root = root_relaxation(parent) if chained else parent
    root_manifest = (
        manifest if root.job_id == parent.job_id else _read_job_manifest(root)
    )

    solvation = manifest.get("solvation") or root_manifest.get("solvation") or {}
    relax_settings = (
        root_manifest.get("relax_protocol_settings")
        or manifest.get("relax_protocol_settings")
        or {}
    )
    box = manifest.get("box_ang") or root_manifest.get("box_ang") or []
    prep = root.prep_params or parent.prep_params or {}
    # How many production legs already sit between the root relaxation and this new run.
    depth, cur = 0, parent
    while cur.run_kind == "production" and cur.parent_job_id and depth < 64:
        depth += 1
        if cur.job_id == root.job_id:
            break
        try:
            cur = _load_parent(cur.parent_job_id)
        except HTTPException:
            break
    return {
        "parent_job_id": parent.job_id,
        "parent_run_kind": parent.run_kind or "relaxation",
        "design_name": parent.design_name,
        "created_at": parent.created_at,
        "continuation": chained,
        # The relaxation the whole chain descends from, and how many production legs are
        # already between it and this run.
        "root_job_id": root.job_id,
        "root_created_at": root.created_at,
        "chain_position": depth + 1,
        "protocol": (
            root_manifest.get("protocol") or manifest.get("protocol") or root.protocol
        ),
        "relax_preset": (
            root_manifest.get("relax_preset")
            or manifest.get("relax_preset")
            or prep.get("relax_preset")
            or ""
        ),
        "seed_checkpoint": spec.name,
        "seed_stage": spec.stage,
        "n_atoms": n_atoms,
        "box_ang": [round(float(v), 2) for v in box] if box else [],
        "carved": bool(solvation.get("carved")),
        "npt_allowed": bool(solvation.get("npt_allowed", not solvation.get("carved"))),
        "padding_nm": solvation.get("padding_nm"),
        "water_shell_nm": solvation.get("water_shell_nm"),
        "sized_for_free_ns": solvation.get("sized_for_free_ns"),
        "mg_conc_mM": prep.get("mg_conc_mM"),
        "ion_conc_mM": prep.get("ion_conc_mM"),
        "ladder_timestep_fs": relax_settings.get("timestep_fs"),
        "anchors": bool((manifest.get("anchors") or {}).get("file")),
        "field": manifest.get("field") or root_manifest.get("field") or None,
        # Only meaningful in a chain: the simulated time already accumulated in the run
        # being continued, so the wizard can say what the extended trajectory totals.
        "parent_length_ns": (
            (manifest.get("ensemble") or {}).get("length_ns") if chained else None
        ),
    }


def _read_job_manifest(job: MdJob) -> dict:
    try:
        return json.loads(
            (job.package_dir(_workspace_dir()) / "manifest.json").read_text()
        )
    except (OSError, ValueError):
        return {}


def _production_deferred(
    body: ProtocolPlanRequest, *, chained: bool = False
) -> list[dict]:
    """Values a production child only resolves when it is created."""
    if body.seed is not None:
        return []
    return [
        {
            "key": "seed",
            "title": "The random seed is drawn when the job is created",
            # What the seed DOES differs between the two cases, and the old wording described
            # only one of them. Off a relaxation it picks the initial velocities, which is
            # what makes sibling runs independent. In a continuation the velocities come from
            # the checkpoint, so the seed only drives the Langevin stream from there on.
            "detail": (
                (
                    "This run inherits its velocities from the checkpoint it continues, so the "
                    "seed does not choose them — it drives the Langevin thermostat's random "
                    "force from that point on. Two continuations of the same checkpoint with "
                    "different seeds do diverge, but they share the parent's whole history, so "
                    "they are not independent samples of it. The number in the reseed column is "
                    "a placeholder; the seed actually used is recorded on the job."
                )
                if chained
                else (
                    "Every production run draws a fresh random NAMD seed, so repeated runs off "
                    "one relaxation are independent samples rather than one thermal history "
                    "repeated. The number in the reseed column is a placeholder; the seed "
                    "actually used is recorded on the job and in its manifest. Pin it only to "
                    "reproduce a specific past trajectory."
                )
            ),
        }
    ]


#: Where each production-only value came from.  Mirrors ``_provenance`` for the fields that
#: live on ``ProductionRunRequest`` rather than on ``CreateJobRequest`` — without it every
#: production control rendered with no chip, so nothing on screen said whether a number was
#: the user's, the package's, or a default.
def _production_provenance(
    body: ProtocolPlanRequest,
    plan: dict,
    restraints: dict,
    choice,
    *,
    manifest: dict,
    chained: bool = False,
) -> dict:
    explicit = set(body.model_fields_set)
    relax_integrator = manifest.get("relax_integrator") or {}

    def entry(value, name, *, reason="", inherited_key=None, inherited_reason=""):
        if name in explicit and getattr(body, name, None) is not None:
            return {"value": value, "provenance": "user", "reason": ""}
        if inherited_key and manifest.get(inherited_key) is not None:
            return {
                "value": value,
                "provenance": "inherited",
                "reason": inherited_reason
                or "recorded when the relaxation package was prepared",
            }
        return {"value": value, "provenance": "default", "reason": reason}

    def integrator_entry(value, name, axis):
        if name in explicit and getattr(body, name, None) is not None:
            return {"value": value, "provenance": "user", "reason": ""}
        if relax_integrator.get(axis) is not None:
            return {
                "value": value,
                "provenance": "inherited",
                "reason": "starts from the parent relaxation's resolved integrator; "
                "this production run may override it",
            }
        legacy_key = name
        if manifest.get(legacy_key) is not None:
            return {
                "value": value,
                "provenance": "inherited",
                "reason": "legacy default recorded when the relaxation was prepared",
            }
        return {"value": value, "provenance": "default", "reason": "compatibility default"}

    return {
        "length_ns": entry(
            float(plan["length_ns"]),
            "length_ns",
            reason="the wizard's own default run length",
        ),
        "dcd_freq": entry(
            int(plan.get("dcd_freq") or _p.PRODUCTION_DCD_FREQ),
            "dcd_freq",
            reason=f"the protocol default ({_p.PRODUCTION_DCD_FREQ} steps "
            f"= 10 ps at 4 fs)",
        ),
        "production_timestep_fs": integrator_entry(
            float(plan["timestep_fs"]),
            "production_timestep_fs",
            "timestep_fs",
        ),
        "production_rigid_bonds": integrator_entry(
            choice.rigid_bonds,
            "production_rigid_bonds",
            "rigid_bonds",
        ),
        "production_hmr": integrator_entry(
            bool(choice.hmr),
            "production_hmr",
            "hmr",
        ),
        "gpu_resident": entry(
            body.gpu_resident if "gpu_resident" in explicit else "auto",
            "gpu_resident",
            reason="auto — decided from the solvated atom count",
        ),
        "enm_restraints": {
            "value": "on" if restraints["enm_restraints"] else "off",
            "provenance": "user"
            if (body.enm_restraints or "auto") != "auto"
            else "derived",
            "reason": restraints["enm_reason"],
        },
        "orientation_restraint": entry(
            bool(body.orientation_restraint),
            "orientation_restraint",
            reason="off by default; enable only when laboratory-frame rotation is not an observable",
        ),
        "orientation_force_constant": entry(
            float(body.orientation_force_constant),
            "orientation_force_constant",
            reason="the Colvars orientation-restraint example value",
        ),
        "langevin_damping": entry(
            float(restraints["damping"]),
            "langevin_damping",
            reason=f"the literature production value "
            f"({_p.PRODUCTION_LANGEVIN_DAMPING:g} ps⁻¹)",
        ),
        "seed": {
            "value": body.seed,
            "provenance": "user" if body.seed is not None else "derived",
            # What the seed DOES depends on whether velocities are being redrawn. In a
            # continuation they are not, so calling it the thing that makes runs
            # independent would be exactly backwards.
            "reason": (
                ""
                if body.seed is not None
                else (
                    "drawn fresh when the job is created; it drives the thermostat "
                    "from the inherited velocities on, it does not choose them"
                    if chained
                    else "drawn fresh when the job is created, so repeated runs sample "
                    "independent trajectories"
                )
            ),
        },
        "allow_undersized_cell": entry(
            bool(body.allow_undersized_cell),
            "allow_undersized_cell",
            reason="off — an undersized cell refuses by default",
        ),
    }


def _box_fit_condition(
    parent: MdJob,
    length_ns: float,
    allow: bool,
    *,
    orientation_restrained: bool = False,
) -> dict:
    """Whether the inherited cell is big enough for this run — as a CONDITION, not a 400.

    The real endpoint refuses an undersized cell unless the caller opts in.  A preview
    that refused would be useless: the whole point is to show the problem, and the
    override, before anything is created.
    """
    from backend.api.routes_md import _assert_cell_fits_a_free_run  # noqa: PLC0415
    from backend.core.namd_solvate import ROTATION_FREE_NS_THRESHOLD  # noqa: PLC0415

    if orientation_restrained:
        return {
            "id": "box_fit",
            "kind": "info",
            "title": "Pose-sized cell (overall rotation restrained)",
            "detail": (
                "The rotation-sized envelope is not required because the quaternion bias "
                "holds the origami near its production-start orientation. Keep ordinary "
                "solvent padding for conformational fluctuations and translation."
            ),
            "ok": True,
            "override": None,
            "applies_to": "all",
            "source": "ProductionRunRequest.orientation_restraint",
        }
    try:
        _assert_cell_fits_a_free_run(parent, length_ns, allow=allow)
        ok, detail = (
            True,
            (
                f"The cell this package was solvated with is large enough for a "
                f"{length_ns:g} ns unrestrained run."
                if length_ns > ROTATION_FREE_NS_THRESHOLD
                else f"Runs up to {ROTATION_FREE_NS_THRESHOLD:g} ns do not need a rotation-sized "
                f"cell, so the cheaper bounding-box cell is fine here."
            ),
        )
    except HTTPException as exc:
        ok, detail = False, str(exc.detail)
    return {
        "id": "box_fit",
        "kind": "info" if ok else "blocking",
        "title": "Cell size" if ok else "The cell is too small for this run length",
        "detail": detail,
        "ok": ok,
        "override": None if ok else "allow_undersized_cell",
        # The RUN LENGTH is what the user changes to resolve this, so the warning belongs
        # against that control — not against a private helper's name.
        "applies_to": "all",
        "source": "ProductionRunRequest.length_ns",
    }


def _workspace_dir():
    from backend.api.routes_md import _workspace  # noqa: PLC0415

    return _workspace()


def _max_steps() -> int:
    from backend.api.routes_md import MAX_PRODUCTION_STEPS  # noqa: PLC0415

    return MAX_PRODUCTION_STEPS


def _max_ns() -> float:
    from backend.api.routes_md import MAX_PRODUCTION_NS  # noqa: PLC0415

    return MAX_PRODUCTION_NS


@router.post("/md/protocol-plan")
async def protocol_plan(body: ProtocolPlanRequest) -> dict:
    """Every parameter this job would run, per stage, without preparing anything.

    Cheap and side-effect-free for a relaxation (no disk at all), so the wizard can
    re-request it on every keystroke behind a short debounce.  A production plan reads the
    parent package's manifest, which is a small JSON file.
    """
    resolved = resolve_relax_preset(body)
    preset = md_presets.get_preset(getattr(resolved, "relax_preset", None))
    available, why = md_presets.preset_availability(preset)

    kind = (body.kind or "relaxation").strip().lower()
    if kind not in ("relaxation", "production"):
        raise HTTPException(400, "kind must be 'relaxation' or 'production'")

    plan = (
        _production_plan(body, resolved)
        if kind == "production"
        else _relaxation_plan(body, resolved)
    )

    stages = plan["stages"]
    edited = sorted({k for k, v in (body.stage_overrides or {}).items() if v})
    return {
        "kind": kind,
        "stage_overrides": body.stage_overrides or {},
        "protected_directives": sorted(_p.PROTECTED_DIRECTIVES),
        "edited_stages": edited,
        "preset": {
            "id": preset.id,
            "label": preset.label,
            "summary": preset.summary,
            "reference": preset.reference,
            "available": available,
            "unavailable_reason": why,
        },
        "protocol": resolved.protocol,
        "request": _provenance(body, resolved),
        "param_groups": [g for g, _ in md_plan.PARAM_GROUPS],
        "totals": {
            "n_stages": len(stages),
            "total_steps": sum(int(s["steps"]) for s in stages),
            "total_ns": round(sum(float(s["ns"]) for s in stages), 4),
        },
        **{k: v for k, v in plan.items() if k != "stages"},
        "stages": stages,
    }
