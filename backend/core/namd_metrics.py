"""
NAMD log parser — temperature, pressure, volume, ns/day.

Reads ETITLE/ENERGY line pairs to extract scalar metrics.
Reads "Benchmark time" lines for ns/day performance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class NamdLogMetrics:
    ns_per_day:       float | None = None
    temperature_k:    float | None = None
    temperature_avg_k: float | None = None
    pressure_bar:     float | None = None
    gpressure_bar:    float | None = None
    pressure_avg_bar: float | None = None
    gpressure_avg_bar: float | None = None
    volume_ang3:      float | None = None
    total_energy_kcal: float | None = None
    kinetic_kcal:     float | None = None
    n_energy_lines:   int          = 0
    timestep:         int   | None = None   # last TS value
    warnings:         list[str]    = field(default_factory=list)


# ── Regexes ───────────────────────────────────────────────────────────────────

# NAMD reports throughput on "Benchmark time:" lines in one of two historical formats:
#   older builds:  "... 0.002345 s/step 0.027123 days/ns 16.00 MB"   (value = days/ns)
#   NAMD 3 (esp. GPU-resident):  "... 0.0117889 s/step 29.3158 ns/day 0 MB"  (value = ns/day)
# Each interval prints one line; the LAST is the most equilibrated, so we take findall[-1].
_RE_DAYS_PER_NS = re.compile(r"([\d.]+(?:e[+-]?\d+)?)\s+days/ns")
_RE_NS_PER_DAY = re.compile(r"([\d.]+(?:e[+-]?\d+)?)\s+ns/day")


# ── Parser ────────────────────────────────────────────────────────────────────

def parse_namd_log(log_path: Path) -> NamdLogMetrics:
    """
    Extract scalar metrics from the last ENERGY frame and the Benchmark line.

    Safe to call on a log that is still being written — reads the file once
    as plain text without acquiring any lock.
    """
    m = NamdLogMetrics()

    try:
        text = log_path.read_text(errors="replace")
    except OSError as exc:
        m.warnings.append(f"Cannot read log {log_path.name}: {exc}")
        return m

    # Build column-index map from the most recent ETITLE line.
    # ETITLE is re-emitted when NAMD restarts from a checkpoint, so take last.
    col_idx: dict[str, int] = {}
    energy_rows: list[list[float]] = []

    for line in text.splitlines():
        if line.startswith("ETITLE:"):
            fields = line.split()
            # fields[0] = "ETITLE:", fields[1..] = column names; data index = name index - 1
            col_idx = {name: i - 1 for i, name in enumerate(fields) if i >= 1}
        elif line.startswith("ENERGY:"):
            vals = line.split()[1:]   # strip "ENERGY:" token
            try:
                energy_rows.append([float(v) for v in vals])
            except ValueError:
                continue

    if energy_rows and col_idx:
        last = energy_rows[-1]
        m.n_energy_lines = len(energy_rows)

        def _get(name: str) -> float | None:
            idx = col_idx.get(name)
            if idx is not None and 0 <= idx < len(last):
                return last[idx]
            return None

        m.timestep         = int(last[col_idx["TS"]]) if "TS" in col_idx and col_idx["TS"] < len(last) else None
        m.temperature_k    = _get("TEMP")
        m.temperature_avg_k = _get("TEMPAVG")
        m.pressure_bar     = _get("PRESSURE")
        m.gpressure_bar    = _get("GPRESSURE")
        m.pressure_avg_bar = _get("PRESSAVG")
        m.gpressure_avg_bar = _get("GPRESSAVG")
        m.volume_ang3      = _get("VOLUME")
        m.total_energy_kcal = _get("TOTAL")
        m.kinetic_kcal     = _get("KINETIC")

    # ns/day from the Benchmark lines (present once a run has timed steps).  Prefer the
    # last "days/ns" value (old format); else the last "ns/day" value (NAMD 3 format).
    dpns = _RE_DAYS_PER_NS.findall(text)
    nspd = _RE_NS_PER_DAY.findall(text)
    if dpns:
        try:
            d = float(dpns[-1])
            if d > 0:
                m.ns_per_day = 1.0 / d
        except ValueError:
            m.warnings.append("Could not parse days/ns from Benchmark line.")
    elif nspd:
        try:
            m.ns_per_day = float(nspd[-1])
        except ValueError:
            m.warnings.append("Could not parse ns/day from Benchmark line.")

    return m


def overall_fraction(
    done: int,
    total: int,
    running_timestep: int | None = None,
    running_steps: int | None = None,
) -> float:
    """Fraction 0..1 of a NAMD job's total work done, for the master progress bar.

    ``done`` completed segments plus the running segment's within-fraction
    (``running_timestep / running_steps``, when a live log gives the step count).
    Mirrors oxDNA's ``job_overall_fraction`` so a SINGLE-segment production child
    advances smoothly instead of reading 0 % until its one segment flips to done.
    Pure — the caller supplies the running step count from the live log.
    """
    if total <= 0:
        return 0.0
    frac = float(done)
    if running_timestep and running_steps:
        frac += min(1.0, max(0.0, float(running_timestep) / float(running_steps)))
    return min(1.0, frac / total)


def parse_namd_log_series(log_paths: list[Path]) -> list[NamdLogMetrics]:
    """Parse multiple segment logs in order (for stage timeline display)."""
    return [parse_namd_log(p) for p in log_paths if p.exists()]


def parse_namd_log_frames(log_path: Path) -> list[dict[str, float]]:
    """Return EVERY ENERGY frame as a {column_name: value} dict (name-indexed).

    Unlike parse_namd_log (which keeps only the last frame's scalars), this yields
    the full per-frame series used by relaxation-cutoff plateau detection. Columns
    are resolved from the most recent ETITLE, so NVT (no VOLUME) and NPT logs both
    parse. Restart-replayed duplicate frames at a resume seam (TS <= previous) are
    dropped so the series is monotone in TS.
    """
    try:
        text = log_path.read_text(errors="replace")
    except OSError:
        return []
    cols: list[str] = []
    out: list[dict[str, float]] = []
    last_ts: float | None = None
    for line in text.splitlines():
        if line.startswith("ETITLE:"):
            cols = line.split()[1:]
        elif line.startswith("ENERGY:") and cols:
            vals = line.split()[1:]
            if len(vals) < len(cols):
                continue
            row: dict[str, float] = {}
            for name, v in zip(cols, vals):
                try:
                    row[name] = float(v)
                except ValueError:
                    pass
            ts = row.get("TS")
            if last_ts is not None and ts is not None and ts <= last_ts:
                continue
            last_ts = ts
            out.append(row)
    return out
