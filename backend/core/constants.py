"""
Topological layer — B-DNA geometric constants.

All physical constants used in nucleotide position calculations must be
imported from this module. Never hardcode these values elsewhere.

Values are taken from the oxDNA coarse-grained model as ground truth,
cross-referenced with standard B-DNA crystallographic parameters.
"""

# ── B-DNA helix geometry ──────────────────────────────────────────────────────

# Rise per base pair along the helix axis, in nanometres.
BDNA_RISE_PER_BP: float = 0.334  # nm/bp

# Twist per base pair, in degrees. Gives ~10.5 bp/turn, consistent with B-DNA.
BDNA_TWIST_PER_BP_DEG: float = 34.3  # degrees/bp

# Twist per base pair in radians (derived, for convenience in geometry code).
import math
BDNA_TWIST_PER_BP_RAD: float = math.radians(BDNA_TWIST_PER_BP_DEG)

# Full turn length in base pairs (360 / twist_per_bp).
BDNA_BP_PER_TURN: float = 360.0 / BDNA_TWIST_PER_BP_DEG  # ~10.495 bp/turn

# Radius from helix axis to the nucleotide centre of mass, in nanometres.
# In the oxDNA model the backbone bead sits ~1.0 nm from the axis.
HELIX_RADIUS: float = 1.0  # nm

# ── Strand geometry — major/minor groove ─────────────────────────────────────

# Angular separation between FORWARD and REVERSE strand backbone beads at the
# same base-pair index, measured at the helix axis.
#
# Angular separation between FORWARD and REVERSE strand backbone beads.
# Set to 150° to match caDNAno's phase convention.
# (Standard B-DNA crystallographic value is 120°; caDNAno uses 150°.)
BDNA_MINOR_GROOVE_ANGLE_DEG: float = 150.0          # degrees
BDNA_MINOR_GROOVE_ANGLE_RAD: float = math.radians(BDNA_MINOR_GROOVE_ANGLE_DEG)

# ── Nucleotide geometry within a strand ──────────────────────────────────────

# Displacement from the backbone position toward the base (along the
# base-normal direction, which is the cross-strand vector), in nanometres.
BASE_DISPLACEMENT: float = 0.3  # nm  (oxDNA reference value)

# ── Lattice inter-helix distances ─────────────────────────────────────────────

# caDNAno honeycomb lattice radius (per-helix spacing unit), in nanometres.
# This is the distance from a helix centre to the midpoint of an edge in the
# triangular dual lattice — NOT the same as HELIX_RADIUS.
HONEYCOMB_LATTICE_RADIUS: float = 1.125  # nm  (caDNAno convention)

# Centre-to-centre distance between adjacent helices on a honeycomb lattice.
# Equals 2 × HONEYCOMB_LATTICE_RADIUS = 2.25 nm.
HONEYCOMB_HELIX_SPACING: float = 2.25  # nm

# Column pitch (x-direction) for the honeycomb lattice.
# Each column is offset by sqrt(3) × HONEYCOMB_LATTICE_RADIUS.
HONEYCOMB_COL_PITCH: float = HONEYCOMB_LATTICE_RADIUS * math.sqrt(3)  # ≈ 1.9486 nm

# Row pitch (y-direction) for the honeycomb lattice.
# cadnano2 convention: each row index increments by 3 × LATTICE_RADIUS = 3.375 nm.
# Within a row, alternating cells (odd parity) are offset by +LATTICE_RADIUS,
# so the actual centre-to-centre distance between adjacent helices is always
# exactly HONEYCOMB_HELIX_SPACING = 2.25 nm regardless of direction.
HONEYCOMB_ROW_PITCH: float = 3.0 * HONEYCOMB_LATTICE_RADIUS  # = 3.375 nm (cadnano2)

# Centre-to-centre distance between adjacent helices on a square lattice.
SQUARE_HELIX_SPACING: float = HONEYCOMB_HELIX_SPACING  # = 2.25 nm

# ── Square lattice helix geometry ─────────────────────────────────────────────

# Twist per base pair for the square lattice (33.75°/bp → 3 turns per 32 bp).
SQUARE_TWIST_PER_BP_DEG: float = 3 * 360.0 / 32  # = 33.75 degrees/bp
SQUARE_TWIST_PER_BP_RAD: float = math.radians(SQUARE_TWIST_PER_BP_DEG)

# Full turn length in base pairs for the square lattice.
SQUARE_BP_PER_TURN: float = 360.0 / SQUARE_TWIST_PER_BP_DEG  # = 32/3 ≈ 10.667 bp/turn

# Column and row pitch (nm) for the square lattice — uniform in both directions.
SQUARE_COL_PITCH: float = SQUARE_HELIX_SPACING   # = 2.6 nm
SQUARE_ROW_PITCH: float = SQUARE_HELIX_SPACING   # = 2.6 nm


# ── oxDNA simulation units ────────────────────────────────────────────────────

# 1 oxDNA length unit in nanometres.
OXDNA_LENGTH_UNIT: float = 0.8518  # nm

# Conversion factor: nm → oxDNA length units.
NM_TO_OXDNA: float = 1.0 / OXDNA_LENGTH_UNIT

# ── Miscellaneous ─────────────────────────────────────────────────────────────

# Number of nucleotides produced per base pair (always 2: one per strand).
NUCLEOTIDES_PER_BP: int = 2

# ── Fast-mode helix-segment XPBD ─────────────────────────────────────────────
# All constants prefixed FAST_ to avoid collision with existing XPBD module-level
# constants in backend/physics/xpbd.py.

# Segment size in base pairs. 21 bp = 2 full B-DNA turns; zero twist residual.
# Chosen to align exactly with the HC crossover period (offsets 0,6,7,13,14,20).
FAST_SEGMENT_BP: int = 21

# Nominal segment length along the helix axis (nm).
FAST_SEGMENT_LENGTH_NM: float = FAST_SEGMENT_BP * BDNA_RISE_PER_BP  # = 7.014 nm

# ── Mechanical parameters (ssDNA / dsDNA) ────────────────────────────────────

# Persistence lengths
SSDNA_PERSISTENCE_LENGTH_NM: float = 2.0   # ssDNA in physiological buffer
DSDNA_PERSISTENCE_LENGTH_NM: float = 50.0  # dsDNA in physiological buffer

# Rise per base / base-pair
SSDNA_RISE_PER_BASE_NM: float = 0.59   # ssDNA relaxed conformation
DSDNA_RISE_PER_BP_NM: float = BDNA_RISE_PER_BP   # alias = 0.334 nm

# Twist aliases
DSDNA_TWIST_PER_BP_DEG: float = BDNA_TWIST_PER_BP_DEG  # alias = 34.3°/bp
SKIP_TWIST_DEFICIT_DEG: float = -34.3   # one missing bp = −34.3° twist deficit

# Helix radius (backbone bead distance from axis)
HELIX_RADIUS_NM: float = HELIX_RADIUS   # alias = 1.0 nm

# Preferred crossover distances (centre-to-centre between helix axes)
HONEYCOMB_HELIX_SPACING_NM: float = HONEYCOMB_HELIX_SPACING   # 2.25 nm
SQUARE_HELIX_SPACING_NM: float = SQUARE_HELIX_SPACING          # 2.25 nm

# ── XPBD solver parameters ───────────────────────────────────────────────────

XPBD_SUBSTEPS: int = 10
XPBD_ITERATIONS: int = 5
XPBD_DAMPING: float = 0.0001
XPBD_CONVERGENCE_THRESHOLD_NM: float = 0.01
XPBD_CONVERGENCE_CONSECUTIVE_FRAMES: int = 3

# Compliance values (α) per the Müller 2020 XPBD formulation.
# Lower α = stiffer constraint. Units: nm² / (arbitrary energy scale).
ALPHA_BACKBONE: float = 1e-6
ALPHA_TWIST: float = 1e-5
ALPHA_BEND_DSDNA: float = 1e-5
ALPHA_BEND_SSDNA: float = 1e-2   # ~1000× more flexible than dsDNA
ALPHA_CROSSOVER: float = 1e-6
ALPHA_REPULSION: float = 1e-3

# ── Fast-mode geometry thresholds ────────────────────────────────────────────

FAST_REPULSION_DIST_NM: float = 2.0    # minimum allowed centre-to-centre distance
FAST_REPULSION_CUTOFF_NM: float = 4.0  # build repulsion pairs within this distance
FAST_CROSSOVER_DIST_HC_NM: float = HONEYCOMB_HELIX_SPACING   # 2.25 nm
FAST_CROSSOVER_DIST_SQ_NM: float = SQUARE_HELIX_SPACING      # 2.25 nm
FAST_MAX_FRAMES: int = 500   # hard cap on solver iterations before forced stop

# ── Crossover site tables ─────────────────────────────────────────────────────
#
# (is_forward, bp_offset_in_period) → (row_delta, col_delta)
#
# is_forward = (row + col) % 2 == 0  (caDNAno parity rule)
# bp_offset  = bp_index % period
#
# If a cell's bp_index % period maps to an entry, the valid crossover neighbor
# is at (row + drow, col + dcol).  No geometry required.

HC_CROSSOVER_PERIOD: int = 21
HC_CROSSOVER_OFFSETS: dict[tuple[bool, int], tuple[int, int]] = {
    # Forward cell (even parity: scaffold runs FORWARD) — cadnano2 canonical
    # cadnano2 _stapL=[[6],[13],[20]], _stapH=[[7],[14],[0]]
    # Even neighbors: [(r,c+1),(r-1,c),(r,c-1)] → indices 0,1,2
    # _stapH[0]=7  → bp7  fwd → neighbor(r,c+1) → (0,+1)
    # _stapL[0]=6  → bp6  fwd → neighbor(r,c+1) → (0,+1)
    # _stapH[1]=14 → bp14 fwd → neighbor(r-1,c) → (-1,0)
    # _stapL[1]=13 → bp13 fwd → neighbor(r-1,c) → (-1,0)
    # _stapH[2]=0  → bp0  fwd → neighbor(r,c-1) → (0,-1)
    # _stapL[2]=20 → bp20 fwd → neighbor(r,c-1) → (0,-1)
    (True,  0): ( 0, -1),
    (True,  6): ( 0, +1),
    (True,  7): ( 0, +1),
    (True, 13): (-1,  0),
    (True, 14): (-1,  0),
    (True, 20): ( 0, -1),
    # Reverse cell (odd parity: scaffold runs REVERSE) — cadnano2 canonical
    # Odd neighbors: [(r,c-1),(r+1,c),(r,c+1)] → indices 0,1,2
    # _stapH[0]=7  → bp7  rev → neighbor(r,c-1) → (0,-1)
    # _stapL[0]=6  → bp6  rev → neighbor(r,c-1) → (0,-1)
    # _stapH[1]=14 → bp14 rev → neighbor(r+1,c) → (+1,0)
    # _stapL[1]=13 → bp13 rev → neighbor(r+1,c) → (+1,0)
    # _stapH[2]=0  → bp0  rev → neighbor(r,c+1) → (0,+1)
    # _stapL[2]=20 → bp20 rev → neighbor(r,c+1) → (0,+1)
    (False,  0): ( 0, +1),
    (False,  6): ( 0, -1),
    (False,  7): ( 0, -1),
    (False, 13): (+1,  0),
    (False, 14): (+1,  0),
    (False, 20): ( 0, +1),
}

SQ_CROSSOVER_PERIOD: int = 32
SQ_CROSSOVER_OFFSETS: dict[tuple[bool, int], tuple[int, int]] = {
    # cadnano2 squarepart.py _stapL=[[31],[23],[15],[7]], _stapH=[[0],[24],[16],[8]]
    # Forward (even parity: (row+col)%2==0) — cadnano2 canonical
    # Even neighbors: [(r,c+1),(r+1,c),(r,c-1),(r-1,c)] → indices 0,1,2,3
    # _stapH[0]=0  → bp0  fwd → neighbor(r,c+1) → (0,+1)
    # _stapL[0]=31 → bp31 fwd → neighbor(r,c+1) → (0,+1)
    # _stapH[1]=24 → bp24 fwd → neighbor(r+1,c) → (+1,0)
    # _stapL[1]=23 → bp23 fwd → neighbor(r+1,c) → (+1,0)
    # _stapH[2]=16 → bp16 fwd → neighbor(r,c-1) → (0,-1)
    # _stapL[2]=15 → bp15 fwd → neighbor(r,c-1) → (0,-1)
    # _stapH[3]=8  → bp8  fwd → neighbor(r-1,c) → (-1,0)
    # _stapL[3]=7  → bp7  fwd → neighbor(r-1,c) → (-1,0)
    (True,  0): ( 0, +1),
    (True, 31): ( 0, +1),
    (True, 23): (+1,  0),
    (True, 24): (+1,  0),
    (True, 15): ( 0, -1),
    (True, 16): ( 0, -1),
    (True,  7): (-1,  0),
    (True,  8): (-1,  0),
    # Reverse (odd parity: (row+col)%2==1) — cadnano2 canonical
    # Odd neighbors: [(r,c-1),(r-1,c),(r,c+1),(r+1,c)] → indices 0,1,2,3
    # _stapH[0]=0  → bp0  rev → neighbor(r,c-1) → (0,-1)
    # _stapL[0]=31 → bp31 rev → neighbor(r,c-1) → (0,-1)
    # _stapH[1]=24 → bp24 rev → neighbor(r-1,c) → (-1,0)
    # _stapL[1]=23 → bp23 rev → neighbor(r-1,c) → (-1,0)
    # _stapH[2]=16 → bp16 rev → neighbor(r,c+1) → (0,+1)
    # _stapL[2]=15 → bp15 rev → neighbor(r,c+1) → (0,+1)
    # _stapH[3]=8  → bp8  rev → neighbor(r+1,c) → (+1,0)
    # _stapL[3]=7  → bp7  rev → neighbor(r+1,c) → (+1,0)
    (False,  0): ( 0, -1),
    (False, 31): ( 0, -1),
    (False, 23): (-1,  0),
    (False, 24): (-1,  0),
    (False, 15): ( 0, +1),
    (False, 16): ( 0, +1),
    (False,  7): (+1,  0),
    (False,  8): (+1,  0),
}

# ── Scaffold crossover site tables ───────────────────────────────────────────
#
# Scaffold crossover positions are a DIFFERENT set from staple crossover positions.
# Derived from cadnano2 honeycombpart.py / squarepart.py _scafL/_scafH tables.
#
# HC scaffold: _scafL=[[1,11],[8,18],[4,15]], _scafH=[[2,12],[9,19],[5,16]]
# HC even parity neighbor order: p0=(r,c+1), p1=(r-1,c), p2=(r,c-1)
HC_SCAFFOLD_CROSSOVER_OFFSETS: dict[tuple[bool, int], tuple[int, int]] = {
    # Forward cell (even parity) ────────────────────────────────────────────
    # p0 (r,c+1): ScafLow[0]={1,11}, ScafHigh[0]={2,12}
    (True,  1): ( 0, +1), (True,  2): ( 0, +1),
    (True, 11): ( 0, +1), (True, 12): ( 0, +1),
    # p1 (r-1,c): ScafLow[1]={8,18}, ScafHigh[1]={9,19}
    (True,  8): (-1,  0), (True,  9): (-1,  0),
    (True, 18): (-1,  0), (True, 19): (-1,  0),
    # p2 (r,c-1): ScafLow[2]={4,15}, ScafHigh[2]={5,16}
    (True,  4): ( 0, -1), (True,  5): ( 0, -1),
    (True, 15): ( 0, -1), (True, 16): ( 0, -1),
    # Reverse cell (odd parity) — neighbor order: p0=(r,c-1), p1=(r+1,c), p2=(r,c+1)
    # p0 (r,c-1): same bp offsets as forward p0
    (False,  1): ( 0, -1), (False,  2): ( 0, -1),
    (False, 11): ( 0, -1), (False, 12): ( 0, -1),
    # p1 (r+1,c): same bp offsets as forward p1
    (False,  8): (+1,  0), (False,  9): (+1,  0),
    (False, 18): (+1,  0), (False, 19): (+1,  0),
    # p2 (r,c+1): same bp offsets as forward p2
    (False,  4): ( 0, +1), (False,  5): ( 0, +1),
    (False, 15): ( 0, +1), (False, 16): ( 0, +1),
}

# SQ scaffold: squareScafLow=[[4,26,15],[18,28,7],[10,20,31],[2,12,23]]
#              squareScafHigh=[[5,27,16],[19,29,8],[11,21,0],[3,13,24]]
# SQ even parity neighbor order: p0=(r,c+1), p1=(r+1,c), p2=(r,c-1), p3=(r-1,c)
SQ_SCAFFOLD_CROSSOVER_OFFSETS: dict[tuple[bool, int], tuple[int, int]] = {
    # Forward cell (even parity) ────────────────────────────────────────────
    # p0 (r,c+1): ScafLow[0]={4,26,15}, ScafHigh[0]={5,27,16}
    (True,  4): ( 0, +1), (True,  5): ( 0, +1),
    (True, 15): ( 0, +1), (True, 16): ( 0, +1),
    (True, 26): ( 0, +1), (True, 27): ( 0, +1),
    # p1 (r+1,c): ScafLow[1]={18,28,7}, ScafHigh[1]={19,29,8}
    (True,  7): (+1,  0), (True,  8): (+1,  0),
    (True, 18): (+1,  0), (True, 19): (+1,  0),
    (True, 28): (+1,  0), (True, 29): (+1,  0),
    # p2 (r,c-1): ScafLow[2]={10,20,31}, ScafHigh[2]={11,21,0}
    (True,  0): ( 0, -1), (True, 10): ( 0, -1),
    (True, 11): ( 0, -1), (True, 20): ( 0, -1),
    (True, 21): ( 0, -1), (True, 31): ( 0, -1),
    # p3 (r-1,c): ScafLow[3]={2,12,23}, ScafHigh[3]={3,13,24}
    (True,  2): (-1,  0), (True,  3): (-1,  0),
    (True, 12): (-1,  0), (True, 13): (-1,  0),
    (True, 23): (-1,  0), (True, 24): (-1,  0),
    # Reverse cell (odd parity) — neighbor order: p0=(r,c-1), p1=(r-1,c), p2=(r,c+1), p3=(r+1,c)
    # p0 (r,c-1): same bp offsets as forward p0
    (False,  4): ( 0, -1), (False,  5): ( 0, -1),
    (False, 15): ( 0, -1), (False, 16): ( 0, -1),
    (False, 26): ( 0, -1), (False, 27): ( 0, -1),
    # p1 (r-1,c): same bp offsets as forward p1
    (False,  7): (-1,  0), (False,  8): (-1,  0),
    (False, 18): (-1,  0), (False, 19): (-1,  0),
    (False, 28): (-1,  0), (False, 29): (-1,  0),
    # p2 (r,c+1): same bp offsets as forward p2
    (False,  0): ( 0, +1), (False, 10): ( 0, +1),
    (False, 11): ( 0, +1), (False, 20): ( 0, +1),
    (False, 21): ( 0, +1), (False, 31): ( 0, +1),
    # p3 (r+1,c): same bp offsets as forward p3
    (False,  2): (+1,  0), (False,  3): (+1,  0),
    (False, 12): (+1,  0), (False, 13): (+1,  0),
    (False, 23): (+1,  0), (False, 24): (+1,  0),
}

# ── Staple colour palette ─────────────────────────────────────────────────────
# Canonical 12-colour palette shared across backend and both frontend views.
# CSS hex strings ("#RRGGBB"), mirrors helix_renderer.js STAPLE_PALETTE exactly.
STAPLE_PALETTE: list[str] = [
    '#ff6b6b', '#ffd93d', '#6bcb77', '#f9844a',
    '#a29bfe', '#ff9ff3', '#00cec9', '#e17055',
    '#74b9ff', '#55efc4', '#fdcb6e', '#d63031',
]
