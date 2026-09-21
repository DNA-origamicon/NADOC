"""Chemical landmarks shared by molecular geometry and Full display projections.

These identify sites within the current residue conformation, not a placement
frame's origin. Ordinary template projections can cache their coordinates;
authored conformations such as CPDs resolve the same names in their local atoms.
"""

FULL_REP_BACKBONE_ATOM = "O5'"
PYRIMIDINE_RING = ("N1", "C2", "N3", "C4", "C5", "C6")
PURINE_RING = ("N9", "C8", "N7", "C5", "C6", "N1", "C2", "N3", "C4")
