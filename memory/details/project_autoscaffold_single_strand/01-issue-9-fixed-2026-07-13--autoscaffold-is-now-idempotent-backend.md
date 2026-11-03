# ✅ ISSUE-9 FIXED 2026-07-13 — autoscaffold is now idempotent (`backend/core/scaffold_reset.py`) — supporting detail

[Topic head](../../project_autoscaffold_single_strand.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## ✅ ISSUE-9 FIXED 2026-07-13 — autoscaffold is now idempotent (`backend/core/scaffold_reset.py`)

**Re-routing an already-routed design no longer re-extends anything.** `reset_scaffold_to_structure()` runs at the
top of `auto_scaffold_seamed` / `auto_scaffold_matched` / `auto_scaffold_seamless` and retracts the design to its
structural seed first, so N routes ≡ 1 route. The routing algorithm itself is UNCHANGED — only its input is
normalised. Pinned by `tests/test_scaffold_idempotence.py` (12 tests).

**It was never teeth-specific.** A plain 4HB bundle (no teeth, no sections) ratcheted `168 → 189 → 199 → 210` bp
and `6 → 9 → 12` crossovers over three routes, on BOTH routers. Teeth is just where it was *visible*.

**The oracle: STAPLES ARE THE STRUCTURE.** Autoscaffold never touches staple strands, so a helix's true extent is
the bp span of its staple domains (including staple overhangs running past the scaffold). Verified: staple spans
held at `[0,167]` across three re-routes while the helices ratcheted to `[-30,179]`. And in the real multi-section
fixtures the staple intervals ARE the scaffold sections, gaps and all — teeth `[(0,41),(84,125),(168,209)]`,
dumbbell `[(0,41),(126,167)]` — i.e. exactly the "clean per-domain seed" that was wanted. **The scaffold is route
output; the staples are the design.** Reset clamps INTO the staple intervals and never grows the scaffold to fill
them; forced ligations bail out (their fixed-edge topology isn't derivable from the staples).

Second bug fixed alongside: the seamed router stamps three `process_id`s on its crossovers
(`auto_scaffold_seamed:seam`, bare `create_near_ends`, `create_far_ends`) but the old clear matched only the
`auto_scaffold_` prefix — so the end-turn crossovers survived every "clear" (hence the accumulation), and
`_clear_auto_scaffold_route_for_seamed` (used by `auto_scaffold_matched`) had never actually worked.

**Retired concern:** `10-6-10hb_seamed.nadoc` being pre-routed is no longer "latent corruption" — a re-route now
resets to the structural seed first, so a pre-routed fixture can't poison a measurement any more.

**Owed:** user eyeball — run Auto-scaffold twice on a teeth design and confirm the faces don't move.

---
