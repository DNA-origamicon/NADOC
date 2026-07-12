---
name: snupi-mimic
description: Plan — recreate base SNUPI "for free" (transcribe published params into the existing CanDo FEM + validate vs on-disk atomistic MD). Extra-crossover-base extension = the only paid MD.
metadata:
  node_type: memory
  type: project
---

# SNUPI mimic — get base SNUPI for free

**Goal:** Test whether *base* SNUPI can be recreated at ~$0 new MD by (1) transcribing SNUPI's
published per-motif parameters (`Literature/SNUPI_SI.pdf`, Tables S1–S5) into a param DB and
(2) wiring them into NADOC's existing corotational beam FEM (`backend/physics/fem_solver.py`),
then validating against on-disk full-atomistic MD (6hbx100_noT). If it holds, the
extra-crossover-base extension (the only part needing GPU MD) plugs into the same param DB.

## Why this is cheap (established 2026-07-11)
- SNUPI (Lee/Kim, ACS Nano 2021) ran **almost no new MD**: regular+nicked BP steps = published
  3DNA values (SI Tables S1–S2); CO motifs = **reused** Bathe-2012 trajectories (the 32-hb
  honeycomb bundles, Fig S2) + a few additions (SI Note S14). All **74-motif** params are
  printed in **SI Tables S1–S5**; Figure S1 plots them.
- SNUPI's model = the **same corotational per-bp beam FE as CanDo**, plus three deltas. NADOC's
  `fem_solver.py` is already a CanDo-replica **validated** vs CanDo (RMSF 0.8–0.97, twist
  ~10–30%, bend ~0.9 — see [[project_cando_fem]]). So this is a small delta on validated code,
  not a rebuild.

## The three deltas (CanDo → SNUPI)
1. **Anisotropic per-motif 6×6 stiffness**, sequence-dependent (6 rigidities EA/GAy/GAz/GJ/EIy/EIz),
   74 motif types — vs the current isotropic scalar EA=1100 / EI=230 / GJ=460. Transcribe S1–S5.
2. **15 coupling coefficients** per motif (trans–rot, incl. twist–stretch ≈ −277 pN·nm) — currently none.
3. **Debye–Hückel inter-helix electrostatic elements** (SI Notes S6/S7) — the one genuinely new
   solver piece; today inter-helix coupling is via crossover links only. **Deferrable to P3.**

## Validation data — ON DISK, no new MD
- **6hbx100_noT** — standard 6-helix honeycomb, no extra bases; complete set at
  `workspace/md_jobs/892ad3d12d4f/package/6hbx100_noT_namd_solvated/` → psf + pdb +
  **20 ns k=0 production DCD (1.96 GB)**. **Primary base-SNUPI target.**
- **3x4SQ** — square lattice, k=0 DCD (`workspace/md_jobs/93cdbbd3a3f1/...`) → validates SQ params.
- 6hbx100_1xT / 2xT, 6hb_2xT — extra-base variants → the EXTENSION targets (base SNUPI can't
  predict these; use after the Δbase extra-base motifs are added).
- ⚠ **18hb trajectory is NOT on this machine** (job `e29d1e5d5ace` absent; only exp30 summary
  docs in `experiments/exp30_18hb_production/`). The 39 GB DCD lives on the work computer —
  sync it if you want 18hb as an extra target; **not needed to start**.
- ⚠ **`Literature/SNUPI_SI.pdf` is gitignored (local only)** — run this plan ON THIS MACHINE,
  or re-copy the SI + main paper on the other computer first.

## Phases
- **P1 — Transcribe params ($0, ½–1 session).** Read SI Tables S1–S5 (+ Notes S3–S5 for
  definitions/units) → `backend/data/parameters/snupi_params.json` (74 motifs ×
  {geometry6, rigidity6, coupling15}; HC + SQ where they differ; record units nN / pN·nm² / pN·nm).
  Cross-check a few CO-step values vs existing `bundle_stiffness.json` (our 10hb 0T extraction) —
  a gross mismatch ⇒ transcription/convention error, flag it. Pin: pytest loads the JSON,
  74 motifs present, values finite, coupling symmetric.
- **P2 — Wire 6×6 anisotropic stiffness into fem_solver (1 session).** Extend `_beam_stiffness_local`
  (scalar → 6×6 material matrix) + add the coupling block; classify each element's motif type +
  read its 2-base sequence via existing `_duplex_bp_per_helix` / `_nick_bps_per_helix` / crossover
  detection. Behind a flag `material="snupi"|"cando"` so the CanDo baseline stays intact + comparable.
  Pin: existing `tests/test_fem_solver.py` green (cando); new test — snupi material loads + solves a fixture.
- **P3 — Electrostatics (SI S6/S7, 1 session, optional for a first result).** Debye–Hückel repulsion
  spring elements between near helices (scaffolding exists: `FEMSpring`, `assemble_field_force`).
  Defer until P4 shows inter-helix spacing / lattice is wrong without it.
- **P4 — Validate vs 6hbx100_noT (1 session).** From the k=0 DCD compute per-bp RMSF (bp-center =
  mean of both-strand C1' — reuse `local_crossover_extract.py` / `build_p_gro_order`), equilibrium
  shape, twist/bend, L_p. Run the mimic FEM on the design → RMSF/shape. Compare RMSF-pattern
  correlation, shape RMSD, twist/bend, L_p for **snupi vs cando vs MD**. Extend to 3x4SQ.
  Success = snupi-material matches MD **at least as well as** cando-isotropic, at $0.

**Verdict test:** "SNUPI for free" = YES if transcribed params + the existing FEM reproduce MD
(and SNUPI's published) shape/RMSF within a stated tolerance. Then the extra-base extension is the
only GPU spend (~$3–8k — [[project_bundle_stiffness_params]] / [[project_crossover_parameterization]]),
plugging into the same param DB.

## Risks / rules
- **Convention conversions** (3DNA vs beam element; SNUPI's own co-rotated local triad). The
  `bundle_stiffness.json` cross-check catches gross errors. Transcribe SNUPI's OWN convention —
  do NOT reuse the Euler-ZYZ extraction pipeline (gimbal-locked K_q3/K_q5; see
  [[feedback_bundle_param_extraction]]).
- **Three-Layer Law:** FEM output is PHYSICAL/display only, never writes topology.
- Don't touch `_PHASE_*`. Concurrent sessions share this tree — never git stash/reset/restore/checkout;
  forbid git in subagent prompts.

## Handoff
Entry point = this file. Start P1. Key references: `backend/physics/fem_solver.py`,
`Literature/SNUPI_SI.pdf` Tables S1–S5 (grep the SI for "Table S1"; they sit after the figures),
[[project_cando_fem]] (existing FEM state + scorecard), [[feedback_bundle_param_extraction]]
(convention lessons), `backend/data/parameters/bundle_stiffness.json` (our 0T cross-check values).
