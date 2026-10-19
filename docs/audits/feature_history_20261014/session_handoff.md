# Dependency overhaul session handoff

Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Updated: October 19, 2026 (S61, Claude session; history browser suite 42 passed). **Sessions since last gate flip or milestone close: 1**
(last reset: routing step editor gate ON, October 18, user-requested; S61 flipped nothing).
**Tools done: 0/4.** Bend/Twist gates are ON; C8 (large-part preview) and C9 (legacy fallback
scope) remain. CAD ledger: **20/34 complete, 14 remaining (7 core, 7 parked)**.

## Current state by tool

| Tool | Gate | Contract status |
|---|---|---|
| Bend/Twist | ON (`DEFORMATION_PREVIEW_ENABLED`, `ISOLATED_DEFORMATION_{HISTORY,CREATION}_ENABLED`) | C1–C7 pass. C8: see below. C9: legacy editor remains the fallback for parts the isolated editor refuses (nanoparticles, proteins, photoproducts, imports, relax/autorefine kinds) — remove per §10 once covered. |
| Extrude | ungated (owned extrusion route) | Seven families qualified on tiny fixtures (S51/S52). C8 unmeasured on real parts; failures/races open. Still on the immutable geometry host. |
| Sweep | OFF (`SWEEP_HISTORY_EDITOR_ENABLED`, `SWEEP_PREVIEW_ENABLED`) | S50/S53 qualified with test-only gates. S54 (downstream nick success/refusal) unstarted. Immutable host (R3). |
| Move/Rotate history | OFF | Not a contract tool. |
| Fine-routing step editor | ON (`ROUTING_HISTORY_EDITOR_ENABLED`) | Edits v1 and positional v2 children. Not a contract tool. |

**Bend/Twist C8 (S61, 18hb × 504 bp scaffolded, autostapled, routed whole-bundle bend):**
- Before S61 the browser refused real parts outright (frontend toy display caps); fixed.
- Preview update in the browser, GPU raster excluded (this desktop's headless WebGL is SwiftShader,
  ~2 s/frame): median **1.46 s**, p95 **1.67 s** alone; 1.59 / 1.73 s inside the full suite
  (budget 0.5 s; 2× allowance 1.0 s → ~3×).
  Split: server + headers ~0.95 s (in-process evaluate 0.63–0.70 s), body 0.08 s, client ~0.6 s.
- Apply 0.2–0.6 s; Open (prepare) 4.5 s server / ~6.3 s browser (no contract budget).
- 18hb × 252: server evaluate 0.35 s → expected within the allowance. Small parts pass.
- Kept out pending review: arm-frame memoization in `deformation.py` (byte-identical; browser
  median 1.27 s / p95 1.42 s) — that file is pinned by the CPD and duplex-relax engine manifests.
- Evidence: [Bend/Twist plan S61](bend_twist_release_acceptance.md); spec
  `frontend/e2e/bend_preview_latency.spec.js` (fixture `bend-large`; `NADOC_C8_SPLIT=1` phase split,
  `NADOC_C8_PROFILE=1` CPU profile, `NADOC_C8_BUDGET_MS=1000` contract check; default ceiling 3 s).

## Delivered since the S58 handoff (details in commits and the Bend/Twist plan)

- **R1 replay cache** (`core/part_replay_cache.py`): hash-chained results; Bend/Twist edits reuse
  deformation-independent routing topology. Apply on 18hb×504: 3.5 s → 0.16–0.25 s.
- **R2 converter** (`core/part_legacy_conversion.py`): delivered, now unmaintained (contract §10).
- **Occupancy invariant** (`core/occupancy.py`): one base per (helix, bp, direction); every mutable
  publication path refuses violations (409 `nucleotide_double_occupancy`). Sealed/immutable
  publication is not decoded in the parent — its worker must check before re-enabling (R3).
- **Fine-routing auto-removal** (`core/fine_routing_targets.py`): an upstream edit that leaves a
  routing child with every target unoccupied removes it (reported; one undo restores). Anything
  else still refuses and names the feature.
- **Positional references** (`core/positional_refs.py`, proof v2): resize, domain shift, forced
  ligation and crossover edits record positions and resolve to the current occupant.
- **Routing step editor ON**; **region autostaple** (`region` on `/design/full-autostaple`, selection
  popup "Autostaple scope"; untouched staples kept exactly; 42/42 regions reproduce the whole run).
- **S61 preview latency** (above), plus a fix for a spurious "Dimensions could not be saved" toast.

## Single next bounded task

**ID:** S63 — Bend/Twist C8: compact coordinate transport for the preview DNA component.
**Depends on:** user decision 1 below. If the user raises the full-size budget so 1.67 s passes,
skip S63, flip nothing (gates are ON), close C8 and take the C9 scope task instead.
**Objective:** cut the per-update transfer/parse/decode cost (~0.25 s of the 1.46 s) by sending the
numeric record columns (positions, normals, tangents, slab pose, helical site) as one base64
little-endian Float64 block per column group in a new preview component version, decoded once into
the existing record objects. Lossless (bit-identical doubles); string/flag columns unchanged.
**Files:** `backend/core/part_dna_comparison{,_codec}.py`, `backend/api/part_deformation_preview_dto.py`,
`frontend/src/features/part_dna_comparison_{codec,model}.js`, `frontend/src/scene/part_dna_comparison_layer.js`,
their tests. Repair comparison (v3) may keep JSON rows.
**Acceptance:** decoded records deep-equal today's rows on HC/SQ fixtures (unit, both sides); browser
p95 on `bend-large` measured and recorded; history browser suite passes.
**Exclusions:** geometry/constants, `deformation.py` and other engine-pinned sources, new lifecycle
layers or endpoints. **Stop:** if p95 cannot reach 1.0 s without engine-pinned edits, report the
remaining gap to the user rather than continuing.

## User decisions pending

1. **Full-size preview budget.** 18hb × 504 is ~2.9× the 500 ms budget (contract §3 is user-revisable).
   Either revise the large-design preview budget, or keep it and fund S63 (+ decision 2).
2. **Engine-manifest transition for `deformation.py`.** Approve recording a reviewed
   source-pin transition so the byte-identical arm-frame memoization (−0.2 s/update) can ship.
3. **C9 scope.** Which parts must the isolated editor cover before the legacy Bend/Twist editor is
   removed (nanoparticles, proteins, imports, relax/autorefine kinds), or keep it as the fallback.
4. Whether to triage the 13 pre-existing `test-smart` failures (10 from untracked sealed strict
   admission, 1 immutable evaluation, 2 junction-balance tolerance).

## Known gaps outside this handoff's task

- VR: `MV-VR-AUTOSTAPLE-SCOPE` in `manual_validation_debt.md` (needs the VR machine).
- Fast suite ~370 s vs 90 s backstop; slow-test triage deferred.
- R3 (Sweep/Extrude onto the preview-session host) and R4 (dependency view, error/blocked states,
  suppress/reorder) not started; the dependency model is mostly a linear topology barrier.

## Session discipline and Git

One task per session; ≤ 15 appended plan evidence lines; no new reports; handoff ≤ 150 lines.
Commits: explicit overhaul-only paths and hunks. Exclude untracked Codex harness/sealed files
(`part_strict_service_reads.py`, its test, `frontend/playwright.deformation-history.config.js` is
untracked but carries this overhaul's spec list) and other sessions' hunks (e.g. in `client.js`).
