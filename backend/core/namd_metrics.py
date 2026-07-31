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
# Every Benchmark line also carries the raw step cost, which is what a time-remaining
# estimate actually needs — no timestep lookup, so one less thing to be missing.
_RE_S_PER_STEP = re.compile(r"([\d.]+(?:e[+-]?\d+)?)\s+s/step")


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


def last_namd_timestep_fast(log_path: Path, tail_bytes: int = 131072) -> int | None:
    """Last ENERGY-frame timestep by reading only the TAIL of the log — the cheap path
    for the master progress bar, which needs just this one number.  :func:`parse_namd_log`
    reads and parses the WHOLE log; on the hot job-list poll (~every 1.5 s while a run is
    live) that re-reads a growing, actively-written log each time and was a cause of the
    frontend's slow-request popup during NAMD runs.  ``TS`` is always the first ENERGY
    column in NAMD output, so no ETITLE column map is needed.  Returns ``None`` if no
    complete ENERGY line sits in the tail window (caller falls back to segment fractions)."""
    try:
        size = log_path.stat().st_size
    except OSError:
        return None
    if size <= 0:
        return None
    try:
        with log_path.open("rb") as fh:
            if size > tail_bytes:
                fh.seek(size - tail_bytes)
                fh.readline()  # drop the partial first line after the seek
            chunk = fh.read()
    except OSError:
        return None
    last_ts: int | None = None
    for line in chunk.split(b"\n"):
        if line.startswith(b"ENERGY:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    last_ts = int(parts[1])
                except ValueError:
                    continue
    return last_ts


def last_xsc_step(path: Path, tail_bytes: int = 8192) -> int | None:
    """Last step recorded in a NAMD ``.xst`` / ``.xsc`` file — the first column of its
    final data row — reading only the TAIL.

    ``.restart.xsc`` is three lines; a ``.xst`` box trace grows all run (one row per
    ``xstFreq``), so both are read the same bounded way.  Returns ``None`` when the tail
    holds no complete data row (header only, empty, or unreadable).
    """
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size <= 0:
        return None
    try:
        with path.open("rb") as fh:
            if size > tail_bytes:
                fh.seek(size - tail_bytes)
                fh.readline()  # drop the partial first line after the seek
            chunk = fh.read()
    except OSError:
        return None
    last: int | None = None
    for raw in chunk.split(b"\n"):
        line = raw.strip()
        if not line or line.startswith(b"#"):
            continue
        try:
            last = int(float(line.split()[0]))
        except (ValueError, IndexError):
            continue
    return last


def live_segment_step(package_dir: Path, segment_name: str) -> int | None:
    """Furthest step a RUNNING segment has demonstrably reached, from every cheap on-disk
    marker.  ``None`` when nothing has been written yet.

    The master progress bar used to read ONLY the log's ENERGY frames, and a production
    conf deliberately prints ~400 of those for the WHOLE run
    (``md_protocols._production_output_freqs``, to keep GPU-resident mode from dragging
    energies back off the card).  On a measured 500 ns / 125M-step run that is one frame
    per 312,500 steps ≈ 8 min of wall clock, so the bar read 0 % for a quarter of an hour
    while NAMD was already 585,000 steps in.

    NAMD writes two far finer step markers into the same package, and neither costs
    anything extra: the box trace (``xstFreq`` — 2,500 steps ≈ 4 s on that run) and the
    restart checkpoint (``restartfreq`` — 5,000 steps).  Take whichever marker is
    furthest along, so the bar tracks the finest cadence the conf happens to use.
    """
    output_dir = package_dir / "output"
    candidates = [
        last_namd_timestep_fast(package_dir / f"{segment_name}.log"),
        last_xsc_step(output_dir / f"{segment_name}.xst"),
        last_xsc_step(output_dir / f"{segment_name}.restart.xsc"),
    ]
    steps = [s for s in candidates if s is not None]
    return max(steps) if steps else None


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


def benchmark_ns_per_day(log_path: Path, head_bytes: int = 256 * 1024) -> float | None:
    """Measured throughput (ns/day) from a log's Benchmark lines, reading only its HEAD.

    NAMD emits "Benchmark time:" a handful of times shortly after a ``run`` starts and
    then never again — on a real production log they land within the first ~15 kB of a
    file that grows to gigabytes.  So this is the mirror of
    :func:`last_timestep_from_tail`: the same bounded-read trick, at the other end of
    the file, because :func:`parse_namd_log` would read the whole thing to recover one
    number that is always near the top.

    Same format handling as :func:`parse_namd_log`: older builds print ``days/ns``,
    NAMD 3 prints ``ns/day``; the last line is the most equilibrated.  Returns ``None``
    when the log has no benchmark line yet (a run that has not timed any steps).
    """
    try:
        with log_path.open("rb") as fh:
            chunk = fh.read(head_bytes)
    except OSError:
        return None
    text = chunk.decode("utf-8", errors="replace")
    dpns = _RE_DAYS_PER_NS.findall(text)
    if dpns:
        try:
            d = float(dpns[-1])
            return 1.0 / d if d > 0 else None
        except ValueError:
            return None
    nspd = _RE_NS_PER_DAY.findall(text)
    if nspd:
        try:
            v = float(nspd[-1])
            return v if v > 0 else None
        except ValueError:
            return None
    return None


def benchmark_s_per_step(log_path: Path, head_bytes: int = 256 * 1024) -> float | None:
    """Wall-clock seconds per integration step, from the log's Benchmark lines (HEAD read).

    The same bounded-read trick as :func:`benchmark_ns_per_day` and the same reason to
    prefer the LAST line (most equilibrated).  Read the step cost directly rather than
    deriving it from ns/day + the conf's ``timestep``: it is the number a time-remaining
    estimate needs, and it lands within ~30 s of a run starting — long before the first
    production ENERGY frame (see :func:`live_segment_step`), which is exactly the window
    where "how long will this take?" is being asked.

    ``None`` when the run has not timed any steps yet.
    """
    try:
        with log_path.open("rb") as fh:
            chunk = fh.read(head_bytes)
    except OSError:
        return None
    hits = _RE_S_PER_STEP.findall(chunk.decode("utf-8", errors="replace"))
    if not hits:
        return None
    try:
        v = float(hits[-1])
    except ValueError:
        return None
    return v if v > 0 else None


def eta_seconds(remaining_steps: int, s_per_step: float | None) -> float | None:
    """Seconds of wall clock left for ``remaining_steps`` at the measured step cost (pure).

    ``None`` when the rate is unknown — an absent estimate is honest, a fabricated one is
    not.  Assumes any segments still queued behind the running one integrate at the same
    cost; that holds across a relaxation ladder (one conf shape throughout) and is exact
    for a single-segment production.
    """
    if not s_per_step or s_per_step <= 0:
        return None
    return max(0, int(remaining_steps)) * float(s_per_step)


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
