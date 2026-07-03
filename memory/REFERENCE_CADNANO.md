---
name: REFERENCE_CADNANO
description: caDNAno v2 import/export — coordinate transforms, helix ID format, stap-only fix, local clone location
type: project
---

## Local Clone
`/home/joshua/cadnano2/` — authoritative reference for HC/SQ geometry
- `cadnano2/model/parts/honeycombpart.py` — HC formula, `getVirtualHelixNeighbors`
- `cadnano2/model/parts/squarepart.py` — SQ formula, neighbor rules
- `cadnano2/model/io/decoder.py` — JSON import logic
- `cadnano2/model/io/encoder.py` — JSON export logic

## NADOC Import/Export Module
`backend/core/cadnano.py` — `import_cadnano(data: dict) → (Design, list[str])`, `export_cadnano(design) → dict`

## Coordinate Transforms

### Honeycomb
```python
# caDNAno → NADOC
x_nadoc = -x_cadnano   # HC X-axis negated
y_cadnano = row * 3R + (R if (row%2)^(col%2) else 0)   # where R = 1.125 nm
# HC row step = 3.375 nm (3R) in caDNAno — NOT NADOC's ROW_PITCH = 2.25 nm
y_nadoc = -(row * 2.25)   # NADOC uses 2.25 nm row pitch
```

### Square
```python
x_nadoc = +(nc * 2.25)   # nc = column index
y_nadoc = -(nr * 2.25)   # nr = row index
```

## Helix ID Format
```
h_XY_{nr}_{nc}
```
- `XY` = lattice type tag (e.g., `HC` or `SQ`)
- `nr` = row index (can be negative)
- `nc` = column index (can be negative)
- Supports negative row/col: `/^h_\w+_(-?\d+)_(-?\d+)$/`

## Direction Convention
```python
helix_num % 2 == 0 → FORWARD
helix_num % 2 == 1 → REVERSE
```
(where `helix_num` = caDNAno vstrand number)

## Known Import Notes
- Stap-only vstrands (no scaffold) now imported correctly (bug fixed 2026-03-24)
- Empty vstrands are skipped
- `bp_start` set to first active bp in caDNAno vstrand
- `length_bp` = full array length (includes unused positions before/after active range)
- Strand start/end bp = global caDNAno indices
- Loop/skip, strand colors, and strand IDs are preserved on round-trip

## Export: bp offset + canonical width (fixed 2026-07-02)
NADOC domains carry GLOBAL bp indices that can be **negative** (overhang extruded
before bp 0) or **exceed `length_bp`** (extra bases, resize-through-boundary,
negative-bp editor segments). caDNAno arrays are 0-based fixed-width, so
`export_cadnano`:
1. scans every `domain_bp_range` + every `loop_skips[*].bp_index` for the true
   `min_bp/max_bp` envelope;
2. shifts **every** bp by one uniform `offset = max(0, -min_bp)` (uniform across
   all helices → crossover / loop-skip columns stay aligned);
3. sizes `array_len = ceil((max_bp+offset+1)/period)*period`, period = 21 HC / 32 SQ.

The offset is applied at every write site: `_fill_strand` pointers + array index,
loop/skip arrays, and `stap_colors` 5′ bp key. Row/col/num (`_assign_grid_coords`)
is untouched.

**Bug this fixed:** old code sized arrays to `max(length_bp)` and indexed directly
→ `IndexError` (bp ≥ len, crashes export → 400) or silent tail-wrap corruption
(bp < 0, Python negative index). Regressed silently — export had ~zero test coverage.

**Round-trip is gauge-relabelled, not identity.** Absolute bp origin is a free
gauge (import re-derives phase/bp_start; SQ grid recovery has a pre-existing ±1
row/col instability; helix FORWARD/REVERSE can flip; colorless staples get a
default `#F7931E` injected). So "export = import of export" is asserted as
**topology conservation**, not raw equality: helix count + per-strand TOTAL base
count by type + loop/skip delta multiset. Domain SEGMENTATION legitimately differs
(import coalesces contiguous same-helix runs).

## Test Coverage
- `tests/test_cadnano.py` — 23 tests, HC/SQ import.
- `tests/test_cadnano_roundtrip.py` — 50 tests: Tier 1 well-formedness (every
  non-ERROR `Examples/*.nadoc`), Tier 2 conservation round-trip (nadoc + native
  JSON fixtures), Tier 3 regression (`2hb_xover_val`, `NS_trans_fix`, `U6hb` +
  explicit negative-bp no-corruption).

## HC Physical Geometry (from cadnano2 source)
```python
R = 1.125   # nm
x = col * R * √3           # COL_PITCH ≈ 1.9486 nm
y = row * 3R + (R if (row%2)^(col%2) else 0)   # row step = 3R = 3.375 nm

# Neighbor rules:
# EVEN parity (row%2 == col%2): neighbors at (r, c+1), (r-1, c), (r, c-1)
# ODD parity: neighbors at (r, c-1), (r+1, c), (r, c+1)
```

