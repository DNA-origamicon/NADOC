#!/usr/bin/env python3
"""Diagnostic: WHY is the 4090 at 4% while the CPU is pinned?

Hypothesis under test: in NAMD's CUDA **offload** mode, bonded forces are computed
on the CPU. NADOC's Aksimentiev ENM adds ~96k extra bonds to a 225k-atom 6hb (and
4.8M to VoltronCore), so the CPU bonded pass may dominate every step while the GPU
idles waiting for it.

Varies, on the SAME system (6hb, HMR + 4 fs, 2400 steps):
  - thread count (+p8 / +p16 / +p32)
  - +setcpuaffinity on/off  (containers can mis-map affinity)
  - GPU-resident vs offload (resident moves bonded ONTO the card)
  - ENM extraBonds on/off   (DIAGNOSTIC ONLY — never a valid production run)

Run on the pod:
    python3 sweep_gpu_util.py --namd /workspace/namd/3.0.2p1-cuda-sm89/namd3
"""

from __future__ import annotations

import argparse
import os
import re
import statistics
import subprocess
import threading
import time
from pathlib import Path

PKG = Path("/workspace/bench/packages/6hb")


class GpuWatch(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.samples: list[int] = []
        self._stop_evt = threading.Event()

    def run(self):
        while not self._stop_evt.is_set():
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True,
            ).stdout.strip()
            if out.isdigit():
                self.samples.append(int(out))
            self._stop_evt.wait(0.5)

    def stop(self):
        self._stop_evt.set()
        self.join(timeout=3)
        s = [v for v in self.samples if v is not None]
        return (statistics.mean(s) if s else 0.0), (max(s) if s else 0)


def require_idle_machine():
    """Refuse to benchmark on a contended machine.

    THE BUG THIS EXISTS FOR: a CPU-only NAMD control run on a degenerate structure
    (VoltronCore) never terminated — its line minimiser sat on NaN forever — and ate
    32 threads underneath every benchmark for an hour. Every ns/day number was
    silently wrong, the GPU showed 4% util, and "GPU-resident gives no speedup" was a
    false conclusion drawn under contention.

    It went unnoticed because **NAMD renames its process to "NAMD masterPe"**, so
    `pgrep -x namd3` matches NOTHING and reports the machine as free. Always match the
    binary PATH via /proc/<pid>/exe or cmdline — never the process name.
    """
    me = os.getpid()
    stale = []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit() or int(p.name) == me:
            continue
        try:
            argv = (p / "cmdline").read_bytes().decode(errors="ignore").split("\0")
        except OSError:
            continue
        if not argv or not argv[0]:
            continue
        # argv[0] must BE the namd binary. Matching anywhere in the cmdline also
        # matches this very script (which takes the namd path as an argument) and
        # any ssh command mentioning it — both of which self-kill / self-block.
        if Path(argv[0]).name.startswith("namd"):
            stale.append((p.name, " ".join(argv)[:80]))

    load1 = float(Path("/proc/loadavg").read_text().split()[0])
    ncpu = os.cpu_count() or 1

    if stale:
        print("REFUSING TO RUN — NAMD is already running on this machine:")
        for pid, cmd in stale:
            print(f"   pid {pid}: {cmd}")
        print("\nKill it first (match the binary path, NOT the process name — NAMD calls")
        print("itself 'NAMD masterPe'):   pkill -9 -f 3.0.2p1-cuda")
        raise SystemExit(1)

    if load1 > 0.5 * ncpu:
        print(f"REFUSING TO RUN — load average {load1:.1f} on {ncpu} cores. Machine is busy;")
        print("any throughput number measured now would be contaminated. Wait for it to settle.")
        raise SystemExit(1)

    print(f"machine idle: load {load1:.2f} / {ncpu} cores, no NAMD running ✓\n")


def ns_per_day(text: str):
    m = re.findall(r"Benchmark time:.*?([0-9.eE+-]+)\s+ns/day", text)
    if m:
        return float(m[-1])
    d = re.findall(r"Benchmark time:.*?([0-9.eE+-]+)\s+days/ns", text)
    if d and float(d[-1]) > 0:
        return 1.0 / float(d[-1])
    return None


def make_conf(src: Path, dst: Path, *, enm: bool, resident: bool, stem: str):
    t = src.read_text()
    t = re.sub(r"(?im)^outputName\s+.*$", f"outputName         output/{stem}", t)
    t = re.sub(r"(?im)^dcdFile\s+.*$", f"dcdFile            output/{stem}.dcd", t)
    t = re.sub(r"(?im)^xstFile\s+.*$", f"xstFile            output/{stem}.xst", t)
    if not enm:
        t = re.sub(r"(?im)^extraBonds\s+.*$", "extraBonds         off", t)
        t = re.sub(r"(?im)^extraBondsFile\s+.*$\n?", "", t)
    t = re.sub(r"(?im)^GPUresident\s+.*$\n?", "", t)
    run_m = re.search(r"(?im)^run\s+\d+\s*$", t)
    run_line = run_m.group(0) if run_m else "run                2400"
    t = re.sub(r"(?im)^run\s+\d+\s*$\n?", "", t)
    if resident:
        t += "\nGPUresident        on\n"
    t += f"\n{run_line}\n"
    dst.write_text(t)


def cell(namd: str, conf: Path, label: str, threads: int, affinity: bool):
    argv = [namd, f"+p{threads}"]
    if affinity:
        argv.append("+setcpuaffinity")
    argv += ["+devices", "0", conf.name]

    w = GpuWatch()
    w.start()
    t0 = time.time()
    proc = subprocess.run(argv, cwd=PKG, capture_output=True, text=True)
    wall = time.time() - t0
    avg, peak = w.stop()
    nspd = ns_per_day(proc.stdout)
    if nspd is None:
        err = re.search(r"FATAL ERROR.*", proc.stdout)
        print(f"  {label:<34} FAILED  {err.group(0)[:60] if err else f'rc={proc.returncode}'}")
        return
    print(f"  {label:<34} {nspd:>7.2f} ns/day   GPU {avg:>5.1f}% avg / {peak:>3d}% peak   {wall:5.1f}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--namd", required=True)
    args = ap.parse_args()

    require_idle_machine()

    base = next(PKG.glob("bench_6hb_fast_offload.conf"))

    with_enm = PKG / "sweep_enm.conf"
    no_enm = PKG / "sweep_noenm.conf"
    res_enm = PKG / "sweep_res_enm.conf"
    res_noenm = PKG / "sweep_res_noenm.conf"
    make_conf(base, with_enm, enm=True, resident=False, stem="sw1")
    make_conf(base, no_enm, enm=False, resident=False, stem="sw2")
    make_conf(base, res_enm, enm=True, resident=True, stem="sw3")
    make_conf(base, res_noenm, enm=False, resident=True, stem="sw4")

    print("6hb_sim_v2 · 225,504 atoms · HMR + rigidBonds all + 4 fs · 2400 steps\n")
    print("=== CUDA OFFLOAD, ENM ON (95,762 extra bonds — the shipped config) ===")
    cell(args.namd, with_enm, "+p16 +setcpuaffinity (baseline)", 16, True)
    cell(args.namd, with_enm, "+p32 +setcpuaffinity", 32, True)
    cell(args.namd, with_enm, "+p8  +setcpuaffinity", 8, True)
    cell(args.namd, with_enm, "+p16 (no affinity)", 16, False)

    print("\n=== CUDA OFFLOAD, ENM OFF (diagnostic only — not a real run) ===")
    cell(args.namd, no_enm, "+p16 +setcpuaffinity, NO ENM", 16, True)
    cell(args.namd, no_enm, "+p32 +setcpuaffinity, NO ENM", 32, True)

    print("\n=== GPU-RESIDENT (bonded moves onto the card) ===")
    cell(args.namd, res_enm, "+p16 resident, ENM ON", 16, True)
    cell(args.namd, res_noenm, "+p16 resident, NO ENM", 16, True)


if __name__ == "__main__":
    main()
