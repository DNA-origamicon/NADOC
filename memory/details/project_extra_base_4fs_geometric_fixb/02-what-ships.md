# What ships — supporting detail

[Topic head](../../project_extra_base_4fs_geometric_fixb.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## What ships
- `prep_24hb_seeded.py --geometric` — builds the geometric model (no oxDNA override) + reorient +
  separate, then keeps the seeded prep's Fix B (`write_hmr_psf(heavy_residues=extra_base_segid_resids,
  heavy_factor=8)`) + mass-consistent soft + fast 4 fs `pre_declashed=True` ladder. Gate PASS
  (0 coincident, min heavy 0.30 A). Job `83a8ed8ded0e` = the validated 1xT package.
- Supporting (uncommitted): `_min_conf(no_enm=)`, `rebuild_enm_from_min` flag + runner reorder,
  ENM 2.8 A clash floor (`rebuild_declashed_references(min_ang=)`), `atomistic.xb_orient_override`
  + `_oxdna_rigid_frame` a1/a3 path (works but NOT needed — orientation wasn't the problem),
  `prep_24hb.py --pre-declashed`.

## Local probe recipe (free, ~35 min, no RunPod)
Truncated ladder off the fast confs: minimize(no-ENM) → `rebuild_declashed_references` → soft 25 ps →
4 fs k0.5/k0.1/k0.01 → unrestrained MGHH 6k steps. Survival of MGHH (TEMP stays 298 K, TOTAL flat) =
4 fs-production-stable. ⚠ blow-up grep must NOT include bare `inf`/`nan` (matches "Info:").
⚠ GPUresident on the 3080 Ti throws "Low global CUDA exclusion count" (host-specific); the runner's
`gpu_resident_probe` auto-downgrades — a manual probe hits it but it is not a physics failure.
