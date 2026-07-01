---
name: MD panel — implementation status and algorithm details
description: What works, what the PBC pipeline does, known limits, and how to extend the trajectory for late frames
type: project
originSessionId: 184cf93b-87e6-47df-98ad-3d8aa2a3bad9
---
## What is built and working

- **`backend/core/md_metrics.py`** — `scan_run_dir`, `parse_log_metrics`, `count_frames`
- **`POST /api/md/load`** in `crud.py` — validates topology/XTC, returns frame count + metrics
- **`/ws/md-run`** WebSocket in `ws.py` — `load`, `seek`, `get_latest` actions
- **`frontend/src/ui/md_panel.js`** — full panel: load, scrubber, play/pause/loop/live, speed, stride, repr, opacity, displacement amp slider
- **`frontend/src/scene/md_overlay.js`** — InstancedMesh beads-only overlay
- **`frontend/index.html`** — `#md-panel` section wired up
- **Frame application** (`applyFemPositions` in `helix_renderer.js`) — NADOC full mode

## PBC correction pipeline (in `_seek_sync`)

Each frame goes through four steps:

**Step 1 — Sequential nearest-image** (`_unwrap_min_image`): walks p_order, applies nearest-image between consecutive atoms. Detects strand boundaries by > 1.0 nm raw distance — does NOT correct those. Fixes all within-strand PBC splits.

**Step 2 — Hybrid PBC correction**:
- Compute `_c_box = np.median(p_box[rigid_mask])` — **median** of rigid atoms (dsDNA, bp≥0), NOT mean. Median is robust when sequential unwrap mislays a minority of atoms at late frames (a biased mean centroid caused 22 Å RMSD spikes at frame 700 until this was fixed).
- `_T_dyn = eq_centroid - _c_box` — dynamic centroid offset (not load-time T, which goes stale after tens of nm of translational drift)
- Rigid atoms (bp≥0): per-atom nearest-image to design equilibrium position in box frame
- ssDNA atoms (bp<0): keep sequential-unwrap position + T_dyn (don't snap to design eq — their large thermal fluctuations cause wrong-image snapping)

**Step 3 — Kabsch rotation**: SVD-based rigid-body alignment to design equilibrium using only rigid atoms. Stores `R_prev` and `prev_frame_idx` in `_ctx`. For sequential playback (|N-N_prev| ≤ 3), detects rotation jumps > 60° and falls back to inlier-only Kabsch.

**Step 4 — Base normals**: rotates P→C1' intra-residue vectors by R_align for slab orientation.

## Performance on 10hb nominal run

- `view_whole.xtc` (0–54.6 ns, 547 frames): RMSD_rigid = 7–9 Å throughout ✓
- `prod_best.part0003.xtc` (3.4–78.2 ns, 749 frames):
  - Frames 0–639 (0–64 ns): RMSD_rigid = 7–13 Å ✓
  - Frames 640–748 (64–78 ns): RMSD_rigid = 10–16 Å (higher due to ~90° rotational diffusion)
  - max_delta capped at ~83 Å (down from 110 Å before any fixes)

## PBC quality check at load time

`_load_sync` runs two checks and populates `load_warnings`:
1. If `view_whole.xtc` exists in the run dir but isn't the loaded XTC → warn
2. Counts atoms relocated > 3 Å by sequential unwrap at the mid-trajectory frame:
   - `view_whole.xtc`: 0 relocated (trjconv-preprocessed)
   - `prod_best.part0003.xtc`: 0–307 relocated depending on frame
   - > 5 relocated → warning with `gmx trjconv -pbc whole` command

Warnings propagate to frontend via `"warnings"` field in the `"ready"` WebSocket message, displayed as yellow log lines in the MD panel.

## How to extend view_whole.xtc for late frames (> 54.6 ns)

```bash
# Concatenate and re-process the full production trajectory
gmx trjcat -f prod_best.part0002.xtc prod_best.part0003.xtc -o prod_cat.xtc
gmx trjconv -f prod_cat.xtc -s em.tpr -pbc whole -o view_whole.xtc
```

## Live mode

`get_latest` rebuilds `mda.Universe` from disk each poll (paths stored in `_ctx["topology_path"]` and `_ctx["xtc_path"]`). Fix was implemented but never validated with an actively-writing XTC.

## Variable naming trap in ws.py `_seek_sync`

`_load_sync` stores eq positions in the result dict as `"eq_positions"`.  
`_seek_sync` reads it as `eq_pos = _ctx.get("eq_positions")`.  
Inside `_seek_sync`, always use `eq_pos` — NOT `eq_positions` (which doesn't exist in that scope and raises NameError). This was the bug causing WebSocket errors after the inlier Kabsch was added.
