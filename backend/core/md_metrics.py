"""
GROMACS run-directory scanning and metrics extraction.

Quick reads only — no trajectory parsing here (use atomistic_to_nadoc for frames).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class RunDirInfo:
    run_dir:      Path
    input_pdb:    Path          # input_nadoc.pdb
    topology_gro: Path          # em.gro preferred; defines atom order for MDAnalysis
    xtc_path:     Path          # best trajectory found
    log_path:     Path | None   # most recent *.log for metrics


@dataclass
class LogMetrics:
    ns_per_day:    float | None = None
    temperature_k: float | None = None
    dt_ps:         float | None = None
    nstxout_comp:  int   | None = None   # frame output stride in steps
    n_frames:      int   | None = None   # filled by count_frames()
    total_ns:      float | None = None   # derived: n_frames * frame_interval_ps / 1000
    warnings:      list[str] = field(default_factory=list)


# ── Directory scanner ─────────────────────────────────────────────────────────

# XTC preference order — earlier entries win.
_XTC_PRIORITY = [
    "view_whole.xtc",
    "prod.xtc",
]
_XTC_GLOB_ORDER = ["prod_best*.xtc", "prod*.xtc", "npt.xtc", "nvt.xtc", "*.xtc"]


def scan_run_dir(run_dir: Path) -> RunDirInfo:
    """
    Locate the key files in a GROMACS run directory.

    Priority for XTC:
      view_whole.xtc > prod.xtc > prod_best*.xtc > prod*.xtc > npt.xtc > nvt.xtc > *.xtc

    Raises ValueError if required files are missing.
    """
    run_dir = Path(run_dir).resolve()
    if not run_dir.is_dir():
        raise ValueError(f"Not a directory: {run_dir}")

    # input_nadoc.pdb — required for chain map
    input_pdb = run_dir / "input_nadoc.pdb"
    if not input_pdb.exists():
        raise ValueError(
            f"input_nadoc.pdb not found in {run_dir}. "
            "This must be a NADOC-generated GROMACS run directory."
        )

    # topology GRO — prefer em.gro (smallest, always present post-EM)
    topology_gro = run_dir / "em.gro"
    if not topology_gro.exists():
        gros = sorted(run_dir.glob("*.gro"))
        if not gros:
            raise ValueError(f"No .gro files found in {run_dir}")
        topology_gro = gros[0]

    # XTC — pick best available
    xtc_path: Path | None = None
    for name in _XTC_PRIORITY:
        candidate = run_dir / name
        if candidate.exists():
            xtc_path = candidate
            break
    if xtc_path is None:
        for pattern in _XTC_GLOB_ORDER:
            candidates = sorted(run_dir.glob(pattern))
            if candidates:
                # For multi-part trajectories pick the last part
                xtc_path = candidates[-1]
                break
    if xtc_path is None:
        raise ValueError(f"No .xtc trajectory found in {run_dir}")

    # Log — prefer logs that contain the full MDP echo (dt = line) because
    # continuation/restart logs omit the MDP header.  Preferred canonical names
    # are tried first; fallback is most-recently-modified.
    _LOG_MDP_PRIORITY = ["prod.log", "nvt.log", "npt.log", "em.log"]
    log_path: Path | None = None
    for name in _LOG_MDP_PRIORITY:
        candidate = run_dir / name
        if candidate.exists():
            log_path = candidate
            break
    if log_path is None:
        all_logs = sorted(run_dir.glob("*.log"), key=lambda p: p.stat().st_mtime)
        log_path = all_logs[-1] if all_logs else None

    return RunDirInfo(
        run_dir      = run_dir,
        input_pdb    = input_pdb,
        topology_gro = topology_gro,
        xtc_path     = xtc_path,
        log_path     = log_path,
    )


# ── Log parser ────────────────────────────────────────────────────────────────

# Performance section: "Performance:       44.841        0.535"
_RE_PERF = re.compile(r"^Performance:\s+([\d.]+)\s+[\d.]+", re.MULTILINE)

# Temperature extraction from GROMACS energy blocks.
# The header/value layout varies by forcefield; two common patterns:
#
# Pattern A (single-header):
#   "   Potential   Kinetic En.   Total Energy   Temperature   Pressure (bar)"
#   "  -4.44e+06    6.45e+05    -3.79e+06        3.10e+02     -8.81e+03"
#
# Pattern B (split two-line header — e.g. CHARMM36 vacuum):
#   "   Coulomb-14   LJ (SR)   ...   Potential"
#   "   Kinetic En.   Total Energy   Temperature   Pressure (bar)   Constr. rmsd"
#   "   6.47e+05    -3.34e+06       3.11e+02       -1.87e+00        3.98e-06"
#
# Both patterns end with a line that has "Temperature" followed by a values line
# where Temperature is the 3rd column (0-based index 2).
_RE_TEMP_HEADER = re.compile(
    r"Kinetic En\.\s+Total Energy\s+Temperature\s+Pressure.*\n"
    r"\s*([-\d.e+]+)\s+([-\d.e+]+)\s+([-\d.e+]+)"
)

# MDP settings echoed at the top of every log
_RE_DT   = re.compile(r"^\s*dt\s*=\s*([\d.e+\-]+)", re.MULTILINE)
_RE_NSTXOUT_COMP = re.compile(r"^\s*nstxout-compressed\s*=\s*(\d+)", re.MULTILINE)


def parse_log_metrics(log_path: Path) -> LogMetrics:
    """
    Extract ns/day, temperature, dt, and nstxout-compressed from a GROMACS .log file.

    Reads the whole file once (logs are typically < 5 MB for short runs).
    For very long runs the file can be large; we read only the tail for Performance.
    """
    m = LogMetrics()

    try:
        text = log_path.read_text(errors="replace")
    except OSError as e:
        m.warnings.append(f"Cannot read log {log_path.name}: {e}")
        return m

    # ns/day — search from end (Performance section is at EOF)
    perf_matches = _RE_PERF.findall(text)
    if perf_matches:
        try:
            m.ns_per_day = float(perf_matches[-1])
        except ValueError:
            m.warnings.append("Could not parse ns/day from Performance section.")

    # Temperature — use the last energy block found.
    # Regex captures (Kinetic En., Total Energy, Temperature) → index 2.
    temp_matches = _RE_TEMP_HEADER.findall(text)
    if temp_matches:
        try:
            m.temperature_k = float(temp_matches[-1][2])
        except (IndexError, ValueError):
            m.warnings.append("Could not parse Temperature from energy block.")

    # dt
    dt_m = _RE_DT.search(text)
    if dt_m:
        try:
            m.dt_ps = float(dt_m.group(1))
        except ValueError:
            m.warnings.append("Could not parse dt.")

    # nstxout-compressed
    nst_m = _RE_NSTXOUT_COMP.search(text)
    if nst_m:
        try:
            m.nstxout_comp = int(nst_m.group(1))
        except ValueError:
            m.warnings.append("Could not parse nstxout-compressed.")

    return m


# ── Frame counter ─────────────────────────────────────────────────────────────


def count_frames(xtc_path: Path, topology_gro: Path) -> int:
    """
    Count the number of frames in an XTC trajectory using MDAnalysis.

    Falls back to 0 on import error (MDAnalysis not installed).
    """
    try:
        import MDAnalysis as mda
        u = mda.Universe(str(topology_gro), str(xtc_path))
        return len(u.trajectory)
    except ImportError:
        return 0
    except Exception:
        return 0


def derive_total_ns(metrics: LogMetrics, n_frames: int) -> float | None:
    """
    Compute total simulation time in ns: n_frames × frame_interval_ps / 1000.

    frame_interval_ps = nstxout_comp × dt_ps
    """
    if metrics.dt_ps is None or metrics.nstxout_comp is None or n_frames == 0:
        return None
    frame_interval_ps = metrics.nstxout_comp * metrics.dt_ps
    return n_frames * frame_interval_ps / 1000.0
