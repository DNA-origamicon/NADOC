"""
Experiment: compare nucleotide backbone angles at bp=0 between
  (A) a caDNAno SQ import (2x4sq.json)
  (B) a native NADOC SQ design (make_bundle_design)

For each helix the "orientation at bp=0" is fully determined by phase_offset,
which sets the backbone azimuth angle in the XY plane at bp index 0.

  backbone_angle = phase_offset + 0 * twist_per_bp_rad = phase_offset

We also compute actual XY-plane backbone positions via geometry.py so the
comparison is concrete rather than just symbolic.
"""

import json, math, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.cadnano import import_cadnano
from backend.core.lattice import make_bundle_design
from backend.core.geometry import nucleotide_positions
from backend.core.models import LatticeType, Direction

# ── Load caDNAno file ──────────────────────────────────────────────────────────
cadnano_path = Path(__file__).resolve().parents[1] / "Examples/cadnano/2x4sq.json"
with open(cadnano_path) as f:
    cadnano_data = json.load(f)

imported_design = import_cadnano(cadnano_data)

# ── Native NADOC SQ design ─────────────────────────────────────────────────────
# 2x4 grid: rows 0-1, cols 0-3 (matching the 2×4 pattern in caDNAno)
cells = [(r, c) for r in range(2) for c in range(4)]
native_design = make_bundle_design(
    cells=cells,
    length_bp=64,
    name="2x4sq_native",
    plane="XY",
    lattice_type=LatticeType.SQUARE,
)

# ── Helper: backbone azimuth at bp=0 ──────────────────────────────────────────
def helix_direction(helix, design):
    """Infer direction of the scaffold strand on this helix from its domains."""
    for strand in design.strands:
        for domain in strand.domains:
            if domain.helix_id == helix.id:
                return domain.direction
    return None

def backbone_azimuth_deg(helix, bp=0):
    """Return the XY-plane azimuth (deg) of the FORWARD-strand backbone at bp."""
    nps = nucleotide_positions(helix)
    fwd_nps = [n for n in nps if n.direction == Direction.FORWARD and n.bp_index == bp]
    if not fwd_nps:
        return None
    pos = fwd_nps[0].position  # [x, y, z]
    dx = pos[0] - helix.axis_start.x
    dy = pos[1] - helix.axis_start.y
    return math.degrees(math.atan2(dy, dx)) % 360

def print_design(label, design):
    print("=" * 72)
    print(f"{label}:")
    print(f"  {'Helix ID':<32} {'Dir':>8} {'phase(deg)':>12} {'FWD backbone az@bp0':>22}")
    print("-" * 72)
    for h in sorted(design.helices, key=lambda h: h.id):
        phase_deg = math.degrees(h.phase_offset) % 360
        d = helix_direction(h, design)
        dir_str = d.value if d else "?"
        az = backbone_azimuth_deg(h, bp=0)
        az_str = f"{az:.2f}" if az is not None else "N/A"
        print(f"  {h.id:<32} {dir_str:>8} {phase_deg:>12.2f} {az_str:>22}")
    print()

# ── Print results ──────────────────────────────────────────────────────────────
print_design("IMPORTED caDNAno design (SQ)", imported_design)
print_design("NATIVE NADOC design (SQ)", native_design)

print("=" * 72)
print("SUMMARY — phase at bp=0 by direction:")
for design_label, design in [("Imported", imported_design), ("Native", native_design)]:
    fwd = [math.degrees(h.phase_offset) % 360
           for h in design.helices
           if helix_direction(h, design) == Direction.FORWARD]
    rev = [math.degrees(h.phase_offset) % 360
           for h in design.helices
           if helix_direction(h, design) == Direction.REVERSE]
    print(f"  {design_label}: FORWARD={fwd[0]:.2f}°  REVERSE={rev[0]:.2f}°"
          f"  (all identical: {len(set(round(v,2) for v in fwd))==1 and len(set(round(v,2) for v in rev))==1})")
