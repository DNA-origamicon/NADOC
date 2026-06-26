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

## HC Physical Geometry (from cadnano2 source)
```python
R = 1.125   # nm
x = col * R * √3           # COL_PITCH ≈ 1.9486 nm
y = row * 3R + (R if (row%2)^(col%2) else 0)   # row step = 3R = 3.375 nm

# Neighbor rules:
# EVEN parity (row%2 == col%2): neighbors at (r, c+1), (r-1, c), (r, c-1)
# ODD parity: neighbors at (r, c-1), (r+1, c), (r, c+1)
```

## Test Coverage
`tests/test_cadnano.py` — 23 tests covering HC and SQ import/export round-trips
