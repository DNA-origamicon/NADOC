---
name: MDAnalysis trajectory reload — _reopen() does not discover new frames
description: u.trajectory._reopen() does not pick up frames written after Universe was opened; must rebuild Universe from disk
type: feedback
originSessionId: 184cf93b-87e6-47df-98ad-3d8aa2a3bad9
---
`u.trajectory._reopen()` resets the file pointer to the beginning but does NOT update the cached frame count. After calling it, `len(u.trajectory)` still returns the count from when the Universe was first opened.

**Why:** MDAnalysis XTC trajectories index all frame offsets at open time. `_reopen()` is an internal seek-to-start, not a re-scan.

**How to apply:** For any live-polling use case where the XTC file may grow (ongoing GROMACS simulation), always rebuild the Universe on each poll:

```python
import MDAnalysis as mda
new_u = mda.Universe(topology_path, xtc_path)
ctx["universe"] = new_u
ctx["n_frames"] = len(new_u.trajectory)
```

Store `topology_path` and `xtc_path` in `_ctx` at load time so they're available in the poll handler. The atom order, `p_order`, `centroid_T`, and `c1p_idx` arrays are all stable across Universe rebuilds (same topology).

**UPDATE 2026-06-11 — prefer `Universe.load_new`, NOT a full rebuild.** A full
`mda.Universe(topology, traj)` per poll re-parses the topology — measured ~1.7 s for a
0.5 M-atom PSF, worse for multi-GB trajectories — which on `/ws/md-run`'s 5 s live poll
backed up the queue and Display MD never rendered. The fix:
```python
u = ctx["universe"]          # keep the existing Universe (topology already parsed)
u.load_new(ctx["xtc_path"])  # re-reads the traj header → DISCOVERS appended frames
ctx["n_frames"] = len(u.trajectory)
```
Verified empirically (XTC 3→6 and DCD 5→12) that `load_new` *does* re-scan offsets and
see new frames — only `_reopen()` is broken, not `load_new`. ~0.003 s vs 0.88–1.7 s for
a rebuild. Also: MDAnalysis floors `n_frames` by file size, so a byte-truncated partial
trailing frame (live mid-write) is simply dropped; still wrap the latest-frame seek in a
try/fallback-one-frame for torn reads. See repo `memory/project_md_sidebar_audit.md` (R1)
and `backend/api/ws.py::_refresh_latest_sync`.
