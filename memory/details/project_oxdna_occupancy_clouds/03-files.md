# Files — supporting detail

[Topic head](../../project_oxdna_occupancy_clouds.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Files

| File | Role |
|---|---|
| `backend/core/occupancy_core.py` | the engine-agnostic core: scoping, **the fit plan**, PCA, k-means, medoids, the verdict |
| `backend/core/oxdna_occupancy.py` | oxDNA feature assembly (nt/bp basis, FENE gate) over that core |
| `backend/core/md_trajectory.py` | `md_occupancy` — NAMD feature assembly over the same core |
| `backend/api/routes_oxdna.py` | `GET .../occupancy`, `POST .../occupancy` (selection + `fit`), `_OCC_PROGRESS` |
| `backend/api/routes_md.py` | the NAMD twin + `_MD_OCC_CACHE` (no shareable frame cache exists) |
| `frontend/src/scene/occupancy_overlay.js` | one copy per state (build, tint, opacity, LOD, per-state show/recolour, dispose) |
| `frontend/src/ui/occupancy_controls.js` | DOM, params, cache, scrollable state list, network |
| `frontend/src/ui/oxdna_display.js` | `_mode = 'occupancy'`, `displayOccupancy`, `onOccupancyClear` |
| `frontend/src/api/client.js` | `getOxdnaOccupancy` / `getOxdnaOccupancyProgress` |
| `tests/test_oxdna_occupancy.py` (26) · `occupancy_overlay.test.js` (46) · `occupancy_controls.test.js` (41) · `e2e/occupancy_clouds.spec.js` | |

## Reuse — nothing here was written twice

`_aligned_downsampled_frames` (frames, unwrap, Kabsch, `_ALIGNED_CACHE`) ·
**`twist_series_stats`** (`oxdna_health.py:387`) returns `{tau_int, n_eff, sem}` — feed it a
cluster's 0/1 membership series and `mean` IS the population, `sem` IS its honest error ·
`_fene_violation_fraction` + `_STRAIN_FRAME_REJECT_FRAC` (torn-frame gate) ·
`_strain_index(design, keys, "wc")` (bp pairing) · `_flatten_cg_frame` (wire format) ·
`buildHelixObjects` (ghost copies). **scipy only — scikit-learn is NOT installed.**
