# NADOC Honeycomb — Scaffold Backbone Starting Orientation Ground Truth

**Status**: Binding reference document. Do not override without explicit DTP decision.
**Date established**: 2026-03-11
**Purpose**: Allow any future AI assistant to derive the correct `phase_offset` values for
`geometry.py` unambiguously, without relying on test-passing heuristics.

---

## 1. Coordinate system

- Helices run along the **+Z axis** (from `axis_start` to `axis_end`).
- Looking **down the +Z axis** at bp=0: **X = right**, **Y = up**, Z = into screen.
- All angles below are in the helix's local XY plane, measured from the local frame.

---

## 2. Local frame for helices along +Z

`_frame_from_helix_axis` in `geometry.py` constructs a right-handed frame:

```
axis_vec = +Z = (0, 0, 1)
ref      = (0, 0, 1)  → collinear → fallback ref = (1, 0, 0)
x_hat = cross(ref, z_hat) = cross((1,0,0), (0,0,1)) = (0,1,0) × ...
```

Working it out explicitly:

```
z_hat = (0, 0, 1)
ref   = (1, 0, 0)          [fallback, since axis is along Z]
x_hat = cross(ref, z_hat) = cross((1,0,0),(0,0,1)) = (0·1−0·0, 0·0−1·1, 1·0−0·0) = (0,−1,0)
y_hat = cross(z_hat, x_hat) = cross((0,0,1),(0,−1,0)) = (0·0−1·(−1), 1·0−0·0, 0·(−1)−0·0) = (1,0,0)
```

Therefore:

```
frame[:,0] = x_hat = (0, −1, 0)    [local x → world −Y]
frame[:,1] = y_hat = (1,  0, 0)    [local y → world +X]
frame[:,2] = z_hat = (0,  0, 1)    [local z → world +Z]
```

---

## 3. Backbone position formula

From `geometry.py`, the radial unit vector for an angle `θ` is:

```python
radial = cos(θ) * frame[:,0] + sin(θ) * frame[:,1]
```

Substituting the frame vectors:

```
radial = cos(θ) * (0,−1,0) + sin(θ) * (1,0,0)
       = (sin(θ), −cos(θ), 0)    [in world XYZ]
```

So the **backbone direction in world space** is:

```
backbone_direction(θ) = (sin(θ), −cos(θ), 0)
```

Verification at selected angles:

| θ    | sin(θ) | −cos(θ) | world direction       |
|------|--------|---------|----------------------|
|  0°  |  0     |  −1     | (0, −1, 0) = −Y (down) |
| 90°  |  1     |   0     | (1,  0, 0) = +X (right) |
| 180° |  0     |  +1     | (0, +1, 0) = +Y (up)   |
| 270° | −1     |   0     | (−1, 0, 0) = −X (left) |

---

## 4. Minor groove offset

The REVERSE strand is offset from the FORWARD strand by `+120°` (minor groove):

```
θ_FORWARD  = phase_offset + bp × twist
θ_REVERSE  = θ_FORWARD + 120°
           = phase_offset + 120° + bp × twist
```

At bp=0:
- FORWARD backbone direction = `backbone_direction(phase_offset)`
- REVERSE backbone direction = `backbone_direction(phase_offset + 120°)`

The two strands are **NOT antipodal** (120° apart, not 180°).
Minor groove = 120°, major groove = 240°.

---

## 5. Honeycomb cell types and scaffold assignment

The NADOC unified cell rule:

```
val = (row + col % 2) % 3
```

| val | Cell type | Scaffold role      | Scaffold strand direction |
|-----|-----------|--------------------|--------------------------|
|  0  | FORWARD   | scaffold IS the FORWARD strand | runs 5'→3' in +Z |
|  1  | REVERSE   | scaffold IS the REVERSE strand | runs 5'→3' in −Z |
|  2  | HOLE      | invalid cell, not rendered     | —                 |

Every adjacent valid-cell pair has one FORWARD cell and one REVERSE cell → **antiparallel by construction**.

---

## 6. Ground-truth starting orientations at bp=0

### Design requirement

For the honeycomb lattice to be visually consistent with caDNAno and physically meaningful,
the scaffold backbone at bp=0 must point **due right (+X)** when looking down +Z.
This is the canonical "east" starting position used in all reference implementations.

The scaffold bead is at `+X` for both cell types, but it is carried by different strand roles:
- FORWARD cell: scaffold IS the FORWARD strand → FORWARD bead must be at +X
- REVERSE cell: scaffold IS the REVERSE strand → REVERSE bead must be at +X

### Derivation for FORWARD cells (val=0)

Scaffold = FORWARD strand. Require scaffold bead at +X:

```
backbone_direction(phase_offset) = +X = (1, 0, 0)
→ sin(phase_offset) = 1, −cos(phase_offset) = 0
→ phase_offset = 90°
```

**FORWARD cell phase_offset = 90° = π/2 rad**

FORWARD bead at bp=0: `(+HELIX_RADIUS, 0, 0)` = due right
REVERSE bead at bp=0: `backbone_direction(90° + 120°) = backbone_direction(210°)`
  = `(sin(210°), −cos(210°), 0) = (−0.5, +0.866, 0)` = upper-left

### Derivation for REVERSE cells (val=1)

Scaffold = REVERSE strand. Require scaffold bead at +X:

```
backbone_direction(phase_offset + 120°) = +X = (1, 0, 0)
→ phase_offset + 120° = 90°
→ phase_offset = −30° = 330°    [modulo 360°]
```

Wait — this gives the REVERSE bead at +X (east), same as FORWARD. Let us re-examine
whether this is actually what "canonical east" means.

**The real constraint is antiparallel scaffold orientation, not co-directional east.**

The honeycomb lattice is designed so that **adjacent scaffolds are antiparallel**.
If FORWARD scaffold points east (+X), then REVERSE scaffold should point **west (−X)**,
since it runs in the opposite direction.

Corrected derivation for REVERSE cells:

Scaffold = REVERSE strand. Scaffold runs in −Z. At bp=0 the scaffold backbone should
point **west (−X)** to be antiparallel to the adjacent FORWARD scaffold (pointing east):

```
backbone_direction(phase_offset + 120°) = −X = (−1, 0, 0)
→ sin(phase_offset + 120°) = −1, −cos(phase_offset + 120°) = 0
→ phase_offset + 120° = 270°
→ phase_offset = 150°
```

**REVERSE cell phase_offset = 150° = 5π/6 rad**

REVERSE (scaffold) bead at bp=0: `backbone_direction(270°) = (−1, 0, 0)` = due left
FORWARD (staple) bead at bp=0: `backbone_direction(150°) = (sin(150°), −cos(150°), 0) = (0.5, +0.866, 0)` = upper-right

---

## 7. Summary table

| Cell type | val | Scaffold strand | phase_offset (correct) | Scaffold bead at bp=0 |
|-----------|-----|-----------------|------------------------|----------------------|
| FORWARD   |  0  | FORWARD         | 90° = π/2 rad          | (+HELIX_RADIUS, 0, 0) = east  |
| REVERSE   |  1  | REVERSE         | 150° = 5π/6 rad        | (−HELIX_RADIUS, 0, 0) = west  |

---

## 8. ASCII cross-section diagram (looking down +Z at bp=0)

```
          Y (up)
          |
          |
   -------+---------- X (right)
          |
          |

FORWARD cell (val=0):              REVERSE cell (val=1):

        (staple, upper-left)               (staple, upper-right)
           *                                       *
          /                                         \
 --------O---------→                 ←---------O--------
         |                                     |
         |                                     |
   center O                             center O

 Scaffold bead (FORWARD strand)    Scaffold bead (REVERSE strand)
 at (+HELIX_RADIUS, 0, 0) = EAST  at (-HELIX_RADIUS, 0, 0) = WEST

 phase_offset = 90° (π/2)         phase_offset = 150° (5π/6)
```

The arrow (→ or ←) represents the scaffold backbone bead position at bp=0.
The staple bead is 120° away (minor groove).

---

## 9. Antiparallel rule verification

For an adjacent FORWARD–REVERSE cell pair:
- FORWARD scaffold bead: east (+X)
- REVERSE scaffold bead: west (−X)
- They point in **opposite directions**, confirming antiparallel.

Additionally, the strand *directions* are antiparallel by construction:
- FORWARD scaffold runs 5'→3' in +Z
- REVERSE scaffold runs 5'→3' in −Z

Both the backbone orientation AND the strand directionality are antiparallel. ✓

---

## 10. Current code status and known bug

As of 2026-03-11, `backend/core/lattice.py` (`make_bundle_design`) uses:

```python
# FORWARD cells (val=0):  phase_offset = math.radians(90.0)   ← CORRECT
# REVERSE cells (val=1):  phase_offset = math.radians(330.0)  ← WRONG
```

The value `330°` gives `θ_REVERSE = 330° + 120° = 450° = 90°`, placing the REVERSE
(scaffold) bead also at east (+X). This makes the two scaffold strands point in the
**same** direction at bp=0, which contradicts the antiparallel constraint.

The correct value is `phase_offset = 150°` for REVERSE cells.

**To fix**: change `math.radians(330.0)` to `math.radians(150.0)` in `lattice.py`
wherever REVERSE cell phase_offset is assigned.

---

## 11. Derivation from first principles (no memorization needed)

Given:
1. `frame[:,0] = (0,−1,0)`, `frame[:,1] = (1,0,0)` for helices along +Z
2. `backbone_direction(θ) = (sin θ, −cos θ, 0)` in world XY
3. REVERSE strand angle = FORWARD angle + 120°
4. FORWARD scaffold must face east (+X): `θ = 90°` → `phase_offset_FORWARD = 90°`
5. REVERSE scaffold must face west (−X): `θ = 270°` → `phase_offset_REVERSE + 120° = 270°` → `phase_offset_REVERSE = 150°`

Any implementation that gets different values has an error somewhere in steps 1–5.
