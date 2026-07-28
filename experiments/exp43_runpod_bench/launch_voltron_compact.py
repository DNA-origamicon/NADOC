#!/usr/bin/env python3
"""Autonomous, spec-driven production NAMD run on a rented RunPod GPU.

Give it a ``JobSpec`` (which NAMD build + which system package + size) and it runs the whole
pipeline with NO intervention (REFERENCE_RUNPOD_RUNBOOK §5-8):

  ASSESS   — atom count read from the package PSF (`natom_from_package`)
  SELECT   — live, value-ranked, arch+VRAM-aware card pick (`backend.core.runpod_select`)
  PACKAGE  — upload + extract; install the git-NAMD libs; verify every shared lib resolves
  PREFLIGHT— arm the pod-side deadman; force or probe the timestep
  RUN      — monitors (blowup / stall / budget kill), a pod-side deadman heartbeat, an
             AUTO-REROLL of a dud-slow pod (per-pod rate varies ~1.5x, §7), selective
             auto-fetch before teardown, and a prove-destroyed `confirmed_pod` teardown

Defaults to the VoltronCore compact spec. Every layer here was learned by burning a pod.

⚠️ Run the independent backstop in the background FIRST:
    python experiments/exp43_runpod_bench/pod_watchdog.py --budget <cap> --max-pod-min <M> &

    RUNPOD_API_KEY=$(cat ~/.runpod_key) setsid nohup \
      python experiments/exp43_runpod_bench/launch_voltron_compact.py \
        --spec voltron_compact --ns 30 --budget 40 --fetch-dcd --force-4fs \
        > /media/jojo/Archive/nadoc_voltron_prod/launch.log 2>&1 &
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import tarfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.runpod_api import RunpodClient, RunpodError  # noqa: E402
from backend.core.runpod_conn import RunpodSSHError  # noqa: E402
from backend.core.runpod_executor import namd_threads  # noqa: E402
from backend.core.runpod_select import (  # noqa: E402
    estimate_rate, load_rate_registry, pick_cards, record_rate,
)
from experiments.exp43_runpod_bench.campaign_common import (  # noqa: E402
    campaign_ledger, campaign_log, confirmed_pod, container_payload,
)

DEADMAN = Path(__file__).parent / "deadman.py"
DEADMAN_TOL_S = 600         # pod self-terminates 10 min after the controller goes dark
PROBE_WATCH_S = 240         # how long to watch the 4 fs probe before giving up (slow-card risk)
BENCH_STEPS = 8000          # measure the real rate past warmup (~5k) before the reroll decision

# compute-caps each NAMD build carries. A card outside its set rents fine and dies at step 0
# ("no kernel image is available"). GIT = sm_50..90 (NO sm_120 -> no RTX 5090); release = +sm_120.
BUILD_CC: dict[str, set[str]] = {
    "git": {"5.0", "6.0", "7.0", "7.5", "8.0", "8.6", "8.9", "9.0"},
    "release": {"8.0", "8.9", "9.0", "12.0"},
}

# Only UNAMBIGUOUS terminal signals — a false positive kills a HEALTHY paid run (runbook §3).
BLOWUP_RE = re.compile(
    r"(?mi)^FATAL ERROR:.*|Atoms moving too fast|no kernel image is available|"
    r"Constraint failure")


@dataclass(frozen=True)
class JobSpec:
    """Everything job-specific; the engine is otherwise general."""
    name: str
    namd_tar: Path            # NAMD build tar (extracts to namd_bin)
    pkg_tar: Path             # system package tar (extracts to workdir); holds the confs below
    workdir: str              # e.g. /root/VoltronCore_compact
    namd_bin: str             # e.g. /root/namd3
    build: str                # "git" | "release" -> BUILD_CC arch set + runpod_select build
    prod_conf: str = "prod4fs.conf"
    prod_stem: str = "prod4fs"
    alt_conf: str = "prod2fs.conf"     # slower-timestep fallback (used by the probe path)
    alt_stem: str = "prod2fs"
    probe_conf: str = "probe4fs.conf"
    timestep_fs: float = 4.0
    alt_timestep_fs: float = 2.0
    disk_gb: int = 60
    apt_libs: str = "libtcl8.6 libfftw3-single3"   # git-NAMD's only non-static deps
    n_atoms: int = 0                   # 0 => read from the package PSF
    heartbeat: str = "/root/nadoc_hb"
    fetch_root: Path = Path("/media/jojo/Archive/nadoc_voltron_prod")
    pod_prefix: str = "nadoc-bench"    # pod_watchdog guards pods whose name starts with this


def voltron_compact_spec() -> JobSpec:
    return JobSpec(
        name="voltron_compact",
        namd_tar=Path("/media/jojo/Archive/nadoc_bench_pkg/namd_git.tar.gz"),
        pkg_tar=Path("/media/jojo/Archive/nadoc_bench_pkg/VoltronCore_compact_prod.tar.gz"),
        workdir="/root/VoltronCore_compact",
        namd_bin="/root/namd3",
        build="git",
    )


SPECS = {"voltron_compact": voltron_compact_spec}


def natom_from_package(pkg_tar: Path) -> Optional[int]:
    """Read !NATOM from the base (non-HMR) PSF inside the package tar — the ASSESS input, so the
    atom count is never hard-coded. Returns None if it can't be found."""
    try:
        with tarfile.open(pkg_tar) as t:
            psfs = [m for m in t.getmembers()
                    if m.name.endswith(".psf") and "_hmr" not in m.name]
            if not psfs:
                return None
            f = t.extractfile(psfs[0])
            # !NATOM follows the !NTITLE block, which can be many thousands of REMARKS lines
            # (one per psfgen patch) — cap generously, reading short header lines is cheap.
            for _ in range(200_000):
                line = f.readline()
                if not line:
                    break
                if b"!NATOM" in line:
                    return int(line.split()[0].decode())
    except Exception:  # noqa: BLE001
        return None
    return None


def nsday(ms_step: float, ts_fs: float) -> float:
    return ts_fs * 1e-6 / (ms_step / 1000.0) * 86400.0


class RerollSlow(Exception):
    """Raised to abandon a dud-slow pod and rent a fresh one (bounded)."""


async def _sh(conn, cmd: str, timeout: float = 60.0) -> str:
    return (await conn.run(cmd, timeout=timeout)).stdout


async def _bg(conn, cmd: str) -> None:
    """Fire a backgrounded command, tolerating a missing channel-EOF (a quirky pod can leave
    ``& echo $!`` without EOF; callers verify liveness separately, so a swallowed timeout is safe)."""
    try:
        await conn.run(cmd, timeout=45, retries=1)
    except Exception as exc:  # noqa: BLE001
        print(f"  (bg launch returned no EOF: {str(exc)[:60]} — verifying liveness)", flush=True)


async def _kill_namd(conn) -> None:
    await _sh(conn, "pkill -9 namd3 2>/dev/null; true")


async def _launch_namd(conn, spec: JobSpec, conf: str, threads: int, logname: str) -> None:
    """Start NAMD detached; verify the log file appears (NAMD renames its process → pgrep useless,
    runbook §3). Raises if NAMD never started."""
    await _bg(conn,
              f"cd {spec.workdir} || exit 90; setsid nohup {spec.namd_bin} +p{threads} "
              f"+setcpuaffinity +devices 0 {conf} > {logname} 2>&1 < /dev/null & echo $!")
    for _ in range(6):                      # up to ~30 s for NAMD to create its log
        await asyncio.sleep(5)
        if "yes" in await _sh(conn, f"test -s {spec.workdir}/{logname} && echo yes"):
            return
    raise RuntimeError(f"NAMD did not start ({logname} never grew)")


async def _probe_4fs(conn, spec: JobSpec, threads: int) -> bool:
    """Run the probe conf and watch for a blowup. True => 4 fs is stable on this system.

    Step-based verdict (RUNBOOK §7): accept once it clears a step COUNT, not a wall-clock window —
    on a slow card 20k steps don't finish in the old 240 s window and it wrongly fell to 2 fs."""
    print("  probe: launching 4 fs stability probe", flush=True)
    await _launch_namd(conn, spec, spec.probe_conf, threads, "probe.log")
    t0 = time.time()
    while time.time() - t0 < PROBE_WATCH_S:
        await asyncio.sleep(15)
        await _sh(conn, f"touch {spec.heartbeat}")
        log = await _sh(conn, f"tail -c 40000 {spec.workdir}/probe.log")
        if BLOWUP_RE.search(log):
            print(f"  probe: 4 fs BLEW UP -> 2 fs\n    "
                  f"{(BLOWUP_RE.search(log).group(0) or '')[:120]}", flush=True)
            await _kill_namd(conn)
            return False
        steps = [int(m) for m in re.findall(r"TIMING:\s*(\d+)", log)]
        if re.search(r"(?m)^(End of program|WRITING)", log) or (steps and max(steps) >= 6000):
            print("  probe: 4 fs cleared ≥6k steps clean -> using 4 fs", flush=True)
            await _kill_namd(conn)
            return True
    print("  probe: no verdict in window; conservative -> 2 fs", flush=True)
    await _kill_namd(conn)
    return False


async def _setup_pod(conn, spec: JobSpec, pod_id: str) -> int:
    """Arch-gated upload + extract + git-NAMD libs + armed deadman. Returns +p thread count.
    Raises (→ acquisition retry) on any dud-pod failure."""
    cc = (await _sh(conn, "nvidia-smi --query-gpu=compute_cap --format=csv,noheader "
                          "2>/dev/null | head -1")).strip()
    gpu = (await _sh(conn, "nvidia-smi --query-gpu=name --format=csv,noheader")).strip()
    print(f"  GPU '{gpu}' compute_cap {cc or '?'}", flush=True)
    if cc and cc not in BUILD_CC[spec.build]:
        raise RuntimeError(f"arch sm_{cc.replace('.', '')} NOT in {spec.build} NAMD build — abort")

    for tar in (spec.namd_tar, spec.pkg_tar):
        t0 = time.time()
        await conn.sftp_put(str(tar), f"/root/{tar.name}")
        print(f"  uploaded {tar.name} ({tar.stat().st_size/1e6:.0f} MB) in "
              f"{time.time()-t0:.0f}s", flush=True)
    await conn.sftp_put(str(DEADMAN), "/root/deadman.py")
    await _sh(conn, f"cd /root && tar -xzf {spec.namd_tar.name} && tar -xzf {spec.pkg_tar.name}",
              timeout=900)
    if spec.apt_libs:
        await _sh(conn, f"export DEBIAN_FRONTEND=noninteractive; "
                        f"apt-get install -y {spec.apt_libs} >/dev/null 2>&1 || "
                        f"{{ apt-get update >/dev/null 2>&1; apt-get install -y {spec.apt_libs} "
                        f">/dev/null 2>&1; }}", timeout=300)
    if "yes" not in await _sh(conn, f"test -x {spec.namd_bin} && echo yes"):
        raise RuntimeError("NAMD binary missing after extract")
    missing = (await _sh(conn, f"ldd {spec.namd_bin} 2>/dev/null | grep 'not found' || true")).strip()
    if missing:
        raise RuntimeError(f"NAMD unresolved libs: {missing[:200]}")

    await _sh(conn, f"touch {spec.heartbeat}")
    await _bg(conn,
              f"cd /root && RUNPOD_POD_ID={pod_id} CTRL_HEARTBEAT={spec.heartbeat} "
              f"DEADMAN_TOL_S={DEADMAN_TOL_S} DEADMAN_LOG=/root/deadman.log "
              f"setsid nohup python3 /root/deadman.py > /root/deadman.out 2>&1 < /dev/null & echo $!")
    await asyncio.sleep(4)
    if "up" not in await _sh(conn, "grep -o 'deadman up' /root/deadman.log 2>/dev/null | head -1"):
        tail = await _sh(conn, "tail -c 400 /root/deadman.out 2>/dev/null; "
                               "tail -c 400 /root/deadman.log 2>/dev/null")
        raise RuntimeError(f"deadman failed to start ({tail.strip()[:150]})")
    print(f"  deadman armed (tol {DEADMAN_TOL_S}s)", flush=True)
    return namd_threads(int(await _sh(conn, "nproc") or 8))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", default="voltron_compact", choices=sorted(SPECS))
    ap.add_argument("--ns", type=float, default=30.0, help="production length in ns")
    ap.add_argument("--budget", type=float, default=40.0, help="USD this-run cap (controller kill)")
    ap.add_argument("--poll", type=float, default=75.0, help="poll interval s")
    ap.add_argument("--fetch-dcd", action="store_true", help="also pull the (bulk) DCD")
    ap.add_argument("--force-2fs", action="store_true", help="skip the probe, run the alt timestep")
    ap.add_argument("--force-4fs", action="store_true",
                    help="skip the probe, run the production timestep directly (once proven stable)")
    ap.add_argument("--inject-fail", action="store_true",
                    help="PREFLIGHT TEST: a guaranteed-FATAL conf, to prove the SANITY monitor "
                         "catches a blowup and tears the pod down")
    ap.add_argument("--max-attempts", type=int, default=6, help="total pod rentals (duds+rerolls)")
    ap.add_argument("--max-reroll", type=int, default=2, help="slow-pod rerolls before accept-any")
    ap.add_argument("--reroll-floor", type=float, default=0.7,
                    help="reroll if measured ns/day < this fraction of the card's expected rate")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    spec = SPECS[args.spec]()
    for tar in (spec.namd_tar, spec.pkg_tar):
        if not tar.exists():
            print(f"missing {tar} — build the package first", file=sys.stderr)
            return 2
    if not DEADMAN.exists():
        print(f"missing {DEADMAN}", file=sys.stderr)
        return 2

    n_atoms = spec.n_atoms or natom_from_package(spec.pkg_tar) or 0
    if not n_atoms:
        print("could not determine atom count from the package PSF", file=sys.stderr)
        return 2

    key = os.environ.get("RUNPOD_API_KEY") or (Path.home() / ".runpod_key").read_text().strip()
    # Kill key for the pod-side deadman self-terminate: the pod's auto-injected RUNPOD_API_KEY
    # 403s the pod DELETE, so hand the deadman a key that CAN terminate (scoped
    # ~/.runpod_key_kill if present, else the account key) via the pod's PID-1 env.
    _kk = Path.home() / ".runpod_key_kill"
    kill_key = _kk.read_text().strip() if _kk.exists() else key
    if args.dry_run:
        print(f"dry run [{spec.name}]: {n_atoms:,} atoms, {spec.build} build, {args.ns} ns, "
              f"cap ${args.budget:.0f}, reroll<{args.reroll_floor:g}x expected (max {args.max_reroll})")
        return 0

    spec.fetch_root.mkdir(parents=True, exist_ok=True)
    rate_reg = load_rate_registry()   # learned per-arch rates (refines the reroll floor + estimates)
    client = RunpodClient(key)
    ledger, clog = campaign_ledger(), campaign_log()
    clog.require_clean()
    start_spent = ledger.spent()
    print(f"[{spec.name}] {n_atoms:,} atoms, {spec.build} build   spend ${start_spent:.2f}  "
          f"cap ${args.budget:.2f}", flush=True)

    # SELECT — live, value-ranked, arch+VRAM-aware fallback list; degrades to the top pinned card.
    gpu_prefs: list[str] = []
    try:
        cands = await pick_cards(key, n_atoms, build=spec.build, resident=True,
                                 timestep_fs=spec.timestep_fs)
        if cands:
            gpu_prefs = [c.key for c in cands]
            print("  cards (live $/ns): " + " > ".join(
                f"{c.label} ${c.usd_per_hour:.2f} {c.ns_day_est:.0f}ns/d ${c.usd_per_ns_est:.2f}/ns"
                for c in cands[:4]), flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"  card selection unavailable ({str(exc)[:80]})", flush=True)
    if not gpu_prefs:
        gpu_prefs = ["NVIDIA GeForce RTX 4090"]        # static degrade

    payload = container_payload(f"{spec.pod_prefix}-{spec.name}", gpu_prefs, disk_gb=spec.disk_gb,
                                env={"RUNPOD_KILL_KEY": kill_key})
    status, attempts, rerolls, accept_any = "unknown", 0, 0, False
    try:
        while attempts < args.max_attempts:
            attempts += 1
            committed = False
            try:
                async with confirmed_pod(client, ledger, clog, payload, spec.name,
                                         usd_hr_hint=1.0, wait_timeout_s=900.0) as (pod, conn):
                    price = float(pod.cost_per_hr or 1.0)
                    cc = (await _sh(conn, "nvidia-smi --query-gpu=compute_cap --format=csv,"
                                          "noheader 2>/dev/null | head -1")).strip()
                    print(f"  [rental {attempts}] pod {pod.id} at ${price:.2f}/hr", flush=True)
                    threads = await _setup_pod(conn, spec, pod.id)

                    # --- pick the timestep + conf (force, probe, or inject-fail test) ----------
                    if args.inject_fail:
                        await _sh(conn, f"cd {spec.workdir} && sed 's/^timestep .*/timestep 100/; "
                                        f"s/^run .*/run 200000/' {spec.alt_conf} > blowup.conf")
                        conf, ts, stem, steps = "blowup.conf", spec.alt_timestep_fs, "blowup", 200000
                        print("  INJECT-FAIL: known-bad conf — the monitor must catch it", flush=True)
                    elif args.force_2fs:
                        conf, ts, stem = spec.alt_conf, spec.alt_timestep_fs, spec.alt_stem
                        steps = int(args.ns * 1e6 / ts)
                        await _sh(conn, f"sed -i 's/^run .*/run {steps}/' {spec.workdir}/{conf}")
                        print(f"  MODE {ts:.0f} fs (forced) — {args.ns} ns = {steps:,} steps", flush=True)
                    else:
                        use_prod = args.force_4fs or await _probe_4fs(conn, spec, threads)
                        if use_prod:
                            conf, ts, stem = spec.prod_conf, spec.timestep_fs, spec.prod_stem
                        else:
                            conf, ts, stem = spec.alt_conf, spec.alt_timestep_fs, spec.alt_stem
                        steps = int(args.ns * 1e6 / ts)
                        await _sh(conn, f"sed -i 's/^run .*/run {steps}/' {spec.workdir}/{conf}")
                        tag = "forced" if args.force_4fs else "probed"
                        print(f"  MODE {ts:.0f} fs ({tag}) — {args.ns} ns = {steps:,} steps", flush=True)

                    # expected rate for THIS card+timestep — the reroll floor (RUNBOOK §7)
                    est = estimate_rate(f"sm_{cc.replace('.', '')}", n_atoms, 1.0,
                                        timestep_fs=ts, resident=True, registry=rate_reg) if cc else None
                    expected = (est or {}).get("ns_day")
                    can_reroll = (not args.inject_fail and not accept_any
                                  and rerolls < args.max_reroll and expected)

                    # --- launch + monitor -----------------------------------------------------
                    await _launch_namd(conn, spec, conf, threads, "prod.log")
                    committed = True
                    t_launch, last_step, last_prog = time.time(), 0, time.time()
                    rate_checked, STALL_S = False, 1200.0
                    while True:
                        await asyncio.sleep(args.poll)
                        await _sh(conn, f"touch {spec.heartbeat}")
                        run_cost = ledger.spent() - start_spent
                        log = await _sh(conn, f"tail -c 60000 {spec.workdir}/prod.log")

                        if BLOWUP_RE.search(log):
                            print(f"  !! SANITY: {BLOWUP_RE.search(log).group(0)[:120]} — killing",
                                  flush=True)
                            await _kill_namd(conn)
                            status = "blewup"
                            break
                        tim = re.findall(r"TIMING:\s*(\d+).*?Wall:\s*[\d.]+,\s*([\d.]+)/step", log)
                        if tim:
                            step = int(tim[-1][0])
                            if step > last_step:
                                last_step, last_prog = step, time.time()
                            recent = [float(t[1]) * 1000.0 for t in tim[-3:]]
                            mss = sum(recent) / len(recent)
                            print(f"  step {last_step:,}/{steps:,}  {last_step*ts*1e-6:.2f} ns  "
                                  f"{mss:.1f} ms/step  {nsday(mss, ts):.1f} ns/day  "
                                  f"${run_cost:.2f}/${args.budget:.0f}  "
                                  f"{(time.time()-t_launch)/3600:.1f}h", flush=True)

                            # AUTO-REROLL: once past warmup, a pod far below the card's expected
                            # rate is a dud-slow pod — kill + rent fresh, bounded (RUNBOOK §7).
                            if not rate_checked and last_step >= BENCH_STEPS and len(tim) >= 3:
                                rate_checked = True
                                measured = nsday(mss, ts)
                                floor = args.reroll_floor * expected if expected else 0.0
                                if can_reroll and measured < floor:
                                    print(f"  SLOW POD: {measured:.1f} ns/day < {floor:.1f} floor "
                                          f"(expect ~{expected:.0f}) — rerolling", flush=True)
                                    await _kill_namd(conn)
                                    raise RerollSlow()
                                print(f"  rate OK: {measured:.1f} ns/day"
                                      + (f" (expect ~{expected:.0f})" if expected else "")
                                      + " — committing to the full run", flush=True)
                                # LEARN: fold this accepted resident pod's real ms/step into the
                                # per-arch registry so future $/ns estimates + reroll floors improve.
                                if cc:
                                    record_rate(f"sm_{cc.replace('.', '')}", n_atoms, mss)

                        if last_step > 0 and time.time() - last_prog > STALL_S:
                            print(f"  !! STALL: flat {STALL_S/60:.0f} min at {last_step:,} — killing",
                                  flush=True)
                            await _kill_namd(conn)
                            status = "stalled"
                            break
                        if run_cost >= args.budget:
                            print(f"  BUDGET ${run_cost:.2f} ≥ ${args.budget:.0f} — stopping",
                                  flush=True)
                            await _kill_namd(conn)
                            status = "budget"
                            break
                        if re.search(r"(?m)^End of program", log) or last_step >= steps:
                            print("  RUN COMPLETE", flush=True)
                            status = "completed"
                            break

                    # --- FETCH before teardown (container disk dies with the pod) --------------
                    dst = spec.fetch_root / pod.id
                    dst.mkdir(parents=True, exist_ok=True)
                    for ext in (".restart.coor", ".restart.vel", ".restart.xsc",
                                ".coor", ".vel", ".xsc"):
                        remote = f"{spec.workdir}/out/{stem}{ext}"
                        if "yes" in await _sh(conn, f"test -f {remote} && echo yes"):
                            try:
                                await conn.sftp_get(remote, str(dst / f"{stem}{ext}"))
                                print(f"  fetched {stem}{ext}", flush=True)
                            except Exception as exc:  # noqa: BLE001
                                print(f"  fetch FAILED {stem}{ext}: {exc}", flush=True)
                    with_log = f"{spec.workdir}/prod.log"
                    if "yes" in await _sh(conn, f"test -f {with_log} && echo yes"):
                        await conn.sftp_get(with_log, str(dst / "prod.log"))
                    if args.fetch_dcd:
                        dcd = f"{spec.workdir}/out/{stem}.dcd"
                        if "yes" in await _sh(conn, f"test -f {dcd} && echo yes"):
                            print("  fetching DCD (bulk — GPU billing while it downloads)", flush=True)
                            await conn.sftp_get(dcd, str(dst / f"{stem}.dcd"))
                    print(f"  results in {dst}", flush=True)
                break   # terminal status reached
            except RerollSlow:
                rerolls += 1
                if rerolls >= args.max_reroll:
                    accept_any = True
                    print(f"  reroll budget spent ({rerolls}) — accepting the next pod as-is",
                          flush=True)
                await asyncio.sleep(5)
            except (RunpodError, RunpodSSHError) as exc:
                if committed:
                    print(f"  pod died AFTER launch ({str(exc)[:100]}) — not restarting", flush=True)
                    if status == "unknown":
                        status = "run_interrupted"
                    break
                print(f"  rental {attempts}/{args.max_attempts}: setup failed "
                      f"({str(exc)[:100]}) — fresh pod", flush=True)
                if attempts >= args.max_attempts:
                    status = "pod_unavailable"
                await asyncio.sleep(10)
    finally:
        live = [p for p in await client.list_pods()
                if not p.is_destroyed and str(p.raw.get("name", "")).startswith(spec.pod_prefix)]
        for p in live:
            print(f"!! pod {p.id} SURVIVED — destroying", flush=True)
            await client.terminate_pod(p.id)
            ledger.close_pod(p.id)
        await client.aclose()

    print(f"\nstatus: {status}   rentals: {attempts} (rerolls {rerolls})   "
          f"cost this run: ${ledger.spent()-start_spent:.2f}   total ${ledger.spent():.2f}",
          flush=True)
    return 0 if status in ("completed", "budget") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
