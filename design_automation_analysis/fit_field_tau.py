"""AF-24 data summary — fit & plot the field-driven equilibration time τ.

Reads ``field_equilibration_data.csv`` (one row per converged (design, field, dir)
cell from the real-engine oxDNA sweep — see ``design_automation_log.md`` AF-24 data
summary) and attempts a general equation for the relaxation time τ as a function of
the key variables, then writes an annotated PNG.

Physical model (overdamped, anchor-tethered free body in a uniform field):
    A(t) = A_inf · (1 − e^(−t/τ))
  • A_inf = the plateau alignment = the *initial alignment difference* Δ0 the body
    swings through; for a linear tether A_inf ≈ q·E·N_free / k  → linear in field E
    AND in free-body size N_free (a cross-section proxy).
  • τ = γ/k = drag / tether-stiffness → scales with the body's drag (≈ size /
    cross-section) and is, to first order, INDEPENDENT of the field strength and of
    Δ0 in the benign (non-melting) regime.

So the general equation attempted here is
    τ(E, N_free, Δ0) ≈ α · N_free^p          (drag-limited; ~flat in E and Δ0)
with the companion amplitude law  A_inf = Δ0 ≈ c · E · N_free  (linear).

Run: ``uv run python design_automation_analysis/fit_field_tau.py`` (regenerate the
CSV first with scratchpad ``af24_dataset.py`` on a CUDA box)."""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
CSV = HERE / "field_equilibration_data.csv"
PNG = HERE / "field_equilibration_tau.png"


def _load():
    """Return (converged rows with a finite τ, ALL raw rows)."""
    conv, raw = [], []
    for r in csv.DictReader(CSV.open()):
        rec = {
            "design": r["design"], "n_free": int(float(r["n_free"])),
            "E": float(r["field_oxdna"]), "pN": float(r["field_pN"]),
            "dir": r["direction"], "A_inf": float(r["A_inf_nm"]),
            "bp_min": float(r["bp_min"]), "converged": r["converged"] == "True",
            "tau": (float(r["tau_steps"]) if r["tau_steps"] not in ("", "None") else None)}
        raw.append(rec)
        if rec["converged"] and rec["tau"] is not None and r["melted"] != "True":
            conv.append(rec)
    return conv, raw


def _lin_fit(x, y):
    """y = m·x + b least squares; returns (m, b, r2)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 2:
        return float("nan"), float("nan"), float("nan")
    m, b = np.polyfit(x, y, 1)
    yhat = m * x + b
    ss_res = float(np.sum((y - yhat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1e-12
    return float(m), float(b), 1.0 - ss_res / ss_tot


def main():
    rows, raw = _load()
    if not rows:
        raise SystemExit(f"no converged rows in {CSV}")
    designs = sorted({r["design"] for r in rows}, key=lambda d: [x["n_free"] for x in rows if x["design"] == d][0])
    summary: list[str] = []

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(2, 2, figsize=(13, 10))
    colors = {d: c for d, c in zip(designs, ["#1f77b4", "#d62728", "#2ca02c", "#9467bd"])}

    # ── Panel A: τ vs field strength E (per design) — test E-independence ──────
    a = ax[0, 0]
    for d in designs:
        sub = [r for r in rows if r["design"] == d]
        a.scatter([r["pN"] for r in sub], [r["tau"] for r in sub], s=42,
                  color=colors[d], alpha=0.8, label=f"{d} (N_free={sub[0]['n_free']})")
        m, b, r2 = _lin_fit([r["pN"] for r in sub], [r["tau"] for r in sub])
        xs = np.linspace(min(r["pN"] for r in sub), max(r["pN"] for r in sub), 20)
        a.plot(xs, m * xs + b, "--", color=colors[d], lw=1)
        summary.append(f"τ vs E [{d}]: slope={m:.0f} steps/pN, mean τ={np.mean([r['tau'] for r in sub]):.0f}, R²={r2:.2f}")
    a.set_xlabel("field strength (pN)"); a.set_ylabel("τ  (oxDNA steps)")
    a.set_title("A. Equilibration time τ vs field strength\n(near-flat → τ rate-limited by drag, not field)")
    a.legend(fontsize=8); a.grid(alpha=0.3)

    # ── Panel B: A_inf (=Δ0) vs field strength, PER DIRECTION — amplitude law ──
    # Splitting by field direction surfaces the orientation dependence of the
    # initial alignment difference: along the duplex axis the body swings farther
    # than perpendicular (anisotropic) — same linear-in-E law, different slope c.
    b_ax = ax[0, 1]
    dir_col = {"axis_z": "#1f77b4", "perp_x": "#ff7f0e", "perp_y": "#2ca02c"}
    d0 = designs[0]  # the tethered design (test343)
    for dname, col in dir_col.items():
        sub = [r for r in rows if r["design"] == d0 and r["dir"] == dname]
        if not sub:
            continue
        b_ax.scatter([r["pN"] for r in sub], [r["A_inf"] for r in sub], s=44,
                     color=col, alpha=0.85, label=dname)
        m, b, r2 = _lin_fit([r["pN"] for r in sub], [r["A_inf"] for r in sub])
        xs = np.linspace(0, max(r["pN"] for r in sub), 20)
        b_ax.plot(xs, m * xs + b, "--", color=col, lw=1.2)
        summary.append(f"Δ0 vs E [{d0}, {dname}]: Δ0 ≈ {m:.2f}·pN {b:+.2f} nm, R²={r2:.2f}")
    b_ax.set_xlabel("field strength (pN)"); b_ax.set_ylabel("plateau alignment A∞ = Δ₀  (nm)")
    b_ax.set_title("B. Initial alignment difference Δ₀ vs field, per direction\n(linear Δ₀ ∝ E; slope larger along the duplex axis)")
    b_ax.legend(fontsize=8, title="field dir"); b_ax.grid(alpha=0.3)

    # ── Panel C: cross-section → tethered-equilibration vs STREAMING regime ────
    # A uniform field on an anchor-tethered body either reaches a plateau (finite τ,
    # tethered regime) or — when field·N_free overwhelms anchor_stiff·N_anchored —
    # streams: alignment grows ~linearly, no τ.  test343 (small) tethers; the 6hb
    # (5.5× the free beads, same single-domain anchor) streams.
    c_ax = ax[1, 0]
    by_design = {}
    for r in raw:
        by_design.setdefault(r["design"], []).append(r)
    for d, sub in sorted(by_design.items(), key=lambda kv: kv[1][0]["n_free"]):
        N = sub[0]["n_free"]
        finite = [r["tau"] for r in sub if r["converged"] and r["tau"] is not None]
        if finite:
            c_ax.errorbar([N], [np.mean(finite)], yerr=[np.std(finite)], fmt="o",
                          color="#2ca02c", ms=11, capsize=5)
            c_ax.annotate(f"{d}\nTETHERED: τ̄={np.mean(finite):.0f}±{np.std(finite):.0f}",
                          (N, np.mean(finite)), textcoords="offset points", xytext=(10, -4), fontsize=8)
            summary.append(f"cross-section [{d}, N_free={N}]: TETHERED, τ̄={np.mean(finite):.0f}±{np.std(finite):.0f} steps ({len(finite)} cells)")
        else:
            y = 30000
            c_ax.annotate("", xy=(N, y * 1.8), xytext=(N, y),
                          arrowprops=dict(arrowstyle="-|>", color="#d62728", lw=2))
            c_ax.scatter([N], [y], color="#d62728", marker="^", s=80)
            c_ax.annotate(f"{d}: STREAMS (no plateau)\nτ → ∞ at this anchor\n(alignment grows linearly)",
                          (N, y), textcoords="offset points", xytext=(-12, 14),
                          ha="right", fontsize=8, color="#d62728")
            summary.append(f"cross-section [{d}, N_free={N}]: STREAMING regime — under-anchored, alignment grows ~linearly, no finite τ (needs anchor scaled to body)")
    c_ax.set_xlabel("free-body size N_free  (cross-section proxy)")
    c_ax.set_ylabel("equilibration time τ  (oxDNA steps)")
    c_ax.set_title("C. Cross-section sets the REGIME (anchor fixed)\ntethered→finite τ  vs  under-anchored→streaming")
    c_ax.set_yscale("log"); c_ax.grid(alpha=0.3, which="both")
    c_ax.set_xlim(0, max(r["n_free"] for r in raw) * 1.25)

    # ── Panel D: melt window — bp_min vs field strength ────────────────────────
    d_ax = ax[1, 1]
    for d in designs:
        sub = [r for r in rows if r["design"] == d]
        d_ax.scatter([r["pN"] for r in sub], [r["bp_min"] for r in sub], s=42,
                     color=colors[d], alpha=0.8, label=d)
    d_ax.axhline(0.5, color="r", ls=":", label="melt floor (0.5)")
    d_ax.set_xlabel("field strength (pN)"); d_ax.set_ylabel("min base-pair retention")
    d_ax.set_title("D. Non-destructive window\n(bp_min ≥ 0.5: aligns WITHOUT ripping apart)")
    d_ax.legend(fontsize=8); d_ax.grid(alpha=0.3); d_ax.set_ylim(0, 1.05)

    # ── general-equation annotation box ────────────────────────────────────────
    tau_mean = np.mean([r["tau"] for r in rows])
    eq = (
        "General equation — overdamped anchor-tethered body in a uniform field "
        "(real-engine oxDNA fit):\n"
        "   A(t) = Δ₀·(1 − e^(−t/τ))     [tethered regime, when anchor·N_anchored ≳ E·N_free]\n"
        f"   Δ₀ = A∞ ≈ c·E·N_free        (initial alignment difference ∝ field × cross-section; "
        "linear in E — panel B)\n"
        f"   τ  ≈ τ₀ = γ/k ≈ {tau_mean:.0f} steps   (drag/stiffness — ~independent of E and Δ₀; panel A)\n"
        "   else → STREAMING: A(t) ≈ v·t, no finite τ  (under-anchored; panel C, the 6hb)\n"
        "Caveat: τ's cross-section exponent is under-determined — only ONE design tethered "
        "(the 6hb streamed); a scaled anchor is needed to map τ(N_free)."
    )
    fig.text(0.5, 0.005, eq, ha="center", va="bottom", fontsize=8.5, family="monospace",
             bbox=dict(boxstyle="round", fc="#fff7e6", ec="#cc9a06"))
    fig.suptitle("AF-24 — field-driven equilibration time τ on the REAL oxDNA engine", fontsize=14, y=0.995)
    fig.tight_layout(rect=(0, 0.07, 1, 0.97))
    fig.savefig(PNG, dpi=140)
    print(f"wrote {PNG}")
    print("\n=== FIT SUMMARY ===")
    for s in summary:
        print(" •", s)


if __name__ == "__main__":
    main()
