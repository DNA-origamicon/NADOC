# Purpose — historical evidence

[Topic head](../../log_atomistic_o3prime.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Purpose
Track every template change and every measurement so we don't redo work or regress.

---

## Entry 1 — Baseline measurement (inherited from prior session)

**Templates in use:** Radial-frame extraction from 1ZEW (extract_all_templates.py).
P = (0.0335, 0.0253, 0.2684), O3' = (0.0077, 0.4931, -0.0832).

**Measurements (NADOC PDB row=0 col=0 FWD helix, bp=10 intra-residue):**
- C3'–O3'–P = **91.19°** (target 119.35°) ← THE BUG
- O3'–P distance = 1.653 Å (target 1.607 Å)
- ε torsion (C4'–C3'–O3'–P) ≈ 95°
- WC H-bonds: GC(C FWD,G REV) = 0.299/0.289 nm ✓, GC(G FWD) 0.332 nm ~, AT pairs 0.348–0.362 nm ~

**Root cause analysis:**
The extraction uses 1ZEW P positions (36°/bp, 0.332 nm rise) as frame origins.
NADOC production uses 34.3°/bp and 0.334 nm rise.
The 1.7°/bp twist difference + 0.002 nm rise difference causes O3'→P to land at the wrong angle.
Also: the C1'→z=0 shift does NOT affect the O3'→P vector (both atoms shift identically).
The vector shift is purely from the frame-stepping mismatch.

**Fix approach decided:** Write `scripts/reextract_nadoc_templates.py` that:
1. Builds synthetic NADOC helix (34.3°/bp, 0.334 nm rise) matched to 1ZEW axis + phase
2. Calls `_atom_frame()` for each residue to get the NADOC-native frame
3. Expresses 1ZEW atoms in those frames
4. Averages → templates guaranteed correct for NADOC's frame stepping

**Risk:** WC H-bond distances may change. The canonical P-P fix for REV will be preserved via `_atom_frame`'s built-in +58.2° correction.

---

## Entry 2 — NADOC-frame extraction run (this session)

**Script:** `scripts/reextract_nadoc_templates.py`
**Status:** COMPLETE — templates applied to `atomistic.py`, 609 tests pass.

**Key diagnostic finding:**
- `predict_o3_angle` (using NADOC-frame extracted SUGAR) still gave 91.15° — same as before.
- Root cause: In the single-template model, `P(N+1) = origin_{N+1} + R_{N+1} @ P_tmpl`. The frame-to-frame transform places this P only **2.05 Å** from C3'(N). The target C3'–P distance for 119.35° at canonical bond lengths (1.52+1.61 Å) is **2.70 Å**. Moving O3' alone cannot bridge this gap (max achievable angle = 82°).

**Fix applied: minimal P_tmpl shift along C3'→P direction:**
- Computed the frame-to-frame transform T(v) = ΔO + M @ v.
- Found unit direction dir = (T(P_tmpl) − C3'_tmpl).normalized()
- Shifted P_tmpl by t = 2.70 − 2.05 = 0.65 Å in template space: ΔP = M^T @ (t * dir)
- ΔP = (−0.062, +0.017, −0.012) nm (consistent across all 5 pairs; std = 0.000)
- Re-derived O3' on the C3'–P intersection circle, biased to crystal orientation.

**New templates:**
- P:  (−0.1020,  0.1588,  0.2560) [was (0.0335, 0.0253, 0.2684)]
- O3': (−0.0605,  0.5756, −0.1253) [was (0.0077, 0.4931, −0.0832)]
- All other SUGAR atoms: updated to NADOC-frame extraction values
- All BASE templates (FWD + REV): updated to NADOC-frame extraction values

**Verified in production (build_atomistic_model):**
- C3'–O3'–P = **120.36°** (target 119.35°, error +1.01°) ✓
- O3'–P dist = 1.603 Å (target 1.607 Å) ✓
- All 609 tests pass ✓

**WC H-bonds (re-measured after this session's template updates):**
| Pair | H-bond | New (nm) | Prev (nm) | Target (nm) |
|------|--------|----------|-----------|-------------|
| GC (FWD C, REV G) | N4–O6 | 0.299 | 0.299 | 0.287 |
| GC (FWD C, REV G) | N3–N1 | 0.289 | 0.289 | 0.293 |
| GC (FWD G, REV C) | O6–N4 | 0.332 | 0.332 | 0.287 |
| GC (FWD G, REV C) | N1–N3 | 0.322 | 0.322 | 0.293 |
| AT (FWD T, REV A) | O4–N6 | 0.365 | 0.362 | 0.290 |
| AT (FWD T, REV A) | N3–N1 | 0.326 | 0.323 | 0.300 |
| AT (FWD A, REV T) | N6–O4 | 0.349 | 0.348 | 0.290 |
| AT (FWD A, REV T) | N1–N3 | 0.328 | 0.327 | 0.300 |

H-bonds essentially unchanged (±0.003 nm). Same issues as before: AT pairs ~0.07 nm too long. No regression from P/O3' correction.

---

## Entry 3 — OP1/OP2 tetrahedral fix + C1'–N bond fix (this session)

**Pre-change measurements:**
- P→OP1 = 1.129 Å (target 1.48 Å), P→OP2 = 1.850 Å — caused by ΔP shift in Entry 2 not applied to OP1/OP2
- O5'–P–OP1 = 142°, O5'–P–OP2 = 101° — very wrong angles
- C1'–N distances: FWD DA=0.31Å, FWD DG=0.88Å (too short); REV all: 1.79–3.31Å (too long)
  Root cause: SUGAR C1' from A:5 (bp_index=2, FWD), base templates from different residues at different bp_indices.
  Combining frame-2 C1' with frame-3/4/5 N9/N1 gives wrong inter-residue distances.

**Fix plan:**
1. OP1/OP2: Keep P, O5', O3'. Compute O3'_prev via inverse frame transform. Place OP1/OP2 at tetrahedral positions relative to P with P→O5' and P→O3'_prev as two known vertices. P→OP = 1.48 Å.
2. Base C1'–N: For each residue type, re-extract base atoms as C1'_sugar + (atom_world − C1'_world)_in_frame. This makes every atom an offset from the SAME residue's C1', guaranteeing correct C1'–N bond length.

---

## Entry 4 — OP1/OP2 fix + C1'–N glycosidic bond fix (this session)

**OP1/OP2 root cause and fix:**
- Root cause: Entry 2 shifted P by ΔP=(−0.062, +0.017, −0.012) nm but OP1/OP2 were not moved.
- Tetrahedral sum approach tried first but abandoned: O5'–P–O3'_prev = 70.5° baseline angle (caused by the P shift) means only 70.6° spread between two bridging ligands; the sum constraint forces OP1/OP2 to 131.8° from each — geometrically forced, wrong.
- Fix applied: `OP1_new = OP1_crystal + ΔP`, `OP2_new = OP2_crystal + ΔP`. Restores crystal P→OP bond vector, just translated to the new P position.
- Results: P→OP1=1.474 Å ✓, P→OP2=1.494 Å ✓, OP1–P–OP2=119.7° ✓

**C1'–N glycosidic bond fix:**
- Root cause: SUGAR C1' extracted from A:5 (bp_index=2, FWD). FWD base templates averaged from A:3–A:8, REV from B:13–B:18. Each bp_index has a different 34.3° rotation in the synthetic NADOC frame, so C1' in those extraction frames has different local (n,y) coords. Combining bp_index=2 C1' with bp_index=3/4/5/6 base atoms gives wrong C1'–N offsets.
- Fix: C1'-referenced extraction — `A_corrected(n,y) = C1'_sugar(n,y) + (A_local(n,y) − C1'_local(n,y))`. z unchanged (no rotation around z at the single-bp level). Applied to both FWD and REV.

**FWD C1'–N distances (production, verified):**
| Residue | C1'–N | C1'–N–C_a | C1'–N–C_b |
|---------|-------|-----------|-----------|
| DA | 1.456 Å | C1'–N9–C4=126.0° ✓ | C1'–N9–C8=128.0° ✓ |
| DT | 1.456 Å | C1'–N1–C2=117.0° ✓ | C1'–N1–C6=121.8° ✓ |
| DG | 1.453 Å | C1'–N9–C4=125.6° ✓ | C1'–N9–C8=128.0° ✓ |
| DC | 1.474 Å | C1'–N1–C2=118.1° ✓ | C1'–N1–C6=121.5° ✓ |

**REV C1'–N distances (production, verified):**
| Residue | C1'–N | C1'–N–C_a | C1'–N–C_b |
|---------|-------|-----------|-----------|
| DA | 1.466 Å | C1'–N9–C4=127.6° ✓ | C1'–N9–C8=126.8° ✓ |
| DT | 1.441 Å | C1'–N1–C2=117.7° ✓ | C1'–N1–C6=120.0° ✓ |
| DC | 1.474 Å | C1'–N1–C2=118.6° ✓ | C1'–N1–C6=121.2° ✓ |
| DG | 1.453 Å | C1'–N9–C4=126.7° ✓ | C1'–N9–C8=126.9° ✓ |

**WC H-bonds (re-measured after this session's changes):**
| Pair | H-bond | New (nm) | Prev (nm) | Target (nm) | Status |
|------|--------|----------|-----------|-------------|--------|
| GC (FWD G, REV C) | O6–N4 | 0.297 | 0.332 | 0.287 | ✓ improved |
| GC (FWD G, REV C) | N1–N3 | 0.289 | 0.322 | 0.293 | ✓ |
| GC (FWD G, REV C) | N2–O2 | 0.270 | n/a | 0.287 | ✓ |
| GC (FWD C, REV G) | N4–O6 | 0.296 | 0.299 | 0.287 | ✓ |
| GC (FWD C, REV G) | N3–N1 | 0.289 | 0.289 | 0.293 | ✓ |
| GC (FWD C, REV G) | O2–N2 | 0.281 | n/a | 0.287 | ✓ |
| AT (FWD A, REV T) | N6–O4 | 0.313 | 0.348 | 0.290 | ✓ improved |
| AT (FWD A, REV T) | N1–N3 | 0.283 | 0.327 | 0.300 | ✓ improved |
| AT (FWD T, REV A) | O4–N6 | 0.265 | 0.362 | 0.290 | ~ close |
| AT (FWD T, REV A) | N3–N1 | 0.216 | 0.323 | 0.300 | ✗ CLASH (< 0.24 nm) |

**WC H-bond regression analysis:**
- GC pairs improved substantially (was 0.332/0.322 for FWD=G/REV=C, now 0.297/0.289 ✓).
- AT pairs: FWD=A/REV=T improved (0.313/0.283 vs 0.348/0.327). FWD=T/REV=A got worse: N3–N1=0.216 nm (VdW clash).
- Root cause of AT regression: REV DA shift by C1'-fix was (+0.046, +0.086) nm in (n,y). This moved N1 of REV DA too close to N3 of FWD DT. The Entry 2 REV DA had its atoms 0.09 nm too far from the FWD strand (H-bonds too long); C1'-fix over-corrected in the FWD=T orientation.
- 609 tests pass; clash requires GROMACS minimization to resolve. Deferred.

**C3'–O3'–P unchanged:** 120.36° at all bp positions ✓

---
