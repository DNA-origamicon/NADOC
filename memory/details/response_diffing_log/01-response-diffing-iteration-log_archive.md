# Response-diffing iteration log — historical evidence

[Topic head](../../response_diffing_log.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

# Response-diffing iteration log

Append-only. One entry per work session. Head/queue lives in `project_response_diffing.md`.

## 2026-08-18 — Planning + profiling

Started from a user report of perceived lag editing large designs over a remote
Tailscale connection. Ruled out network (direct P2P, ~5ms RTT via `tailscale
status`/`tailscale ping`). Traced the actual cost to full-design re-serialization on
every mutation. User asked to profile before committing scope.

Profiled 4 real `.nadoc` files offline (`Design.from_json` + `design.to_dict()` +
`_geometry_for_design`/`_geometry_for_helices`, gzip level 3). Found feature-log body
blobs account for 53–90% of gzipped topology payload on every design sampled (not just
heavily-edited ones) — a much bigger and cheaper win than expected, and separable from
geometry. Core topology minus blobs is small (45–52 KB gz for 3/4 files), so general
topology diffing was excluded from scope as high-risk/low-marginal-value. Landed on two
levers: FL (feature-log blob suppression, broad + low risk) and GEO (extend existing
`changed_helix_ids` partial-geometry mechanism to ~25 more bounded-footprint routes).

Plan approved by user. Backlog seeded in `project_response_diffing.md`. Starting
execution with FL-01.

## 2026-08-18 — Lever 1 implemented (FL-01–04)

Flipped `_design_response`/`_design_response_with_geometry` (`backend/api/crud.py`)
to strip feature-log body blobs by default, via two new kwargs:
`preserve_feature_log_id` (keep one entry's body — used by routes that just created
it) and `full_feature_log` (skip stripping entirely — the cold-load escape hatch).

Turned out the cold-load exemption list was much bigger than "GET /design alone" —
found it properly by grepping structural markers (`design_state.clear_history()`,
`design_state.set_design_branch()`) instead of guessing route-by-route. Ended up
exempting 13 routes: GET /design, 8 clear_history-based load/import/create routes,
3 branch-switch routes (loadout select/activate/roll-to-job-state), plus a
conditional in `delete_loadout` (only when it actually switches branch).

Also found mid-implementation that `_design_replace_response` (the undo/redo/
edit-feature/delete-feature/seek fan-in, 5 internal call sites) can't safely use the
new default at all yet: `edit_feature` regenerates an existing feature-log entry's
body IN PLACE under the same id, and the client's cache-merge logic can only fill in
a MISSING body, not tell a stale one from a fresh one. Left that whole path on
full_feature_log=True (unchanged behavior) and filed it as FL-06, a new backlog item
needing its own investigation (body versioning or a narrower "safe to strip" proof)
rather than guessing.

Deleted `_slim_mutation_history_payload` (the old opt-in helper) — its 5 former call
sites now pass `preserve_feature_log_id` directly, which is strictly more general.

Added 3 regression tests to `tests/test_feature_log_snapshot.py`: ordinary mutation
(PUT /design/metadata) strips by default, GET /design retains full bodies, POST
/design/load retains full bodies. All existing feature-log tests
(test_feature_log_snapshot.py, test_reference_geometry.py) still pass unchanged —
28→31 and 20→20 respectively.

`just test-smart`: FAST, 7103 passed, 114 skipped. One DEFERRED (needs FULL suite)
reported — traced to an unrelated prior commit touching backend/api/state or main.py
(not in this session's diff), not something this change caused.

FL-05 (in-app verification: Feature Log panel / revert / seek / reload-recovery in the
running app) is blocked — requires driving the live dev server, which needs the
user's go-ahead per feedback_no_live_server_mutation_for_verify. Left pending.

Moving to Lever 2 (GEO-01 onward) next — no dependency on FL-05.

## 2026-08-18 — Lever 2 started: GEO-01 through GEO-08

GEO-01 (`scaffold-domain-paint`) turned out to be stale before any code change: its
only caller is the 2D cadnano-editor, which always sends `X-NADOC-Skip-Geometry`, so
`_design_response_with_geometry` already short-circuits to the geometry-free path —
`changed_helix_ids` would never be exercised. Marked stale, no edit.

GEO-02 through GEO-05 (generate-binder, domain-shift, crossovers/place,
crossovers/place-batch) used the existing `_strand_occupancy`/`_local_changed_helices`
diff utility (`backend/core/render_diff.py`) already powering `add_nick` /
`delete_crossover` / the extrude routes — captured before/after each mutation, fed
`changed_helix_ids`. domain-shift additionally needed `partial_axes=True`: caught by
`tests/test_domain_shift.py`'s existing assertion that `helix_axes` reflects the
shifted domain's new `segments` — a shifted domain doesn't move the helix's axis
endpoints, but does change what range the axis-stick segments cover, and that's
axis-carried metadata, not geometry-carried.

GEO-06/07/08 (crossover + forced-ligation extra-bases) needed a DIFFERENT fix, not
`changed_helix_ids`: `extra_bases` lives on the `Crossover`/`ForcedLigation` record,
never on a strand domain, and grepping confirmed `design_geometry.py` never reads it
— no real nucleotide moves at all. `changed_helix_ids=[]` looked tempting but is
actively dangerous: traced the frontend logic and `json.changed_helix_ids?.length`
being falsy for an empty list means `_syncFromDesignResponse` takes the FULL
REPLACEMENT branch with an empty nucleotides array, wiping the scene. The correct,
already-proven mechanism is `geometry_unchanged: true` (`patch_strands_reference`
established it, but it was previously untested on the frontend side) — switched all
3 routes to it and wired the matching `skipGeometry` check into their 3 client.js
wrappers. This is a real, if small, scope creep: a frontend companion change, not
just backend. Added both a backend test and a new frontend test file
(`client_extra_bases_geometry_unchanged.test.js`, mirrors the existing
`overhang_endpoints.test.js` fetch-mock pattern). `just test-smart`: 7105 passed.
`just test-frontend`: 336 files / 5735 passed. Not exercised in a running browser
(no live-server access without the user's go-ahead) — flagged as such, not claimed.

Lesson for the remaining GEO items: don't assume `changed_helix_ids` is always the
right tool. Check what field the mutation actually touches and whether
`design_geometry.py`/`_geometry_for_helices` ever reads it before reaching for the
occupancy-diff pattern.

## 2026-08-18 — GEO-09 through GEO-13

GEO-09 (overhang-rotations batch) and GEO-10/11 (sub-domain rotation, single + batch)
turned out NOT to be mechanical additions. Rotation lives on `Overhang.rotation` /
sub-domain theta+phi, never on a strand domain, so occupancy-diffing (the tool used
for GEO-02–05) can't see this class of change at all — wrong tool regardless of any
other concern. More importantly, the sibling single-overhang rotation route
(`patch_overhang`) has an explicit existing comment: full geometry is CHOSEN
deliberately on a rotation commit so the frontend rebuilds from server-authoritative
positions instead of trusting its own in-memory drag-preview state, and
`overhang_orientation_menu.js`/`_panel.js` confirm the batch route is used in exactly
that "reset previews to identity" flow. GEO-09 is not a miss — left alone.
GEO-10/11 have a real, un-itemized opportunity the original plan's inventory missed:
each has a `commit=False` LIVE-PREVIEW branch (fires every gizmo-drag frame) that
IS a legitimate partial-geometry candidate, separate from the `commit=True` branch
that should stay full for the same reason as GEO-09. Documented the split and
deferred rather than guess at asymmetric preview/commit logic in a live-drag path
that's hard to unit-test and impossible to verify without a running browser.

GEO-12 (`overhangs/batch-delete`) can delete a whole helix, not just shrink a domain
— verified `_local_changed_helices` handles that correctly (the deleted strand's old
helix set gets unioned in) and correctly bails to full geometry when
`overhang_connections` changed too (the linked-overhang case). Added
`partial_axes=True` since a removed helix must also drop out of the frontend's
`currentHelixAxes`, which only happens via the partial-axes merge branch. This route
had ZERO prior test coverage — added `test_overhangs_batch_delete_ships_partial_geometry`.

GEO-13 (`resize-free-end`) resizes one domain's bp range on an already-known helix
(no occupancy diffing needed — used `changed_helix_ids=[spec.helix_id]` directly,
matching the existing `extend_helix_bounds` precedent) + `partial_axes=True` (same
axis-segments reasoning as GEO-03/domain-shift).

Noticed in passing: `extend_helix_bounds` (pre-existing, untouched) passes
`changed_helix_ids` WITHOUT `partial_axes=True` despite its docstring saying it moves
axis_start/end — logged as an observation in the backlog head, not investigated or
fixed (out of scope, not one of this initiative's routes).

`just test-smart`: 7105 passed, 115 skipped, no failures.
