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

## Current importer v3 — authorized November 22/23 repair

New imports must also run the [mandatory bond review](../docs/design_bond_review.md):
strictly more than 20% forced-ligation bonds or stretched backbone edges triggers
review, checking both the whole-design and interhelix-junction populations.
The application warns and marks the actual import feature; agent publication
requires a clean report or a documented exact-design review as well as replay.

New imports use version 3; recorded versions 1 and 2 remain unchanged for replay.
V3 uses the existing native lattice position, phase and twist functions together:
HC phases 107.15°/77.15°, exact 720/21° twist, positive-row axes. Source numbering
must agree with lattice parity. No locked legacy or native constants were changed.
`length_bp` is the occupied span, not padded caDNAno array width; axis endpoints
are `bp_start * rise` and `(bp_start + length_bp) * rise`. This prevents imported
helices being mistaken for deliberately posed helices by the normalization guard.

Standard external imports are recentered in XY by the recorded import command.
Native canonical straight HC exports additionally carry bounded, explicit
`nadoc_roundtrip` metadata: original lattice cells, bp origin/extents, one common
XY translation, route-owned sequences, and a source-topology digest. V3 restores
that frame and skips recentering. It contains no atoms, phases, reference models,
or arbitrary Design snapshot. Stale or malformed metadata is rejected; versions
1/2 cannot consume it. Plain external caDNAno readers retain standard vstrands
but do not preserve this extension's exact-coordinate/sequence guarantee.
Posed, bent, reference-atom and other ineligible designs retain normal lossy
caDNAno export semantics; do not claim an arbitrary .nadoc roundtrip is exact.

Regressions cover every standard HC neighbor/parity/register class, 21-bp
periodicity, long nonzero starts, legacy authoring digests, and strict absolute
atom/base/backbone/bond identity for positive/negative native origins. Evidence:
`.development-artifacts/gur-hc-import-v3-20261123/`.

## Historical coordinate transforms — versions 1 and 2 only

### Honeycomb
```python
# Legacy caDNAno importer, prior to XY recentering
x_nadoc = (col - min_col) * R * sqrt(3)
y_cadnano = row * 3R + (R if (row%2)^(col%2) else 0)   # where R = 1.125 nm
y_nadoc = max_y_cadnano - y_cadnano
# Native NADOC honeycomb instead uses positive y_cadnano, with the same 3R row step.
# Importer v2 preserves the source grid cells for crossover lookup.
```

The former negative-X/2.25nm-row formula in this reference was stale. These legacy
HC axes and phases differ from native geometry. A reflection alone is not
universally invalid; the complete axis/angular convention must agree.

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
- V3 `length_bp` = occupied span; v1/v2 retain full padded array length for replay
- Strand start/end bp = global caDNAno indices
- Loop/skip and strand colors are retained; import identities are newly allocated

## November22/23 — confirmed honeycomb importer geometry divergence

Gür6HB source topology is valid:342core junctions match the caDNAno honeycomb
tables at their original indices. Import stores the full padded array width as
`length_bp`, but trims axis endpoints to active sites. The >1nm Z-extent guard
in `deformation._normalize_helix_for_grid` misidentifies that mismatch as a posed
helix and retains all9imported frames. Its effective phases remain322.2°/252.2°
and rounded34.3°/bp, against reflected-Y axes. Native HC uses107.15°/77.15°,
720/21°/bp and positive-row axes. These values are different conventions;
do not change locked constants or silently migrate stored designs.

VoltronCoreArm is SQUARE, with consistent native XY and active-span helix
lengths: its core passes the normalization guard, using native303.75°/273.75°
and33.75°/bp. All1206ordinary crossover endpoint distances are below1.2nm.
It does not validate the failing honeycomb/trimmed-array branch.

History:10c576ef(March20) calibrated both legacy HC phase paths;
a6df304c(April11) changed native phases/grid conventions and introduced
normalization without updating importer constants;998b63f7(April17) preserved
storedXY;3a7fa705(June12) added the pose guard;47c834db(August6) made native
HC twist commensurate while the importer retained34.3°. Source and measured
evidence: `.development-artifacts/gur-import-root-cause-20261123/`.
That diagnosis preceded the explicitly authorized v3 repair described above.

## Export: bp offset + canonical width (fixed 2026-07-02)
NADOC domains carry GLOBAL bp indices that can be **negative** (overhang extruded
before bp 0) or **exceed `length_bp`** (extra bases, resize-through-boundary,
negative-bp editor segments). caDNAno arrays are 0-based fixed-width, so
`export_cadnano`:
1. scans every `domain_bp_range` + every `loop_skips[*].bp_index` for the true
   `min_bp/max_bp` envelope;
2. shifts **every** bp by one uniform nonnegative lattice-period multiple large
   enough to make `min_bp + offset >= 0` (preserving crossover register);
3. sizes `array_len = ceil((max_bp+offset+1)/period)*period`, period = 21 HC / 32 SQ.

The offset is applied at every write site: `_fill_strand` pointers + array index,
loop/skip arrays, and `stap_colors` 5′ bp key. Row/col/num (`_assign_grid_coords`)
is untouched.

**Bug this fixed:** old code sized arrays to `max(length_bp)` and indexed directly
→ `IndexError` (bp ≥ len, crashes export → 400) or silent tail-wrap corruption
(bp < 0, Python negative index). Regressed silently — export had ~zero test coverage.

**Plain caDNAno roundtrip can relabel the origin.** Without NADOC metadata,
global bp/cell origins and sequences are not guaranteed to survive; default
staple colors can be inserted. The broad legacy tests assert topology
conservation. V3's eligible native HC exports instead restore exact absolute
molecular geometry and sequences using the bounded extension described above.
Import identities and domain segmentation need not be identical.

## Test Coverage
- `tests/test_cadnano_honeycomb_geometry.py` — complete standard HC site classes,
  exact deposited Gür source, native distances, SQ frame and legacy replay digests.
- `tests/test_cadnano_geometry_roundtrip.py` — absolute atoms/bonds/base/backbone
  identity, negative origins, sequences and malformed metadata rejection.
- `tests/test_cadnano.py` — HC/SQ import.
- `tests/test_cadnano_roundtrip.py` — Tier 1 well-formedness (every
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
