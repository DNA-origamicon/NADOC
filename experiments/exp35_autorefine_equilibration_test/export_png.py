"""exp35 PNG exporter — turn whatever result JSON exists into annotated PNGs.

Standalone (no GPU, no re-sim): reads ``results/{residual,proxy,e2e}_result.json`` +
``results/profiles/twistseries_*.json`` and writes PNGs to ``results/profiles/png/``.  Reuses
exp34 ``plot34`` panels.  Designed to be fired by the end-of-job trigger (``trigger_export.sh``)
so a PNG of the resulting data appears the instant a run finishes — independent of the runner's
own inline plotting.

  python export_png.py            # export every result JSON present
  python export_png.py residual   # just one mode
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "exp34_finetune_validation"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import plot34 as plot  # noqa: E402

RESULTS_DIR = HERE / "results"
PROFILE_DIR = RESULTS_DIR / "profiles"
PNG_DIR = PROFILE_DIR / "png"

# point plot34's module-level dirs at exp35
plot.RESULTS_DIR = RESULTS_DIR
plot.PROFILE_DIR = PROFILE_DIR
plot.PNG_DIR = PNG_DIR


def _load(p: pathlib.Path):
    return json.loads(p.read_text()) if p.exists() else None


def _series_rec(label: str, total_skips, ts_block, eq_block) -> dict:
    """A plot34-compatible record (label + total_skips + equilibrated) for save_twistseries_png;
    it reads the per-frame data itself from profiles/twistseries_<label>.json."""
    return {"label": label, "total_skips": total_skips,
            "twist_series": ts_block or {}, "equilibrated": eq_block or {}}


def export_residual() -> pathlib.Path | None:
    r = _load(RESULTS_DIR / "residual_result.json")
    if not r or r.get("status") != "ok":
        print(f"[export] residual: no ok result ({(r or {}).get('status')})")
        return None
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    series = _load(PROFILE_DIR / "twistseries_residual_d+4.json")
    if not series:
        print("[export] residual: no twist series JSON")
        return None
    v = r.get("verdict", {})
    eq = r.get("equilibrated", {})

    fig, ax = plt.subplots(figsize=(11, 5.6))
    plot._twist_series_panel(ax, series, _series_rec("residual_d+4", r.get("total_skips"),
                                                     r.get("twist_series"), eq))
    verdict = "PASS" if v.get("passed") else "FAIL"
    vcolour = "#1b7837" if v.get("passed") else "#b2182b"
    t0_steps = v.get("t0_steps", 0) or 0
    ax.set_title(
        f"exp35 residual-transient — d+4 = {r.get('total_skips')} skips (3×6×400)   |   "
        f"{verdict}\n"
        f"burn-in t0 = {t0_steps/1e6:.2f}M steps   |   "
        f"whole-prod mean {v.get('whole_production_mean_deg')}°   |   "
        f"equilibrated {eq.get('mean')}±{eq.get('sem')}°  (N_eff {eq.get('n_eff')})",
        fontsize=10, color=vcolour)
    # verdict criteria box
    crit = v.get("criteria", {})
    box = "\n".join([
        f"PASS criteria:",
        f" t0 ≤ 1M steps:        {crit.get('t0_le_1M_steps')}",
        f" |whole−eq| ≤ 2°:      {crit.get('whole_vs_eq_within_2deg')}",
        f" |eq| ≤ 2° (d+4≈0):    {crit.get('equilibrated_within_2deg_of_zero')}",
    ])
    ax.text(1.012, 0.30, box, transform=ax.transAxes, fontsize=8, va="top", ha="left",
            family="monospace", bbox=dict(boxstyle="round", fc="white", ec=vcolour, lw=2))
    out = PNG_DIR / "residual_d+4.png"
    fig.savefig(out, dpi=120, bbox_inches="tight")
    plt.close(fig)
    print(f"[export] residual → {out}  ({verdict})")
    return out


def export_proxy() -> list[pathlib.Path]:
    r = _load(RESULTS_DIR / "proxy_result.json")
    if not r:
        return []
    outs = []
    for it in r.get("iteration_series", []):
        label = f"proxy_iter{it['iter']}"
        rec = _series_rec(label, 0, {"mean": it.get("whole_mean")},
                          {"t0_frames": it.get("t0_frames"), "mean": it.get("mean"),
                           "sem": it.get("sem"), "n_eff": it.get("n_eff")})
        p = plot.save_twistseries_png(rec)
        if p:
            outs.append(p)
    print(f"[export] proxy → {len(outs)} iteration PNGs")
    return outs


def export_e2e() -> list[pathlib.Path]:
    r = _load(RESULTS_DIR / "e2e_result.json")
    if not r:
        return []
    outs = []
    for it in r.get("iteration_series", []):
        label = f"e2e_iter{it['iter']}"
        rec = _series_rec(label, r.get("converged_skips_total") or 0,
                          {"mean": it.get("whole_mean")},
                          {"t0_frames": it.get("t0_frames"), "mean": it.get("mean"),
                           "sem": it.get("sem"), "n_eff": it.get("n_eff")})
        p = plot.save_twistseries_png(rec)
        if p:
            outs.append(p)
    # convergence summary: twist + skip-count vs iteration
    its = r.get("iterations") or []
    if its:
        fig, ax = plt.subplots(figsize=(8.5, 5))
        ax.axhline(0, color="#444", lw=0.8, ls="--", label="twist-zero target")
        xs = list(range(len(its)))
        tw = [i.get("measured") if i.get("measured") is not None else i.get("global_twist_deg")
              for i in its]
        ax.plot(xs, tw, "-o", color="#2166ac", label="steering twist (deg)")
        ax.set_xlabel("iteration"); ax.set_ylabel("twist (deg)")
        ax.set_title(f"exp35 e2e — converged period {r.get('converged_period')}, "
                     f"{r.get('converged_skips_total')} skips, twist {r.get('converged_twist_deg')}°, "
                     f"PASS={r.get('pass')}", fontsize=10)
        ax.grid(alpha=0.25); ax.legend(fontsize=8)
        out = PNG_DIR / "e2e_convergence.png"
        fig.tight_layout(); fig.savefig(out, dpi=120); plt.close(fig)
        outs.append(out)
    print(f"[export] e2e → {len(outs)} PNGs")
    return outs


def export_design() -> list[pathlib.Path]:
    outs = []
    for rp in sorted(RESULTS_DIR.glob("design_*_result.json")):
        r = _load(rp)
        if not r or r.get("status") != "ok":
            continue
        label = f"design_{r.get('design')}"
        series = _load(PROFILE_DIR / f"twistseries_{label}.json")
        if not series:
            continue
        rec = _series_rec(label, r.get("total_skips"), r.get("twist_series"),
                          r.get("equilibrated"))
        p = plot.save_twistseries_png(rec)
        if p:
            outs.append(p)
        eq = r.get("equilibrated", {})
        print(f"[export] design {r.get('design')}: {r.get('total_skips')} skips, "
              f"equilibrated {eq.get('mean')}±{eq.get('sem')}° → {p}")
    return outs


def main() -> None:
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "residual"):
        export_residual()
    if which in ("all", "proxy"):
        export_proxy()
    if which in ("all", "e2e"):
        export_e2e()
    if which in ("all", "design"):
        export_design()


if __name__ == "__main__":
    main()
