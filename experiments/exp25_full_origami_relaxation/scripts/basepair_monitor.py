"""Live C1' base-pair monitor for full-origami NAMD runs.

The monitor identifies C1'...C1' partners from the reference PDB/PSF, then polls
a growing DCD and reports the latest safe frame.  When launched with
``--namd-cmd`` it owns the NAMD process and terminates it if the paired fraction
falls below ``--min-paired`` after ``--grace-frames`` analysed frames.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree


SEARCH_LO_ANG = 8.5
SEARCH_HI_ANG = 13.0
DEFAULT_PAIRED_MAX_ANG = 12.0


def _c1p(u):
    sel = u.select_atoms("name C1'")
    if not len(sel):
        sel = u.select_atoms("name C1X")
    if not len(sel):
        raise RuntimeError("No C1' atoms found.")
    return sel


def build_pairs(psf: Path, pdb: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    import MDAnalysis as mda

    u = mda.Universe(str(psf), str(pdb))
    c1 = _c1p(u)
    pos = c1.positions
    segids = c1.atoms.segids
    tree = cKDTree(pos)
    used = np.zeros(len(pos), dtype=bool)
    pi: list[int] = []
    pj: list[int] = []

    for i in range(len(pos)):
        if used[i]:
            continue
        cands = []
        for j in tree.query_ball_point(pos[i], SEARCH_HI_ANG):
            if j <= i or used[j] or segids[j] == segids[i]:
                continue
            d = float(np.linalg.norm(pos[i] - pos[j]))
            if d >= SEARCH_LO_ANG:
                cands.append((d, j))
        if cands:
            _, j = min(cands)
            used[i] = used[j] = True
            pi.append(i)
            pj.append(j)

    if not pi:
        raise RuntimeError("No base pairs identified.")
    pi_arr = np.asarray(pi, dtype=int)
    pj_arr = np.asarray(pj, dtype=int)
    d0 = np.linalg.norm(pos[pi_arr] - pos[pj_arr], axis=1)
    return pi_arr, pj_arr, d0


def latest_metrics(
    psf: Path,
    dcd: Path,
    pairs: tuple[np.ndarray, np.ndarray, np.ndarray],
    safe_back: int,
    paired_max_ang: float,
) -> dict | None:
    if not dcd.exists() or dcd.stat().st_size == 0:
        return None

    import MDAnalysis as mda

    try:
        u = mda.Universe(str(psf), str(dcd))
        n_frames = len(u.trajectory)
        if n_frames <= safe_back:
            return None
        frame = n_frames - 1 - safe_back
        u.trajectory[frame]
        c1 = _c1p(u)
        i, j, _ = pairs
        diff = c1.positions[i] - c1.positions[j]
        box = u.trajectory.ts.dimensions
        if box is not None and len(box) >= 3:
            L = box[:3]
            diff -= L * np.round(diff / L)
        d = np.sqrt((diff * diff).sum(axis=1))
        frac = float((d < paired_max_ang).mean())
        return {
            "frame": int(frame),
            "n_frames": int(n_frames),
            "n_pairs": int(len(i)),
            "paired_fraction": frac,
            "paired_percent": frac * 100.0,
            "mean_c1_ang": float(d.mean()),
            "p90_c1_ang": float(np.percentile(d, 90)),
            "max_c1_ang": float(d.max()),
        }
    except Exception as exc:
        return {"error": str(exc)}


def _terminate(proc: subprocess.Popen, timeout_s: float = 15.0) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.25)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--psf", type=Path, required=True)
    ap.add_argument("--pdb", type=Path, required=True)
    ap.add_argument("--dcd", type=Path, required=True)
    ap.add_argument("--out-jsonl", type=Path, required=True)
    ap.add_argument("--min-paired", type=float, default=0.95)
    ap.add_argument("--paired-max-ang", type=float, default=DEFAULT_PAIRED_MAX_ANG)
    ap.add_argument("--poll-seconds", type=float, default=20.0)
    ap.add_argument("--safe-back", type=int, default=2)
    ap.add_argument("--grace-frames", type=int, default=3)
    ap.add_argument("--namd-cmd", nargs=argparse.REMAINDER)
    args = ap.parse_args()

    pairs = build_pairs(args.psf, args.pdb)
    baseline = float((pairs[2] < args.paired_max_ang).mean())
    args.out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    print(
        f"Identified {len(pairs[0])} C1' base pairs; "
        f"paired_max={args.paired_max_ang:.2f} Å; "
        f"baseline={baseline*100:.2f}%; trip<{args.min_paired*100:.2f}%"
    )
    if args.min_paired > baseline:
        print(
            "WARNING: min-paired is above the reference baseline; "
            "the monitor may trip immediately.",
            flush=True,
        )

    proc: subprocess.Popen | None = None
    if args.namd_cmd:
        proc = subprocess.Popen(args.namd_cmd, preexec_fn=os.setsid)
        print(f"Started NAMD pid={proc.pid}")

    seen_frame = -1
    analysed = 0
    tripped = False

    try:
        while True:
            metrics = latest_metrics(args.psf, args.dcd, pairs, args.safe_back, args.paired_max_ang)
            if metrics and "error" not in metrics and metrics["frame"] > seen_frame:
                seen_frame = metrics["frame"]
                analysed += 1
                metrics["wall_time"] = time.time()
                with args.out_jsonl.open("a") as fh:
                    fh.write(json.dumps(metrics) + "\n")
                print(
                    f"frame={metrics['frame']} paired={metrics['paired_percent']:.2f}% "
                    f"mean={metrics['mean_c1_ang']:.2f}Å p90={metrics['p90_c1_ang']:.2f}Å",
                    flush=True,
                )
                if analysed >= args.grace_frames and metrics["paired_fraction"] < args.min_paired:
                    print(
                        f"TRIP: paired fraction {metrics['paired_fraction']:.4f} "
                        f"< {args.min_paired:.4f}",
                        flush=True,
                    )
                    tripped = True
                    if proc is not None:
                        _terminate(proc)
                    break
            elif metrics and "error" in metrics:
                print(f"monitor read skipped: {metrics['error']}", flush=True)

            if proc is not None and proc.poll() is not None:
                break
            if proc is None and metrics is not None and "error" not in metrics:
                break
            time.sleep(args.poll_seconds)
    finally:
        if proc is not None and proc.poll() is None and tripped:
            _terminate(proc)

    if proc is not None and proc.returncode not in (0, None) and not tripped:
        sys.exit(proc.returncode)
    if tripped:
        sys.exit(2)


if __name__ == "__main__":
    main()
