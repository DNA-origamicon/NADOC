"""
Tolerance-based comparison of pipeline parameter outputs.

Physics doesn't need to be identical across runs (stochastic MD), but:
  - Signs must match on all angular/stiffness params
  - r0_ang (strand separation) must agree within REL_TOL — it converges quickly
  - k_* stiffness values are NOT magnitude-checked: at 1 ns (ESS≈9) they vary
    by orders of magnitude between runs; sign check is all we can expect
  - Stiffness matrix structure must be present
  - mrdna_params keys must all be present
"""
from __future__ import annotations

REL_TOL = 0.10   # 10% relative tolerance — applied only to stable geometric params
# hj_equilibrium_angle_deg is excluded: at 1 ns the DX junction samples both
# stacking isomers (isoI/isoII) so the sign is not deterministic at this timescale.
SIGN_KEYS = ("r0_ang", "k_bond_kJ_mol_ang2",
             "k_dihedral_kJ_mol_rad2", "k_bend_kJ_mol_rad2")
# Only r0 is stable enough for magnitude comparison at 1 ns.
# k_* have ESS≈9 → order-of-magnitude variation; caught by sign check only.
SCALAR_KEYS = ("r0_ang",)


def params_match(current: dict, reference: dict) -> tuple[bool, str]:
    """
    Compare current and reference parameter dicts.

    Returns (ok, report_string).
    """
    failures: list[str] = []

    curr_p = current.get("mrdna_params", {})
    ref_p  = reference.get("mrdna_params", {})

    # All expected keys present
    for k in SIGN_KEYS:
        if k not in curr_p:
            failures.append(f"Missing key in mrdna_params: {k}")

    # Sign checks
    for k in SIGN_KEYS:
        if k not in curr_p or k not in ref_p:
            continue
        c, r = curr_p[k], ref_p[k]
        if r == 0:
            continue
        if (c > 0) != (r > 0):
            failures.append(
                f"Sign mismatch on {k}: current={c:.4g}, reference={r:.4g}"
            )

    # Magnitude checks (relative tolerance)
    for k in SCALAR_KEYS:
        if k not in curr_p or k not in ref_p:
            continue
        c, r = curr_p[k], ref_p[k]
        if r == 0:
            continue
        rel_diff = abs(c - r) / abs(r)
        if rel_diff > REL_TOL:
            failures.append(
                f"{k}: current={c:.4g}, reference={r:.4g}, "
                f"rel_diff={rel_diff:.1%} > {REL_TOL:.0%}"
            )

    # Structural checks
    if "stiffness" not in current:
        failures.append("Missing 'stiffness' matrix in output")
    elif len(current["stiffness"]) != 6:
        failures.append(f"stiffness has wrong shape: {len(current['stiffness'])}x?")

    if "cov" not in current:
        failures.append("Missing 'cov' matrix in output")

    if "n_frames" not in current or current["n_frames"] < 10:
        failures.append(f"Too few frames: {current.get('n_frames')}")

    ok = len(failures) == 0
    report = "\n".join(f"  FAIL: {f}" for f in failures) if failures else "  All checks passed."
    return ok, report
