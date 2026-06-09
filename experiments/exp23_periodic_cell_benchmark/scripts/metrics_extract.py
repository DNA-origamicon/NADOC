"""
metrics_extract.py — Extract standardised health metrics from a NAMD run.

Reads a NAMD .log file (and optionally an .xst file) and writes a JSON sidecar
with temperature, energy, pressure, volume, Z-cell, timing, and error flags.
Called by run_hypothesis.py but also usable standalone.

Usage
-----
    python scripts/metrics_extract.py \\
        --log results/foo.log \\
        --xst results/foo.xst \\   # optional
        --id H001 \\
        --out metrics/H001_metrics.json

Output JSON schema
------------------
{
  "hypothesis_id":  str,
  "log_file":       str,
  "n_energy_frames": int,
  "temperature":    {"mean": float, "std": float, "min": float, "max": float},
  "total_energy":   {"mean": float, "std": float, "last": float},
  "potential":      {"mean": float, "std": float, "last": float},
  "pressure":       {"mean": float, "std": float},
  "volume_angstrom3": {"first": float, "last": float, "drift_pct": float},
  "z_cell_angstrom":  {"mean": float, "std": float, "min": float, "max": float},
                       # only if --xst provided
  "wall_time_s":    float,   # from last TIMING line
  "ns_per_day":     float,   # computed from TIMING if present
  "timestep_fs":    float,
  "bp_fraction_final": float | null,  # from base_pairing JSON sidecar if present
  "fatal_errors":   [str],
  "warnings":       [str]
}
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
from pathlib import Path

# ── Column indices in NAMD ENERGY lines ──────────────────────────────────────
# line.split() layout:
#  [0]ENERGY: [1]TS [2]BOND [3]ANGLE [4]DIHED [5]IMPRP [6]ELECT [7]VDW
#  [8]BOUNDARY [9]MISC [10]KINETIC [11]TOTAL [12]TEMP [13]POTENTIAL
#  [14]TOTAL3 [15]TEMPAVG [16]PRESSURE [17]GPRESSURE [18]VOLUME
#  [19]PRESSAVG [20]GPRESSAVG
_COL_TEMP      = 12
_COL_TOTAL     = 11
_COL_POTENTIAL = 13
_COL_PRESSURE  = 16   # instantaneous group pressure
_COL_VOLUME    = 18

# XST column indices (0-based after step column)
# step a_x a_y a_z b_x b_y b_z c_x c_y c_z ...
_XST_AX = 1   # Lx
_XST_BY = 5   # Ly
_XST_CZ = 9   # Lz


def _parse_energy_lines(log_path: Path) -> dict:
    """Return lists of per-frame values parsed from ENERGY: lines."""
    temps, totals, potentials, pressures, volumes = [], [], [], [], []
    with open(log_path) as fh:
        for line in fh:
            if not line.startswith("ENERGY:"):
                continue
            parts = line.split()
            try:
                temps.append(float(parts[_COL_TEMP]))
                totals.append(float(parts[_COL_TOTAL]))
                potentials.append(float(parts[_COL_POTENTIAL]))
                pressures.append(float(parts[_COL_PRESSURE]))
                volumes.append(float(parts[_COL_VOLUME]))
            except (IndexError, ValueError):
                continue
    return dict(temp=temps, total=totals, potential=potentials,
                pressure=pressures, volume=volumes)


def _parse_timing(log_path: Path, timestep_fs: float) -> tuple[float, float]:
    """Return (wall_time_s, ns_per_day) from last TIMING line."""
    wall_s = math.nan
    steps = 0
    with open(log_path) as fh:
        for line in fh:
            if not line.startswith("TIMING:"):
                continue
            # TIMING: 250000  CPU: ..., Wall: 361.9, ...
            m = re.search(r"Wall:\s*([\d.]+)", line)
            if m:
                wall_s = float(m.group(1))
            m2 = re.match(r"TIMING:\s+(\d+)", line)
            if m2:
                steps = int(m2.group(1))
    if wall_s and steps and not math.isnan(wall_s):
        total_ns = steps * timestep_fs * 1e-6
        ns_per_day = total_ns / (wall_s / 86400)
    else:
        ns_per_day = math.nan
    return wall_s, ns_per_day


def _parse_xst(xst_path: Path) -> dict:
    """Return Z-cell stats from XST file. Ignores comment lines."""
    zvals = []
    with open(xst_path) as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) > _XST_CZ:
                try:
                    zvals.append(float(parts[_XST_CZ]))
                except ValueError:
                    continue
    if not zvals:
        return {}
    return dict(mean=statistics.mean(zvals),
                std=statistics.stdev(zvals) if len(zvals) > 1 else 0.0,
                min=min(zvals), max=max(zvals))


def _scan_errors(log_path: Path) -> tuple[list[str], list[str]]:
    """Return (fatal_errors, warnings) from NAMD log."""
    fatals, warns = [], []
    sentinel_re = re.compile(r"-9{7,}")
    with open(log_path) as fh:
        for line in fh:
            if "FATAL ERROR" in line:
                fatals.append(line.strip())
            elif "Atoms moving too fast" in line:
                fatals.append(line.strip())
            elif sentinel_re.search(line):
                fatals.append("Sentinel energy detected: " + line.strip()[:120])
            elif "Low global CUDA exclusion count" in line:
                if "System is unstable" in line or "FATAL" in line:
                    fatals.append(line.strip())
                else:
                    warns.append("minimization_low_cuda_exclusion")
            elif "Warning:" in line or "WARNING:" in line:
                warns.append(line.strip()[:120])
    # Deduplicate warnings while preserving order
    seen: set[str] = set()
    uniq_warns = []
    for w in warns:
        if w not in seen:
            seen.add(w)
            uniq_warns.append(w)
    return fatals, uniq_warns[:20]  # cap warnings at 20


def _load_bp_fraction(log_path: Path, hyp_id: str) -> float | None:
    """
    Look for a base_pairing JSON sidecar next to the log, or in the metrics dir.
    Returns final bp_fraction_final if found, else None.
    """
    # log is at results/hyp_runs/HXXX/HXXX.log → exp root is 4 parents up
    exp_root = log_path.parent.parent.parent.parent
    candidates = [
        log_path.with_suffix(".bp.json"),
        log_path.parent / f"{hyp_id}_bp.json",
        exp_root / "metrics" / f"{hyp_id}_bp.json",
    ]
    for c in candidates:
        if c.exists():
            try:
                data = json.loads(c.read_text())
                return float(data.get("bp_fraction_final", data.get("final_fraction")))
            except Exception:
                pass
    return None


def extract(log_path: Path, hyp_id: str, xst_path: Path | None,
            timestep_fs: float) -> dict:
    """Return the full metrics dict for one NAMD run."""
    energy = _parse_energy_lines(log_path)
    wall_s, ns_per_day = _parse_timing(log_path, timestep_fs)
    fatals, warns = _scan_errors(log_path)
    bp = _load_bp_fraction(log_path, hyp_id)

    def _stats(vals: list[float]) -> dict:
        if not vals:
            return dict(mean=math.nan, std=math.nan)
        return dict(mean=statistics.mean(vals),
                    std=statistics.stdev(vals) if len(vals) > 1 else 0.0)

    temps = energy["temp"]
    result: dict = dict(
        hypothesis_id=hyp_id,
        log_file=str(log_path),
        n_energy_frames=len(temps),
        temperature=dict(
            mean=statistics.mean(temps) if temps else math.nan,
            std=statistics.stdev(temps) if len(temps) > 1 else 0.0,
            min=min(temps) if temps else math.nan,
            max=max(temps) if temps else math.nan,
        ),
        total_energy={**_stats(energy["total"]),
                      "last": energy["total"][-1] if energy["total"] else math.nan},
        potential={**_stats(energy["potential"]),
                   "last": energy["potential"][-1] if energy["potential"] else math.nan},
        pressure=_stats(energy["pressure"]),
        volume_angstrom3=dict(
            first=energy["volume"][0] if energy["volume"] else math.nan,
            last=energy["volume"][-1] if energy["volume"] else math.nan,
            drift_pct=(abs(energy["volume"][-1] - energy["volume"][0])
                       / energy["volume"][0] * 100)
            if len(energy["volume"]) > 1 else 0.0,
        ),
        timestep_fs=timestep_fs,
        wall_time_s=wall_s,
        ns_per_day=ns_per_day,
        bp_fraction_final=bp,
        fatal_errors=fatals,
        warnings=warns,
    )

    if xst_path and xst_path.exists():
        result["z_cell_angstrom"] = _parse_xst(xst_path)

    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--log", required=True, type=Path, help="NAMD .log file")
    ap.add_argument("--xst", type=Path, default=None, help="NAMD .xst file (optional)")
    ap.add_argument("--id", dest="hyp_id", default="unknown",
                    help="Hypothesis ID, e.g. H001")
    ap.add_argument("--out", type=Path, default=None,
                    help="Output JSON path (default: <log>.metrics.json)")
    ap.add_argument("--timestep", type=float, default=2.0,
                    help="Timestep in fs (default 2.0)")
    ap.add_argument("--print", action="store_true", dest="do_print",
                    help="Also print JSON to stdout")
    args = ap.parse_args()

    if not args.log.exists():
        print(f"ERROR: log file not found: {args.log}", file=sys.stderr)
        sys.exit(1)

    result = extract(args.log, args.hyp_id, args.xst, args.timestep)

    out_path = args.out or args.log.with_suffix(".metrics.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, default=str))
    print(f"Metrics written to {out_path}")

    if args.do_print:
        print(json.dumps(result, indent=2, default=str))

    if result["fatal_errors"]:
        print(f"\nFATAL ERRORS ({len(result['fatal_errors'])}):", file=sys.stderr)
        for e in result["fatal_errors"]:
            print(f"  {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
