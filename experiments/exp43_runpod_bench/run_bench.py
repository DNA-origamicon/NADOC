#!/usr/bin/env python3
"""Run the NADOC NAMD benchmark matrix ON THE POD. Stdlib only — no NADOC here.

    python3 run_bench.py --namd /workspace/namd/3.0.2p1-cuda-sm89/namd3 --rate 0.34

Each package lives in ``packages/<key>/`` and is a real NADOC solvated package
(manifest.json + <stem>.psf + <stem>_hmr.psf + confs + forcefield/). The design's
name_stem is read from its manifest, so nothing here is design-specific.

Minimisation is cached on the network volume: run it once per package, ever.

Writes ``benchmark_report.md`` — paste that into chat. Safe to interrupt; finished
cells are cached in ``results.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import asdict
from pathlib import Path

from bench_matrix import (
    BENCH_STEPS,
    MATRIX,
    PACKAGES,
    CellResult,
    HostInfo,
    classify_failure,
    cost_per_ns,
    make_bench_conf,
    ns_per_day,
    parse_atom_count,
    render_report,
)

BUNDLE = Path(__file__).resolve().parent


def _sh(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


def require_idle_machine():
    """Refuse to benchmark on a contended machine.

    A CPU-only NAMD control run on a degenerate structure never terminated (its line
    minimiser sat on NaN) and ate 32 threads underneath an entire benchmark. Every
    ns/day was ~6x too low, the GPU showed 4% util, and "GPU-resident gives no
    speedup" was a false conclusion drawn under contention.

    It hid because NAMD renames its process to "NAMD masterPe" — `pgrep -x namd3`
    matches NOTHING. Match argv[0], and skip our own pid (this script takes the NAMD
    path as an ARGUMENT, so a substring match self-blocks).
    """
    me = os.getpid()
    stale = []
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) == me:
            continue
        try:
            argv = (proc / "cmdline").read_bytes().decode(errors="ignore").split("\0")
        except OSError:
            continue
        if argv and argv[0] and Path(argv[0]).name.startswith("namd"):
            stale.append((proc.name, " ".join(argv)[:80]))
    load1 = float(Path("/proc/loadavg").read_text().split()[0])
    ncpu = os.cpu_count() or 1
    if stale:
        print("REFUSING TO RUN — NAMD already running:")
        for pid, cmd in stale:
            print(f"   pid {pid}: {cmd}")
        raise SystemExit(1)
    if load1 > 0.5 * ncpu:
        print(f"REFUSING TO RUN — load {load1:.1f} on {ncpu} cores; numbers would be contaminated.")
        raise SystemExit(1)
    print(f"machine idle: load {load1:.2f} / {ncpu} cores ✓")


def probe_host(namd_bin: str, rate: float, threads: int) -> HostInfo:
    gpu = _sh(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"]).splitlines()
    vram = _sh(
        ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"]
    ).splitlines()
    nproc = _sh(["nproc"])
    ram_gb = None
    mi = Path("/proc/meminfo")
    if mi.exists():
        m = re.search(r"MemTotal:\s+(\d+) kB", mi.read_text())
        if m:
            ram_gb = int(m.group(1)) / 1024 / 1024

    banner = subprocess.run([namd_bin], capture_output=True, text=True, timeout=60).stdout
    m = re.search(r"NAMD\s+([0-9][\w.]*)", banner)
    ver = m.group(1) if m else "?"

    # NAMD's banner reports the UPSTREAM version ("3.0.2") and carries no patch
    # suffix, so the tile-list fix is invisible there. Sniffing the banner for "p1"
    # always says "stock" and cries wolf on a correctly patched build. The install
    # path is the honest signal (build_patched_namd.sh writes ...3.0.2p1...).
    patched = "p1" in str(namd_bin).lower() or ver.startswith("3.1")

    return HostInfo(
        gpu=gpu[0] if gpu else "?",
        vram_mb=int(vram[0]) if vram and vram[0].isdigit() else None,
        vcpus=int(nproc) if nproc.isdigit() else None,
        host_ram_gb=ram_gb,
        namd_build=f"{ver}p1" if patched and not ver.startswith("3.1") else ver,
        namd_is_patched=patched,
        pod_id=_sh(["hostname"]) or "?",
        usd_per_hour=rate,
        threads=threads,
    )


class VramSampler(threading.Thread):
    """Poll nvidia-smi during a run; keep the peak.

    The flag is `_stop_evt`, NOT `_stop`: threading.Thread has a private `_stop()`
    that join() calls, so an attribute named `_stop` shadows it and join() dies with
    "'Event' object is not callable" — AFTER the work succeeded, which reads as a
    NAMD failure and sends you debugging the wrong thing.
    """

    def __init__(self, interval: float = 2.0):
        super().__init__(daemon=True)
        self.peak = 0
        self._stop_evt = threading.Event()
        self.interval = interval

    def run(self) -> None:
        while not self._stop_evt.is_set():
            out = _sh(
                ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"]
            )
            for line in out.splitlines():
                if line.strip().isdigit():
                    self.peak = max(self.peak, int(line.strip()))
            self._stop_evt.wait(self.interval)

    def stop(self) -> int:
        self._stop_evt.set()
        self.join(timeout=5)
        return self.peak or 0


def run_namd(namd_bin: str, conf: Path, log: Path, *, threads: int, gpu: bool):
    argv = [namd_bin, f"+p{threads}", "+setcpuaffinity"]
    if gpu:
        argv += ["+devices", "0"]
    argv.append(conf.name)

    sampler = VramSampler() if gpu else None
    if sampler:
        sampler.start()
    t0 = time.time()
    with log.open("w") as fh:
        proc = subprocess.run(argv, cwd=conf.parent, stdout=fh, stderr=subprocess.STDOUT)
    wall = time.time() - t0
    return proc.returncode, wall, (sampler.stop() if sampler else 0)


def package_stem(pkg_dir: Path) -> str:
    mf = pkg_dir / "manifest.json"
    if mf.exists():
        stem = json.loads(mf.read_text()).get("name_stem")
        if stem:
            return stem
    psf = next((p for p in pkg_dir.glob("*.psf") if not p.stem.endswith("_hmr")), None)
    if not psf:
        raise RuntimeError(f"cannot determine name_stem for {pkg_dir}")
    return psf.stem


def ensure_minimized(pkg_dir: Path, namd: str, threads: int, key: str):
    """Minimise once per package; cached on the volume.

    The GPU-resident cell MUST start from minimised coordinates: from raw build
    coordinates the ideal-B-DNA clashes blow the integrator up at step 1 ("Atoms
    moving too fast") BEFORE the residency check fires — which is how a
    residency-incompatible package once reached production.
    """
    min_conf = next(pkg_dir.glob("*_00_min_*.conf"), None)
    if min_conf is None:
        return False, "", "no minimisation conf in package"
    stem = f"output/{min_conf.stem}"
    if (pkg_dir / f"{stem}.coor").exists():
        print(f"  [{key}] minimisation cached ✓")
        return True, stem, ""

    (pkg_dir / "output").mkdir(exist_ok=True)
    print(f"  [{key}] minimising…", flush=True)
    log = pkg_dir / f"{min_conf.stem}.bench.log"
    rc, wall, _ = run_namd(namd, min_conf, log, threads=threads, gpu=True)
    ok = rc == 0 and (pkg_dir / f"{stem}.coor").exists()
    if ok:
        print(f"  [{key}] minimised in {wall / 60:.1f} min ✓")
        return True, stem, ""
    fail = classify_failure(log.read_text(errors="ignore"))
    why = f"minimisation failed: {fail[0]}" if fail else f"minimisation failed (rc={rc})"
    print(f"  [{key}] {why}")
    return False, "", why


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--namd", required=True)
    ap.add_argument("--namd-cpu", default="")
    ap.add_argument("--rate", type=float, default=0.34)
    ap.add_argument("--threads", type=int, default=0, help="0 = all vCPUs")
    ap.add_argument("--only", default="", help="comma-separated cell ids or package keys")
    args = ap.parse_args()

    threads = args.threads or int(_sh(["nproc"]) or "8")
    cpu_namd = args.namd_cpu or args.namd

    require_idle_machine()
    host = probe_host(args.namd, args.rate, threads)
    print(f"host: {host.gpu} · {host.vram_mb} MB · {host.vcpus} vCPU · NAMD {host.namd_build}")
    if not host.namd_is_patched:
        print("  ⚠️  NAMD does not look patched — expect the empty-patch tile-list crash.", file=sys.stderr)

    cache = BUNDLE / "results.json"
    done = {r["cid"]: r for r in json.loads(cache.read_text())} if cache.exists() else {}

    want = {w.strip() for w in args.only.split(",") if w.strip()}
    cells = [c for c in MATRIX if not want or c.cid in want or c.package in want]

    results = [CellResult(**r) for r in done.values()]
    seeds: dict[str, tuple[bool, str, str]] = {}

    for cell in cells:
        if cell.cid in done:
            print(f"[{cell.cid}] cached ✓")
            continue
        cfg, pkg = cell.cfg, cell.pkg
        pkg_dir = BUNDLE / "packages" / cell.package
        print(f"\n[{cell.cid}] {pkg.label} · {cfg.integrator} · {cfg.mode}", flush=True)

        if not pkg_dir.is_dir():
            results.append(CellResult(cid=cell.cid, ok=False, skipped="package not in bundle"))
            continue

        stem = package_stem(pkg_dir)
        if cell.package not in seeds:
            seeds[cell.package] = ensure_minimized(pkg_dir, args.namd, threads, cell.package)
        ok_min, seed_stem, why = seeds[cell.package]
        if not ok_min:
            results.append(CellResult(cid=cell.cid, ok=False, skipped=why))
            continue

        src = next(pkg_dir.glob("*_01_300K_*k0p5_p10.conf"), None)
        if src is None:
            results.append(CellResult(cid=cell.cid, ok=False, skipped="no k0.5 relax conf"))
            continue

        psf = f"{stem}_hmr.psf" if cfg.hmr else f"{stem}.psf"
        if not (pkg_dir / psf).exists():
            results.append(CellResult(cid=cell.cid, ok=False, skipped=f"{psf} missing"))
            continue

        tag = cell.cid.replace("/", "_")
        conf = pkg_dir / f"bench_{tag}.conf"
        conf.write_text(
            make_bench_conf(
                src.read_text(),
                psf=psf,
                timestep_fs=cfg.timestep_fs,
                gpu_resident=cfg.gpu_resident,
                run_steps=BENCH_STEPS,
                out_stem=f"output/bench_{tag}",
                seed_stem=seed_stem,
            )
        )
        log = pkg_dir / f"bench_{tag}.log"
        rc, wall, peak = run_namd(
            cpu_namd if cfg.build == "cpu" else args.namd,
            conf, log, threads=threads, gpu=cfg.build != "cpu",
        )
        text = log.read_text(errors="ignore")
        nspd = ns_per_day(text)
        fail = classify_failure(text)
        ok = rc == 0 and nspd is not None

        res = CellResult(
            cid=cell.cid, ok=ok,
            atoms=parse_atom_count(text),
            ns_per_day=nspd,
            usd_per_ns=cost_per_ns(nspd, args.rate),
            wall_s=wall,
            peak_vram_mb=peak or None,
            failure_kind=None if ok else (fail[0] if fail else f"rc={rc}"),
            failure_why=None if ok else (fail[1] if fail else None),
            log_path=str(log.relative_to(BUNDLE)),
        )
        results.append(res)
        print(
            f"  ✓ {nspd:.2f} ns/day · peak VRAM {peak} MB · {wall / 60:.1f} min"
            if ok else f"  ✗ {res.failure_kind} — {res.failure_why or ''}"
        )
        cache.write_text(json.dumps([asdict(r) for r in results], indent=2))

    report = render_report(host, results)
    (BUNDLE / "benchmark_report.md").write_text(report)
    print("\n" + "=" * 72 + "\n" + report + "=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
