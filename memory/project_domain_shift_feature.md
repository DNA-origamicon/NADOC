---
name: Domain shift feature — drag-to-move domains in cadnano editor
description: Architecture, gotchas, and lessons from building cadnano-editor drag-to-move-domain (POST /design/domain-shift). Read before touching shift_domains, the cadnano editor's domain-drag logic, the importer crossover classifier, or the helix axis math used by lattice mutations.
type: project
originSessionId: fdc481cc-d1e5-40f0-848f-0796d43300bb
---
# Domain shift feature (branch `feature-log-update`, 2026-05-03)

## What was built

**Frontend** ([frontend/src/cadnano-editor/pathview.js](frontend/src/cadnano-editor/pathview.js)) — drag-to-move-domain in the standalone cadnano editor: select a domain (or Ctrl-multiselect several), click-drag the body, ghost rectangles preview at the snapped delta, release commits via `POST /design/domain-shift`. Sits alongside the end-drag-resize at the same priority order in `pointerdown` (cap → sprite → arc → domain body → lasso). Helpers: `_resolveDomainDragEntries`, `_computeDomainDragLimits`, `_drawDomainDragGhost`. Co-selected domain endpoints are excluded from the blocker list (so two selected domains can shift past each other's endpoints by the shared delta).

**Backend** ([backend/core/lattice.py](backend/core/lattice.py) `shift_domains`, [backend/api/crud.py](backend/api/crud.py) `POST /design/domain-shift`) — pure builder applies all per-strand shifts, validates pre/post state (no Crossover at endpoint or strictly inside, no overlap on `(helix, direction)`, no negative bp), updates ForcedLigation bp anchors that match any shifted domain endpoint, rebuilds helix axes, and reconciles inline overhangs. Wired through `mutate_with_minor_log` with op_subtype `'domain-shift'` so it lands as a child under the open `RoutingClusterLogEntry` ("Fine Routing"). Replay branch in `_replay_minor_op` for slider seek.

## Critical gotchas (read before changing this code)

### 1. cadnano `length_bp` is the FULL caDNAno array, not the physical extent

[cadnano.py:456-466](backend/core/cadnano.py#L456) sets `length_bp = array_len` (e.g. 832) while `axis_start.z = first_bp * RISE` and `axis_end.z = last_bp * RISE`. So **`bp_start + length_bp - 1` is NOT the last physical bp** — the axis only spans `last_bp - first_bp` intervals.

Any code that does `helix_end_bp = bp_start + length_bp - 1` for grow/trim decisions on a cadnano-imported helix will be wrong by hundreds of bp. The legacy trim formula in `shift_domains` and `resize_strand_ends` divided by `helix.length_bp`, collapsing the axis to ~1 bp on these files. Fix in `shift_domains`: replaced grow+trim with a single rebuild that uses physical units:

```python
new_axis_start = old_axis_start + aDir * (lo_bp - old_bp_start) * RISE
new_axis_end   = old_axis_start + aDir * (hi_bp - old_bp_start) * RISE
```

This works for both conventions (`length_bp == physical extent` for native, `length_bp == array length` for cadnano imports). **`resize_strand_ends` still has the legacy formula and the same bug** — fix it the same way before any cadnano-import file is shifted via end-resize.

### 2. `_reconcile_inline_overhangs` needs POST-shift scaffold coverage

Calling `_scaffold_coverage_by_helix(design)` on the *original* design when the scaffold itself was shifted gives stale coverage. The reconcile then thinks staples extending past the OLD scaffold high are overhangs and splits them. Mirror the fix in `shift_domains`: build `updated_design = design.model_copy(update={"strands": [strands_by_id.get(s.id, s) for s in design.strands]})` and pass `_scaffold_coverage_by_helix(updated_design)`.

### 3. Importer crossover classification — same-bp + lattice-neighbour

[crossover_positions.py — `extract_crossovers_from_strands`](backend/core/crossover_positions.py) emits `Crossover` only when `d0.end_bp == d1.start_bp` AND the two helices are valid lattice neighbours at that bp (per `crossover_neighbor` checking BOTH the staple and scaffold offset tables). Everything else (mismatched bp = scadnano loopouts, same-bp non-neighbours like Δrow=2) emits a `ForcedLigation` with `three_prime` = d0's exit and `five_prime` = d1's entry.

[Design.from_json](backend/core/models.py) runs two on-load fix-ups in order: (a) `_reclassify_invalid_crossovers` moves saved Crossover records that fail the lattice-neighbour test into `forced_ligations`, (b) `_backfill_dropped_forced_ligations` adds FLs for cross-helix transitions that have NO existing Crossover or FL covering them (older imports silently dropped these). Both are idempotent — re-saving and re-loading does not duplicate.

**Concrete numbers from `Ultimate Polymer Hinge 191016.nadoc`:** 829 → 813 crossovers (16 reclassified as FLs), 0 → 29 FLs (16 reclassified + 13 backfilled). dom 22 had a Crossover at h_XY_5_6 (23,26)↔h_XY_3_7 (25,27) — Δrow=2, Δcol=1 — which reclassify correctly converts to FL, unblocking the move.

### 4. ForcedLigation bp tracking — fire on ANY matching domain endpoint, not just terminal

The original `shift_domains` only updated FL anchors when `is_first` / `is_last` was set. After classification audit, FLs can anchor INTERNAL domain endpoints too (e.g., dom 46 of a 97-domain scaffold strand). Generalized rule:

```python
for fl in forced_ligations:
    for shift in shifts_record:
        # Match by (helix, direction) on either side; update bp by the shift's delta.
```

Internal-domain shifts now keep their bracketing FLs in sync. Test: `test_internal_domain_shift_updates_fl_anchors_at_endpoints`.

### 5. Frontend `getGeometry()` was dropping `helix_axes.segments`

Three places in [client.js](frontend/src/api/client.js) parse `helix_axes` (line 182, 649, 696). Only the embedded-response path (line 182) was forwarding `segments`. After a cadnano-editor mutation, the broadcast → re-fetch path went through `getGeometry()` (line 649) which dropped `segments`, forcing the renderer to fall back to local computation that doesn't apply per-segment cluster transforms. Fixed all three to forward `segments`.

### 6. Co-selected domains must NOT block each other in the limit calc

`_computeDomainDragLimits` builds a `coSelected` set keyed by `${strandId}\x00${domainIndex}` and skips those domains in the "other endpoints" lookup. Without this, multi-selecting two adjacent domains and dragging makes them clamp each other to zero even though they shift together by the shared delta.

## Decisions worth remembering

- **"Forced crossover" = `ForcedLigation` records only.** Plain `Crossover` rows always block the drag, regardless of `process_id`.
- **Other-side of FL is untouched on shift.** When only our side's domain shifts, only the matching `*_bp` updates; the other side's bp stays put. If both sides of an FL are co-selected, both update by the shared delta because both domains are in the entries list.
- **bp 0 is a hard floor.** Negative bp is rejected. Backend auto-grows the helix on the upper end via the unified rebuild.
- **LINKER strands are draggable** under the same rules.
- **A domain with a real (lattice-valid) Crossover at either endpoint is NOT moveable** — relaxing this would require shifting the crossover bp along with the domain, which is a separate design decision.

## Verification surface

- 27 tests in [tests/test_domain_shift.py](tests/test_domain_shift.py): basic shift, both-end FLs, internal-domain FL tracking, co-selected blockers, scaffold-shift-doesn't-split-staple, cadnano-style `length_bp >> physical span` axis preservation, Fine Routing cluster, undo, revert, slider seek, and a `test_dom22_scenario_remains_movable_after_axis_fix` regression that constructs the exact non-neighbour-crossover-at-endpoint shape and verifies the full pipeline (reclassify → shift → axis rebuild → FL track).
- 10 tests in [tests/test_importer_crossover_classification.py](tests/test_importer_crossover_classification.py): classifier rules + `from_json` reclassify/backfill + idempotence + valid-Crossover preservation.
- Full backend regression: 767 pass.

## Files modified (this feature)

- [backend/core/models.py](backend/core/models.py) — `'domain-shift'` in `MinorOpSubtype`, `_reclassify_invalid_crossovers`, `_backfill_dropped_forced_ligations`, `Design.from_json` runs both.
- [backend/core/crossover_positions.py](backend/core/crossover_positions.py) — `extract_crossovers_from_strands` returns `(crossovers, forced_ligations)` with lattice-neighbour classification.
- [backend/core/lattice.py](backend/core/lattice.py) — `shift_domains` (new); FL update generalized to internal domains; grow+trim → unified rebuild.
- [backend/core/cadnano.py](backend/core/cadnano.py), [backend/core/scadnano.py](backend/core/scadnano.py) — pass helices+lattice to classifier; assign returned forced_ligations.
- [backend/api/crud.py](backend/api/crud.py) — `DomainShiftRequest`, `_build_domain_shift`, `POST /design/domain-shift`, `_replay_minor_op` branch.
- [frontend/src/cadnano-editor/api.js](frontend/src/cadnano-editor/api.js) — `shiftDomains()`.
- [frontend/src/cadnano-editor/pathview.js](frontend/src/cadnano-editor/pathview.js) — domain-drag state, helpers, ghost, pointer handlers.
- [frontend/src/cadnano-editor/main.js](frontend/src/cadnano-editor/main.js) — `onShiftDomains` wiring.
- [frontend/src/api/client.js](frontend/src/api/client.js) — `helix_axes.segments` forwarded in all three parsers.

## Deferred / known limitations

- ~~**`resize_strand_ends` still has the legacy `length_bp` divisor bug.**~~ **PORTED 2026-05-09.** The unified physical-RISE rebuild from `shift_domains` was ported into `resize_strand_ends`: removed the per-entry grow block, replaced the `(lo - old_lo) / helix.length_bp` trim formula with `(lo_bp - old_bp_start) * BDNA_RISE_PER_BP` offsets, and switched to post-shift scaffold coverage for inline-overhang reconciliation. Convention side-effect: native helices' `axis_end` now sits at `(bp_start + length_bp - 1) * RISE` (cadnano convention), matching `shift_domains` — `test_resize_strand_ends_grow_helix_forward` updated to assert the new convention.
- **Existing saved files have stale split staples** from the old `_reconcile_inline_overhangs` bug (e.g., `stap_19_92` in Ultimate Polymer Hinge has 2 domains where it should have 1). The fix prevents new splits but doesn't unsplit existing ones — would need a separate migration pass.
- **No frontend logic for shifting Crossover bps when both halves' domains are co-selected.** Currently a real Crossover at either end blocks the move outright. Could relax by shifting the crossover anchor too — open question if user requests it.
