# Coexistence hazards (found 2026-07-30 resolving the contradicting peer — none covered by any test) — supporting detail

[Topic head](../../project_overhang_duplex_foundation.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### Coexistence hazards (found 2026-07-30 resolving the contradicting peer — none covered by any test)

9. ~~Different-length pairs are excluded from overhang co-motion.~~ **CONFIRMED BY TEST, THEN
   FIXED 2026-07-30.** The prediction was right: a 90° driver rotation moved the WC pair distance
   from **1.93 nm → 5.25 nm** — the driven overhang stayed behind — and the materialized duplex
   cluster's `domain_ids` held only `('oh_strand_a', 0)`, omitting the driven domain entirely.
   Root cause was **one lookup read by three sites**: `driven_to_driver` (co-rotation partners),
   `driven_bound_oh_ids` (the driven-side self-rotation skip), and transitively
   `_duplex_domain_refs` → `materialize_duplex_cluster` (the gizmo-drag scope) all built their map
   from `design.overhang_bindings` **only**, while `relocate_duplex`'s `__duplex_reloc__` binding
   is transient and never persisted (`duplex.py:311`).
   **Fix:** new `deformation._bound_driver_driven_pairs(design)` returns `driven → driver` from
   **both** bound bindings and bound duplexes (bindings win on conflict — they agree anyway, since
   `_propagate_driver_to_binding` syncs duplex→binding); both call sites now use it, which fixes
   the cluster scope for free. **Pinned by** `tests/test_overhang_binder_rotation.py`
   `test_diff_length_duplex_partner_follows_rotated_driver` (geometry: WC pair distance preserved
   through a 90° driver rotation) + `test_diff_length_duplex_cluster_contains_the_driven_domain`
   (structure: the driven domain is in the cluster's `domain_ids`). Both assert the no-binding
   precondition first, so they fail loudly if the length fork ever changes. Still **not
   app-verified** — the in-app check is: connect a 10-mer to a 24-mer, rotate the duplex, confirm
   the driven overhang follows.
10. **Driver sync is one-directional.** `PATCH /design/duplexes/{id}` pushes duplex→binding
    (`_propagate_driver_to_binding` + `reapply_binding_driver`). **Nothing pushes binding→duplex** —
    `patch_overhang_binding` (`crud.py:8586`) has zero `duplexes` references, so flipping the driver
    through a binding-side route leaves `Duplex.driver` stale and the panel's toggle shows the
    wrong side.
11. **Deleting either record leaves the other dangling.** `delete_duplex`
    (`routes_duplex.py:283-294`) never touches bindings; `delete_overhang_binding`
    (`crud.py:8887`) never touches `duplexes`.
12. **Re-Connect on the same pair reuses a stale duplex.** `apply_connection_version`'s teardown
    (`crud.py:7741-7759`) reverts topology and strips `overhang_bindings` but **never strips
    `duplexes`**, so the follow-up `connect_duplex` 409s ("already connected by a duplex") and the
    panel swallows it — the old register survives a reconnect.
13. **Headless can't produce what the UI produces.** No headless method makes both records; a
    different-length `apply_connection_version` makes **neither**. Any automation oracle built on
    the headless path is therefore testing a state the app never produces (and vice versa). This is
    also why the disjoint test sets never caught items 9-12: apply-path tests assert bindings and
    never inspect duplexes, connect-path tests assert duplexes and never inspect bindings, and
    **no test exercises the panel's apply→connectDuplex sequence** (`connectDuplex` has zero hits
    in any `*.test.js`).

**Phase 5 (attachments) needs no work** — fluorophores/quenchers/biotin are the pre-existing
`StrandExtension.modification` feature (full CRUD, Bézier-arc bead geometry on a `__ext_` helix,
emission glow + FRET). To label an overhang: add `StrandExtension{strand_id, end,
modification:'cy3'}` on the overhang's staple terminus. A duplicate `Attachment` model was built
and fully reverted (user caught it). If internal-base labels are ever wanted, EXTEND
`StrandExtension` — never a second model.
