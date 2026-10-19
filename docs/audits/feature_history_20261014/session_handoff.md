# Dependency overhaul session handoff

Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Updated: October 19, 2026 (S63, Claude session). **Sessions since last gate flip or milestone close: 2**
(last reset: routing step editor gate ON, October 18; S61 and S63 flipped nothing).
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

**Bend/Twist C8 (S61 + S63, 18hb × 504 bp scaffolded, autostapled, routed whole-bundle bend):**
- Browser preview update, GPU raster excluded (this desktop renders WebGL on the CPU via
  SwiftShader): median **1.17 s**, p95 **1.23 s** (session start 1.75 / 1.98 s; budget 0.5 s, 2× = 1.0 s).
  Split: server + headers ~0.73 s (in-process evaluate ~0.67 s), body 0.06 s, client ~0.41 s.
- Shipped: compact v3 preview transport (f64 block), arm-frame memoization (engine pins moved via
  reviewed transition `preview-axis-frame-cache-v1`, user-approved), loopback no-gzip, GC pause,
  hidden-tube skip, single validation/decode. Apply 0.2–0.6 s; Open 4.5 s server / ~6 s browser.
- Remaining server cost is spread thin (geometry 0.14, record validation incl. guard slab recompute
  0.14, axes 0.09, prefix deep copy 0.05, 4 whole-model admissions 0.06 s). Evidence:
  [Bend/Twist plan S61/S63](bend_twist_release_acceptance.md); spec `e2e/bend_preview_latency.spec.js`.

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

**ID:** S64 — Bend/Twist C8: per-session reuse in preview evaluate (server half).
**Objective:** within one open preview session, compute topology-only work once (record inventory,
prefix admission, scalar record rows) and reuse it for every slider evaluate; send only the f64
block plus a reference to the prepare-time rows. Keep every coordinate guard (finite, slab
registration) per evaluate. **Acceptance:** `bend-large` p95 measured and recorded; decoded
records equal full projection on fixtures; history browser suite passes. **Exclusions:** dropping
guards, geometry/constants changes, new endpoints or lifecycle layers. **Stop:** if p95 cannot
reach 1.0 s, report the gap and the progressive (axes-first) option to the user.

## User decisions pending

1. **C9 legacy-editor removal list** (approve items individually; until covered, parts with these
   use the legacy editor). Display (`part_deformation_preview_dto._admit`, `check_scope`, frontend
   DNA validator) and/or replay (`_before_command`) refuse:
   a. strand extensions (`extensions`; extension-upsert/delete replay is admitted)
   b. overhang linkers (`overhang_connections`, `__lnk__` helices, linker strands; linker-add/patch/delete)
   c. overhang bindings and duplexes (`overhang_bindings`, `duplexes`, binds_overhang domains; duplex-*)
   d. connection versions (`connection_versions`; overhang-bulk pending actions)
   e. staple groups (`staple_groups`; display metadata only)
   f. cluster joints and Join constraints (`cluster_joints`, `cluster_join_constraints`; cluster-join)
   g. flexible segments (`flexible_segment_marks`, `flexible_connections`; flexible-relax)
   h. nanoparticles (+ conjugations, connection versions, `__np__` helices; nanoparticle-*)
   i. proteins and streptavidin (`protein_assets`, `protein_attachments`, `__strep_dna__`; protein-*)
   j. photoproducts/CPD (`photoproduct_junctions`; photoproduct-*) — experimental
   k. numerical relax/refine rows (duplex-relax, flexible-relax, nanoparticle-connection-relax,
      autorefine-skips, cando-autorefine-marks, scaffold-budget-fit, encode-sweep-curvature)
   l. other unreplayed kinds: legacy auto-scaffold, route-for-polymerization, create-near/far-ends,
      cluster-paste, element-paste, cluster-pose, curve-path, aptamer/protein import, generate-design
   m. old files without a recipe root (§10 says not required; removing the fallback drops editing
      their bends/twists)
   Removal targets once approved scope is covered: `_legacyDeformationEdit` (app/feature_editor.js),
   `onUnsupported` in ui/deformation_tool_launcher.js and ui/blunt_end_menus.js, and the legacy
   mutating deformation preview/PATCH routes.
2. **Sealed-path failures (11 of 13):** uncommitted Codex work makes strict mode admit sealed preview
   and display routes (`part_strict_http.py` hunks; untracked `part_strict_deformation_preview_http.py`,
   `part_immutable_display_reads.py`, `part_strict_service_reads.py`, `part_strict_activity_reads.py`,
   7 untracked test files). Contract parks the sealed path. Options: park behind an off switch,
   delete, or finish it (R3).
3. **Junction-balance tolerance (2 of 13):** measured O5′ placement (mandatory since `29046524`) gives
   DX arc deltas 1.016e-3 nm (square) / 1.368e-3 nm (honeycomb) vs the pre-measured 1.0e-3 tolerance
   (sibling test already uses 1.1e-3). Geometry oracle — approve new tolerances or review placement.
4. **Progressive preview** (if S64 misses): draw deformed axes first (~0.1 s server), nucleotides after.

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
