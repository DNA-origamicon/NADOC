"""
Verify atomistic geometry after template updates.

Reports:
  1. OP1/OP2 geometry (bond lengths, angles around P)
  2. C1'–N glycosidic bond distances (FWD and REV, all 4 base types)
  3. C1'–N–C bond angles surrounding the glycosidic nitrogen
  4. WC H-bond distances for GC and AT pairs
  5. C3'–O3'–P inter-residue angle

Run from the NADOC root:
  python scripts/verify_atomistic_geometry.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from backend.core.lattice import make_bundle_design
from backend.core.atomistic import build_atomistic_model


def dist_ang(a1, a2):
    """Distance in Å."""
    return np.linalg.norm(np.array([a1.x, a1.y, a1.z]) - np.array([a2.x, a2.y, a2.z])) * 10


def dist_nm(a1, a2):
    """Distance in nm."""
    return np.linalg.norm(np.array([a1.x, a1.y, a1.z]) - np.array([a2.x, a2.y, a2.z]))


def angle_deg(a1, vertex, a2):
    p1 = np.array([a1.x, a1.y, a1.z])
    pv = np.array([vertex.x, vertex.y, vertex.z])
    p2 = np.array([a2.x, a2.y, a2.z])
    v1 = p1 - pv
    v2 = p2 - pv
    cos = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-12)
    return float(np.degrees(np.arccos(np.clip(cos, -1, 1))))


def main():
    # Create a single-helix design with a known sequence covering all 4 base types.
    # Complement: A↔T, G↔C.  FWD sequence (5'→3'): ATGCATGCATGCATGCATGC (20 bp)
    # REV sequence (5'→3'): GCATGCATGCATGCATGCAT (complementary, reversed)
    fwd_seq = "ATGCATGCATGCATGCATGC"
    rev_seq = "".join({"A": "T", "T": "A", "G": "C", "C": "G"}[b] for b in reversed(fwd_seq))

    design = make_bundle_design(cells=[(0, 0)], length_bp=20, plane='XY')

    # Assign sequences to the two strands.
    # FWD strand is the scaffold (FORWARD direction), REV strand is the staple (REVERSE direction).
    for strand in design.strands:
        from backend.core.models import Direction
        has_fwd = any(d.direction == Direction.FORWARD for d in strand.domains)
        if has_fwd:
            strand.sequence = fwd_seq
        else:
            strand.sequence = rev_seq

    model = build_atomistic_model(design)

    # Index atoms by (helix_id, bp_index, direction, name)
    atom_idx: dict = {}
    for a in model.atoms:
        atom_idx[(a.helix_id, a.bp_index, a.direction, a.name)] = a

    h = design.helices[0]
    hid = h.id

    def get(bp, direction, name):
        return atom_idx.get((hid, bp, direction, name))

    # ── 1. OP geometry at bp=5 FWD ───────────────────────────────────────────
    print("=" * 60)
    print("1. OP1/OP2 geometry (bp=5, FWD)")
    print("=" * 60)
    bp = 5
    P        = get(bp,     "FORWARD", "P")
    OP1      = get(bp,     "FORWARD", "OP1")
    OP2      = get(bp,     "FORWARD", "OP2")
    O5p      = get(bp,     "FORWARD", "O5'")
    O3p_prev = get(bp - 1, "FORWARD", "O3'")

    if all([P, OP1, OP2, O5p]):
        print(f"  P→OP1  = {dist_ang(P, OP1):.3f} Å  (target 1.48 Å)")
        print(f"  P→OP2  = {dist_ang(P, OP2):.3f} Å  (target 1.48 Å)")
        print(f"  P→O5'  = {dist_ang(P, O5p):.3f} Å  (target 1.60 Å)")
        if O3p_prev:
            print(f"  P→O3'(N-1) = {dist_ang(P, O3p_prev):.3f} Å  (target 1.61 Å)")
        print(f"  O5'-P-OP1  = {angle_deg(O5p, P, OP1):.1f}°  (tetrahedral ~109.5°)")
        print(f"  O5'-P-OP2  = {angle_deg(O5p, P, OP2):.1f}°  (tetrahedral ~109.5°)")
        print(f"  OP1-P-OP2  = {angle_deg(OP1, P, OP2):.1f}°  (target ~119°)")
        if O3p_prev:
            print(f"  O3'(N-1)-P-OP1 = {angle_deg(O3p_prev, P, OP1):.1f}°")
            print(f"  O3'(N-1)-P-OP2 = {angle_deg(O3p_prev, P, OP2):.1f}°")
            print(f"  O5'-P-O3'(N-1) = {angle_deg(O5p, P, O3p_prev):.1f}°  (bridging-bridging)")
    else:
        print("  ERROR: missing atoms")

    # ── 2. C3'–O3'–P inter-residue angle ────────────────────────────────────
    print()
    print("=" * 60)
    print("2. C3'–O3'–P inter-residue angle (FWD strand)")
    print("=" * 60)
    for bp in [3, 5, 8, 10]:
        C3p    = get(bp,     "FORWARD", "C3'")
        O3p    = get(bp,     "FORWARD", "O3'")
        P_next = get(bp + 1, "FORWARD", "P")
        if C3p and O3p and P_next:
            a = angle_deg(C3p, O3p, P_next)
            d = dist_ang(O3p, P_next)
            print(f"  bp={bp}: C3'–O3'–P = {a:.2f}°  (target 119.35°)  O3'–P = {d:.3f} Å")

    # ── 3. C1'–N glycosidic bond distances ──────────────────────────────────
    print()
    print("=" * 60)
    print("3. C1'–N glycosidic bond distances")
    print("=" * 60)

    def n_atom_name(residue):
        return "N9" if residue in ("DA", "DG") else "N1"

    def report_c1n(bp_i, direction):
        c1p = get(bp_i, direction, "C1'")
        if c1p is None:
            return
        residue = None
        for a in model.atoms:
            if a.helix_id == hid and a.bp_index == bp_i and a.direction == direction and a.name == "C1'":
                residue = a.residue
                break
        if residue is None:
            return
        n_name = n_atom_name(residue)
        n_at = get(bp_i, direction, n_name)
        if c1p and n_at:
            d = dist_ang(c1p, n_at)
            print(f"  {direction[:3]} bp={bp_i} {residue}: C1'–{n_name} = {d:.3f} Å  (target 1.47–1.48 Å)")
            if residue in ("DA", "DG"):
                c4 = get(bp_i, direction, "C4")
                c8 = get(bp_i, direction, "C8")
                if c4: print(f"    C1'–{n_name}–C4 = {angle_deg(c1p, n_at, c4):.1f}°  (target ~126°)")
                if c8: print(f"    C1'–{n_name}–C8 = {angle_deg(c1p, n_at, c8):.1f}°  (target ~125°)")
            else:
                c2 = get(bp_i, direction, "C2")
                c6 = get(bp_i, direction, "C6")
                if c2: print(f"    C1'–{n_name}–C2 = {angle_deg(c1p, n_at, c2):.1f}°  (target ~117°)")
                if c6: print(f"    C1'–{n_name}–C6 = {angle_deg(c1p, n_at, c6):.1f}°  (target ~120°)")

    # FWD sequence: ATGCATGCATGCATGCATGC
    # bp: 0=A 1=T 2=G 3=C 4=A 5=T 6=G 7=C (repeating)
    print("  FWD strand (bp indices for each residue type):")
    for bp_i, base in enumerate(fwd_seq):
        residue_map = {"A": "DA", "T": "DT", "G": "DG", "C": "DC"}
        report_c1n(bp_i, "FORWARD")

    print()
    # REV sequence: GCATGCATGCATGCATGCAT (complement reversed)
    # At bp=0 REV the base is complement of fwd bp=0 (A) = T → DT
    # At bp=1 REV → complement of A at bp=1... wait, need to think about this.
    # The REV strand sequence is assigned 5'→3' which is bp=19 down to bp=0
    # So rev_seq[0] is at bp=19, rev_seq[1] at bp=18, etc.
    # rev_seq = complement(reversed(fwd_seq)) = complement([C,G,T,A,C,G,T,A,...])
    # fwd:  0=A 1=T 2=G 3=C 4=A 5=T 6=G 7=C 8=A 9=T 10=G 11=C 12=A 13=T 14=G 15=C 16=A 17=T 18=G 19=C
    # comp: 0=T 1=A 2=C 3=G 4=T 5=A 6=C 7=G 8=T 9=A 10=C 11=G 12=T 13=A 14=C 15=G 16=T 17=A 18=C 19=G
    # So REV at bp=0 is DT (complement of A), at bp=1 is DA, at bp=2 is DC, at bp=3 is DG
    print("  REV strand (bp indices for each residue type):")
    for bp_i in range(20):
        report_c1n(bp_i, "REVERSE")

    # ── 4. WC H-bond distances ───────────────────────────────────────────────
    print()
    print("=" * 60)
    print("4. WC H-bond distances")
    print("=" * 60)

    def check_hbond(bp_i, fwd_atom, rev_atom, target_nm, label):
        fa = get(bp_i, "FORWARD", fwd_atom)
        ra = get(bp_i, "REVERSE", rev_atom)
        if fa and ra:
            d = dist_nm(fa, ra)
            flag = "✓" if abs(d - target_nm) < 0.05 else "~"
            print(f"  bp={bp_i} {fwd_atom}(FWD)···{rev_atom}(REV)"
                  f" = {d:.3f} nm  (target {target_nm:.3f} nm) {flag}")
        else:
            print(f"  bp={bp_i} {label}: atoms not found")

    # bp=0: FWD=DA, REV=DT (A-T pair, FWD=A)
    print("  bp=0  FWD=DA / REV=DT (AT, FWD=A):")
    check_hbond(0, "N6", "O4", 0.290, "N6···O4")
    check_hbond(0, "N1", "N3", 0.300, "N1···N3")

    # bp=1: FWD=DT, REV=DA (A-T pair, FWD=T)
    print("  bp=1  FWD=DT / REV=DA (AT, FWD=T):")
    check_hbond(1, "O4", "N6", 0.290, "O4···N6")
    check_hbond(1, "N3", "N1", 0.300, "N3···N1")

    # bp=2: FWD=DG, REV=DC (G-C pair, FWD=G)
    print("  bp=2  FWD=DG / REV=DC (GC, FWD=G):")
    check_hbond(2, "O6", "N4", 0.287, "O6···N4")
    check_hbond(2, "N1", "N3", 0.293, "N1···N3")
    check_hbond(2, "N2", "O2", 0.287, "N2···O2")

    # bp=3: FWD=DC, REV=DG (G-C pair, FWD=C)
    print("  bp=3  FWD=DC / REV=DG (GC, FWD=C):")
    check_hbond(3, "N4", "O6", 0.287, "N4···O6")
    check_hbond(3, "N3", "N1", 0.293, "N3···N1")
    check_hbond(3, "O2", "N2", 0.287, "O2···N2")

    print()
    print("Done.")


if __name__ == "__main__":
    main()
