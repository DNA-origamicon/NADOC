#!/usr/bin/env python3
"""Health gate for the F027 full B_tube production-candidate pipeline.

The checker is intentionally usable outside the runner:

    python f027_health_check.py --package-dir .../B_tube_namd_solvated \
      --segment F027_04_310K_NVT_k1_100ps --name-stem B_tube

It writes one JSON record with NAMD log metrics plus C1'/Watson-Crick structural
metrics, appends that record to output/F027_health.jsonl by default, prints a
compact status line, and exits nonzero when a gate fails.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.md_health import run_health_check  # noqa: E402
from backend.core.namd_metrics import parse_namd_log  # noqa: E402


def _finite_energy_ok(log_path: Path) -> tuple[bool, str]:
    if not log_path.exists():
        return False, f"log not found: {log_path.name}"
    text = log_path.read_text(errors="replace")
    bad_markers = [
        "-99999999999.9999",
        "FATAL ERROR",
        "ERROR:",
        "Atoms moving too fast",
        "Periodic cell has become too small",
    ]
    hits = [marker for marker in bad_markers if marker in text]
    if hits:
        return False, "log markers: " + ", ".join(hits)
    return True, ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--package-dir", type=Path, required=True)
    ap.add_argument("--segment", required=True)
    ap.add_argument("--stage", default="")
    ap.add_argument("--name-stem", default="B_tube")
    ap.add_argument("--min-c1", type=float, default=0.90)
    ap.add_argument("--min-wc", type=float, default=0.85)
    ap.add_argument(
        "--wc-policy",
        choices=("fail", "warn", "off"),
        default="fail",
        help=(
            "How to handle the Watson-Crick ref-relative proxy. F027 uses warn "
            "during staged relaxation because the generated B_tube reference is "
            "not idealized for a strict heavy-atom H-bond cutoff."
        ),
    )
    ap.add_argument("--paired-max-ang", type=float, default=13.0)
    ap.add_argument("--min-temp-k", type=float, default=None)
    ap.add_argument("--max-temp-k", type=float, default=None)
    ap.add_argument("--safe-back", type=int, default=0)
    ap.add_argument("--jsonl", type=Path, default=None)
    ap.add_argument("--summary", type=Path, default=None)
    args = ap.parse_args()

    package_dir = args.package_dir.resolve()
    out_dir = package_dir / "output"
    log_path = package_dir / f"{args.segment}.log"
    jsonl = args.jsonl or (out_dir / "F027_health.jsonl")
    summary = args.summary or (out_dir / "F027_latest_health.json")

    log_ok, log_reason = _finite_energy_ok(log_path)
    metrics = parse_namd_log(log_path)
    effective_min_wc = args.min_wc if args.wc_policy == "fail" else 0.0
    health = run_health_check(
        package_dir,
        args.segment,
        args.name_stem,
        min_c1_paired=args.min_c1,
        min_wc_ref_relative=effective_min_wc,
        paired_max_ang=args.paired_max_ang,
        safe_back=args.safe_back,
    )

    reasons: list[str] = []
    warnings: list[str] = []
    if not log_ok:
        reasons.append(log_reason)
    if not health.passed:
        reasons.append(health.reason or health.error or "structural health failed")
    if (
        args.wc_policy == "warn"
        and health.wc_ref_relative_fraction is not None
        and health.wc_ref_relative_fraction < args.min_wc
    ):
        warnings.append(
            f"WC ref-relative {health.wc_ref_relative_fraction*100:.1f}% "
            f"< warning {args.min_wc*100:.1f}%"
        )
    temp = metrics.temperature_avg_k or metrics.temperature_k
    if temp is not None and args.min_temp_k is not None and temp < args.min_temp_k:
        reasons.append(f"temperature {temp:.2f} K < {args.min_temp_k:.2f} K")
    if temp is not None and args.max_temp_k is not None and temp > args.max_temp_k:
        reasons.append(f"temperature {temp:.2f} K > {args.max_temp_k:.2f} K")

    passed = not reasons
    record = {
        "wall_time": time.time(),
        "segment": args.segment,
        "stage": args.stage or args.segment,
        "passed": passed,
        "reason": "; ".join(reasons),
        "warnings": warnings,
        "wc_policy": args.wc_policy,
        "namd": {
            "timestep": metrics.timestep,
            "temperature_k": metrics.temperature_k,
            "temperature_avg_k": metrics.temperature_avg_k,
            "pressure_bar": metrics.pressure_bar,
            "gpressure_bar": metrics.gpressure_bar,
            "volume_ang3": metrics.volume_ang3,
            "total_energy_kcal": metrics.total_energy_kcal,
            "ns_per_day": metrics.ns_per_day,
            "n_energy_lines": metrics.n_energy_lines,
        },
        "health": {
            "c1_paired_fraction": health.c1_paired_fraction,
            "c1_mean_ang": health.c1_mean_ang,
            "c1_p90_ang": health.c1_p90_ang,
            "c1_max_ang": health.c1_max_ang,
            "wc_absolute_fraction": health.wc_absolute_fraction,
            "wc_ref_relative_fraction": health.wc_ref_relative_fraction,
            "wc_mean_hbond_ang": health.wc_mean_hbond_ang,
            "wc_p90_max_hbond_ang": health.wc_p90_max_hbond_ang,
            "n_c1_pairs": health.n_c1_pairs,
            "n_wc_pairs": health.n_wc_pairs,
            "frame": health.frame,
            "error": health.error,
        },
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    with jsonl.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    summary.write_text(json.dumps(record, indent=2) + "\n")

    c1_pct = (health.c1_paired_fraction or 0.0) * 100.0
    wc_pct = (health.wc_ref_relative_fraction or 0.0) * 100.0
    status = "PASS" if passed else "FAIL"
    print(
        f"{status} {args.segment}: C1'={c1_pct:.2f}% WC={wc_pct:.2f}% "
        f"T={temp if temp is not None else 'n/a'} reason={record['reason']}"
        + (f" warnings={'; '.join(warnings)}" if warnings else "")
    )
    raise SystemExit(0 if passed else 2)


if __name__ == "__main__":
    main()
