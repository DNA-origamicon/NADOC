---
name: feedback-namd-4fs-production-only
description: "4.0 fs is the ONLY acceptable NAMD PRODUCTION timestep. Never propose lowering production dt to dodge a RATTLE/instability — fix the clash instead. Lower dt is allowed ONLY in ramp/anneal/relaxation stages."
metadata:
  node_type: memory
  type: feedback
  originSessionId: 78578ada-ee6f-4f68-bc99-2b8ae2ee803d
---

**4.0 fs is the DEFAULT and the only AUTO-selected timestep for a NAMD PRODUCTION run.** Never
*silently* suggest, plan, size, or launch a production run at a lower timestep to dodge an
instability. Lower timesteps are legitimate **only** inside minimization, soft relaxation,
annealing, or a heating **ramp** that leads UP to a 4 fs production run — never reached by
downgrading a 4 fs production run itself. Two by-name exceptions exist, both requiring an
explicit user choice, never an automatic downgrade:
- the **1.0 fs conservative-reference** path (`rigidBonds none`, no HMR) — a deliberately-
  requested accuracy mode;
- the **2.0 fs manual medium** path (`rigidBonds all` + GPUresident, standard masses, no HMR) —
  added 2026-07 as a user-selectable option in the Advanced card's **Production timestep**
  dropdown (1/2/4 fs), which flags a warning when 4/2 fs is picked without the fast relaxation
  ladder. `require_sanctioned_production_timestep(dt, allow_manual_2fs=True)` permits 2.0 ONLY
  when that manual flag is set; the automatic `fast`-derived path still yields only 4/1 fs, so
  the anti-drift protection is intact.

Truly intermediate values (**2.5 / 3.0 / 3.5 fs**) remain banned outright — the dropdown never
offers them and the guard rejects them even manually. Those are the "shave the timestep to
survive a RATTLE clash" anti-pattern; the fix is still to remove the clash, not lower dt.

**Why:** when a 4 fs run trips `Constraint failure in RATTLE algorithm for atom N` or
`Atoms moving too fast`, the failure is almost always a **local geometry/force problem** — a
clash or an over-stretched bond at a few sites — NOT a verdict that 4 fs is too large for the
system. For the 24hb extra-crossover-base campaign the trigger is a **bad initial guess**: the
geometric build stacks neighbouring extra-base sugars (159 clash pairs, C4'–C4' to 0.29 Å) and
the declash minimiser relieves the overlap by stretching a C4'–C5' bond to ~3.1 Å, which a
4 fs rigid-bonds RATTLE step cannot integrate. **The fix is to remove the clash** (oxDNA-seed
the design so the extra bases start declashed — `backend/core/oxdna_seed.py`,
`prep_24hb_seeded.py`, the `pre_declashed` path in `md_protocols.prepare_mgh_slow_release`),
**not to lower the production timestep.** Many other extra crossover bases and end ssDNA loops
in the same design run fine at 4 fs — proof the 4 fs ceiling is a fixable local artefact, not a
global property. A prior session repeatedly drifted toward "accept 3.0 fs and match it"; that is
the anti-pattern this rule exists to block. (The superseded
`experiments/exp43_runpod_bench/TIMESTEP_CEILING_REPORT.md` reached the 3 fs conclusion BEFORE
the oxDNA-seed fix; read its correction header.)

**How to apply:**
- Enforced in code: `md_protocols.require_sanctioned_production_timestep(dt, allow_manual_2fs=…)`
  raises on any non-sanctioned dt (allows 4/1 always, 2 only with the manual flag, never
  2.5/3/3.5); `experiments/exp43_runpod_bench/preflight.py` mechanically FAILS a package whose
  GPUresident/production conf uses a `timestep` other than 4.0 or 2.0 before any GPU is rented.
- The user-facing knob: Advanced card → **Production timestep** dropdown (1/2/4 fs), wired
  `frontend` → `CreateJobRequest.production_timestep_fs` → `manifest["production_timestep_fs"]`
  → `routes_md._production_fast_plan` → `build_production_conf(timestep_fs=…)`. A declash design
  requesting 4 fs is still force-dropped to 1 fs (rigidBonds-all HMR can't survive its clashes).
  See [[project_md_job_system]].
- If a 4 fs run is unstable, diagnose and remove the offending clash/stretch (seed from oxDNA;
  targeted minimization; per-residue/selective HMR on dangling sugars; extraBonds during
  equilibration) — see the ranked levers in
  `experiments/exp43_runpod_bench/NAMD_4FS_RATTLE_RESEARCH.md`.
- Never write `NADOC_*`/hand-edit a production conf to a lower dt to "get it running." A run
  that only survives below 4 fs is not a shippable production result.

Related: [[REFERENCE_RUNPOD_RUNBOOK]], [[project_benchmark_tuning]], [[oxdna_relaxation]],
[[periodic_md]], [[crossover_parameterization]], [[gpu-value-is-two-axes]].

---

## The relaxation protocol must NEVER constrain the production timestep (2026-07-28)

**User correction, verbatim in spirit:** *"The purpose of the relax is to get the atoms in
positions such that the user can run a production run with any settings they wish."*

A ladder exists to deliver equilibrated **coordinates**. Once it has, production samples them at
whatever sanctioned timestep the user picks. The relax's own integrator is an implementation
detail of how the coordinates were reached, not a property of the coordinates.

I violated this by refusing 2/4 fs production on any `declash` package, on two premises that
both fail:

- **"no HMR PSF"** — production **builds one on demand** from the package's own PSF
  (`write_hmr_psf`; `_append_production_segments` already did this). It is an artefact the fast
  ladder happens to leave behind, never a prerequisite. `md_ensemble.build_replica_package` now
  does the same instead of silently downgrading 4 fs → 1 fs when the parent lacked one.
- **"residual ssDNA contacts crash RATTLE"** — that describes the **starting** structure, which
  is exactly what the ladder removed. Measured: a `rigidBonds all` 2 fs production off a declash
  relax ran 412k steps with zero RATTLE failures.

**Cost of getting it wrong:** the refusal path marked the *parent* job failed, flipping a
completed 12/12 ladder to "failed" in the job list and discarding the record of hours of work.
A production request is never a property of the run that produced the coordinates — **treat the
relaxation as read-only from the production route.**

**Warn, never block.** 4 fs on an extra-base design can still hit the Fix-B problem (HMR lightens
C5' on unpaired inserts → RATTLE), so the plan returns `timestep_warning`. That is an empirical
stability question the run answers, and the instability rescue already handles it — it is not
grounds to forbid the attempt. See [[project_extra_base_4fs_geometric_fixb]].
