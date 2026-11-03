---
name: project_oxdna_efield
description: PLAN ONLY (2026-06-18) — electric-field forces in oxDNA via per-nucleotide string forces + overhang/cluster anchor traps; new field-production stage; deflection-map + field-arrow viz in the Dynamics panel.
metadata: 
  node_type: memory
  type: project
  originSessionId: 04f374be-7bd2-410d-9aa3-d95baabd5f73
---

# oxDNA Electric-Field Forces — PLAN ONLY (2026-06-18)

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

<a id="-field-direction-rotation-rings--azel-inputs-replaces-tip-drag--xyz-boxes--2026-07-16-out-of-session-work"></a>
- [⚡ Field direction: rotation RINGS + Az/El inputs (replaces tip-drag + xyz boxes) — 2026-07-16 (out-of-session work)](details/project_oxdna_efield/01-field-direction-rotation-rings--azel-inputs-replaces-tip-drag--x.md#-field-direction-rotation-rings--azel-inputs-replaces-tip-drag--xyz-boxes--2026-07-16-out-of-session-work)

## 1. Physics & the load-bearing gotchas

- **oxDNA has NO native E-field force.** Force types: string, mutual_trap, trap, twist,
  repulsion_plane(+moving), attraction_plane, sphere/yukawa_sphere, com, LJ_wall, sawtooth,
  hard_wall, repulsive_sphere_moving, repulsive_kepler_poinsot. The one we use is **`string`**
  = a constant (or linearly-ramping) force `F = F0·dir` (+`rate`·t) on selected `particle`s.
- **Uniform field ⇒ equal constant force on every nucleotide.** DNA backbone carries ~1 charge
  per phosphate (≈1 per nucleotide bead in oxDNA's 1-bead-per-nt model). A uniform E pushes every
  bead with the same `F0` along the same `dir`. So an "E-field" = N identical `string` blocks
  (or one block with `particle = all`, same `dir`).
- **GOTCHA 1 — COM drift (the big one).** Equal force on all beads = net force on the
  center of mass ⇒ a free structure just streams across the periodic box. **Anchors are
  physically required, not a convenience.** Pin part of the structure; the anchored beads
  absorb the net force and the rest deflects against them (the Kopperger 2018 tethered-arm
  regime — *A self-assembled nanoscale robotic arm controlled by electric fields*, Science 359:296).
  **POLICY — WARN-ONLY, ALL ENGINES, STANDING (ratified 2026-07-11; supersedes any "requires an
  anchor / →400" language anywhere below or in the ledgers).** A missing anchor NEVER blocks a run
  on ANY engine (mrDNA / oxDNA / NAMD / LAMMPS), in ANY layer (REST, runner, live session,
  chain-stage, AND every UI launch button). An unanchored field runs; the user gets a non-blocking
  COM-drift *warning* only. The shared predicate is `field_anchor.field_needs_strand_anchor`
  (advisory — decides whether to SHOW the warning, it does NOT gate a 400). Currently ACTIVE in
  code: verified no backend path 400s/raises on missing-anchor, and the last UI hold (the mrDNA
  panel launch) was changed to warn-and-proceed on 2026-07-11. Any future field/anchor work MUST
  stay warn-only. See "Anchor requirement relaxed to a warning" below.
- **GOTCHA 2 — quasi-static only.** oxDNA models no explicit ions/screening and no
  hydrodynamics, and its timestep can't reach kHz AC fields. This captures the **mechanical
  deflection of a tethered structure under a steady field**, NOT free-solution electrophoretic
  mobility or gel migration. Document this prominently; don't let it be read as a mobility predictor.
- **GOTCHA 3 — effective charge is contested.** Manning counterion condensation drops the
  effective backbone charge to ~0.25 e/phosphate, and it's salt-dependent. So a V/m→force
  conversion has a soft fudge factor. → We make **force-per-nucleotide the canonical stored
  value** (honest about what oxDNA applies); a V/m helper fills it in via an *editable*
  effective-charge constant.
- **Sign convention.** Force on the (negative) backbone is antiparallel to E. With force
  canonical, the user effectively sets the *force arrow* (where DNA is pushed); the V/m helper
  points force opposite to the entered field.
- **Unit conversion:** 1 oxDNA force unit ≈ **48.63 pN**. `F0_oxdna = F_pN / 48.63`. V/m helper:
  `F_pN = q_eff · e · E(V/m) · 1e12` with `q_eff≈0.25` (editable), `e=1.602e-19 C`.
- **Stage interaction.** Existing relaxation uses mutual traps (pairing) in stages 1–2, dropped
  for equil/production. The field is a **new production-like stage**: `external_forces=True`,
  but the forces file holds **field string-forces + anchor traps**, NOT the pairing mutual_traps.
  → forces-file generation must become *composable* (sources: pairing | anchors | field).
- **Optional:** a `repulsion_plane` at the anchor surface models the substrate the origami is
  tethered to (stops it passing through). Defer to a later phase.

<a id="2-anchors-decision-clusters--domains--overhangs-overhangs-recommended"></a>
- [2. Anchors (decision: clusters / domains / overhangs; overhangs recommended)](details/project_oxdna_efield/02-2-anchors-decision-clusters--domains--overhangs-overhangs-recomme.md#2-anchors-decision-clusters--domains--overhangs-overhangs-recommended)

<a id="3-backend-changes-headless-first-per-feature_development"></a>
- [3. Backend changes (headless-first, per FEATURE_DEVELOPMENT)](details/project_oxdna_efield/02-2-anchors-decision-clusters--domains--overhangs-overhangs-recomme.md#3-backend-changes-headless-first-per-feature_development)

<a id="4-validation-oracle-anti-shovel--assert-a-property-not-http-200"></a>
- [4. Validation oracle (anti-shovel — assert a property, not HTTP 200)](details/project_oxdna_efield/02-2-anchors-decision-clusters--domains--overhangs-overhangs-recomme.md#4-validation-oracle-anti-shovel--assert-a-property-not-http-200)

<a id="5-frontend-ux-decisions-extend-dynamics-panel-viz--deflection-map--field-arrows"></a>
- [5. Frontend UX (decisions: extend Dynamics panel; viz = deflection-map + field arrows)](details/project_oxdna_efield/02-2-anchors-decision-clusters--domains--overhangs-overhangs-recomme.md#5-frontend-ux-decisions-extend-dynamics-panel-viz--deflection-map--field-arrows)

<a id="6-phasing"></a>
- [6. Phasing](details/project_oxdna_efield/03-6-phasing.md#6-phasing)

- [6. Phasing — continued detail](details/project_oxdna_efield/04-6-phasing.md)

<a id="fieldanchor-setup-viz-2026-06-19-shipped"></a>
- [Field+anchor setup viz (2026-06-19, SHIPPED)](details/project_oxdna_efield/04-6-phasing.md#fieldanchor-setup-viz-2026-06-19-shipped)

<a id="live-ephemeral-re-aimable-field-mode-2026-06-23-shipped"></a>
- [Live (ephemeral, re-aimable) field mode (2026-06-23, SHIPPED)](details/project_oxdna_efield/04-6-phasing.md#live-ephemeral-re-aimable-field-mode-2026-06-23-shipped)

<a id="live-latency-speedups--cuda--in-memory-readout-2026-06-23"></a>
- [Live latency speedups — CUDA + in-memory readout (2026-06-23)](details/project_oxdna_efield/04-6-phasing.md#live-latency-speedups--cuda--in-memory-readout-2026-06-23)

<a id="live-reconfigure--toggle-floor--e-field--anchors-mid-session-2026-06-23"></a>
- [Live reconfigure — toggle floor / E-field / anchors mid-session (2026-06-23)](details/project_oxdna_efield/05-live-reconfigure--toggle-floor--e-field--anchors-mid-session-2026.md#live-reconfigure--toggle-floor--e-field--anchors-mid-session-2026-06-23)

<a id="out-of-date-job-guard--design-edited-after-a-relax-2026-06-23"></a>
- [Out-of-date job guard — design edited after a relax (2026-06-23)](details/project_oxdna_efield/05-live-reconfigure--toggle-floor--e-field--anchors-mid-session-2026.md#out-of-date-job-guard--design-edited-after-a-relax-2026-06-23)

- [Roll/return re-audit (2026-08-08) — continued detail](details/project_oxdna_efield/05-live-reconfigure--toggle-floor--e-field--anchors-mid-session-2026.md)

<a id="rollreturn-re-audit-2026-08-08"></a>
- [Roll/return re-audit (2026-08-08)](details/project_oxdna_efield/05-live-reconfigure--toggle-floor--e-field--anchors-mid-session-2026.md#rollreturn-re-audit-2026-08-08)

<a id="trajectory-arrow-follows-the-on-screen-runs-field-2026-07-06-shipped"></a>
- [Trajectory arrow follows the on-screen run's field (2026-07-06, SHIPPED)](details/project_oxdna_efield/06-trajectory-arrow-follows-the-on-screen-runs-field-2026-07-06-ship.md#trajectory-arrow-follows-the-on-screen-runs-field-2026-07-06-shipped)

## Anchor requirement relaxed to a warning (2026-07-10, SHIPPED)
The hard "a uniform field needs ≥1 anchor" restriction is GONE on every engine — a field
with no anchor (and no opposing surface) is now allowed, with the UI showing a non-blocking
warning notice about the resulting centre-of-mass drift. User decision; scope = all engines,
warning surfaced frontend-only.
- **Backend (all 400/raise guards removed → allow + warn/log):** oxDNA `/field` + `/run`
  (`routes_oxdna.py`), oxDNA live `/start` + `/reconfigure` + the `n_anchored==0` start guard
  (`routes_oxdna_live.py`), NAMD single-job create + chain create (`routes_md.py`), NAMD prep
  (`md_protocols.py` → `logger.warning`), mrDNA create (`routes_mrdna.py`) + runner
  (`mrdna_runner.py` → `logger.warning`, the `n_held==0` raise softened), LAMMPS
  (`lammps_runner.py` → `logger.warning`). `oxdna_interface.write_field_forces` no longer raises
  on empty anchors — it writes the field `string` block with no traps. CanDo/FEM already fell
  back to a centroid pin (unchanged). The shared predicate `field_anchor.field_needs_strand_anchor`
  + its tests are KEPT (still a valid physics helper) but no backend caller blocks on it anymore.
- **Frontend (warning notice, no block):** `forces_card.js` apply-style ready line now reads
  "⚠ no anchor — the whole structure will drift down-field…" (conditioned on a new `getAnchorCount`
  dep wired for oxDNA/CanDo/NAMD; clears once an anchor is added). The launch/POST blocks were
  removed from `oxdna_jobs_panel.js`, `md_jobs_panel.js`, `cando_jobs_panel.js`, and
  `oxdna_live_controller.js` (start + reconfigure). `chain_sim_model.stagePreflight` ALREADY
  treated this as a `warn` (unchanged) — now aligned with the backend that no longer 400s the chain.
- **Tests flipped** (were asserting the block): backend — `test_oxdna_relaxation` (write_field_forces
  writes field-only), `test_oxdna_surface`, `test_headless_oxdna_build`, `test_namd_efield` (×2),
  `test_mrdna_field`, `test_lammps_routes` + `test_lammps_runner`, `test_oxdna_live_session` (×2),
  `test_chain_completion_e2e`; frontend — `forces_card.test`, `oxdna_live_controller.test` (×2).
  Full backend suite 4665 pass (2 flipped after the FULL run); frontend 2614 pass.

## 7. Open questions to resolve before/within Phase 1

- Default anchor `stiff` and field-stage length/`dt` (start from the equil stage's values).
- Ramp the field (`rate>0`) to avoid a startup kick, or step it on? (Lean: short linear ramp.)
- Box size / PBC: a deflecting tethered arm needs head-room; may need a larger box than relax.
- Substrate `repulsion_plane` at the anchor face — Phase 3+ / ask.
