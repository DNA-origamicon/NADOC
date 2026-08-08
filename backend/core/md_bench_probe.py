"""md_bench_probe.py — measure this machine instead of consulting a table.

WHY THIS EXISTS.  Every throughput decision in the MD stack used to come from constants
measured once, on one machine, on one design:

    md_optimize.K_GPU_RESIDENT / K_OFFLOAD   6hbx100_90deg on an RTX 2080 Super
    md_optimize._SMALL_SYSTEM_RESIDENT_PENALTY = 0.89   RTX 3080 Ti, +p16
    md_protocols._RESIDENT_MIN_ATOMS = 100_000          same source

exp52 (2026-08-05) measured the same question on THIS box — RTX 2080 SUPER, +p8, the
patched 3.0.2p1 build — and got the opposite answer: GPU-resident is 1.86-2.06x FASTER at
32,754 atoms, where the table predicts a 0.89x LOSS.  Neither measurement is wrong; the
constant is simply not portable, and it was being applied as if it were.

So: run the two-step probe, on this machine, and use the number that comes back.  A
measurement takes tens of seconds and is cached per (machine, build, system size); a wrong
constant costs 2x on every run forever.

This module NEVER changes a setting on its own.  It returns numbers.  What to do with them
is the caller's decision, and — per the wizard's contract — the user's.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

#: Long enough for NAMD's own Benchmark line to stabilise (it reports after the first few
#: cycles), short enough that probing is cheap.  Must be a multiple of stepspercycle.
PROBE_STEPS = 600

#: Where measurements live, so a machine is probed once per system size rather than once
#: per wizard click.
CACHE_NAME = "md_bench_cache.json"

#: Atom counts within this ratio of each other reuse the same measurement — throughput is
#: dominated by atom count, and re-probing for a 3% size change is waste.
_SIZE_BUCKET = 1.35


@dataclass(frozen=True)
class ProbeResult:
    """One measured configuration."""

    label: str
    gpu_resident: bool
    threads: int
    ms_per_step: Optional[float]
    ns_per_day: Optional[float]
    ok: bool
    error: Optional[str] = None


def _parse_benchmark(text: str) -> tuple[Optional[float], Optional[float]]:
    """(ms/step, ns/day) from NAMD's own Benchmark line — its number, not ours."""
    hits = re.findall(
        r"Benchmark time:.*?([\d.eE+-]+) s/step\s+([\d.eE+-]+) (ns/day|days/ns)", text
    )
    if not hits:
        return None, None
    s_step, val, unit = float(hits[-1][0]), float(hits[-1][1]), hits[-1][2]
    ns_day = val if unit == "ns/day" else (1.0 / val if val else None)
    return s_step * 1000.0, ns_day


def _first_error(text: str) -> Optional[str]:
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(("ERROR:", "FATAL ERROR")):
            return s
    return None


def run_probe(
    package_dir: Path,
    conf_name: str,
    *,
    namd_bin: str,
    threads: int,
    devices: str = "0",
    timeout_s: float = 600.0,
) -> tuple[str, int]:
    """Run one conf; return (log text, returncode).  No interpretation here."""
    cmd = [namd_bin, f"+p{threads}", "+setcpuaffinity"]
    if devices and devices.strip().lower() not in ("cpu", "none"):
        cmd += ["+devices", devices]
    cmd.append(conf_name)
    log = package_dir / f"{Path(conf_name).stem}.log"
    with log.open("w") as fh:
        proc = subprocess.run(
            cmd,
            cwd=package_dir,
            stdout=fh,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=timeout_s,
        )
    return log.read_text(errors="ignore"), proc.returncode


def probe_gpu_resident(
    package_dir: Path,
    name_stem: str,
    *,
    namd_bin: str,
    start_checkpoint: Optional[str] = None,
    threads: int = 8,
    devices: str = "0",
    steps: int = PROBE_STEPS,
) -> list[ProbeResult]:
    """Measure GPUresident on vs off on an ALREADY SOLVATED package.

    Two confs identical but for one line, run back to back on the same starting
    coordinates — the design exp52 used, because anything else compares two systems rather
    than two settings.  Returns both results even when one fails: "it refused to run" is
    itself the answer for a combination the caller was considering.
    """
    from backend.core.md_protocols import _common_header  # noqa: PLC0415

    box = _box_from_manifest(package_dir)
    out: list[ProbeResult] = []
    for resident in (False, True):
        label = f"resident_{'on' if resident else 'off'}"
        conf = f"bench_probe_{label}.conf"
        header = _common_header(
            name_stem,
            box,
            (package_dir / "mgh_extrabonds.txt").exists(),
            rigid_bonds="all",
            timestep=2.0,
            gpu_resident=resident,
        )
        start = (
            (
                f"binCoordinates     output/{start_checkpoint}.coor\n"
                f"extendedSystem     output/{start_checkpoint}.xsc\n"
                f"temperature        300\n"
            )
            if start_checkpoint
            else "temperature        300\n"
        )
        (package_dir / conf).write_text(
            header
            + f"outputName         output/bench_probe_{label}\n"
            + "dcdFreq            0\n"
            + "outputEnergies     600\n"
            + "restartfreq        0\n"
            + "langevin           on\nlangevinTemp       300\n"
            + "langevinDamping    1\nlangevinHydrogen   off\n"
            + start
            + f"run                {steps}\n"
        )
        try:
            text, rc = run_probe(
                package_dir, conf, namd_bin=namd_bin, threads=threads, devices=devices
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            out.append(
                ProbeResult(label, resident, threads, None, None, False, str(exc))
            )
            continue
        err = _first_error(text)
        ms, ns = _parse_benchmark(text)
        out.append(
            ProbeResult(
                label,
                resident,
                threads,
                ms,
                ns,
                ok=(rc == 0 and err is None and ms is not None),
                error=err,
            )
        )
    return out


def _box_from_manifest(package_dir: Path) -> tuple[float, float, float]:
    manifest = json.loads((package_dir / "manifest.json").read_text())
    return tuple(float(x) for x in manifest["box_ang"])  # type: ignore[return-value]


# ── Cache ───────────────────────────────────────────────────────────────────────
def machine_key(gpu_name: Optional[str], namd_bin: str, threads: int) -> str:
    """What makes a measurement transferable: the card, the build, the thread count.

    All three moved between the historical measurement and exp52, and all three can move
    the answer — which is exactly why one constant could not serve every machine.
    """
    return f"{gpu_name or 'cpu'}|{Path(namd_bin).parent.name}|p{threads}"


def cache_path(workspace: Path) -> Path:
    return Path(workspace) / CACHE_NAME


def load_measurement(workspace: Path, key: str, n_atoms: int) -> Optional[dict]:
    """A previous measurement for this machine at a comparable system size, or None."""
    p = cache_path(workspace)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    best = None
    for entry in data.get(key, []):
        n = entry.get("n_atoms") or 0
        if not n:
            continue
        ratio = max(n, n_atoms) / max(1, min(n, n_atoms))
        if ratio <= _SIZE_BUCKET and (best is None or ratio < best[0]):
            best = (ratio, entry)
    return best[1] if best else None


def save_measurement(
    workspace: Path,
    key: str,
    n_atoms: int,
    results: list[ProbeResult],
    *,
    design_stem: str = "",
) -> dict:
    """Record a measurement.  Append-only per machine key; never overwrites history."""
    p = cache_path(workspace)
    try:
        data = json.loads(p.read_text()) if p.exists() else {}
    except (OSError, ValueError):
        data = {}
    entry = {
        "n_atoms": int(n_atoms),
        "design": design_stem,
        "measured_at": time.time(),
        "results": [asdict(r) for r in results],
        "resident_speedup": _speedup(results),
    }
    data.setdefault(key, []).append(entry)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2))
    except OSError as exc:  # noqa: BLE001
        logger.warning("could not write %s: %s", p, exc)
    return entry


def _speedup(results: list[ProbeResult]) -> Optional[float]:
    on = next((r for r in results if r.gpu_resident and r.ok and r.ns_per_day), None)
    off = next(
        (r for r in results if not r.gpu_resident and r.ok and r.ns_per_day), None
    )
    if not on or not off or not off.ns_per_day:
        return None
    return round(on.ns_per_day / off.ns_per_day, 3)


def resident_verdict(entry: Optional[dict]) -> dict:
    """Turn a measurement into something a user can read, WITHOUT deciding for them.

    Returns ``{"measured": bool, "faster": "on"|"off"|None, "speedup": float|None,
    "detail": str}``.  Callers surface this; nothing here writes a setting.
    """
    if not entry:
        return {
            "measured": False,
            "faster": None,
            "speedup": None,
            "detail": (
                "Not measured on this machine yet — the built-in crossover is an "
                "estimate from other hardware and has been wrong by 2x here."
            ),
        }
    sp = entry.get("resident_speedup")
    if not sp:
        return {
            "measured": True,
            "faster": None,
            "speedup": None,
            "detail": "Measured, but one of the two runs did not report a benchmark.",
        }
    faster = "on" if sp > 1.0 else "off"
    return {
        "measured": True,
        "faster": faster,
        "speedup": sp,
        "detail": (
            f"Measured on this machine at {entry.get('n_atoms', 0):,} atoms: "
            f"GPU-resident is {sp:.2f}x "
            f"{'faster' if sp > 1 else 'slower'} than CUDA offload."
        ),
    }
