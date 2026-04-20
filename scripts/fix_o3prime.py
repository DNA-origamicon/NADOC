"""
Compute the correct O3' template coordinate.

Root cause: P_RADIUS=0.971 moves P 0.043 nm radially beyond crystallographic
position (0.928 nm), causing C3'-O3'-P = 93.6° instead of 119.35°.

O3' is constrained by intra-residue bonds (C3'-O3' length, C4'-C3'-O3' angle).
The only free DOF is rotation around the C4'-C3' bond axis (= ε torsion δ).
This sweep finds the rotation that best satisfies inter-residue tetrahedral constraints.

Run: cd /home/joshua/NADOC && uv run python scripts/fix_o3prime.py
"""
import math, sys
import numpy as np

try:
    import httpx as requests
except ImportError:
    import requests

API = "http://localhost:8000/api"
FRAME_ROT_RAD = -0.646577  # −37.05°
P_O3_BOND = 0.1607         # nm

SUGAR_TEMPLATE = {
    "P":    np.array([ 0.0000,  0.0000,  0.2712]),
    "OP1":  np.array([-0.1167, -0.0413,  0.3513]),
    "OP2":  np.array([ 0.0779, -0.1025,  0.1955]),
    "O5'":  np.array([-0.0596,  0.1096,  0.1710]),
    "C5'":  np.array([-0.0925,  0.2420,  0.2161]),
    "C4'":  np.array([-0.0352,  0.3475,  0.1233]),
    "O4'":  np.array([ 0.1092,  0.3562,  0.1320]),
    "C3'":  np.array([-0.0669,  0.3300, -0.0253]),
    "O3'":  np.array([-0.0957,  0.4573, -0.0821]),
    "C2'":  np.array([ 0.0635,  0.2795, -0.0840]),
    "C1'":  np.array([ 0.1620,  0.3572,  0.0000]),
}

def norm(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v

def angle_deg(v1, v2):
    c = float(np.dot(norm(v1), norm(v2)))
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))

def dihedral(p1, p2, p3, p4):
    b1 = p2-p1; b2 = p3-p2; b3 = p4-p3
    n1 = np.cross(b1, b2); n2 = np.cross(b2, b3)
    n1n, n2n = np.linalg.norm(n1), np.linalg.norm(n2)
    if n1n < 1e-12 or n2n < 1e-12: return 0.0
    n1 /= n1n; n2 /= n2n
    m1 = np.cross(n1, norm(b2))
    return math.degrees(math.atan2(float(np.dot(m1, n2)), float(np.dot(n1, n2))))

def reconstruct_frame(atom_world):
    names = [n for n in SUGAR_TEMPLATE if n in atom_world]
    T = np.array([SUGAR_TEMPLATE[n] for n in names])
    W = np.array([atom_world[n] for n in names])
    Tc, Wc = T - T.mean(0), W - W.mean(0)
    U, s, Vt = np.linalg.svd(Wc.T @ Tc)
    R = U @ np.diag([1, 1, np.linalg.det(U @ Vt)]) @ Vt
    origin = W.mean(0) - R @ T.mean(0)
    return origin, R


def rotate_point_around_axis(point, pivot, axis, angle_rad):
    """Rotate `point` around `axis` through `pivot` by `angle_rad` (Rodrigues)."""
    v = point - pivot
    ax = norm(axis)
    c, s = math.cos(angle_rad), math.sin(angle_rad)
    return pivot + v*c + np.cross(ax, v)*s + ax*np.dot(ax, v)*(1-c)


def main():
    # ── Fetch NADOC model ─────────────────────────────────────────────────────
    r1 = requests.post(f"{API}/design", json={"name": "o3fix", "lattice_type": "HONEYCOMB"})
    assert 200 <= r1.status_code < 300
    r2 = requests.post(f"{API}/design/helix-at-cell", json={"row": 1, "col": 1, "length_bp": 21})
    assert 200 <= r2.status_code < 300
    des = requests.get(f"{API}/design").json()["design"]
    h = des["helices"][0]
    r3 = requests.post(f"{API}/design/scaffold-domain-paint",
                       json={"helix_id": h["id"], "lo_bp": 0, "hi_bp": 20})
    assert 200 <= r3.status_code < 300
    r4 = requests.get(f"{API}/design/atomistic")
    assert 200 <= r4.status_code < 300
    amap = {(a["bp_index"], a["direction"], a["name"]): np.array([a["x"], a["y"], a["z"]])
            for a in r4.json()["atoms"]}

    def residue(bp, direction):
        return {n: amap[(bp, direction, n)] for n in SUGAR_TEMPLATE if (bp, direction, n) in amap}

    BP = 10
    atoms_N  = residue(BP,   "FORWARD")
    atoms_N1 = residue(BP+1, "FORWARD")

    origin_N, R_N = reconstruct_frame(atoms_N)

    c4  = atoms_N["C4'"]
    c3  = atoms_N["C3'"]
    o3  = atoms_N["O3'"]
    p_N1  = atoms_N1["P"]
    op1   = atoms_N1["OP1"]
    op2   = atoms_N1["OP2"]
    o5    = atoms_N1["O5'"]

    # Current intra-residue geometry
    c3o3_len  = np.linalg.norm(o3 - c3)
    c4c3o3_ang = angle_deg(c4 - c3, o3 - c3)
    print(f"Current C3'-O3': {c3o3_len*10:.3f} Å  C4'-C3'-O3': {c4c3o3_ang:.2f}°")
    print(f"Current C3'-O3'-P(next): {angle_deg(c3-o3, p_N1-o3):.2f}°  (1zew: 119.35°)")
    eps_cur = dihedral(c4, c3, o3, p_N1)
    print(f"Current ε: {eps_cur:.2f}°  (1zew: 97.84°)")
    print(f"Current O3'-P distance: {np.linalg.norm(p_N1-o3)*10:.3f} Å")
    print(f"Current O3'-P-OP1: {angle_deg(o3-p_N1, op1-p_N1):.2f}° (1zew: 109.29°)")
    print(f"Current O3'-P-OP2: {angle_deg(o3-p_N1, op2-p_N1):.2f}° (1zew: 107.74°)")
    print(f"Current O3'-P-O5': {angle_deg(o3-p_N1, o5-p_N1):.2f}° (1zew: 105.10°)")

    # ── Sweep O3' around C4'-C3' bond axis ───────────────────────────────────
    # Rotation axis: C4'→C3' direction
    rot_axis = norm(c3 - c4)

    # O3' must stay at: distance c3o3_len from C3', angle c4c3o3_ang from C4'-C3'
    # Parametrize by rotation angle θ around the C4'→C3' axis, with θ=0 = current O3'.

    # Target inter-residue angles from 1zew
    TARGET_OP1 = 109.29
    TARGET_OP2 = 107.74
    TARGET_O5  = 105.10
    TARGET_C3O3P = 119.35

    best_err = 1e9
    best_theta = 0.0
    best_o3 = o3.copy()

    n_steps = 3600
    results = []
    for i in range(n_steps):
        theta = 2 * math.pi * i / n_steps
        o3_new = rotate_point_around_axis(o3, c3, rot_axis, theta)

        # Intra-residue checks
        c3o3_new = np.linalg.norm(o3_new - c3)
        c4c3o3_new = angle_deg(c4 - c3, o3_new - c3)

        # Inter-residue
        dist_o3p = np.linalg.norm(p_N1 - o3_new)
        c3o3p_ang = angle_deg(c3 - o3_new, p_N1 - o3_new)
        ang_op1 = angle_deg(o3_new - p_N1, op1 - p_N1)
        ang_op2 = angle_deg(o3_new - p_N1, op2 - p_N1)
        ang_o5  = angle_deg(o3_new - p_N1, o5  - p_N1)

        # Error: weighted sum of all constraint violations
        err = (
            (ang_op1 - TARGET_OP1)**2 +
            (ang_op2 - TARGET_OP2)**2 +
            (ang_o5  - TARGET_O5 )**2 +
            (c3o3p_ang - TARGET_C3O3P)**2
        )

        results.append((err, theta, o3_new, ang_op1, ang_op2, ang_o5, c3o3p_ang, dist_o3p))
        if err < best_err:
            best_err = err
            best_theta = theta
            best_o3 = o3_new.copy()

    results.sort(key=lambda x: x[0])
    best = results[0]
    best_err, best_theta, best_o3, b_op1, b_op2, b_o5, b_c3o3p, b_dist = best

    print(f"\n=== Best O3' rotation (θ = {math.degrees(best_theta):.2f}°) ===")
    print(f"O3'-P-OP1:   {b_op1:.2f}°  (target {TARGET_OP1}°)")
    print(f"O3'-P-OP2:   {b_op2:.2f}°  (target {TARGET_OP2}°)")
    print(f"O3'-P-O5':   {b_o5:.2f}°  (target {TARGET_O5}°)")
    print(f"C3'-O3'-P:   {b_c3o3p:.2f}°  (target {TARGET_C3O3P}°)")
    print(f"O3'-P dist:  {b_dist*10:.3f} Å  (target 1.607 Å)")
    print(f"C3'-O3' len: {np.linalg.norm(best_o3-c3)*10:.3f} Å  (canonical 1.45 Å)")
    print(f"C4'-C3'-O3': {angle_deg(c4-c3, best_o3-c3):.2f}°  (canonical 108°)")
    print(f"RMS error:   {math.sqrt(best_err):.2f}°")

    # Epsilon torsion at best position
    eps_best = dihedral(c4, c3, best_o3, p_N1)
    print(f"ε torsion:   {eps_best:.2f}°  (1zew: 97.84°)")

    # Back-transform to template coords in frame(N)
    new_o3_template = R_N.T @ (best_o3 - origin_N)
    curr_o3 = SUGAR_TEMPLATE["O3'"]
    print(f"\nCurrent O3' template: ({curr_o3[0]:.4f}, {curr_o3[1]:.4f}, {curr_o3[2]:.4f})")
    print(f"Best O3' template:    ({new_o3_template[0]:.4f}, {new_o3_template[1]:.4f}, {new_o3_template[2]:.4f})")
    print(f"Delta:                ({new_o3_template[0]-curr_o3[0]:.4f}, {new_o3_template[1]-curr_o3[1]:.4f}, {new_o3_template[2]-curr_o3[2]:.4f})")

    # Show top 5 candidates
    print(f"\nTop 5 rotation angles:")
    for i, (err, th, o3n, op1, op2, o5a, c3o3p, dist) in enumerate(results[:5]):
        print(f"  {i+1}: θ={math.degrees(th):.1f}°  OP1={op1:.1f}° OP2={op2:.1f}° O5'={o5a:.1f}° C3'O3'P={c3o3p:.1f}° RMS={math.sqrt(err):.2f}°")

    # ── Verify with the best O3' ──────────────────────────────────────────────
    print(f"\n=== Verification with new template coord ===")
    # New O3' in world = origin_N + R_N @ new_o3_template
    o3_check = origin_N + R_N @ new_o3_template
    dist_check = np.linalg.norm(p_N1 - o3_check)
    print(f"Round-trip error: {np.linalg.norm(o3_check - best_o3)*10:.6f} Å")
    print(f"O3'-P-OP1: {angle_deg(o3_check-p_N1, op1-p_N1):.2f}°")
    print(f"O3'-P-OP2: {angle_deg(o3_check-p_N1, op2-p_N1):.2f}°")
    print(f"O3'-P-O5': {angle_deg(o3_check-p_N1, o5-p_N1):.2f}°")
    print(f"O3'-P dist: {dist_check*10:.3f} Å")

    # ── What is the best achievable? Show range ───────────────────────────────
    all_errs = [math.sqrt(r[0]) for r in results]
    print(f"\nBest achievable RMS: {min(all_errs):.2f}°  Worst: {max(all_errs):.2f}°")
    print("(If best RMS > 5°, the geometry cannot be fixed by moving O3' alone)")
    print("(Root cause: P_RADIUS=0.971 moved P off crystallographic position)")

if __name__ == "__main__":
    main()
