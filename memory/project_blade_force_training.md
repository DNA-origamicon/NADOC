---
name: blade-force-training
description: "BLADE force-training off the relaxed 6hbx100_90deg NAMD: send the RESTART bundle (not the trajectory) via runpodctl, the production MUST capture forces (capture_vel_force) on >=1 restart-seeded segment, return only the DNA-force .npz to Archive + verify the carved PSF is 197,107 atoms / 1264 nt first."
metadata:
  node_type: memory
  type: project
---

# BLADE force-training off the relaxed 6hbx100_90deg — three things not to lose

The **other computer** trains **BLADE** on forces from a RunPod production seeded from the
**relaxed 6hbx100_90deg** NAMD. Three hard requirements — a positions-only run **wastes the pod**:
it yields a validation trajectory but **nothing to train BLADE on**.

## 1. Transfer the RESTART BUNDLE, not the trajectory
Send the paired restart set (`*.restart.coor` + `.restart.vel` + `.restart.xsc`, **~50–100 MB**) with
**`runpodctl send` → `runpodctl receive`, machine → pod directly.** NOT SFTP off the network volume
(~0.9 MB/s — impractical for anything but this compact bundle; it's why we process on-pod). `runpodctl`
is a direct P2P code handoff. Do **not** send the trajectory or the full solvated box.
(`runpodctl` is not yet used anywhere in the repo — grep is empty; this is a manual step for now.)

## 2. The production MUST capture forces (`capture_vel_force`)
Run the **propagator-reference protocol with `capture_vel_force`** for **at least one segment seeded
from a relaxed restart**. **Forces**, not just positions, are the BLADE training signal. A positions-only
production gives a validation trajectory and nothing to train on.
⚠️ `capture_vel_force` is **NOT yet a NADOC code flag** (grep across `backend/`/`experiments/` is empty) —
it needs wiring: NAMD emits a force DCD via a config directive, and the reducer (§3) must pull forces,
not just coordinates.

## 3. Return only the DNA-force .npz; verify the PSF FIRST
- Return **only the compact DNA-force `.npz`** to the **Archive drive** (`/media/jojo/Archive`, never
  the ~92 %-full system disk). Not the full trajectory. (Same reduce-on-pod pattern as the crossover
  extraction: compute the small product on the pod, ship only the `.npz`.)
- **Verify the relaxed PSF is 197,107 atoms / 1264 nt against the current design BEFORE committing the
  long run.**

## Verified structure facts (this machine, 2026-07-19)
- **Design:** `workspace/6hbx100_90deg.nadoc` — **1264 nt** (DNA ≈ **42,125 atoms** in the PSF, ≈33 atoms/nt ✓).
- **Relaxed FULL box:** job `6d3b1a440ace` →
  `/media/jojo/Archive/NADOC_archive/6d3b1a440ace/package/6hbx100_90deg_namd_solvated/`
  — PSF **770,219 atoms** (DNA 42,125 + **728,094 bulk water**). Restart bundle: `output/*.restart.{coor,vel,xsc}`.
- ⚠️ **197,107 ≠ the full box.** 197,107 atoms / 1264 nt is a **water-CARVED** system (DNA 42 k +
  ~155 k shell ≈ 51.6 k waters). It does **not** exist on this machine's disk yet. So point 3's check is
  really: **carve the DNA + hydration shell** from the 770 k box (see `water_shell_carve`), confirm it
  lands at exactly 197,107 / 1264 nt, THEN run. Sending the full 770 k box instead would blow both the
  runpodctl transfer (§1) and the pod's compute.
