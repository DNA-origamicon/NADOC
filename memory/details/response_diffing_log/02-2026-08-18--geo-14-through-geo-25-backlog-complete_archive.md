# 2026-08-18 — GEO-14 through GEO-25 (backlog complete) — historical evidence

[Topic head](../../response_diffing_log.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## 2026-08-18 — GEO-14 through GEO-25 (backlog complete)

Worked through the rest of Lever 2. Pattern held: about half of the remaining items
needed real per-route investigation rather than mechanical `changed_helix_ids`
application.

**Deferred as one family (GEO-14, GEO-21, GEO-25, and the un-itemized general PATCH
branch of GEO-24):** every route that calls `relax_direct_binding` or
`_apply_driver_to_joint` can rigid-translate or re-lock joints/clusters outside the
one named overhang/binding — an unbounded helix set that neither occupancy-diffing
nor a direct id list can safely express without modeling the joint kinematics
properly first. Left on full geometry, documented why in the backlog rather than
guessed.

**Done via direct/known helix ids (no occupancy diffing needed):**
- GEO-15/16 (extension delete, batch + single): `__ext_<id>` synthetic helix ids —
  a documented existing convention, not something I invented. Had to fix an existing
  test (`test_routes_extensions_fast_delete.py`) whose mock lambda's signature didn't
  anticipate the new kwarg.
- GEO-19 (flexible-relax): `cluster_transforms[i].helix_ids` directly — confirmed
  safe unlike the rotation-commit family because the server does no additional
  authoritative computation, it only persists poses the frontend already computed.

**Done via `_strand_occupancy`/`_local_changed_helices` (GEO-02's pattern):**
- GEO-17 (protein conjugate) — creates a binder strand, same shape as GEO-02.

**Done via the `geometry_unchanged` contract (GEO-06's pattern, needs the frontend
companion change too):**
- GEO-22/23 (nucleotide-transform put/delete) — turned out to be a TWO-WAY split:
  `design_geometry.py::apply_nucleotide_transforms_to_geometry` only bakes
  `kind=="base"` poses into real geometry (confirmed by reading it — it filters to
  `kind == "base"` explicitly). `kind=="extra_base"` gets `geometry_unchanged`;
  `kind=="base"` gets a real `changed_helix_ids=[transform.helix_id]`.
- GEO-24 (overhang-bindings, 2 of its 3 `_binding_response` callers): a freshly
  created binding always starts `bound=False` (pure metadata), and the display-pose
  PATCH route's own docstring says "does not relocate topology" — both safe. Added a
  `geometry_unchanged` kwarg to the shared `_binding_response` helper rather than
  duplicating the branch three times.

**Investigated, no code change needed:**
- GEO-01 (scaffold-domain-paint): already free via the 2D-editor's
  always-on skip-geometry header.
- GEO-09/10/11 (overhang + sub-domain rotation): rotation lives on `Overhang.rotation`
  / sub-domain theta+phi, never a strand domain — wrong tool even setting aside the
  deliberate full-geometry-on-commit design choice its sibling route documents.
  GEO-10/11 do have a real, previously-unnoticed opportunity (their `commit=False`
  live-preview branch, fired every gizmo-drag frame) — documented but not
  implemented; asymmetric preview/commit logic in a live-drag path is exactly what
  "stop and flag rather than guess" is for.
- GEO-18 (flexible-segment mark/unmark): scoped correctly (only the marked bead's own
  helix needs re-shipping; `apply_marks` never touches other helices' geometry) but
  not implemented — `FlexibleSegmentMark` has no `helix_id` field, needs resolving at
  each of 3 call sites, and the batch route's `replace=True` case needs the union of
  every OLD and NEW mark's helix.
- GEO-20 (connection-versions non-local fallback): already using the same defensive
  `_local_changed_helices` pattern as everything else here; "improving" it means
  extending the shared utility itself, not a per-route change.

Backend: `just test-smart` FAST, 7105 passed, 115 skipped, no failures (final run
after all of GEO-14–25). Frontend: `just test-frontend`, 336 files / 5735 passed
(covers all `client.js`/`overhang_endpoints.js` companion changes across the whole
initiative — GEO-06/07/08, GEO-22/23, GEO-24).

**Not verified in a running browser** for any of this — no live-server access without
the user's go-ahead (`feedback_no_live_server_mutation_for_verify`). FL-05 (the
Lever-1 in-app check) is still open for the same reason.

**Backlog status at end of this session:** Lever 1 complete (FL-01–04, FL-07 landed;
FL-05 blocked on live app access; FL-06 newly discovered, unscoped, needs its own
investigation before undo/redo/edit-feature can safely default-strip). Lever 2:
13 of 25 items shipped, 2 already-optimal (no-op), 10 investigated-and-deferred with
documented reasons (mostly the joint/cluster-kinematics family and the rotation
preview/commit split). Nothing was guessed at under time pressure — every deferral
has a concrete, written reason and, where possible, a concrete next step.
