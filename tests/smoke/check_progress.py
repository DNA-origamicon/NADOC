#!/usr/bin/env python3
"""
Quick progress check for a running smoke test.

Usage:
    python tests/smoke/check_progress.py [run_dir]

If run_dir is omitted, auto-detects the newest /tmp/nadoc_smoke_* directory.
"""
from __future__ import annotations
import sys
import glob
import subprocess
from pathlib import Path


def _frame_count(xtc: Path) -> int:
    r = subprocess.run(
        ["gmx", "check", "-f", str(xtc)],
        capture_output=True, text=True,
    )
    for line in (r.stdout + r.stderr).splitlines():
        if "Last frame" in line:
            # "Last frame   50 time   1000.000"
            parts = line.split()
            try:
                return int(parts[2]) + 1
            except (IndexError, ValueError):
                pass
    return 0


def _log_tail(log: Path, n: int = 3) -> str:
    if not log.exists():
        return "  (not started)"
    lines = log.read_text(errors="replace").splitlines()
    return "\n".join(f"  {l}" for l in lines[-n:] if l.strip())


def main() -> None:
    if len(sys.argv) > 1:
        run_dir = Path(sys.argv[1])
    else:
        candidates = sorted(glob.glob("/tmp/nadoc_smoke_*"), key=lambda p: Path(p).stat().st_mtime, reverse=True)
        if not candidates:
            print("No nadoc_smoke_* directories found in /tmp.")
            return
        run_dir = Path(candidates[0])

    print(f"Run dir: {run_dir}")
    print()

    stages = [
        ("EM",         run_dir / "em.log",   None),
        ("NVT",        run_dir / "nvt.log",  None),
        ("NPT",        run_dir / "npt.log",  None),
        ("Production", run_dir / "prod.log", run_dir / "prod.xtc"),
    ]

    for label, log, xtc in stages:
        exists = log.exists()
        status = "done" if exists else "pending"

        # If log exists and prod.xtc does not yet, it's the active stage
        if exists and xtc is not None and not (run_dir / "smoke_params.json").exists():
            frames = _frame_count(xtc) if xtc.exists() else 0
            # production.mdp nsteps
            mdp = run_dir / "production.mdp"
            nsteps = 500000
            nstxout = 10000
            if mdp.exists():
                for line in mdp.read_text().splitlines():
                    if line.strip().startswith("nsteps"):
                        try: nsteps = int(line.split("=")[1].split(";")[0])
                        except: pass
                    if line.strip().startswith("nstxout-compressed"):
                        try: nstxout = int(line.split("=")[1].split(";")[0])
                        except: pass
            total_frames = nsteps // nstxout
            pct = 100 * frames / total_frames if total_frames else 0
            status = f"RUNNING — {frames}/{total_frames} frames ({pct:.0f}%)"

        print(f"  [{label:12s}] {status}")

    print()
    if (run_dir / "smoke_params.json").exists():
        import json
        d = json.loads((run_dir / "smoke_params.json").read_text())
        p = d.get("mrdna_params", {})
        print(f"  COMPLETE — r0={p.get('r0_ang', '?'):.2f} Å  "
              f"hj={p.get('hj_equilibrium_angle_deg', '?'):.1f}°  "
              f"k_bond={p.get('k_bond_kJ_mol_ang2', '?'):.4f}")
    else:
        print("  Still running…")


if __name__ == "__main__":
    main()
