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
# In B-DNA the two phosphate groups in a base pair are NOT diametrically
# opposite (180°).  The minor groove subtends ~120° and the major groove
# subtends ~240°.  This offset means base normals are cross-strand vectors
# (backbone → other backbone), NOT purely inward radial vectors.
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
SQUARE_HELIX_SPACING: float = 2.6  # nm  (same convention)

# ── oxDNA simulation units ────────────────────────────────────────────────────

# 1 oxDNA length unit in nanometres.
OXDNA_LENGTH_UNIT: float = 0.8518  # nm

# Conversion factor: nm → oxDNA length units.
NM_TO_OXDNA: float = 1.0 / OXDNA_LENGTH_UNIT

# ── Miscellaneous ─────────────────────────────────────────────────────────────

# Number of nucleotides produced per base pair (always 2: one per strand).
NUCLEOTIDES_PER_BP: int = 2
