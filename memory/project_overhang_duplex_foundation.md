---
name: overhang-duplex-foundation
description: "The Duplex graph (Proposal B) — register-bearing hybridization edges over helix bp intervals. The pairing MODEL of record for overhangs: multivalency, mismatches, toeholds, different lengths. Phases 0-4b shipped; Phase 6 (retire OverhangBinding) never started. Rank P1."
metadata:
  node_type: memory
  type: project
---

# Overhang Duplex foundation (Proposal B)

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

**Rank:** P1 — the model is live, wired and is the direction the assembly tier already
committed to; two concrete Phase-4b follow-ups remain and Phase 6 is untouched.

**Status (probed 2026-07-30, `/audit-plan`).** Phases 0-4b **shipped and wired**: model,
routes, classifier, migration-on-load, producer, driver toggle, relocation, and the
2026-07-01 linker-bridge relax rewrite are all live. History is in
`project_overhang_duplex_foundation_archive.md` — **don't read it in a routine loop**;
everything current is below.

**The one thing to know before editing anything here:**

> The Duplex is the pairing model **by intent**, not yet in fact. Today it **coexists** with
> `OverhangBinding`, and which one you get depends on **length, not connection type**:
>
> | Caller | Equal-length | Different-length |
> |---|---|---|
> | **Connections panel** | binding **+** duplex — the binding relocates; the duplex is *display* (the panel's own comment `overhang_connections_panel.js:592` says "the display duplex") | **duplex only** — binding skipped `crud.py:7652`, `relocate_duplex` does the move |
> | Raw API / headless `apply_connection_version` | binding only | **NEITHER — silent no-op** |
> | Raw API / headless `connect_duplex` | duplex only | duplex only |
>
> The panel always calls `_ensureDuplexForPair` (`:595`, gated on `ctIsDirect` — **type only,
> no length or binding check**), so a UI connect always makes a duplex; `crud.py:7645-7655`
> says the duplex "is created separately by the frontend's `_ensureDuplexForPair`" — **the
> backend deliberately relies on the frontend to finish the job**, which is why the headless
> row has a hole. On the common (equal-length) path the **binding** still moves geometry and
> serves Relax: `lattice.py` and `deformation.py` read `overhang_bindings`, never `duplexes`;
> the panel's Relax precedence is linker > binding > duplex (`:438-450`), so `relaxDuplex`
> never fires there. Frontend render reads duplexes at one site (`helix_renderer.js:111`,
> unioned with bindings, only picking 360° vs 180° cylinders) — **nothing draws the
> connection**; the bond is visible because the driven tip was relocated in topology.

## Locked decisions (user, 2026-06-30) — invariants, do not drift

- **Coordinate (Q1):** reuse the existing helix bp index. `DuplexEnd = {overhang_id,
  start_bp, end_bp}` in that overhang's backing-domain helix coordinate; order encodes 5'→3'
  (mirrors `sequences.py` `bp = d.start_bp + offset*sign(end-start)`). No per-overhang slot index.
- **Register vs apply (Q1):** when APPLIED both ends are co-located on the driver's helix; the
  *relative* bp positioning on that shared helix IS the register. Moving overhangs while
  UNAPPLIED must NOT change the stored applied register.
- **Slide (Q2):** a cadnano drag UPDATES the register, never breaks the handler. Sliding to
  zero overlap is allowed — warn, don't error.
- **Mismatches yes, bulges deferred (Q3):** both ends EQUAL length (no gapped alignment).
  Per-base WC check → paired/mismatch. Bulges deferred indefinitely.
- **Driver explicit (Q4):** `Duplex.driver: 'left'|'right'`, user-set. Multivalent v1 rule:
  longest overhang drives.
- **Process (Q5):** automation + validation per phase before the next.
- **Length preservation:** connecting two DIFFERENT-length overhangs must NEVER resize either.
  The duplex pairs the shorter window (`length = min(lenA, lenB)`, anchored at each attach end);
  the longer keeps its full length and its excess becomes a **toehold**. No create/apply step
  touches `Domain.start_bp/end_bp`. Pinned by `test_duplex_crud.py:114`
  (`test_connect_different_lengths_preserves_both`) + `test_duplex_length_preserve.py`.

<a id="trap--the-one-ends-up-the-length-of-the-other-bug-user-reported-2026-06-30"></a>
- [TRAP — the "one ends up the length of the other" bug (user-reported 2026-06-30)](details/project_overhang_duplex_foundation/01-trap--the-one-ends-up-the-length-of-the-other-bug-user-reported-2.md#trap--the-one-ends-up-the-length-of-the-other-bug-user-reported-2026-06-30)

<a id="code-map-every-line-probed-2026-07-30"></a>
- [Code map (every line probed 2026-07-30)](details/project_overhang_duplex_foundation/01-trap--the-one-ends-up-the-length-of-the-other-bug-user-reported-2.md#code-map-every-line-probed-2026-07-30)

<a id="backend"></a>
- [Backend](details/project_overhang_duplex_foundation/01-trap--the-one-ends-up-the-length-of-the-other-bug-user-reported-2.md#backend)

<a id="frontend"></a>
- [Frontend](details/project_overhang_duplex_foundation/01-trap--the-one-ends-up-the-length-of-the-other-bug-user-reported-2.md#frontend)

<a id="the-relax-that-is-actually-running-2026-07-01-rewrite--supersedes-every-earlier-swing-description"></a>
- [The relax that is actually running (2026-07-01 rewrite — supersedes every earlier swing description)](details/project_overhang_duplex_foundation/01-trap--the-one-ends-up-the-length-of-the-other-bug-user-reported-2.md#the-relax-that-is-actually-running-2026-07-01-rewrite--supersedes-every-earlier-swing-description)

## Open items (rewritten against the probe — these are what is genuinely left)

1. **Phase 4b(1) — driver flip for a binding-LESS relocated duplex.** `patch_duplex` re-places
   only binding-backed duplexes (via `reapply_binding_driver`); a different-length duplex keeps
   the field edit with no geometry change. Flipping to make the SHORTER side the driver is also
   ill-defined (it would stretch the longer down) — likely constrain the toggle to longest-drives
   for different lengths. **Unclaimed by every sibling doc.**
2. **Phase 4b(2) — relax for the binding-less duplex.** `overhang_duplex_cluster` gave it a
   *placement* (midpoint seat + cluster, 2026-07-01) but not a settle. Note the doc's old claim
   that `relax_direct_binding` 422s when the driven tip isn't on the driver helix is **wrong**:
   the 422 (`direct_relax.py:108`) fires on *no relocated tip domain found*; helix identity is
   only an unasserted comment at `:373`.
3. **Phase 6 — retire `OverhangBinding` — never started, and it is not close.** `overhang_bindings`
   is READ from ~35 sites in `crud.py` plus `lattice.py:3614`, `deformation.py:1023,1135`,
   `primitive_placement.py:60`, `routes_duplex.py:127,208,274`, and **11 frontend modules**
   (`animation_player`, `helix_renderer`, `client`, `overhang_connections_panel`,
   `overhang_pathview`, `overhang_sequences_panel`, `animation_panel`, `overhangs_manager_popup`,
   `domain_designer_panel`, `assembly_overhangs_manager_popup`,
   `assembly_overhang_connections_panel`). The **assembly tier already executed this pattern** —
   `AssemblyOverhangBinding` is docstring-marked superseded + migrated-on-load
   ([[assembly_overhang_bindings]]) — so copy that playbook, don't invent one.
4. **Orphans in a "shipped" surface.** `revert_duplex_relocation` (`duplex.py:347`) has **no
   caller at all** — so a binding-less relocation cannot be reverted; `summarize_duplexes`
   (`:427`) is test-only; and the client fns `createDuplex` / `deleteDuplex` /
   `syncDuplexesFromBindings` have **zero callers** although their routes are live and registered.
   Either wire them or delete them.
5. **Reserved fields that stayed reserved.** `binding_mode`, `target_joint_id`,
   `locked_angle_deg` are **never read anywhere** — they were the Phase-4 geometry-coupling slots
   and the geometry went through `OverhangSpec.rotation/translation` instead.
6. **Stale docstring.** `models.py:537` still says *"Phase 0: this model exists and validates but
   NOTHING consumes `Design.duplexes` yet"* — contradicted by the load/import bridge, the
   validator, 9 routes and two panels. One-line fix.
7. **Four "NOT hand-driven" gestures were never filed as manual-validation debt.** Nothing in
   `manual_validation_debt.md` (repo **root**) covers: the Gen-click→choice dialog; Relax on a
   binding-less duplex; right-click-overhang-bead→extensions; the post-rewrite Relax on
   `2x2_OH_test.nadoc` (both bonds close, ONLY the duplex reorients — the clusters must not spin).
   The MV rows that do exist (MV-CONNLINK / MV-DUPMENU / MV-DUPTAUT / MV-DUPPIVOT) belong to
   [[overhang_duplex_cluster]], not to this plan.
8. **Test depth is lopsided for the phases called shipped.** `test_duplex_geometry.py`,
   `test_duplex_relocate.py`, `test_duplex_length_preserve.py` are **one test each**, and the three
   panel duplex specs are 1/2/1 cases — for Phases 4/4b, the ones that move geometry.

<a id="coexistence-hazards-found-2026-07-30-resolving-the-contradicting-peer--none-covered-by-any-test"></a>
- [Coexistence hazards (found 2026-07-30 resolving the contradicting peer — none covered by any test)](details/project_overhang_duplex_foundation/02-coexistence-hazards-found-2026-07-30-resolving-the-contradicting.md#coexistence-hazards-found-2026-07-30-resolving-the-contradicting-peer--none-covered-by-any-test)

## The doc fork (read this before trusting a sibling)

Nothing supersedes this file — it is the only definition of `DuplexEnd`,
`classify_duplex_pairing`, `overhang_pairing_map` and the length-preservation law. But it is no
longer the only entry point, and two heavily-trafficked siblings are **duplex-blind**:

| If the task is… | Open | Caveat |
|---|---|---|
| pairing model / register / multivalency / toehold | **this file** | — |
| "connect two overhangs in the app" | [[overhang-connections-panel]] | **RESOLVED 2026-07-30** — it was duplex-blind (its ★ UNIFIED section describes the pipeline purely in `OverhangBinding` terms); a correction block with the truth table above now sits under that header. It is still the right doc for the version/apply/teardown machinery — just read its ⚠ blocks first |
| duplex geometry / pose / gizmo | [[overhang-duplex-cluster]] | its head still says "planning; no code" — false, P0–P3 shipped 2026-07-01 |
| cross-part pairing | [[assembly_overhang_bindings]] | the **most current** duplex doc (2026-07-11); owns `AssemblyDuplex` + the shared `classify_antiparallel` kernel |
| sub-domain metadata / Domain Designer | [[overhang_subdomains]] | **duplex-blind**; its Phase 5/6 is exactly what Phase 6 above retires |

<a id="related"></a>
- [Related](details/project_overhang_duplex_foundation/03-related.md#related)
