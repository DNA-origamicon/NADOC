# Relax presets shipped (2026-07-29) — `backend/core/md_presets.py` — supporting detail

[Topic head](../../REFERENCE_AKSIMENTIEV_PROTOCOL.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Relax presets shipped (2026-07-29) — `backend/core/md_presets.py`

**ONE control**, **defaults to Standard**.  Since 2026-08-03 it lives in the **Job Wizard**
(`＋ New job`), not in a launch-form dropdown — `#md-jobs-relax-preset` is gone with the
Advanced card.  See `project_md_job_system.md`.
The old `#md-jobs-preset` protocol dropdown is GONE — there were briefly two menus both
labelled "Protocol", and they could contradict: the panel always sent `protocol`, so it
always sat in `model_fields_set` and the preset's own protocol never won. "Standard
(Aksimentiev)" + separately-selected implicit solvent produced a job promising explicit
MgCl₂/CUFIX and running with no water at all, uncaught.

| id | label | protocol | state |
|---|---|---|---|
| `fast_shape` | Fast Shape Check (Vacuum) | `vacuum_enrgmd_namd` | **SHIPPED 2026-07-30** |
| `implicit_gbis` | Implicit Solvent (GBIS) | `implicit_gbis_namd` | **host-gated** — needs a non-CUDA NAMD build, so DISABLED on this machine |
| `standard` | Standard (Aksimentiev) | `equilibrium_aware_namd` | **default**; runs the vacuum stage first |
| `full_physics` | Slow (full physics) | `equilibrium_aware_namd` | padding 2.5 nm, early-stop OFF |
| `design_speed` | Optimised for the design (fast) | `equilibrium_aware_namd` | **2026-08-03**; every measured accelerator on: HMR + 4 fs, early-stop ON, bbox cell (padding 1.2 nm), production dt 4 fs |
| `literature` | Match the literature (Aksimentiev) | `equilibrium_aware_namd` | **2026-08-03**; nothing traded for speed: early-stop OFF, `fast=False`, padding 2.0 nm, production dt **2.0 fs** (the paper's), and `allow_water_shell_carve=False` — a carve is REFUSED, not auto-fitted, because it forces NVT and so deletes the settle stage AND the box-size equilibration criterion |

The two 2026-08-03 tiers exist because that is the question a run actually turns on: are you
reproducing the reference, or getting an answer about your design?  `standard` /
`full_physics` / `implicit_gbis` are unchanged so existing jobs stay reproducible.

⚠ **Availability is HOST-aware, not just build-aware** (`preset_availability`). GBIS is
unsupported on the NAMD 3 CUDA nonbonded kernel (crashes in `buildTileLists`), so it needs
a multicore build — which this machine does not have. Two bugs were found by actually
running it, both now fixed:

1. `prepare_implicit_gbis_namd()` did not accept `gpu_resident_mode` /
   `production_timestep_fs`, so **every GBIS job had been failing at prep since commit
   8823377 (2026-07-28)** — the GPU-resident dropdown added them to the ONE shared
   `run_in_threadpool(prepare, ...)` kwarg set without updating that signature. Pinned by
   `tests/test_prepare_signatures.py`, which parses the real call site with `ast` and
   checks every protocol's entry point against it.
2. Even with prep fixed, the run died on the first segment because of the CUDA build. The
   preset now probes `find_namd(prefer_cpu=True)` at catalogue time, so the menu greys it
   out **and** `POST /md/jobs` 400s up front instead of paying for solvation first.

To actually use GBIS here, install the multicore build at
`~/Applications/NAMD_3.0.2_Linux-x86_64-multicore/namd3`; the preset re-enables itself.

**`protocol` is DERIVED from the preset, never separately selectable.** `_apply_relax_preset`
forces it; every other field is a default that an explicit request value overrides. API
compatibility: `protocol` alone (no `relax_preset`) is still honoured as the legacy path;
both-and-agreeing is fine; both-and-contradicting is a **400**, not a silent override.

**`mgh_slow_release` is retired from the menu, not from the API** — it is
`equilibrium_aware_namd` with `require_full_topology` OFF (`prepare_equilibrium_aware_namd`
is a four-line wrapper that adds the gate), i.e. a validation choice wearing a protocol's
label. Old jobs and scripted callers still work; `presetIdForProtocol` maps it to `null`
so a draft recorded with it restores to the default, which is the same ladder anyway.
`GET /md/relax-presets` serves the catalogue; the UI module is
`frontend/src/ui/md_relax_presets.js` (16 vitest tests) and renders an unavailable tier
disabled-with-reason rather than hiding it.

**`fast_shape` SHIPPED AND WAS RETIRED, 2026-07-30 — read this before reviving it.**
The tutorial's §3.2 unfolds caDNAno's abstract parallel-helix lattice. NADOC *derives*
geometry from topology + B-DNA constants + deformations, so no design ever arrives in
that state (measured: `6hbx100_90deg`'s ideal build already holds ~98.5° of per-helix
bend). Worse, the repulsion surrogate needs a >22 nt crossover-free span while honeycomb
crossovers recur every 21 nt → **zero push bonds** on a dense bundle → the run has no
interhelical force term at all, and bundles swelled 5.6–10% AWAY from the Mg-screened
equilibrium. Reviving it needs a NADOC-native spacing restraint (the lattice pitch is
known from topology), not mrdna's transplanted rule. Historic note follows.

 Both blockers this used to list are closed: the
placement rule is `backend/core/namd_push_bonds.py` (mrdna's, ported from exp48 with its
self-test now collected as `tests/test_namd_push_bonds.py`), and the DNA-only package
path is `backend/core/namd_vacuum.py`. The hextube's `.exb` settled the parameters —
`k = 1 kcal/mol/Å², r₀ = 31 Å`, and only **64** of them for the hextube (sparse, NOT one
per base pair) alongside 75,503 ENM terms. Reproduced exactly on NADOC designs:
2hb → 0 push bonds, 6hb → 11, 24hb → 495.

## Other defaults flipped (2026-07-29)

- **Box sizing → `rotation`** (`namd_solvate.DEFAULT_BOX_MODE`), cubic `2·r_max + 2·pad`.
  `resolve_box_mode` falls back to `bbox` **with a recorded note** when rotation would
  exceed the hardware's atom cap — a cell too big to run is not safer than one too small,
  because it forces a carve, which forces NVT, which kills the free stage rotation sizing
  existed to protect. Cap comes from the same `md_vram` helpers the carve sizer uses
  (3.17 M atoms on this box); estimator validated against the real 2hb package
  (predicted 33,276 vs actual 32,572).
- **Electrostatics → the tutorial's** `switchdist 8 / cutoff 10 / pairlistdist 12`,
  `PMEGridSpacing 1.5`. ⚠ **`fullElectFrequency 2` was deliberately NOT adopted** — it is
  dt-dependent. At their 2 fs it means PME every 4 fs, which our 4 fs path already does
  with `fullElect 1`; copying the literal 2 would put PME on an 8 fs interval, past the
  r-RESPA resonance limit. The invariant is `PME_MAX_INTERVAL_FS = 4.0`, not the literal
  value. This costs ~12 of the measured +39 %.
- **`early_stop_relax` → ON by default** (request, model and checkbox). `full_physics`
  turns it back off — a stage you intend to publish should not be truncated.

## What of this is now implemented (2026-07-29)

Shipped: carved package ⇒ `langevinPiston off` in production AND reseed
(`package_npt_allowed` reads the manifest's new `solvation` block); `margin 3` on NPT
stages; `xstFreq` capped at 10 ps so the 300 ps criterion is resolvable; the box-trace
criterion itself as `md_cell_health.settle_report`, recorded per NPT stage on the job;
`is_collapsing` + a refusal to auto-resume a collapsing cell; `box_mode="rotation"` in
`namd_solvate` plus an always-on `box_check` in the manifest. See
[[project_water_shell_carve]] for the details and the measured thresholds.

The Note-4 settle stage IS now a default ladder segment (`_0S_`, 500 ps) — see the
"restrained, not fixed" note below for how it realises "DNA position fixed".
Also not changed: padding default (still 1.2 nm; `box_mode` still defaults to `bbox`), so
sizing is *reported* on every build but not *changed* without opting in.
