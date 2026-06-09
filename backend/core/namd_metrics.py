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

# "Info: Benchmark time: 16 CPUs 0.002345 s/step 0.027123 days/ns 16.00 MB memory"
_RE_BENCHMARK = re.compile(r"(\d+\.\d+(?:e[+-]?\d+)?)\s+days/ns")

# "WallClock: 60.000  CPUTime: 58.000  Memory: 1200.000 MB"  (alternate timing)
# ns/day also appears as: "ns/day:" in some NAMD versions
_RE_NSDAY = re.compile(r"ns/day:\s*([\d.]+(?:e[+-]?\d+)?)")


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

    # ns/day from Benchmark line (present at end of completed run)
    bench = _RE_BENCHMARK.search(text)
    if bench:
        try:
            dpns = float(bench.group(1))
            if dpns > 0:
                m.ns_per_day = 1.0 / dpns
        except ValueError:
            m.warnings.append("Could not parse days/ns from Benchmark line.")
    else:
        nsday = _RE_NSDAY.search(text)
        if nsday:
            try:
                m.ns_per_day = float(nsday.group(1))
            except ValueError:
                pass

    return m


def parse_namd_log_series(log_paths: list[Path]) -> list[NamdLogMetrics]:
    """Parse multiple segment logs in order (for stage timeline display)."""
    return [parse_namd_log(p) for p in log_paths if p.exists()]
