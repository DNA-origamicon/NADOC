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
# In B-DNA the two phosphate groups in a base pair are NOT antipodal.
# The minor groove subtends ~120° and the major groove subtends ~240°,
# consistent with standard B-DNA crystallographic parameters.
BDNA_MINOR_GROOVE_ANGLE_DEG: float = 120.0          # degrees
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
# Each row is spaced by one helix spacing (2 × LATTICE_RADIUS = 2.25 nm) in y,
# forming a triangular close-packed arrangement where every interior helix has
# 6 nearest neighbours at exactly HONEYCOMB_HELIX_SPACING apart.
HONEYCOMB_ROW_PITCH: float = 2.0 * HONEYCOMB_LATTICE_RADIUS  # = 2.25 nm

# Centre-to-centre distance between adjacent helices on a square lattice.
SQUARE_HELIX_SPACING: float = HONEYCOMB_HELIX_SPACING  # = 2.25 nm

# ── Square lattice helix geometry ─────────────────────────────────────────────

# Twist per base pair for the square lattice (33.75°/bp → 3 turns per 32 bp).
SQUARE_TWIST_PER_BP_DEG: float = 3 * 360.0 / 32  # = 33.75 degrees/bp
SQUARE_TWIST_PER_BP_RAD: float = math.radians(SQUARE_TWIST_PER_BP_DEG)

# Full turn length in base pairs for the square lattice.
SQUARE_BP_PER_TURN: float = 360.0 / SQUARE_TWIST_PER_BP_DEG  # = 32/3 ≈ 10.667 bp/turn

# Crossover repeat period (bp) for the square lattice.
SQUARE_CROSSOVER_PERIOD: int = 8

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
