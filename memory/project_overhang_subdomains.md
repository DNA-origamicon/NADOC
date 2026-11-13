---
name: Overhang sub-domains + Domain Designer (Phases 1-7)
description: SubDomain model, Domain Designer tab, per-sub-domain rotation (backend-only now), OverhangBinding. Audited 2026-07-31.
type: project
---

# Overhang sub-domains + Domain Designer

## Sequence resize root ownership (2026-11-12)

Sequence edits now determine the free terminus from the selected overhang's
own strand domain. A shared helix must not use its first crossover as every
handle's root or shrink to one handle's length. Dedicated helices retain root
position and helical phase while their origin changes; one-base shrink/regrowth
uses domain direction. Nonterminal overhangs have no free end to resize.
VoltronCoreArmV2 QD_OH1 diagnostic: 15→10 bases keeps root 1223 and moves free
end 1209→1214, with zero root axis/phase displacement and unchanged crossover
records. Existing user file was not rewritten. Native regression structures use
recorded bundle/extrusion/sequence commands and guarded publication/replay.

Undo already restored backend state exactly. Renderer connection signatures now
include strand-domain junction endpoints, and partial patch/overlay paths decline
junction changes so persistent crossover arcs refresh. Closing Domain Designer also
refreshes arcs after its deferred helix rebuild, including a queued undo. Browser validation remains
MV-66 while the active-NAMD guard blocks smoke. Validation: FAST backend
20,835 passed (90 skipped), frontend 10,435 passed (1 skipped), lint passed;
broad FULL suite remains deferred without a test session. Metadata-only patches
do not resize from an existing sequence-length mismatch. The legacy connection
reassignment test now retains its 16-bp root separation: its former 8-bp duplex
only fitted because the old resize incorrectly moved a covalent root.

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

**Rank:** P2 — the feature ships and is in daily use; what remains is a dead-rotation carcass to
remove, two live endpoints with no UI, one latent geometry asymmetry, and zero frontend tests.
No wanted capability is blocked, and `OverhangBinding` is on a documented deprecation path.

**Status (audited 2026-07-31 against the code — every anchor below was probed):**

| Phase | Claim in the log | Reality |
|---|---|---|
| 1 `SubDomain` model + CRUD + thermo | shipped | **SHIPPED, live** |
| 2 | folded into 3 | n/a |
| 3 Domain Designer tab | shipped | **SHIPPED, live** — minus the Tm-settings panel, which was never built |
| 4 per-sub-domain θ/φ rotation | shipped | **Backend SHIPPED and still read by geometry. UI DELETED by the user 2026-05-11.** Editing path is a carcass |
| 5 `OverhangBinding` | shipped | Model + CRUD **SHIPPED**. Its headline behaviour — bind ⇒ freeze the joint at a solved angle — was **REVERTED at user request 2026-05-14**. The solver is dead code |
| 6 binding-event animations | "not started" | **Shipped elsewhere, under a different architecture** → [[project_strand_animations]]. Nothing named in the Phase-6 plan (`BindingEventLogEntry`, `scene/binding_overlay.js`, `event_type`) exists |
| 7 pathview rework + ss single-strand linker | shipped | **SHIPPED, live** |

History (the verbatim 7-phase log) → `project_overhang_subdomains_archive.md`. Don't read it in a
routine loop.

## Two facts the phase log gets backwards

1. **Binding no longer locks a joint.** `crud.py:8724-8733`: *"no automatic post-bind cluster
   relax… Earlier iterations auto-rotated the joint on bind; reverted at user request
   2026-05-14."* Bind now does **topology relocation only** (`compute_bind_topology` /
   `apply_bind_topology`), and `locked_angle_deg` stays `None` unless an external caller supplies
   one — which nothing does. Consequences: `binding_relax.compute_locked_angle` (`:610`) has
   **zero callers repo-wide**, and `cluster_gizmo`'s grey "locked" ring (`cluster_gizmo.js:395`,
   keyed on `joint.min_angle_deg === joint.max_angle_deg`) no longer fires from a binding. The
   *bound* semantics that survived live in [[project_overhang_binding_extensions]], not here.
2. **Phase 6 is not open work.** Unzip / toehold-displacement animation shipped as the
   `frontend/src/strand-anim/` subsystem + `scene/overhang_unzip_overlay.js` +
   `scene/overhang_strand_anim.js` (both imported at `main.js:112-113`), driven by
   `OverhangSpec.strand_anim_setup` (`models.py:300`) and `AnimationKeyframe.strand_anim_phi`
   (`models.py:1726`), with modes `unzip` / `displacement` (`animation_panel.js:58`). `shear` was
   dropped. Keyframed φ ⇒ the export-determinism carryover is satisfied by construction.

<a id="which-doc-to-open-this-territory-has-seven"></a>
- [Which doc to open (this territory has seven)](details/project_overhang_subdomains/01-which-doc-to-open-this-territory-has-seven.md#which-doc-to-open-this-territory-has-seven)

## Locked decisions (still binding — do not renegotiate)

1. Sub-domains are addressable segments of ONE continuous strand — no new nicks, no new strand
   entities. Gapless tiling: Σ `length_bp` == backing domain length, contiguous, every bp owned.
2. Every overhang always has ≥1 sub-domain. Old files lazy-migrate via the `OverhangSpec`
   `@model_validator(mode='after')` (`models.py:302`, idempotent, UUID5 from `NADOC_SUBDOMAIN_NS`).
   The validator can't see the backing domain length, so **creation-site construction in
   `lattice.py` is primary** and `crud.py:6232 _backfill_sub_domains_if_empty` repairs
   validator-made length-1 stubs on load *and* import.
3. Sequence ownership = parent canonical + per-sub-domain override. Top-level overhang sequence
   write returns 409 if any sub-domain has an active override.
4. Resize policy: the **last** sub-domain absorbs Δ length; 422 if that pushes it below 1 bp or
   below its own override length.
5. Rotation = 2-DOF parent-relative chain. θ ∈ [-180,180] around the parent axis, φ ∈ [0,180] from
   it; φ-ref = world-Y projected ⊥ parent_axis, **world-Z fallback when `|parent_axis·Y| > 0.9`**.
   sd 0's parent axis = helix tangent at the junction bp; sd N>0's = the upstream sub-domain's END
   tangent after all upstream rotations. Compose θ first, then φ.
6. **Three-Layer Law: `SubDomain` is TOPOLOGY.** Geometry/atomistic read only.
7. `feedback_overhang_definition`: the overhang stays one contiguous strand region; sub-domains are
   pure metadata over it.

<a id="traps"></a>
- [Traps](details/project_overhang_subdomains/02-traps.md#traps)

<a id="backend--probed-locations-2026-07-31"></a>
- [Backend — probed locations (2026-07-31)](details/project_overhang_subdomains/02-traps.md#backend--probed-locations-2026-07-31)

<a id="frontend--probed-locations-2026-07-31"></a>
- [Frontend — probed locations (2026-07-31)](details/project_overhang_subdomains/02-traps.md#frontend--probed-locations-2026-07-31)

## Open items (live, probed 2026-07-31)

1. **Merge is unreachable from the UI.** `mergeSubDomains` is put into `ddApi`
   (`overhangs_manager_popup.js:1834`) and **never invoked**; the panel binds split (pathview
   right-click) with no merge affordance. Backend `crud.py:6650` is live and tested. Split is
   currently one-way.
2. **Tm settings has no UI** — same shape: `patchTmSettings` in `ddApi:1835`, zero invocations;
   `PATCH /design/tm-settings` (`crud.py:7080`) live. The Phase-3 "Tm settings panel" deliverable
   was never built, so `na_mM`/`conc_nM` are only reachable by API.
3. **Decide the fate of the rotation-editing carcass.** Dead: `scene/sub_domain_gizmo.js` (381
   LOC), the wrappers `patchSubDomainRotation` / `patchSubDomainRotationsBatch` /
   `getSubDomainFrame` (`overhang_endpoints.js:217/226/236`, zero production callers), and
   `e2e/sub_domain_rotation.spec.js` — 4 of its 8 specs probe `window.__nadocSubDomainGizmo`, which
   production no longer sets, and the rest target θ/φ inputs deleted in Phase 7. **Do NOT delete
   the backend side with it:** `crud.py:5249/5333/5410` and the `deformation.py` chain walk still
   read θ/φ out of saved files, pinned by 24 tests. Either restore the gizmo or delete
   gizmo+wrappers+spec and keep the backend as a file-format-only path.
4. **Latent geometry asymmetry: beads and shafts disagree on a duplex-cluster driver.** The axes
   path `continue`s past the sub-domain chain when `_overhang_is_duplex_cluster_driver`
   (`deformation.py:808`) is true (`:1969`); the bead path (`:1131`) never calls that check and
   still applies the chain. A saved design with non-zero sub-domain θ/φ on a bound-duplex driver
   would render beads and shaft in different places. Latent only because no UI can set θ/φ.
   **Static analysis, not app-verified.**
5. **`compute_locked_angle` is dead code** (`binding_relax.py:610`, 0 callers) — see "backwards"
   above. The old "multi-DOF locked-angle relax" carryover is moot while nothing calls the 1-DOF
   path. Decide: delete, or re-wire behind an explicit user action.
6. **Zero frontend tests over ~5.7k LOC.** No vitest file touches `overhang_pathview`,
   `domain_designer_panel`, `overhangs_manager_popup`, or the `domainDesigner` store slice. The
   only coverage is e2e: `domain_designer.spec.js` (11), `overhang_bindings.spec.js` (6), and the
   broken rotation spec (8).
7. **Orphan exports to prune:** `listSubDomains` (`overhang_endpoints.js:155`, 0 callers);
   `listOverhangBindings` (e2e-only — so `GET /design/overhang-bindings` `crud.py:8444` has no
   production consumer); `store.domainDesigner.activePane`, which defaults to `'preview'`, a pane
   deleted in Phase 7, and is read by nobody.
8. **`OverhangBinding` is on a documented deprecation path, and sub-domain granularity is what gets
   lost.** `models.py:519` declares `Duplex` supersedes it;
   `duplex.py:63 synthesize_duplexes_from_bindings` runs on **every** load and import
   (`crud.py:1367/1401`), so every binding design carries a parallel duplex graph; Phase 6 of
   [[project_overhang_duplex_foundation]] retires bindings outright. But `DuplexEnd` is
   `{overhang_id, start_bp, end_bp}` — **bp intervals, not sub-domain refs** — and
   `OverhangBinding.sub_domain_a_id/_b_id` is read by the duplex path in exactly one place, the
   one-shot migration at `duplex.py:76-78`. `design_automation_backlog.md:162` already flags the
   sub-domain-binding half of AF-37 ⚠ ASK USER FIRST for this reason. **Ask before assuming
   sub-domain-level bindings survive the retirement.**
9. Phase-7 follow-ups, carried unverified: ss linker bridge nucleotides don't flow through
   `/api/design/geometry` (3D ssDNA bridge deferred); the orphan-overhang three-tier helix-id
   fallback could be resolved at load time instead; linker resize while a binding is selected may
   need a `cluster_joints` cache invalidation.

Both geometry entry points are fully wired — `apply_overhang_rotation_if_needed` ←
`design_geometry.py:397/761`, `crud.py:5478`; `_apply_ovhg_rotations_to_axes` ← `crud.py:403/410/1295`,
`routes_blade.py:357` — so items 3 and 4 are about a live path, not a dormant one.


## Sequence work feedback (2026-11-12, ISSUE-192)

Sequence writes in the main/2D spreadsheets, Overhangs/Connections panels and
Domain Designer share nonmodal activity tracking (`sequence_activity.js`) through
geometry application/paint and scheduled hairpin/dimer checks. A scoped queue
serializes writes and replaces only unsent sequence drafts. Focused spreadsheet
and Overhangs-panel drafts defer refresh until focus leaves the edit controls;
Domain Designer retains its existing in-place annotation updates. The canonical
sequence PATCH now returns embedded geometry, partial for local identity-pose
resizes and sequence replacements, with conservative full-geometry fallback.
No authored geometry algorithm or sequence check was removed.
