---
type: project
status: active
authority: canonical
review_after: 2026-10-01
---
# Response-diffing backlog

Driver for burning down "ship a diff instead of the whole design" work. Every mutating
API response currently re-serializes state proportional to the whole design, not the
edit — `_design_response`/`_design_response_with_geometry` (`backend/api/crud.py:298`/`:397`)
always ship the full `design.to_dict()`, and most callers of the latter ship full
nucleotide geometry too. Full narrative + profiling is in the approval plan this backlog
was seeded from; the numbers that matter are reproduced below so future sessions don't
need to re-derive them.

## Profiling evidence (2026-08-18, offline, 4 real `.nadoc` files from `workspace/`)

| file | #helix | topo gz | geo gz | feature_log blob share of topo gz |
|---|---|---|---|---|
| VoltronCoreScad.nadoc | 59 | 3,118,029 | 822,665 | 53.2% |
| VoltronCore.nadoc | 59 | 383,903 | 889,454 | 87.0% |
| 3x6x400_test_manual_skips.nadoc | 18 | 516,213 | 824,784 | 90.1% |
| 6hb_validated.nadoc | 6 | 333,877 | 809,990 | 86.7% |

Method: `Design.from_json` (`backend/core/models.py:3096`) loaded directly, `design.to_dict()`
vs `_geometry_for_design`/`_geometry_for_helices` (`backend/core/design_geometry.py`), gzip
level 3 (matches `GZipMiddleware`, `backend/api/main.py:344`).

**Conclusion driving scope:** core topology minus feature-log body blobs is already small
(45–52 KB gz for 3 of 4 files) — general strand/domain/crossover diffing is excluded, too
risky for too little (see `.claude/rules/api-and-state.md` mutation-contract warning). Two
levers instead:

- **Lever 1 (FL-xx)** — stop re-shipping feature-log body blobs
  (`design_snapshot_gz_b64`/`pre_state_gz_b64`/`post_state_gz_b64`/`diff_*_b64`) on every
  mutation response. 53–90% of gzipped topology payload on every design sampled, not just
  heavily-edited ones. The client already has a generic reconstruction path
  (`_mergeFeatureLogPayloads`, `frontend/src/api/client.js:485`), proven at 5 call sites
  (`_slim_mutation_history_payload`, `crud.py:1110,1275,1377,5039,5890`) — just needs to
  become the default instead of opt-in.
- **Lever 2 (GEO-xx)** — extend the existing partial-geometry mechanism
  (`changed_helix_ids`, nicknamed "Fix B") from ~24 of 75 `_design_response_with_geometry`
  call sites to the remaining ones with a semantically bounded touched-helix set.

**Deferred, not itemized here:** second-round-trip triage among ~108 bare `_design_response`
call sites (one audit task, not per-route); assembly-layer diffing (`_assembly_response`,
92 call sites, no existing partial mechanism — greenfield follow-on); general topology
diffing (excluded per above).

## Operating rule

One item per iteration: implement, verify, flip its status, append a line to
`memory/response_diffing_log.md`. FL items first — prerequisite-free, highest ROI/risk
ratio. Stop and flag (do not guess) if a route's touched-helix-set computation is
ambiguous — that class of mistake is a silent correctness bug per the mutation-contract
rule, not a visible error.

## Queue — Lever 1 (do first)

| ID | Item | Status |
|---|---|---|
| FL-01 | Flip `_design_response`/`_design_response_with_geometry` default to strip feature-log blobs (reuse `_strip_feature_log_payloads`, `crud.py:254`) + set `feature_log_payloads_partial=True`, except cold-load paths | **done** — new kwargs `preserve_feature_log_id`/`full_feature_log` on both helpers |
| FL-02 | Enumerate + exempt every cold-load path. Known: `GET /design` (`crud.py:852`) — the only `_request('GET','/design')` site is `client.js:836`. Verify no others (restart-recovery flow near `main.js:4838`) | **done** — exempted (all pass `full_feature_log=True`): `GET /design`; every `design_state.clear_history()` route (`create_design`, `create_bundle`, `load_design`, `import_design`, `import_cadnano_design`, `import_scadnano_design`, `import_pdb_design`, `import_pdb_auto`); every `design_state.set_design_branch()` route (`select_loadout`, `activate_last_editable_loadout`, `roll_active_to_job_state`); `delete_loadout` conditionally (only when it actually switches branch); all 5 internal calls inside `_design_replace_response` (undo/redo/edit-feature/delete-feature/seek fan-in — deferred correctness nuance, see FL-06 below, not just "cold load") |
| FL-03 | Reconcile the 5 existing `_slim_mutation_history_payload` sites with the new default (still needed to preserve a *newly created* entry's body, or redundant?) | **done** — `_slim_mutation_history_payload` deleted; all 5 sites now pass `preserve_feature_log_id=_entry.id` directly into their `_design_response_with_geometry`/`_design_response` call |
| FL-04 | Regression test: non-entry-creating mutation (e.g. `add_nick`) on a design with feature-log history → response strips blobs, `_mergeFeatureLogPayloads` reconstitutes, `persistDesign()` output byte-identical to unstripped baseline | **done** — 3 new tests in `tests/test_feature_log_snapshot.py` (`test_ordinary_mutation_strips_feature_log_bodies_by_default` via `PUT /design/metadata`, `test_get_design_cold_load_retains_full_feature_log_bodies`, `test_load_design_cold_load_retains_full_feature_log_bodies`); existing `test_extrude_response_slims_old_history_but_retains_server_recovery_bodies` + `test_patch_strands_reference_route_round_trips_with_geometry` still pass unchanged. `just test-smart`: FAST, 7103 passed, 114 skipped. One DEFERRED (FULL suite) reported — traced to an unrelated prior commit touching `backend/api/state`/`main.py`, not this change; needs a user-opened `just test-session` to clear |
| FL-05 | In-app check: Feature Log panel / revert / seek / reload-recovery still work after a routine edit strips blobs | **blocked** — needs the user to confirm it's safe to drive the live dev server (`feedback_no_live_server_mutation_for_verify`); not run yet |
| FL-07 (new, discovered while starting GEO-02) | **Critical fix, already shipped.** `mutate_with_feature_log`/`mutate_with_minor_log` have 47+ call sites across the router files; only the original 5 explicitly threaded `preserve_feature_log_id`. Every other one (confirmed live on `auto_break`, likely all of `routes_protein.py`, `routes_assign_sequences.py`, `routes_clusters.py`, etc.) would have shipped its own BRAND-NEW entry's body EMPTY under FL-01's default-strip — a real bug, not just a missed optimization, since the client has never cached that entry's id and can't backfill it. Fixed structurally instead of by 47-site audit: a per-request ContextVar (`doc_context.py::_last_feature_log_entry_id`, mirrors the existing `_request_revision` pattern) is set inside both `mutate_with_feature_log` and `mutate_with_minor_log` (the latter preserves the PARENT `RoutingClusterLogEntry.id`, not the child's — `_strip_feature_log_payloads` only matches top-level ids) right after the entry/cluster is created, reset per-request by `DocContextMiddleware`. `_design_response` now falls back to `design_state.current_request_feature_log_entry_id()` whenever `preserve_feature_log_id` isn't explicitly passed. Closes the whole class for every existing AND future caller — no per-route audit needed. Verified with a dedicated test (`test_route_that_never_threads_preserve_id_still_keeps_its_new_entry_body`, asserts `auto_break`'s source literally doesn't pass the param, then proves its response body survives anyway). `just test-smart`: FAST, 7104 passed, 114 skipped | **done** |
| FL-06 (new, discovered during FL-02) | `_design_replace_response` (undo/redo/edit-feature/delete-feature/seek fan-in) currently ALWAYS ships full feature-log bodies (`full_feature_log=True` on all 5 internal calls) — deliberately conservative because `edit_feature` can regenerate an entry's body IN PLACE under the same id, and the client's merge-from-cache logic can't distinguish a stale cached body from a fresh one. A real optimization here needs either a body-version/hash the client can compare, or a narrower proof that `edit_feature`'s replay always changes only entries after the edited index (letting earlier entries strip safely). Needs its own investigation before touching | pending, not itemized in original plan |

## Queue — Lever 2 (after Lever 1)

`backend/api/crud.py`:

| ID | Route | Line | Status |
|---|---|---|---|
| GEO-01 | `POST /design/scaffold-domain-paint` | 2489 | **stale** — its only caller (`cadnano-editor/api.js`) always sends `X-NADOC-Skip-Geometry: 1`, which already short-circuits `_design_response_with_geometry` to the geometry-free path (`should_skip_geometry()` check fires first). `changed_helix_ids` would never be exercised. No code change needed |
| GEO-02 | `POST /design/overhang/{id}/generate-binder` | 2641 | **done** — `_strand_occupancy`/`_local_changed_helices` (the existing generic diff utility, `backend/core/render_diff.py`) before/after `mutate_with_feature_log` |
| GEO-03 | `POST /design/domain-shift` | 2765 | **done** — same utility + `partial_axes=True` (a shifted domain changes the helix's axis `segments` even though the axis itself doesn't move — caught by `tests/test_domain_shift.py`'s existing `helix_axes` assertion, which failed without it) |
| GEO-04 | `POST /design/crossovers/place` | 3325 | **done** — same utility |
| GEO-05 | `POST /design/crossovers/place-batch` | 3385 | **done** — same utility |
| GEO-06 | `PATCH /design/crossovers/{id}/extra-bases` | 4340 | **done** — NOT `changed_helix_ids` (wrong tool: `extra_bases` lives on the `Crossover` record, `design_geometry.py` never reads it, no real nucleotide moves at all). Switched to the `geometry_unchanged: true` contract `patch_strands_reference` already established, + wired the matching `skipGeometry` check into the 3 client.js wrappers (frontend companion change — `client.js:patchCrossoverExtraBases` etc). Backend test `test_extra_bases_patch_flags_geometry_unchanged`; frontend test `client_extra_bases_geometry_unchanged.test.js` (3 cases, mirrors `overhang_endpoints.test.js`'s existing pattern). `just test-smart`: 7105 passed. `just test-frontend`: 336 files / 5735 passed |
| GEO-07 | `PATCH /design/crossovers/extra-bases/batch` | 4302 | **done** — same fix as GEO-06, same commit |
| GEO-08 | `PATCH /design/forced-ligations/{id}/extra-bases` | 4378 | **done** — same fix, no dedicated test yet (no existing test file for this route at all; the GEO-06 test covers the identical code pattern) |
| GEO-09 | `PATCH /design/overhangs/rotations` (main path) | 5228 | **investigated, deliberately left full-geometry, not a miss** — its sibling single-overhang route (`patch_overhang`, ~line 5248) has an explicit comment: full geometry is chosen ON PURPOSE for a rotation commit so the frontend rebuilds from server-authoritative positions instead of trusting its own in-memory drag-preview state (`overhang_orientation_menu.js`/`overhang_orientation_panel.js` confirm this route fires from a "reset previews to identity" flow). Also: rotation lives on the `Overhang.rotation` field, not any strand domain, so `_strand_occupancy`/`_local_changed_helices` (the tool used for GEO-02–05) can't see this kind of change anyway — wrong tool even if the preview concern didn't exist |
| GEO-10 | `PATCH /design/overhang/{id}/sub-domains/{id}/rotation` | 5427 | **investigated, split finding, not yet acted on.** This route has TWO branches sharing one docstring: `commit=False` is a LIVE PREVIEW fired on every gizmo-drag frame (`design_state.set_design_silent`, no feature-log entry) — the actual hot path, and a legitimate partial-geometry candidate since a preview frame doesn't need the "reset from stale preview" guarantee its own commit does. `commit=True` is the final authoritative commit and should stay full, matching GEO-09's sibling reasoning. The original plan inventory only looked at the commit branch (mislabeled "(commit)" in the plan doc) and missed that the preview branch is the higher-value target. Needs its own follow-up: compute the overhang's backing helix id directly from `_find_ovhg_or_404`'s result (not occupancy-diffing — this is a pose-only change) and apply `changed_helix_ids` ONLY on the `commit=False` branch. Deferred rather than guessed under time pressure — a live-drag interaction path is hard to unit-test meaningfully and impossible to verify without a running browser |
| GEO-11 | `PATCH .../sub-domains/rotations-batch` | 5539 | **same split finding as GEO-10** (batch preview vs. batch commit) — deferred alongside it |
| GEO-12 | `POST /design/overhangs/batch-delete` | 6161 | **done** — `_local_changed_helices` (can remove whole helices, not just domains; the utility's own bail-to-full-geometry when `overhang_connections` changed protects the linked-overhang case) + `partial_axes=True` (a removed helix must also drop from `currentHelixAxes`, which only happens via the partial-axes merge branch). New test `test_overhangs_batch_delete_ships_partial_geometry` (route had zero prior coverage) |
| GEO-13 | `POST /design/overhang/{id}/resize-free-end` | 6536 | **done** — direct `changed_helix_ids=[spec.helix_id]` (helix identity already known, no occupancy diffing needed) + `partial_axes=True` (same axis-segments reasoning as GEO-03). Existing `tests/test_sub_domains.py` coverage still passes; no dedicated new assertion on response shape (existing tests don't check it either way) |

Non-`crud.py`:

| ID | Route | File:Line | Status |
|---|---|---|---|
| GEO-14 | `POST /design/duplexes/{id}/relax` | `routes_duplex.py:395` | **investigated, deferred — same family as GEO-21.** Calls `relax_direct_binding`, whose docstring says it may "rigid-translate the driven root CLUSTER" — an unbounded set of helices outside the two named overhangs, not expressible via occupancy-diffing (rotation/cluster-transform changes aren't domain changes) or a simple direct helix-id list. Needs real investigation into `relax_direct_binding`'s cluster-kinematics branch before a partial response is safe; guessing risks silently leaving stale positions on helices outside the reported set |
| GEO-15 | `DELETE /design/extensions/batch` | `routes_extensions.py:156` | **done** — direct `changed_helix_ids=[f"__ext_{eid}" for eid in id_set]`; extensions live on synthetic `__ext_<id>` helices (documented convention in `_design_response_with_geometry`'s own docstring), never a real strand's helix, so no occupancy diffing needed. Fixed an existing test (`test_routes_extensions_fast_delete.py`) whose mock lambda had a too-narrow signature for the new kwarg — legitimate test maintenance, not a behavior conflict |
| GEO-16 | `DELETE /design/extensions/{id}` | `routes_extensions.py:271` | **done** — same fix, single id |
| GEO-17 | `POST /design/protein/conjugate` | `routes_protein.py:328` | **done** — same `_strand_occupancy`/`_local_changed_helices` pattern as GEO-02 (also creates a binder strand via `make_binder_for_overhang`); added the `render_diff` import to `routes_protein.py` |
| GEO-18 | flexible-segment mark/unmark (3 routes via `_flex_log_response`) | `routes_flexible_segments.py:95` | **investigated, deferred.** `_strand_occupancy` is the wrong tool (marks never touch domains). But it's simpler than first feared: `apply_marks` "never mutates clusters or topology — only the derived connection list," so the only helix that actually needs re-shipped geometry is the marked bead's own (`is_flexible_segment` is a real per-nucleotide geometry field per `_design_replace_response`'s comment, not a pure frontend derivation). `FlexibleSegmentMark` has no `helix_id` field though — needs resolving via `strand_id`+`domain_index` at each of the 3 call sites, and the `batch` route's `replace=True` case needs the UNION of every OLD and NEW mark's helix (all previous marks are cleared). Correctly scoped now, but not implemented this pass — lower traffic than the routes already done, and `replace=True`'s "old ∪ new" case still needs care to get right rather than guess |
| GEO-19 | `POST /design/flexible-relax` | `routes_flexible_segments.py:157` | **done** — helix ids resolved directly from `cluster_transforms[i].helix_ids` for every affected cluster (no occupancy diffing needed — pose-only). Confirmed safe unlike GEO-09's rotation-commit case: the frontend already ran the relax solve and this endpoint only persists the exact poses it previewed with, so there's no "authoritative server recompute over stale preview" concern. `partial_axes=True` (cluster rigid-transform moves axis positions) |
| GEO-20 | connection-version non-local fallback | `routes_connection_versions.py:506` | **investigated, already optimal, no action.** This route ALREADY applies `_local_changed_helices` (line ~495) and only reaches the full-geometry line 506 fallback when that returns `None` — i.e. it's already using the same defensive pattern as the newly-fixed routes. "Narrowing the trigger" would mean extending `_local_changed_helices` itself to handle more cases (e.g. partial extension/connection diffs) — that changes a shared utility every other GEO fix in this backlog also depends on, which is a real feature addition, not a per-route fix. Out of scope here |
| GEO-21 | `POST /design/overhang-bindings/{id}/relax` | `routes_relaxation.py:60` | **investigated, deferred — same family as GEO-14.** Identical docstring/mechanism (`relax_direct_binding`), identical cluster-kinematics risk |
| GEO-22 | `PUT /design/nucleotide-transform` | `routes_nucleotide_transforms.py:113` | **done, but two-way split, not a single mechanical fix.** `design_geometry.py::apply_nucleotide_transforms_to_geometry` only bakes `kind == "base"` poses into real geometry — `kind == "extra_base"` is explicitly excluded (applied client-side instead, same as the extra-bases sequence routes). So: `base` → `changed_helix_ids=[transform.helix_id]` (real geometry win); `extra_base` → `geometry_unchanged: true` + the same `skipGeometry` frontend companion change as GEO-06/07/08, applied to both `putNucleotideTransform`/`deleteNucleotideTransform` in `client.js` |
| GEO-23 | `DELETE /design/nucleotide-transform/{id}` | `routes_nucleotide_transforms.py:132` | **done** — same two-way split, branches on `existing.kind` |
| GEO-24 | overhang-binding create/patch/display-pose (3 routes via `_binding_response`) | `routes_overhang_bindings.py:25` | **split, 2 of 3 done.** `_binding_response` gained a `geometry_unchanged` kwarg. Applied to `create_overhang_binding` (a fresh binding always starts `bound=False` — pure metadata, no strand/geometry change) and `patch_binding_display_pose` (its own docstring: "Annotation-only... Does not relocate topology"), + the matching `skipGeometry` frontend companion on both `overhang_endpoints.js` wrappers. The general PATCH route (`patch_overhang_binding`, unnamed in the original inventory but the 3rd `_binding_response` caller) drives `_apply_driver_to_joint` — same joint/cluster-kinematics risk as GEO-14/21/25, left on full geometry, not itemized as its own row originally |
| GEO-25 | `DELETE /design/overhang-bindings/{id}` | `routes_overhang_bindings.py:530` | **investigated, deferred — same family as GEO-14/21.** Also drives `_apply_driver_to_joint` (heir-claimant migration can re-open/re-lock a joint window), same unbounded-helix-set risk |

**Excluded, no bounded footprint by construction (do not itemize):** `create_bundle`
(`crud.py:1413`), `auto_crossover` (`crud.py:3443`), `roll_active_to_job_state`
(`crud.py:8319`), `revert_to_before_feature` all branches (`crud.py:8398/8434/8492`), the
undo/redo/edit/delete-feature fan-in (`_design_replace_response`, already has its own
partial branch for the common case), `full_autostaple` (`routes_assign_sequences.py:508`),
`auto-scaffold-{seamed,matched,seamless}` + `route-for-polymerization`
(`routes_scaffold_routing.py`), all loadout routes (`routes_design_loadouts.py`).

**Observed in passing during GEO-12/13, not investigated further:** `extend_helix_bounds`
(`crud.py`, pre-existing code, not touched by this initiative) passes
`changed_helix_ids=[helix_id]` with no `partial_axes=True`, yet its own docstring says it
"Adjusts axis_start/axis_end" — which per the domain-shift (GEO-03) / resize-free-end
(GEO-13) lesson should need `partial_axes=True` to actually reach the frontend. Possibly a
latent, unrelated gap, or there's a compensating mechanism not investigated here. Flagging
only so it isn't lost — a future session should check it independently.

## Per-iteration verification

- Backend change → `just test-smart`, report its FAST/fast+slow decision and pass count
  verbatim.
- FL-04 and at least one GEO item → add/extend a targeted backend test.
- After the first FL item and first few GEO items → load a representative large design
  in the running app and visually confirm (`just dev` + `just frontend`), per CLAUDE.md's
  verification law. Never claim a check passed without running it.

## Next handoff (backlog complete as of 2026-08-18)

Every FL and GEO item above is in a terminal state (done / stale / investigated-and-
deferred). Nothing left pending except items already flagged as blocked or requiring
fresh scoping:

1. **FL-05** — in-app check (Feature Log panel / revert / seek / reload-recovery still
   work after routine edits strip blobs). Blocked on live dev-server access
   (`feedback_no_live_server_mutation_for_verify`) — ask the user, or do it next time
   the app is confirmed safe to touch.
2. **FL-06** — undo/redo/edit-feature/delete-feature/seek (`_design_replace_response`)
   currently always ships full feature-log bodies. A real fix needs either a
   body-version/hash the client can compare, or a proof that `edit_feature`'s replay
   only ever changes entries after the edited index. Needs its own investigation
   session, not a quick follow-up.
3. **GEO-10/11 preview branch** — the `commit=False` live-preview branch of the
   sub-domain rotation routes is a real, scoped opportunity (compute the overhang's
   backing helix directly, apply `changed_helix_ids` ONLY there, leave `commit=True`
   full). Fires every gizmo-drag frame, so probably the single highest-value item left
   — but needs care given the coalesce-window feature-log logic sitting right next to it.
4. **GEO-18** — flexible-segment mark/unmark. Scoped (see its row above) but not
   implemented: resolve `helix_id` from `strand_id`+`domain_index` at each of 3 call
   sites; the batch route's `replace=True` case needs old ∪ new mark helices.
5. **The joint/cluster-kinematics family** (GEO-14, GEO-21, GEO-25, GEO-24's general
   PATCH branch) — all four need `relax_direct_binding`/`_apply_driver_to_joint`
   understood well enough to bound the affected helix set before any partial response
   is safe. Likely a single investigation session covers all four at once, since
   they share the same two underlying mechanisms.
6. **Lever 2b / assembly-layer diffing / general topology diffing** — as scoped in
   the original plan, still out of scope for this backlog.

Start a fresh session on whichever of 1–5 matches available context (live app access
→ #1; a few hours of focused kinematics reading → #5; otherwise #3 or #4).
