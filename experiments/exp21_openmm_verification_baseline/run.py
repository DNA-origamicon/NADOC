"""
Exp21 — OpenMM GBNeck2 Verification Baseline
=============================================
Characterises C1' drift metrics for single-helix and 6HB designs under short
AMBER14+OL15+GBNeck2 implicit-solvent MD (2 ps, 10 ps, 50 ps) at 300 K.

Usage
-----
    python experiments/exp21_openmm_verification_baseline/run.py

Requires openmm:
    conda install -c conda-forge openmm>=8.0

Outputs (written to results/)
------------------------------
    metrics.json              — all VerificationResult fields per (design, duration)
    per_helix_rmsd_bar.png    — bar chart: per-helix RMSD at each NVT duration
    global_rmsd_timeseries.png — global RMSD vs NVT duration for each design
    inter_helix_com_drift.png — COM drift bar chart for 6HB design
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Add project root to path so we can import backend without pip install
sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Design, DesignMetadata, Direction, Domain, Helix,
    LatticeType, Strand, StrandType, Vec3,
)
from backend.checkers.openmm_checker import verify_design_with_openmm, VerificationResult

OUT = Path(__file__).parent / "results"
OUT.mkdir(exist_ok=True)


# ── Design definitions ──────────────────────────────────────────────────────────

def _make_single_helix(length_bp: int = 42) -> Design:
    helix = Helix(
        id="h0",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=length_bp * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=length_bp,
    )
    scaffold = Strand(
        id="scaffold",
        domains=[Domain(helix_id="h0", start_bp=0, end_bp=length_bp - 1,
                        direction=Direction.FORWARD)],
        strand_type=StrandType.SCAFFOLD,
    )
    staple = Strand(
        id="staple",
        domains=[Domain(helix_id="h0", start_bp=length_bp - 1, end_bp=0,
                        direction=Direction.REVERSE)],
    )
    return Design(
        id="single_42bp",
        helices=[helix],
        strands=[scaffold, staple],
        lattice_type=LatticeType.HONEYCOMB,
        metadata=DesignMetadata(name="Single helix 42 bp"),
    )


def _make_6hb(length_bp: int = 42) -> Design:
    """Honeycomb 6HB at axial positions from standard HC lattice."""
    # Honeycomb lattice nearest-neighbour spacing
    SPACING = 2.25  # nm

    # 6 helix positions in honeycomb layout (column, row)
    # Using the same CELLS as exp13_6hb_cohesion
    import math
    positions_xy = [
        (0.0,               0.0),
        (SPACING,           0.0),
        (SPACING / 2,       SPACING * math.sqrt(3) / 2),
        (-SPACING / 2,      SPACING * math.sqrt(3) / 2),
        (-SPACING,          0.0),
        (-SPACING / 2,     -SPACING * math.sqrt(3) / 2),
    ]

    helices = [
        Helix(
            id=f"h{i}",
            axis_start=Vec3(x=xy[0], y=xy[1], z=0.0),
            axis_end=Vec3(x=xy[0], y=xy[1], z=length_bp * BDNA_RISE_PER_BP),
            phase_offset=0.0,
            length_bp=length_bp,
        )
        for i, xy in enumerate(positions_xy)
    ]

    strands = []
    for i, h in enumerate(helices):
        strands.append(Strand(
            id=f"scaf{i}",
            strand_type=StrandType.SCAFFOLD,
            domains=[Domain(helix_id=h.id, start_bp=0, end_bp=length_bp - 1,
                            direction=Direction.FORWARD)],
        ))
        strands.append(Strand(
            id=f"stpl{i}",
            domains=[Domain(helix_id=h.id, start_bp=length_bp - 1, end_bp=0,
                            direction=Direction.REVERSE)],
        ))

    return Design(
        id="6hb_42bp",
        helices=helices,
        strands=strands,
        lattice_type=LatticeType.HONEYCOMB,
        metadata=DesignMetadata(name="6HB 42 bp"),
    )


# ── Experiment configurations ───────────────────────────────────────────────────

DESIGNS = [
    ("single_helix_42bp", _make_single_helix(42)),
    ("6hb_42bp",          _make_6hb(42)),
]

NVT_CONFIGS = [
    ("2ps",  1_000),
    ("10ps", 5_000),
    ("50ps", 25_000),
]

REPORTING_INTERVAL = 500   # frames every 1 ps at 2 fs/step


# ── Run ─────────────────────────────────────────────────────────────────────────

def run_all() -> dict:
    """Run all (design, duration) combinations and return collected metrics."""
    all_results: dict[str, dict] = {}

    for design_name, design in DESIGNS:
        print(f"\n{'='*60}")
        print(f"Design: {design_name}")
        print(f"{'='*60}")

        for duration_label, n_steps_nvt in NVT_CONFIGS:
            run_key = f"{design_name}__{duration_label}"
            print(f"\n  NVT duration: {duration_label} ({n_steps_nvt} steps)")

            t0 = time.time()
            result: VerificationResult = verify_design_with_openmm(
                design,
                n_steps_minimize=500,
                n_steps_nvt=n_steps_nvt,
                temperature_k=300.0,
                reporting_interval=REPORTING_INTERVAL,
                prefer_gpu=True,  # use CUDA if available, CPU fallback
            )
            elapsed = time.time() - t0

            print(f"    platform:       {result.platform_used}")
            print(f"    elapsed:        {elapsed:.1f} s")
            print(f"    n_atoms:        {result.n_atoms}")
            print(f"    potential_E:    {result.potential_energy_kj_per_mol:.1f} kJ/mol")
            print(f"    global_rmsd:    {result.global_rmsd_nm*10:.2f} Å")
            print(f"    max_deviation:  {result.max_deviation_nm*10:.2f} Å")
            print(f"    passed:         {result.passed}")
            if result.warnings:
                print(f"    warnings:       {result.warnings}")

            # Serialise result
            all_results[run_key] = {
                "design_name":                  design_name,
                "duration_label":               duration_label,
                "n_steps_nvt":                  n_steps_nvt,
                "elapsed_s":                    elapsed,
                "platform_used":                result.platform_used,
                "n_atoms":                      result.n_atoms,
                "potential_energy_kj_per_mol":  result.potential_energy_kj_per_mol,
                "global_rmsd_nm":               result.global_rmsd_nm,
                "max_deviation_nm":             result.max_deviation_nm,
                "per_helix_rmsd_nm":            result.per_helix_rmsd_nm,
                "inter_helix_com_drift_nm":     result.inter_helix_com_drift_nm,
                "passed":                       result.passed,
                "warnings":                     result.warnings,
                "ff_description":               result.ff_description,
            }

    return all_results


def save_metrics(all_results: dict) -> None:
    out_path = OUT / "metrics.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\nMetrics written to {out_path}")


def plot_global_rmsd_timeseries(all_results: dict) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    duration_labels = [d for d, _ in NVT_CONFIGS]
    x = np.arange(len(duration_labels))

    for design_name, _ in DESIGNS:
        rmsds = []
        for dur_label, _ in NVT_CONFIGS:
            key = f"{design_name}__{dur_label}"
            if key in all_results:
                rmsds.append(all_results[key]["global_rmsd_nm"] * 10)  # nm → Å
            else:
                rmsds.append(float("nan"))
        ax.plot(x, rmsds, marker="o", label=design_name)

    ax.axhline(3.0, color="red", linestyle="--", linewidth=0.8, label="Pass threshold (3 Å)")
    ax.set_xticks(x)
    ax.set_xticklabels(duration_labels)
    ax.set_xlabel("NVT duration")
    ax.set_ylabel("Global C1′ RMSD (Å)")
    ax.set_title("Global C1′ drift vs NADOC geometric prediction")
    ax.legend()
    ax.grid(axis="y", alpha=0.4)

    path = OUT / "global_rmsd_timeseries.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {path}")


def plot_per_helix_rmsd(all_results: dict) -> None:
    """Bar chart of per-helix RMSD at the 10 ps duration."""
    fig, axes = plt.subplots(1, len(DESIGNS), figsize=(5 * len(DESIGNS), 5), sharey=False)
    if len(DESIGNS) == 1:
        axes = [axes]

    for ax, (design_name, _) in zip(axes, DESIGNS):
        key = f"{design_name}__10ps"
        if key not in all_results:
            ax.set_title(f"{design_name}\n(no data)")
            continue
        per_helix = all_results[key]["per_helix_rmsd_nm"]
        helix_ids = sorted(per_helix)
        rmsds_ang = [per_helix[h] * 10 for h in helix_ids]

        ax.bar(helix_ids, rmsds_ang, color="steelblue", alpha=0.8)
        ax.axhline(3.0, color="red", linestyle="--", linewidth=0.8, label="Avg threshold (3 Å)")
        ax.axhline(5.0, color="orange", linestyle="--", linewidth=0.8, label="Max threshold (5 Å)")
        ax.set_xlabel("Helix ID")
        ax.set_ylabel("Per-helix C1′ RMSD (Å)")
        ax.set_title(f"{design_name} — 10 ps")
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.4)
        plt.setp(ax.get_xticklabels(), rotation=30, ha="right")

    fig.tight_layout()
    path = OUT / "per_helix_rmsd_bar.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {path}")


def plot_inter_helix_com_drift(all_results: dict) -> None:
    """Bar chart of inter-helix COM drift for 6HB at 10 ps."""
    key = "6hb_42bp__10ps"
    if key not in all_results:
        print("No 6HB 10ps data for COM drift plot.")
        return

    com_drift = all_results[key]["inter_helix_com_drift_nm"]
    if not com_drift:
        print("No COM drift pairs computed.")
        return

    pairs = sorted(com_drift)
    drifts_ang = [com_drift[p] * 10 for p in pairs]

    fig, ax = plt.subplots(figsize=(max(6, len(pairs) * 0.6), 5))
    ax.bar(pairs, drifts_ang, color="darkorange", alpha=0.8)
    ax.axhline(2.0, color="red", linestyle="--", linewidth=0.8, label="2 Å guidance")
    ax.set_xlabel("Helix pair")
    ax.set_ylabel("Inter-helix COM distance drift (Å)")
    ax.set_title("6HB inter-helix COM drift — 10 ps GBNeck2\n"
                 "(implicit-Mg²⁺ caveat: expect ~2–3 Å systematic overestimate)")
    ax.legend()
    ax.grid(axis="y", alpha=0.4)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    fig.tight_layout()

    path = OUT / "inter_helix_com_drift.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {path}")


if __name__ == "__main__":
    print("Exp21 — OpenMM GBNeck2 Verification Baseline")
    print("=" * 60)

    all_results = run_all()
    save_metrics(all_results)
    plot_global_rmsd_timeseries(all_results)
    plot_per_helix_rmsd(all_results)
    plot_inter_helix_com_drift(all_results)

    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    for run_key, data in all_results.items():
        status = "PASS" if data["passed"] else "FAIL"
        print(
            f"  [{status}] {run_key:40s}  "
            f"RMSD={data['global_rmsd_nm']*10:.2f} Å  "
            f"maxDev={data['max_deviation_nm']*10:.2f} Å"
        )
