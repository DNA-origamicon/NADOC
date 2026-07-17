---
name: ssDNA linker relax + FJC lookup + interactive config modal
description: Slab+SAW FJC pre-baked lookup, OverhangConnection bridge fields, interactive R_ee×Rg picker modal, and the bin-based relax pipeline for ss linkers (shipped 2026-05-11)
type: project
originSessionId: 28ceab75-0964-4b1d-9639-563decc73ea2
---
# ssDNA linker relax (shipped 2026-05-11)

Closes the "ss linker: replace tube arc with rendered bridge nucleotides" item that was deferred in [project_overhang_connections](project_overhang_connections.md). The ss bridge is now a chain of N FJC bead positions drawn between the two complement anchors; the user picks an R_ee range from a pre-baked histogram and the chain shape is loaded from the matching bin.

## Pipeline overview

1. **Build-time** — `scripts/generate_ssdna_fjc_lookup.py` runs an adaptive streaming FJC sampler per length (n_bp=2..35 currently — `MAX_NEW_ALGORITHM_BP`). Drops samples that violate the slab (0 ≤ x_i ≤ D, D=b√N_kuhn) or SAW (≥0.6 nm pairwise) constraints. Bins R_ee into 40 percentile-based edges (P0.5..P99.5), drops out-of-range samples (not clip — clipping piled the tails into bin 0/39 as a fake spike), and keeps ONE representative shape per non-empty bin plus per-bin Rg sub-histograms. Targets ≥3000 binned samples per length (`TARGET_N_BOTH_OK`). Writes `backend/data/ssdna_fjc_lookup.json` (~3-4 MB, committed).

2. **Runtime backend** — `backend/core/ssdna_fjc.py` loads the JSON, exposes `bin_positions`, `bin_r_ee`, `bin_rg`, `resolve_bin_index`, `default_bin_index`, `transform_to_chord`. The transform is anisotropic: stretch+rotate the canonical chain (anchored 5'→3' along +x with R_ee on +x axis) so its endpoints land on the actual anchor positions in design frame.

3. **Relax** — `relax_ss_linker(design, conn, joint_ids, bin_index, r_ee_min_nm, r_ee_max_nm)` in `backend/core/linker_relax.py` stores `bridge_relaxed=True`, `bridge_bin_index`, `bridge_r_ee_min_nm`, `bridge_r_ee_max_nm` on the `OverhangConnection`. Joint rotation step (for 1-DOF clusters) still uses the chord-magnitude loss with the bin's mean R_ee as the target.

4. **Render** — `frontend/src/scene/overhang_link_arcs.js` checks `conn.bridge_relaxed`: pre-relax draws the Bezier fallback arc; post-relax fetches the bin's positions via the loader mirror (`frontend/src/scene/ssdna_fjc.js`) and `transformToChord`s them between the two complement anchors.

## OverhangConnection schema additions

In [backend/core/models.py](backend/core/models.py):

```python
bridge_relaxed: bool = False
bridge_bin_index: int = 0
bridge_r_ee_min_nm: Optional[float] = None
bridge_r_ee_max_nm: Optional[float] = None
```

Legacy `.nadoc` designs (pre-2026-05-11) load with defaults and render as Bezier arcs until the user runs Relax.

## Interactive config modal

`frontend/src/ui/linker_config_modal.js` — replaces the prior 3-button "Rg ± σ" popup. Layout (CSS grid 1fr 1fr):

- **Left: R_ee histogram** (520×200 canvas). Orange thumb (`#f0883e`) = `r_ee_min`, cyan thumb (`#39d0d8`) = `r_ee_max`. Drag to pick a range. Defaults: 10% inset from the occupied-bin extremes.
- **Right: Rg histogram** (520×200). Updates on every R_ee thumb move via `filteredRgHistogram(n_bp, r_ee_min, r_ee_max)` which sums the per-R_ee-bin `rg_subcounts` rows in the selected range. Read-only — no thumbs.
- **Bottom: 3D viewer** (700×320). Orbitable Three.js scene with the representative chain for the centre bin of the current R_ee range. `_create3DViewer(container, w, h)` returns `{setChain(positions), dispose()}` using `OrbitControls` + render-on-demand (only draws when the camera moves or chain swaps).
- **Footer**: Apply + Cancel. Apply path: `patchOverhangConnection(conn.id, {length_value, length_unit})` then `relaxLinker(conn.id, null, {binIndex, rEeMinNm, rEeMaxNm})`.

Help → "FJC sim" opens the same modal in `readOnly: true` mode (no Apply, lets the user explore the table).

### Critical gotchas

1. **State declaration before footer code** — `const state = {...}` must be declared BEFORE the footer's `Apply` handler references `state.statusEl`, otherwise temporal-dead-zone `ReferenceError: Cannot access 'state' before initialization`.
2. **Filtered Rg histogram uses sub-histograms, not live recompute** — the backend pre-bakes `rg_subcounts: [n_bins × n_bins]` so the frontend cross-filter is a sum of rows. Don't try to recompute by re-binning — the JSON only ships ONE rep shape per R_ee bin.
3. **Histograms must have ≥3000 binned samples per length** — the user is explicit on this. If you change `BATCH_SIZE` or `MAX_TOTAL_SAMPLES` make sure the longest lengths (n_bp=30..35) still hit the target. Acceptance rate drops sharply with N_kuhn — n_bp=35 needs ~960K total draws.

## Generator design

`_build_bin_entries(n_bp, n_kuhn, rng)`:

**Phase A — ranging.** Draw batches until ≥1000 slab+SAW samples accumulate. Compute R_ee + Rg percentile edges (P0.5..P99.5). Phase A's positions are NOT kept (only R_ee + Rg for the percentile fit).

**Phase B — filling.** Stream batches; per batch, `_process_batch` updates per-bin counts, rep shapes, and Rg sub-histograms. Loop until `state["binned_n"] >= TARGET_N_BOTH_OK` OR `n_total >= MAX_TOTAL_SAMPLES`.

State fields:
- `pool_n_total` — all slab+SAW samples drawn (in-range + outliers)
- `pool_n_outliers` — slab+SAW samples whose R_ee fell outside `r_ee_edges` (dropped, not clipped)
- `binned_n` — slab+SAW samples actually placed in a histogram bin (the user-visible count)

Mean / std are computed against `binned_n` (only in-range samples contribute to the sums) so the printed stats match the histogram the user sees.

Output JSON per length:
```
n_bp, n_kuhn, contour_nm, wall_separation_nm
r_ee_mean_nm, r_ee_std_nm, rg_mean_nm, rg_std_nm
n_total, n_slab_ok, n_saw_ok, n_both_ok (=pool_n_total), n_binned, n_outliers
r_ee_bin_edges_nm: [n_bins+1 floats]
rg_bin_edges_nm:   [n_bins+1 floats]
bins: [{count, rep_r_ee_nm, rep_rg_nm, rep_positions, rg_subcounts}] × HIST_BINS
```

## API

- `GET  /api/ssdna-fjc-lookup` — returns the loaded JSON (cacheable; modal reads this).
- `POST /api/design/overhang-connections/{id}/relax` — now accepts `bin_index`, `r_ee_min_nm`, `r_ee_max_nm` in `RelaxLinkerRequest` for ss linkers. ds linkers ignore these fields (chord-target stays as `(bp-1) × BDNA_RISE_PER_BP`).

## Files

- [scripts/generate_ssdna_fjc_lookup.py](scripts/generate_ssdna_fjc_lookup.py) — generator
- [backend/data/ssdna_fjc_lookup.json](backend/data/ssdna_fjc_lookup.json) — output (committed)
- [backend/core/ssdna_fjc.py](backend/core/ssdna_fjc.py) — backend loader + transforms
- [backend/core/linker_relax.py](backend/core/linker_relax.py) — `relax_ss_linker`, `fjc_positions_in_design_frame`, `_anchor_pos_and_normal` (handles `__s` ss linker strand)
- [backend/core/models.py](backend/core/models.py) — `OverhangConnection.bridge_*` fields
- [backend/api/crud.py](backend/api/crud.py) — `GET /ssdna-fjc-lookup`, `RelaxLinkerRequest` schema
- [frontend/src/scene/ssdna_fjc.js](frontend/src/scene/ssdna_fjc.js) — frontend mirror of loader + `filteredRgHistogram` + `transformToChord` + `fjcChainBetween`
- [frontend/src/ui/linker_config_modal.js](frontend/src/ui/linker_config_modal.js) — modal
- [frontend/src/scene/overhang_link_arcs.js](frontend/src/scene/overhang_link_arcs.js) — Bezier pre-relax, FJC bead chain post-relax
- [frontend/src/scene/selection_manager.js](frontend/src/scene/selection_manager.js) — `_showSsLinkerConfigPicker` lazy-imports the modal
- [frontend/src/main.js](frontend/src/main.js) — Help → "FJC sim" lazy-import
- [tests/test_ssdna_fjc.py](tests/test_ssdna_fjc.py) — 17 schema-aware tests; the `relax_ss_linker` ones call the **core fn directly** and assert only bin *bookkeeping* (`fjc_bin_index`, `bridge_relaxed`, `bridge_r_ee_*`)
- [tests/test_headless_build.py](tests/test_headless_build.py) — **the ss relax's HEADLESS + geometric pins (AF-39, 2026-07-16)**: `_two_overhang_leaves_ss_linker` + 4 tests driving `hb.relax_overhang_connection(bin_index=…)`. Pins **bin → chord**: relaxing at bins 23 vs 39 (n_bp=20) lands the chord on each bin's own R_ee ±0.05 nm, 1.34 nm apart — the bin is not bookkeeping, it *chooses the geometry*. Also proves by contradiction that the ss target is NOT the ds duplex span (same relax is green vs R_ee, RED vs ds).
  - **Fixture gotcha:** `generate_linker_topology` is load-bearing — without it geometry emits no `__lnk__` bridge and `_anchor_pos_and_normal` silently falls back to the overhang's own backbone nuc ([linker_relax.py:712](backend/core/linker_relax.py#L712)). Real complement anchor is `[2.0, 0.866, 0]` → degenerate joint origin `[2.0,0,0]`.
  - **Pick reachable bins:** the moving anchor rides a radius-2.0 circle → chord confined to [2.773, 6.759] nm. n_bp=20's *default* bin 27 (R_ee 3.179) sits 0.007 nm from the start chord — under the oracle's eps → near-vacuous. Use bins 23/39.

## Tuning knobs

In `scripts/generate_ssdna_fjc_lookup.py`:
- `BATCH_SIZE = 20_000` — per-batch FJC samples
- `TARGET_N_BOTH_OK = 3_000` — minimum binned samples per length
- `MAX_TOTAL_SAMPLES = 2_000_000` — safety cap per length
- `HIST_BINS = 40` — bin count for both axes
- `MAX_NEW_ALGORITHM_BP = 35` — lengths beyond this get a placeholder entry

To extend coverage to longer chains: raise `MAX_NEW_ALGORITHM_BP`, expect longer generation time (~minutes per length past n_bp=30).
