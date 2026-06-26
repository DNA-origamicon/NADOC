---
name: SQ importer geometry fix — cadnano and scadnano
description: Three changes required for correct SQ crossover geometry; staple 0/80 failures achieved 2026-04-20
type: project
originSessionId: b8a5dca6-8e5d-4d81-b1a6-8bc73570a376
---
Both `cadnano.py` and `scadnano.py` required the same three fixes to make SQ staple crossover arc distances ≤ 1.2 nm.

**Why:** The crossover offset table's pN direction (`delta=(-1,0)`) expects lower grid row = north. The original code placed north at higher y (or used a normalized nr convention that mis-mapped pN/pS to bp=23,24 instead of bp=7,8), so phase 337° aligned the wrong bp positions.

**The three fixes:**

1. `_SQ_PHASE_FORWARD = math.radians(337.0)` — was 222° in cadnano.py; scadnano already correct.
2. **y negated**: For SQ axis, `y = -nr * SQUARE_ROW_PITCH` (cadnano) / `return x_pre, -y_pre` (scadnano). North = lower cadnano/scadnano row = lower y in NADOC.
3. **Raw grid_pos**: `grid_pos=(row, col)` using the original file's row/col (not normalized nr/nc). This makes the pN lookup `(row-1, col)` find the correct physical neighbor at bp=7,8.

**Parity note:** For the 2x4hb test, `(row + col) % 2 == num % 2` holds for all helices, so raw coordinates preserve the FORWARD/REVERSE parity convention.

**Result (2026-04-20):** `2x4hb_sq_test.json` staple: 0/80 failures, max=1.02 nm. Scaffold: 160/240 failures — separate open issue, not fixed here.

**How to apply:** If SQ crossover arcs look wrong, check: (1) phase=337°, (2) y is negated, (3) grid_pos is raw file coordinates. All three must hold together.
