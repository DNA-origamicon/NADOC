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
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import Field

from backend.api import state as design_state
from backend.api.routes_md import (CreateJobRequest, ProductionRequest,
                                   production_fast_plan, production_seed_checkpoint,
                                   resolve_relax_preset)
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


class ProtocolPlanRequest(CreateJobRequest):
    """A job request, plus what the plan needs that a job request does not carry.

    Subclasses ``CreateJobRequest`` so ``model_fields_set`` — which is how provenance is
    computed — means exactly what it means on the real create path.
    """
    kind: str = Field("relaxation", description="'relaxation' or 'production'")
    parent_job_id: Optional[str] = Field(
        None, description="Production only: the relaxation job to seed from.")
    length_ns: Optional[float] = Field(None, gt=0.0, description="Production run length.")
    steps: Optional[int] = Field(None, ge=100, description="Production step count.")
    dcd_freq: Optional[int] = Field(None, ge=100, description="Production DCD interval.")
    allow_undersized_cell: bool = Field(
        False, description="Production only: proceed despite a cell too small to let the "
                           "structure rotate freely.")
    enm_restraints: str = Field(
        "auto", description="Production only: keep an elastic network through the run "
                            "('auto' | 'on' | 'off').")
    langevin_damping: Optional[float] = Field(
        None, gt=0.0, description="Production only: Langevin coupling, ps^-1.")
    stage_overrides: dict = Field(
        default_factory=dict,
        description="Per-stage NAMD directive overrides, keyed by stage index (and '*'). "
                    "Applied to the emitted confs, so the stage table shows the run as "
                    "edited and marks every cell that departs from the protocol.")
    n_atoms_hint: Optional[int] = Field(
        None, ge=1,
        description="Solvated atom count, when the caller already knows it (an existing "
                    "package, or a disk estimate). Resolves the values this plan would "
                    "otherwise have to report as deferred.")


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
    "minimize_steps": "relaxation",
    "protocol": "relaxation",
    # The production run only — recorded at prep, applied when production runs.
    "production_timestep_fs": "production",
    "production_rigid_bonds": "production",
    "production_hmr": "production",
    "production_ns_intent": "production",
    # Everything else — solvation, chemistry, hardware — is shared by both, because the
    # cell and the PSF a relaxation builds are the ones production inherits verbatim.
}


def _integrator_conditions(resolved: CreateJobRequest) -> list[dict]:
    """Every measured objection to the chosen integrator combinations, both scopes.

    The ladder's base timestep still falls back to `fast` when the caller has not chosen
    one, so this reports on what the confs will actually carry rather than on the raw
    request.  Warnings only — see md_integrator.
    """
    ladder_dt = (float(resolved.relax_timestep_fs)
                 if resolved.relax_timestep_fs is not None
                 else (4.0 if resolved.fast else 2.0))
    if resolved.force_soft:
        ladder_dt = 1.0
    out = integrator_warnings(
        resolve_integrator(ladder_dt, resolved.relax_rigid_bonds, resolved.relax_hmr),
        scope="relaxation")
    out += integrator_warnings(
        resolve_integrator(float(resolved.production_timestep_fs or 4.0),
                           resolved.production_rigid_bonds, resolved.production_hmr),
        scope="production")
    return out


def _provenance(body: ProtocolPlanRequest,
                resolved: CreateJobRequest) -> dict:
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
                "reason": (f"the {preset.label} protocol owns this setting — changing it "
                           f"would make the protocol's name untrue, so it is not offered "
                           f"as a choice here"),
            }

    if preset.defaults.get("protocol"):
        out["protocol"] = {
            "value": resolved.protocol, "provenance": "derived",
            "reason": (f"derived from the {preset.label} preset — protocol is never "
                       f"selected separately, because a protocol that disagrees with its "
                       f"preset is a job that promises one physics and runs another"),
        }

    if (resolved.salt_mode or "").lower() == "screening":
        for name in _FORCED_BY_SALT_MODE:
            sent = getattr(body, name, None) if name in explicit else None
            out[name] = {
                "value": _SCREENING_VALUES[name],
                "provenance": "forced",
                "reason": ("screening mode pins the ionic conditions to the validated "
                           "origami defaults: magnesium neutralises the backbone as "
                           "Mg(H2O)6 and there is no sodium. Switch salt mode to custom "
                           "to set these."),
                **({"overridden_from": sent} if sent is not None else {}),
            }

    if resolved.force_soft and resolved.fast:
        out["fast"] = {
            "value": False, "provenance": "forced",
            "reason": ("the soft integrator cannot use hydrogen-mass repartitioning or a "
                       "4 fs timestep, so forcing every stage soft turns fast mode off"),
        }
    return out


def _design_flags() -> dict:
    """Design facts that change the protocol, if a design is loaded (never raises)."""
    try:
        design = design_state.get_or_404()
    except Exception:  # noqa: BLE001 — no design loaded is a normal wizard state
        return {"known": False, "extra_bases": False, "extensions": False}
    try:
        return {
            "known": True,
            "extra_bases": bool(_p.design_has_extra_bases(design)),
            "extensions": bool(_p.design_has_extensions(design)),
        }
    except Exception:  # noqa: BLE001 — a malformed design must not break the preview
        return {"known": False, "extra_bases": False, "extensions": False}


def _relaxation_plan(body: ProtocolPlanRequest, resolved: CreateJobRequest) -> dict:
    carved = float(resolved.water_shell_nm or 0.0) > 0.0
    gbis = resolved.protocol == md_presets.IMPLICIT_PROTOCOL
    flags = _design_flags()
    # Mirrors prepare_mgh_slow_release: declash turns itself on for designs that are BUILT
    # clashed (extra bases at crossovers, free single-stranded tails), and that choice
    # cascades into the integrator tier for the whole ladder.
    declash = bool(resolved.declash or flags["extra_bases"] or flags["extensions"])
    force_soft = bool(resolved.force_soft)
    gentle_ladder = declash and not force_soft
    # The ladder's base timestep: explicit if chosen, else the historical fast-derived
    # 4/2 fs.  `fast` is now only the NAME for "the base timestep is 4 fs" — mirrors
    # prepare_mgh_slow_release so the preview and the run agree.
    ladder_dt = (float(resolved.relax_timestep_fs)
                 if resolved.relax_timestep_fs is not None
                 else (4.0 if resolved.fast else 2.0))
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
        structure_psf=("design_hmr.psf"
                       if resolve_integrator(ladder_dt, resolved.relax_rigid_bonds,
                                             resolved.relax_hmr).hmr else None),
        carved=carved,
        gbis=gbis,
        minimize_steps=int(resolved.minimize_steps),
        n_atoms=body.n_atoms_hint,
        force_resident={"on": True, "off": False}.get(
            str(resolved.gpu_resident or "auto").lower()),
        anchors_file="anchors_fixed.pdb" if resolved.anchors else None,
        field=resolved.field or None,
    )
    try:
        stages = md_plan.relaxation_stages(
            ctx, soft=force_soft, gentle=gentle_ladder, nvt_only=carved,
            timestep_fs=ladder_dt,
            stage_overrides=body.stage_overrides or None)
    except ValueError as exc:      # a protected directive — say which, do not 500
        raise HTTPException(400, str(exc)) from exc
    conditions = md_plan.protocol_conditions(
        carved=carved, gbis=gbis, force_soft=force_soft, gentle_ladder=gentle_ladder,
        early_stop=bool(resolved.early_stop_relax),
        gpu_resident_mode=str(resolved.gpu_resident or "auto"), stages=stages,
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
                conditions.append({
                    "id": "water_box_will_not_fit", "kind": "warning",
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
                    "applies_to": "all", "source": "CreateJobRequest.water_shell_nm",
                })
        except Exception:                                     # noqa: BLE001, S110
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
        conditions.append({
            "id": "carve_refused", "kind": "forced",
            "title": "A water-shell carve is not allowed for this protocol",
            "detail": ("The water is never trimmed to fit the hardware under this "
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
                       "carve."),
            "applies_to": "all", "source": "CreateJobRequest.allow_water_shell_carve",
        })

    # Both scopes' integrator objections, stated as conditions so each one lands against
    # the control that caused it (their `source` names the request field).
    conditions = list(conditions) + _integrator_conditions(resolved)
    warnings: list[str] = []
    if gbis:
        warnings.append(
            "Implicit-solvent stages keep the explicit ladder's NAMES (they say NPT and "
            "MGHH) so a resumed job stays continuous, but the configs below are what "
            "really runs: constant volume, no water box, no magnesium.")
    if declash and not flags["known"]:
        warnings.append(
            "No design is loaded, so this preview assumes the declash setting you sent "
            "rather than reading the design's extra bases and extensions.")
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
        raise HTTPException(400, "A production plan needs parent_job_id — the relaxation "
                                 "whose equilibrated coordinates it starts from.")
    parent = _load_parent(body.parent_job_id)
    if parent.status != MdStatus.completed:
        raise HTTPException(
            400, "Production seeds from a COMPLETED relaxation; this one has not finished.")

    spec, seed_warning, seed_reason = production_seed_checkpoint(parent)
    if spec is None:
        raise HTTPException(400, seed_reason or "No equilibrated checkpoint is available.")

    req = ProductionRequest(
        length_ns=body.length_ns, steps=body.steps, dcd_freq=body.dcd_freq,
        production_timestep_fs=resolved.production_timestep_fs,
        gpu_resident=resolved.gpu_resident,
    )
    plan = production_fast_plan(parent, req)

    package_dir = parent.package_dir(_workspace_dir())
    try:
        manifest = json.loads((package_dir / "manifest.json").read_text())
    except (OSError, ValueError):
        manifest = {}
    name_stem = manifest.get("name_stem") or "design"
    carved = bool((manifest.get("solvation") or {}).get("carved"))
    ladder_fast = bool((manifest.get("fast_relaxation") or {}).get("enabled"))

    from backend.api.routes_md import _production_restraint_plan  # noqa: PLC0415
    restraints = _production_restraint_plan(
        parent, body.enm_restraints, body.langevin_damping)
    # The file does not exist until the child package is built (it is rebuilt from the
    # equilibrated checkpoint), but the plan has to SHOW that production will carry one —
    # the whole point is that the restraint row differs from the ladder's.
    enm_file = (f"{name_stem}_prod_k{_p.PRODUCTION_ENM_K:g}.enm.extra"
                if restraints["enm_restraints"] else None)

    ctx = md_plan.PlanContext(
        name_stem=name_stem,
        fast=bool(plan.get("fast")),
        carved=carved,
        mgh_extrabonds=bool(manifest.get("mgh_extrabonds", True)),
        structure_psf=(f"{name_stem}_hmr.psf" if plan.get("hmr", plan.get("fast"))
                       else None),
        rigid_bonds=plan.get("rigid_bonds"),
        hmr=plan.get("hmr"),
        n_atoms=body.n_atoms_hint,
        force_resident=plan.get("force_resident"),
    )
    timestep_fs = float(plan["timestep_fs"])
    stages = md_plan.production_stages(
        ctx, total_steps=int(plan["total_steps"]), timestep_fs=timestep_fs,
        stage_idx=len({s.get("stage") for s in manifest.get("segments", [])}) + 1,
        previous=spec.name, npt=not carved,
        damping=restraints["damping"], enm_file=enm_file,
        stage_overrides=body.stage_overrides or None,
    )

    # The relaxation column to diff against: the SAME conf writer, run on the parent's own
    # recorded segment, so "what changes when I go to production" is a real comparison and
    # not two differently-derived descriptions.
    last_ctx = md_plan.PlanContext(
        name_stem=name_stem, fast=ladder_fast, carved=carved,
        mgh_extrabonds=ctx.mgh_extrabonds, n_atoms=body.n_atoms_hint,
    )
    last_params = md_plan.stage_parameters(spec, last_ctx)

    conditions: list[dict] = []
    if seed_warning:
        conditions.append({
            "id": "seed_checkpoint", "kind": "warning",
            "title": f"Starting from {spec.name}", "detail": seed_warning,
            "applies_to": [spec.name], "source": "routes_md._production_ready_checkpoint",
        })
    else:
        conditions.append({
            "id": "seed_checkpoint", "kind": "info",
            "title": f"Starting from {spec.name}",
            "detail": ("Coordinates and cell come from this stage; velocities are drawn "
                       "fresh at 300 K with this run's own random seed, so several "
                       "productions off one relaxation are independent samples."),
            "applies_to": [spec.name], "source": "md_ensemble.build_replica_package",
        })
    if plan.get("timestep_warning"):
        conditions.append({
            "id": "timestep_warning", "kind": "warning",
            "title": "Timestep advisory", "detail": plan["timestep_warning"],
            "applies_to": "all", "source": "routes_md._production_fast_plan",
        })
    conditions.append({
        "id": "timestep_independence", "kind": "info",
        "title": f"Production timestep: {timestep_fs:g} fs",
        "detail": ("The relaxation never constrains this. A ladder exists to hand over "
                   "equilibrated coordinates; once it has, production may run at any "
                   "sanctioned timestep — 4 fs (the default, hydrogen-mass repartitioned), "
                   "2 fs (rigid bonds, standard masses) or 1 fs (the conservative "
                   "reference). Anything in between is refused outright."),
        "applies_to": "all", "source": "md_protocols.require_sanctioned_production_timestep",
    })
    conditions.append({
        "id": "production_restraints",
        "kind": "info" if restraints["enm_restraints"] else "warning",
        "title": ("An elastic network is retained through production"
                  if restraints["enm_restraints"]
                  else "This production is genuinely unrestrained"),
        "detail": (
            ("Rebuilt from the equilibrated coordinates this run starts from — never from "
             "the pre-relaxation build, which would pull the structure back to it. "
             f"k = {_p.PRODUCTION_ENM_K:g} kcal/mol/A^2 on base-ring atoms within 8 A. "
             "Note the published productions use a DENSER network (all non-hydrogen pairs "
             "within 5 A), so this is the same restraint constant on a sparser network. "
             f"Chosen because {restraints['enm_reason']}.")
            if restraints["enm_restraints"] else
            ("The Aksimentiev-group 200+ ns origami productions a run like this would be "
             "compared against are NOT unrestrained — they retain a network at "
             f"k = {_p.PRODUCTION_ENM_K:g} throughout. Sampling a template-built structure "
             "with none at all gives a measurably softer ensemble: more breathing, more "
             "terminal fraying, larger RMSD drift. "
             f"Chosen because {restraints['enm_reason']}.")),
        "applies_to": "all", "source": "routes_md._production_restraint_plan",
    })
    conditions.append({
        "id": "production_damping", "kind": "info",
        "title": f"Langevin coupling {restraints['damping']:g} ps⁻¹",
        "detail": ("The ladder runs at 5 ps⁻¹ — strong coupling while a template-built "
                   "structure dumps strain. Production runs weak, because at 5 the "
                   "dynamics are overdamped and every time-dependent measurement "
                   "(diffusion, relaxation and correlation times, breathing kinetics) is "
                   "scaled by something unrelated to the system. Equilibrium averages are "
                   "unaffected either way."),
        "applies_to": "all", "source": "md_protocols.PRODUCTION_LANGEVIN_DAMPING",
    })
    conditions.append(_box_fit_condition(parent, float(plan["length_ns"]),
                                         bool(body.allow_undersized_cell)))
    if carved:
        conditions.append({
            "id": "carved_nvt", "kind": "forced",
            "title": "Constant volume (the package was solvated with a water-shell carve)",
            "detail": ("The cell contains vacuum, so a barostat would collapse it onto the "
                       "structure. Production runs NVT for the same reason the ladder did."),
            "applies_to": "all", "source": "md_protocols.build_production_conf",
        })

    return {
        "stages": stages,
        "seed_checkpoint": {"name": spec.name, "stage": spec.stage,
                            "warning": seed_warning or ""},
        "last_relax_stage": {"name": spec.name, "stage": spec.stage,
                             "params": last_params},
        "asymmetries": md_plan.production_asymmetries(last_params, stages[0]["params"]),
        "comparison": md_plan.stage_diff(last_params, stages[0]["params"]),
        "timestep_plan": {
            "timestep_fs": timestep_fs,
            "total_steps": int(plan["total_steps"]),
            "length_ns": float(plan["length_ns"]),
            "fast": bool(plan.get("fast")),
            "warning": plan.get("timestep_warning") or "",
        },
        "limits": {"max_steps": _max_steps(), "max_ns": _max_ns()},
        "field_scopes": dict(FIELD_SCOPE),
        "conditions": conditions + integrator_warnings(
            resolve_integrator(float(plan.get("timestep_fs") or 4.0),
                               plan.get("rigid_bonds"), plan.get("hmr")),
            scope="production"),
        "retries": md_plan.retry_policy(),
        "deferred": [],
        "warnings": [w for w in (seed_warning, plan.get("timestep_warning")) if w],
    }


def _box_fit_condition(parent: MdJob, length_ns: float, allow: bool) -> dict:
    """Whether the inherited cell is big enough for this run — as a CONDITION, not a 400.

    The real endpoint refuses an undersized cell unless the caller opts in.  A preview
    that refused would be useless: the whole point is to show the problem, and the
    override, before anything is created.
    """
    from backend.api.routes_md import _assert_cell_fits_a_free_run  # noqa: PLC0415
    from backend.core.namd_solvate import ROTATION_FREE_NS_THRESHOLD  # noqa: PLC0415
    try:
        _assert_cell_fits_a_free_run(parent, length_ns, allow=allow)
        ok, detail = True, (
            f"The cell this package was solvated with is large enough for a "
            f"{length_ns:g} ns unrestrained run."
            if length_ns > ROTATION_FREE_NS_THRESHOLD else
            f"Runs up to {ROTATION_FREE_NS_THRESHOLD:g} ns do not need a rotation-sized "
            f"cell, so the cheaper bounding-box cell is fine here."
        )
    except HTTPException as exc:
        ok, detail = False, str(exc.detail)
    return {
        "id": "box_fit", "kind": "info" if ok else "blocking",
        "title": "Cell size" if ok else "The cell is too small for this run length",
        "detail": detail, "ok": ok,
        "override": None if ok else "allow_undersized_cell",
        "applies_to": "all", "source": "routes_md._assert_cell_fits_a_free_run",
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

    plan = (_production_plan(body, resolved) if kind == "production"
            else _relaxation_plan(body, resolved))

    stages = plan["stages"]
    edited = sorted({k for k, v in (body.stage_overrides or {}).items() if v})
    return {
        "kind": kind,
        "stage_overrides": body.stage_overrides or {},
        "protected_directives": sorted(_p.PROTECTED_DIRECTIVES),
        "edited_stages": edited,
        "preset": {
            "id": preset.id, "label": preset.label, "summary": preset.summary,
            "reference": preset.reference, "available": available,
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
