---
name: overhang-connections-panel
description: "Right-sidebar 'Overhang Connections' section — SHIPPED and live. The ConnectionVersion candidate-library + Connect/Apply/Relax pipeline of record, and the only live UI producer of OverhangBindings besides the Domain Designer. P2: one real automation hole (different-length direct connect is frontend-only) + 3 small user-gated deferrals."
metadata:
  node_type: memory
  type: project
  originSessionId: 411c7065-557d-4292-881a-1efe67847be9
---

# Overhang Connections sidebar panel — SHIPPED

**Rank:** P2 — the feature ships end-to-end and this file is the only prose for the
`ConnectionVersion` pipeline (both [[overhang-duplex-foundation]] and [[overhang-subdomains]]
delegate to it). What's left is one genuine defect (different-length direct connect can't be
driven headlessly) plus three small, explicitly user-gated deferrals.

**Status — probed 2026-07-31 (`/audit-plan`). Every anchor in this file resolved; nothing here
was found dead.** The panel is `frontend/src/ui/overhang_connections_panel.js` (1713 LOC),
injected at [main.js:4130](frontend/src/main.js) — still exactly 2 lines in `main.js` (import
`:98` + init `:4130`), as designed.

Build history → **`project_overhang_connections_panel_archive.md`** (known-stale; don't read it
in a routine loop). The old end-to-root *splice* model described there was deleted 2026-06-30.

## What it is

Right-sidebar `.panel-section#overhang-connections-section` (static markup,
[frontend/index.html:6998](frontend/index.html), below `#overhang-panel` at `:6960`), default
collapsed. Two overhang dropdowns (A/B) + a 12-variant connection-type icon picker + a
persisted **candidate library** (`ConnectionVersion`) so several alternative connections for the
same overhang pair can be explored with at most ONE materialized at a time.

Selection auto-populates the two slots as a **2-slot LRU** (`_placePick:1640`, per-slot stamps
`_slotTA`/`_slotTB`, `++_clock`) — fill an empty slot first, else evict the slot populated *less*
recently. An earlier "sliding window" (A=older, B=newer, reassigns both) was wrong and replaced;
the slot a pick lands in is stable.

## The Connect / Apply pipeline (verified in code)

`_onConnect:665` → teardown → set sequences → `POST /design/connection-versions` →
`POST …/{id}/apply` (**the only call that can create an `OverhangBinding`**) →
`_ensureDuplexForPair:595` → `POST /design/duplexes/connect`.

`_ensureDuplexForPair` is gated on connection **TYPE ONLY** (`ctIsDirect`) — no length check, no
binding check — so the panel **always** creates a Duplex for a direct connection. Its own comment
calls it "the display duplex".

Apply itself is one atomic backend endpoint (`apply_connection_version`, `crud.py:7700`, one
`mutate_with_feature_log` → one undo): set both overhang sequences via `_build_overhang_patch`
(**which resizes each overhang to `len(sequence)`**) → tear down the pair's current
connection/binding → recreate the version's type → mark applied + clear the pair's others.

### The length fork (the load-bearing table)

The fork is **length, not connection type**:

| Caller | Equal-length pair | Different-length pair |
|---|---|---|
| **This panel** | `OverhangBinding` **+** `Duplex` (binding relocates; the duplex is display) | **`Duplex` only** — the binding is skipped and `relocate_duplex` does the move |
| Raw API / headless `apply_connection_version` | Binding only | **NEITHER — silent no-op** ← open item 1 |
| Raw API / headless `connect_duplex` | Duplex only | Duplex only |

`_cv_create_bound_binding` returns early when the two attach sub-domains differ in length
([crud.py:7642-7653](backend/api/crud.py)), with a comment that says the duplex "is created
separately by the frontend's `_ensureDuplexForPair`" — i.e. **the backend deliberately relies on
the frontend to finish the job.** Mirror guard on the duplex side:
[routes_duplex.py:205-215](backend/api/routes_duplex.py) relocates *only* when no binding exists
for the pair.

### Direct apply = relocation, NOT a joint lock

Create `OverhangBinding(bound=True, driver_oh_id=A, driven_oh_id=B, …)` + relocate via
`compute_bind_topology(driver_side="a")` → `apply_bind_topology`. **A is the driver (its helix
HOSTS the duplex); B is driven (its tip domain relocates onto A's helix, antiparallel). NEITHER
overhang is consumed.**

**`bound` does not lock a joint angle** — the bind path hard-writes `locked_angle_deg = None`
([crud.py:8688](backend/api/crud.py)) and `compute_locked_angle` (`binding_relax.py:610`) has
**zero callers**; the auto-rotate-the-joint-on-bind behaviour was reverted at user request
2026-05-14 (comment `crud.py:8725-8733`). The panel's Bound checkbox (`:1357-1363`) is a plain
`patchOverhangBinding({bound})` → topology relocation only. See [[overhang-subdomains]].

**caDNAno display:** after relocation the driven overhang's extrude crossover would land at a
mismatched bp, so `apply_bind_topology` drops it and emits a `ForcedLigation` for the root↔tip
backbone bond. A validator flags any crossover whose halves sit at mismatched bp
("Improper crossover(s) at invalid lattice positions", `validator.py:231`).

**Relax** = `POST /design/overhang-bindings/{id}/relax` (`crud.py:7812`) →
`direct_relax.relax_direct_binding` (`direct_relax.py:320`), duplex twin at
`routes_duplex.py:296`. Since 2026-07-01 this is the **linker-bridge method** (arc-minimize via
cluster joints → re-seat at the oriented midpoint via `duplex_midpoint_placement` → clash-spin
the duplex), **not** the old swing; `swing_*` fields are gone repo-wide. Full description in
[[overhang-duplex-foundation]].

**Co-rotation is fixed for duplex-only pairs (2026-07-30):** `driven_to_driver`,
`driven_bound_oh_ids` and the cluster scope all come from
`deformation._bound_driver_driven_pairs:985`, which reads bound **duplexes** as well as bound
bindings. Pinned by `test_overhang_binder_rotation.py::test_diff_length_duplex_*` (`:342`, `:380`).

## Code locations (probed 2026-07-31)

### Frontend

| Thing | Where |
|---|---|
| Panel factory `initOverhangConnectionsPanel` | `ui/overhang_connections_panel.js:124` (1713 LOC, singleton) |
| `_onConnect` / `_onApply` / `_onSecondary` | `:665` / `:759` / `:438` |
| `_ensureDuplexForPair` / `_teardownPair` | `:595` (called `:690`, `:771`) / `:787` |
| Selection LRU | `_selectedOverhangIds:1606` → `_onSelectionChange:1626` → `_placePick:1640` |
| Popover (opens leftward, `position:fixed`) | `_openPopover:1656` |
| Shared CT helpers | `ui/ct_icons.js` — `CT_VARIANTS:340`, `endOf:357`, `ctIsForbidden:369`, `ctForbiddenReason:383`, `ctAttachPair:411`, `ctIsDirect:422`, `ctIsIndirect:427`, `ctLinkerType:432`, `ctVariantForConnection:438`. **All 9 have exactly the same 3 importers**: this panel, `assembly_overhang_connections_panel.js`, and the test |
| Sequence-preview helpers | `scene/design_queries.js` — `assembleOverhangSequence:144`, `overhangDomainLength:122`, `pairingSegments:219` (`isComplement:195` is **not** used by this panel) |
| API wrappers | all in `api/overhang_endpoints.js`; every one has a live call site — `createConnectionVersion:90`, `patchConnectionVersion:97`, `deleteConnectionVersion:102`, `applyConnectionVersion:117`, `relaxOverhangBinding:107`, `createOverhangBinding:257`, `createOverhangConnection:71`, `connectDuplex:303`, `relaxDuplex:317` |
| DOM ids | static in `index.html`: `oconn-{heading,arrow,body,select-a,select-b,button-box,popover,length,length-row,generate,apply,secondary,list,details,pair-warning,seq-row-a/b,seq-input-a/b,seq-gen-a/b}`. Runtime-only classes: `oconn-row*`, `oconn-version-row`, `oconn-group-header`, `oconn-driver-box`, `oconn-seq-preview`, `oconn-applied-badge`, `oconn-bridge-input`. Assembly twin uses `#asm-oconn-*` (`index.html:6568+`) |

### Backend

| Thing | Where |
|---|---|
| `ConnectionVersion` model | `core/models.py:675-702` (11 fields); `Design.connection_versions` `:2256` |
| Routes (**still in `crud.py` — the carve-up has not reached them; no `routes_connection_versions.py` exists**) | `POST` `:7511` · `PATCH` `:7543` · `DELETE` `:7577` · `POST …/{id}/apply` `:7699`; registered via `crud_router` (`api/main.py:27,226`) |
| `_cv_*` helpers (all have live callers, no orphans) | `_assign_connection_version_names:7481`, `_cv_enforce_applied_mutex:7500`, `_cv_attach_pair:7593`, `_cv_is_direct:7602`, `_cv_is_indirect:7606`, `_cv_linker_type:7610`, `_cv_sub_domain_at_attach:7614`, `_cv_create_bound_binding:7622` |
| Overhang resize on apply | `_build_overhang_patch` `crud.py:4724` (4 callers) |
| Bind topology | `binding_relax.py` — `compute_bind_topology:193` (still takes `driver_side`), `apply_bind_topology:367`, `revert_bind_topology:505`, `BindTopology.forced_ligation:86` |
| Direct relax | `core/direct_relax.py` — `_find_driven_tip_and_root:76`, `relax_direct_binding:320` (callers: `crud.py:7837`, `routes_duplex.py:323`, `headless_hinge_build.py:505`) |
| Linker topology | `lattice.py` — `generate_linker_topology:4350`, `remove_linker_topology:4475` |
| Duplex cluster | `duplex_cluster.py` — `_duplex_domain_refs:116`, `materialize_duplex_cluster:156` (5 callers incl. `crud.py:7695`) |
| Headless | `headless_build.apply_connection_version` `:1043` |

## Tests (probed — the doc undercounted every one of these)

Backend, all **fast** (no `slow` marks): `tests/test_connection_versions.py` **16**,
`tests/test_direct_connection_unified.py` **10**, `tests/test_overhang_binder_rotation.py` **4**,
plus `test_headless_build.py::test_apply_end_to_root_cadnano_clean_after_apply:585`.
Oracles: `assert_direct_binding_applied` / `assert_direct_binding_relaxed_pose` in
`tests/automation_harness.py`.

Vitest — **12 panel spec files** (the doc named 6): `overhang_connections_panel.test.js` 8,
`.versions` 10, `.seqpair` 9, `.bindrelax` 6, `.details` 5, `.selection` 5, `.glow` 3,
`.driver` 2, `.openpair` 2, `.seqpreview` 2, `.duplex` 1, `.lengthcap` 1. Plus
`ct_icons.test.js` 17 and `design_queries.test.js` 53. **No E2E spec covers this panel.**

## Open items (live, 2026-07-31)

1. **Different-length direct connect has no headless path.** `_cv_create_bound_binding` bails on
   unequal attach sub-domains and defers to the frontend, so `apply_connection_version` via raw
   API / `headless_build` produces **neither** a binding nor a duplex — a silent no-op. Fix =
   move the `_ensureDuplexForPair` step server-side into `apply_connection_version`. This is the
   one item with real value; it blocks automating different-length direct connections.
2. **`_onSecondary`'s docstring (`overhang_connections_panel.js:429-437`) still describes the
   deleted swing relax** ("swings the driver's overhang duplex about its root"). Superseded
   2026-07-01 by the linker-bridge method. Wrong doc-in-code on the panel's own relax button.
3. **Dead import:** `patchOverhang` is imported at `overhang_connections_panel.js:40` and never
   invoked in the panel.
4. **Three copies of the polarity-forbidden rule still exist** (the old deferred #2, not done):
   `overhangs_manager_popup.js:912 _ctIsForbidden` (+ `_ctForbiddenReason:946`; that file imports
   *nothing* from `ct_icons.js`), `assembly_overhangs_manager_popup.js:929 _isForbidden` (imports
   only `ctTileSvg`), and the shared `ct_icons.ctIsForbidden:369`. Repointing the two popups is
   the cleanup.
5. **`length_unit` is hardcoded `'bp'` on the write path** (`:821`) — the old deferred #3. Read
   paths already honour `'nm'` (`:1094`, `:1389` `…/0.334`) and the model allows both
   (`models.py:348,726`), so only the write path is missing a toggle.
6. **NOT hand-driven (manual-validation debt)** — filed as `MV-OCONN-1/2/3` in
   `manual_validation_debt.md`: the create/delete round-trip against a real backend; the 3D
   duplex render + cadnano + gizmo co-rotation after a direct apply/relax; the
   drag-resize-then-open-section sequence preview.

**Not an open item — the user declined it.** "Retire the old Overhangs Manager modal once the
section reaches parity" was the doc's deferred #1; the user chose "keep modal live too". The
modal (`overhangs_manager_popup.js`, 2473 LOC) is fully wired at `main.js:92-94,4129,956-959`
and writes the same records. Recorded so nobody re-proposes the retirement.

## Doc fork — which sibling to open

- [[overhang-duplex-foundation]] (**P1**) — the pairing MODEL of record. Owns the `Duplex` graph,
  the migration-on-load, and the retirement plan for `OverhangBinding`. Read it before touching
  any pairing.
- [[overhang-duplex-cluster]] — owns `materialize_duplex_cluster` + the duplex pose-as-child-cluster
  and this panel's apply toast.
- [[overhang-subdomains]] — owns `SubDomain` + the Domain Designer tab (the *other* live producer
  of `OverhangBinding`s) and the 2026-05-14 bind-locks-joint revert.
- [[overhang_connections]] — the linker data model + the `_overhang_binding_partner_refs`
  co-rotation rule.
- [[ct_tab]] — the manager CT tab this section re-houses; [[assembly_overhang_bindings]] — the
  assembly twin panel.

## Key facts

- Overhang ids encode polarity as a `_5p`/`_3p` suffix (`ovhg_{helix}_{bp}_{5p|3p}`,
  `lattice.py:3003`). `endOf` parses it; that is the whole basis of the live 5'/3' button update —
  mechanical, no topology reasoning (per [[crossover_no_reasoning]]).
- The panel creates **no** root DOM: all `#oconn-*` ids are static markup read via
  `getElementById` at `:138-157`.
- Sequence previews N-pad to the backing-domain length (`assembleOverhangSequence` +
  `overhangDomainLength`) and colour by `pairingSegments` anchored at the **bound/attach** end,
  excess at the free tip (user-confirmed register).
