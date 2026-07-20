"""BLADE reference-capture driver — rent ONE RunPod pod (network volume + namd3),
seed a 2 fs / no-HMR / NVT capture from the relaxed 04_MGHH_only_p100 restart, run
vel+force capture, export the DNA-only training .npz on the pod, fetch only the npz
to the Archive drive, and reap.

Teardown is triple-guarded: client.pod()'s finally terminates the pod; we also book
to the campaign ledger and close it; and pod_watchdog.py (run separately) is the
independent budget/age backstop that kills the pod if THIS process dies. The pod is
named "nadoc-bench-blade-*" so the watchdog will adopt+guillotine it.

Usage:
  RUNPOD_API_KEY=$(cat ~/.runpod_key) python blade_capture_driver.py --mode pilot   [--dry-run] [--gpu-max-usd 1.5]
  RUNPOD_API_KEY=$(cat ~/.runpod_key) python blade_capture_driver.py --mode production

--dry-run builds the payload + checks prerequisites and exits WITHOUT renting.
"""
import argparse
import asyncio
import json
import re
import shutil
import sys
import time
from pathlib import Path

REPO = Path("/home/jojo/Work/NADOC")
EXP43 = REPO / "experiments/exp43_runpod_bench"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(EXP43))

from backend.core.runpod_api import RunpodClient, build_create_payload, ssh_endpoint  # noqa: E402
from backend.core.runpod_conn import RunpodConnection  # noqa: E402
from backend.core.runpod_script import recommend_gpus  # noqa: E402
from spend_ledger import SpendLedger  # noqa: E402

SSH_KEY = str(Path.home() / ".ssh/id_ed25519")
VOLUME_ID = "77pnhye88p"          # EU-RO-1 volume holding the multi-arch namd3
NAMD = "/workspace/namd/3.0.2p1-cuda-a80/namd3"
LEDGER = Path("/media/jojo/Archive/nadoc_bench_campaign/spend.json")
BUNDLE = Path("/media/jojo/Archive/NADOC_archive/_blade_ref_bundle_6hbx100_90deg")
ARCHIVE_OUT = Path("/media/jojo/Archive/NADOC_archive/_blade_ref_out")
N_ATOMS = 770219
NAME_STEM = "6hbx100_90deg"
WORKDIR = "/workspace/blade_capture"   # fixed on the persistent volume → reuse across runs
CTRL_HB = "/workspace/controller_heartbeat"  # controller→pod liveness token (deadman)
DEADMAN_TOL_S = 600                    # controller silent this long → pod self-terminates

SHIM_INIT = ""  # empty package markers
SHIM_ATOMISTIC = (
    "_GRO_DNA_RESNAMES = {'A','ADE','C','CYT','DA','DA3','DA5','DC','DC3','DC5',"
    "'DG','DG3','DG5','DT','DT3','DT5','G','GUA','T','THY'}\n"
)
SHIM_LOCAL_RUN = '''\
from pathlib import Path
def captured_outputs(job, workspace_dir):
    ws = Path(workspace_dir); out = job.package_dir(ws) / "output"; result = {}
    for seg in job.segments:
        vel = out / f"{seg.name}.veldcd"; frc = out / f"{seg.name}.forcedcd"; dcd = out / f"{seg.name}.dcd"
        if vel.exists() or frc.exists():
            result[seg.name] = {"dcd": str(dcd) if dcd.exists() else None,
                                "veldcd": str(vel) if vel.exists() else None,
                                "forcedcd": str(frc) if frc.exists() else None}
    return result
'''


def build_shim(dst: Path):
    """Assemble _shim/backend/... with the REAL windows.py + minimal stubs."""
    base = dst / "backend"
    (base / "core").mkdir(parents=True, exist_ok=True)
    (base / "ml" / "propagator").mkdir(parents=True, exist_ok=True)
    for p in [base / "__init__.py", base / "core/__init__.py",
              base / "ml/__init__.py", base / "ml/propagator/__init__.py"]:
        p.write_text(SHIM_INIT)
    (base / "core/atomistic_to_nadoc.py").write_text(SHIM_ATOMISTIC)
    (base / "ml/propagator/local_run.py").write_text(SHIM_LOCAL_RUN)
    # The REAL export code — verbatim, so the npz schema matches the trainer exactly.
    (base / "ml/propagator/windows.py").write_text(
        (REPO / "backend/ml/propagator/windows.py").read_text())


def _box_from_seed_xsc() -> list:
    """Equilibrated orthorhombic box (Å) from the seed .xsc: data line is
    `step a_x a_y a_z b_x b_y b_z c_x c_y c_z o_x o_y o_z` → lengths (a_x, b_y, c_z)."""
    xsc = next(BUNDLE.glob("output/*_04_300K_NPT_MGHH_only_p100.xsc"))
    for ln in xsc.read_text().splitlines():
        if ln.strip() and not ln.startswith("#"):
            v = ln.split()
            return [float(v[1]), float(v[5]), float(v[9])]
    return [288.059, 89.119, 306.483]


def pod_manifest(seg_name: str, dcd_freq: int) -> str:
    """Minimal manifest.json export_windows reads (box_ang + the capture seg's dcd_freq)."""
    return json.dumps({"box_ang": _box_from_seed_xsc(),
                       "segments": [{"name": seg_name, "dcd_freq": dcd_freq}]}, indent=2)


def local_files_with_sizes():
    return {str(p.relative_to(BUNDLE)): p.stat().st_size
            for p in BUNDLE.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"}


async def run(conn, cmd, timeout, label):
    r = await conn.run(cmd, timeout=timeout)
    if r.rc:
        print(f"[{label}] rc={r.rc} stderr={(r.stderr or '')[-400:]}", flush=True)
    return r


async def upload_skip_by_size(conn, files: dict):
    for rel, sz in sorted(files.items()):
        remote = f"{WORKDIR}/{rel}"
        r = await conn.run(f"stat -c %s {remote} 2>/dev/null || echo M", timeout=30)
        if (r.stdout or "").strip() == str(sz):
            print(f"  skip (present) {rel}", flush=True); continue
        print(f"  put {rel} ({sz/1e6:.1f} MB)", flush=True)
        await conn.sftp_put(str(BUNDLE / rel), remote)


def parse_ms_per_step(log_text: str):
    # NAMD prints "Benchmark time: N CPUs M s/step ..." and "Info: Benchmark time: ..."
    m = re.findall(r"Benchmark time:.*?([0-9.eE+-]+)\s*s/step", log_text)
    if m:
        return float(m[-1]) * 1000.0
    m2 = re.findall(r"TIMING:.*?([0-9.]+)\s*s/step", log_text)
    return float(m2[-1]) * 1000.0 if m2 else None


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["pilot", "production"], required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-namd", action="store_true",
                    help="reuse DCDs already on the volume; run only pip + export")
    ap.add_argument("--gpu-max-usd", type=float, default=1.50)
    ap.add_argument("--run-timeout-min", type=float, default=None)
    args = ap.parse_args()

    if args.mode == "pilot":
        equil, cap, dcd_freq = f"{NAME_STEM}_05_pilot_equil", f"{NAME_STEM}_06_pilot_capture", 100
        run_timeout = (args.run_timeout_min or 40) * 60
    else:
        equil, cap, dcd_freq = f"{NAME_STEM}_05_equil", f"{NAME_STEM}_06_capture", 500
        run_timeout = (args.run_timeout_min or 900) * 60

    gpus = recommend_gpus(N_ATOMS, gpu_resident=False, max_usd_per_hour=args.gpu_max_usd)
    gpu_ids = [g.key for g in gpus]
    assert gpu_ids, "no GPU fits"
    pod_name = f"nadoc-bench-blade-{args.mode}"
    # Deadman's switch: inject the Restricted kill key so the pod can self-terminate on
    # loss of controller heartbeat (lands in /proc/1/environ; deadman.py reads it there).
    kill_key_file = Path.home() / ".runpod_key_kill"
    pod_env = {}
    if kill_key_file.exists():
        pod_env["RUNPOD_KILL_KEY"] = kill_key_file.read_text().strip()
    payload = build_create_payload(
        name=pod_name, gpu_type_ids=gpu_ids, network_volume_id=VOLUME_ID,
        interruptible=False, cloud_type="SECURE", container_disk_gb=40,
        env=pod_env or None)

    print(f"MODE={args.mode}  equil={equil}  capture={cap}  dcd_freq={dcd_freq}", flush=True)
    print(f"GPU priority: {gpu_ids}", flush=True)
    print(f"pod name: {pod_name}  volume: {VOLUME_ID}  workdir: {WORKDIR}", flush=True)
    assert Path(SSH_KEY).exists(), f"missing ssh key {SSH_KEY}"
    assert BUNDLE.exists(), f"missing bundle {BUNDLE}"
    for c in (equil, cap):
        assert (BUNDLE / f"{c}.conf").exists(), f"missing conf {c}"

    # SEQUENCE PREFLIGHT — the poly-T-scaffold guard (6hbx100_90deg incident). Two
    # independent checks: the DESIGN the box was built from (scaffold fully sequenced?),
    # and the built PSF being sent (any poly-T DNA segment? catches a stale/unsequenced
    # box even if the current design was later fixed). FAIL LOUD *before* renting.
    from backend.core.md_sequence_guard import (  # noqa: E402,PLC0415
        scaffold_sequence_problems, psf_polyt_problems)
    seq_problems: list[str] = []
    design_path = REPO / f"workspace/{NAME_STEM}.nadoc"
    if design_path.exists():
        from backend.core.models import Design  # noqa: PLC0415
        seq_problems += [f"[design] {p}" for p in
                         scaffold_sequence_problems(Design.model_validate_json(design_path.read_text()))]
    else:
        print(f"WARN: design {design_path} not found — relying on the PSF check only", flush=True)
    seq_problems += [f"[psf] {p}" for p in psf_polyt_problems(BUNDLE / f"{NAME_STEM}.psf")]
    if seq_problems:
        print("SEQUENCE PREFLIGHT FAILED — refusing to rent (poly-T / unassigned scaffold):", flush=True)
        for p in seq_problems:
            print(f"  - {p}", flush=True)
        print("Assign the scaffold sequence and rebuild the box before running.", flush=True)
        return 7
    print("sequence preflight OK (scaffold fully sequenced; no poly-T PSF segment)", flush=True)

    print(f"payload gpuTypeIds={payload.get('gpuTypeIds')} vol={payload.get('networkVolumeId')} "
          f"cloud={payload.get('cloudType')} interruptible={payload.get('interruptible')}", flush=True)
    ARCHIVE_OUT.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        print("DRY-RUN OK — payload built, prerequisites present, NOT renting.", flush=True)
        return 0

    key = (Path.home() / ".runpod_key").read_text().strip()
    client = RunpodClient(key)
    ledger = SpendLedger(LEDGER)
    booked = {"id": None}

    def on_created(info):
        booked["id"] = info.id
        try:
            ledger.open_pod(info.id, float(info.cost_per_hr or 1.0), note=pod_name)
        except Exception as e:
            print(f"ledger.open_pod warn: {e}", flush=True)
        print(f"POD CREATED id={info.id} (billing started)", flush=True)

    t0 = time.time()
    try:
        async with client.pod(payload, fallbacks=[], on_created=on_created) as pod:
            host, port = ssh_endpoint(pod)
            print(f"POD UP id={pod.id} {host}:{port} ${pod.cost_per_hr}/hr", flush=True)
            conn = RunpodConnection(host=host, port=port, pod_id=pod.id, client_keys=[SSH_KEY])
            await conn.connect()

            nproc = int(((await conn.run("nproc", timeout=30)).stdout or "8").strip() or 8)
            threads = max(1, min(nproc // 2, 16))
            await conn.mkdir_p(WORKDIR)
            await conn.mkdir_p(f"{WORKDIR}/output")

            print("UPLOAD bundle (skip-by-size):", flush=True)
            await upload_skip_by_size(conn, local_files_with_sizes())
            # per-run pod manifest + export shim + export script
            man_local = Path("/tmp/blade_pod_manifest.json")
            man_local.write_text(pod_manifest(cap, dcd_freq))
            await conn.sftp_put(str(man_local), f"{WORKDIR}/manifest.json")
            shim = Path("/tmp/blade_shim")
            if shim.exists():
                shutil.rmtree(shim)
            build_shim(shim)
            for p in shim.rglob("*"):
                if p.is_file():
                    await conn.sftp_put(str(p), f"{WORKDIR}/_shim/{p.relative_to(shim)}")
            await conn.sftp_put(str(Path(__file__).parent / "pod_export.py"), f"{WORKDIR}/pod_export.py")

            out_npz = f"{WORKDIR}/{cap}.dna.npz"
            namd_block = "" if args.skip_namd else (
                f'echo "== equil ==" >> chain.log\n'
                f'{NAMD} +p{threads} +setcpuaffinity +devices 0 {equil}.conf > {equil}.log 2>&1\n'
                f'echo "== capture ==" >> chain.log\n'
                f'{NAMD} +p{threads} +setcpuaffinity +devices 0 {cap}.conf > {cap}.log 2>&1\n')
            chain = f"""#!/bin/bash
cd {WORKDIR}
rm -f CHAIN_DONE CHAIN_FAIL
echo "== start ==" > chain.log
set -e
{namd_block}echo "== deps ==" >> chain.log
python3 -m pip install --break-system-packages --no-input MDAnalysis scipy numpy >> pip.log 2>&1
echo "== export ==" >> chain.log
python3 pod_export.py {WORKDIR} {NAME_STEM} {cap} {out_npz} 4.0 > export.log 2>&1
touch CHAIN_DONE
"""
            chain = chain.replace("set -e\n", "set -e\ntrap 'touch CHAIN_FAIL' ERR\n")
            # launch_detached wants a script PATH on the pod (it runs `bash <path>`), not
            # the script body — write it to a file, sftp it, then launch by path.
            chain_local = Path(f"/tmp/blade_chain_{args.mode}.sh")
            chain_local.write_text(chain)
            await conn.sftp_put(str(chain_local), f"{WORKDIR}/nadoc_chain.sh")
            pid = await conn.launch_detached(f"{WORKDIR}/nadoc_chain.sh", WORKDIR)
            print(f"CHAIN launched pid={pid} threads={threads}", flush=True)

            # Deadman's switch: seed the controller heartbeat, ship + launch deadman.py. If
            # this process/machine dies and stops refreshing the heartbeat, the pod self-
            # terminates (Restricted key) after DEADMAN_TOL_S — no billing leak on our death.
            await conn.run(f"date +%s > {CTRL_HB}", timeout=20)
            await conn.sftp_put(str(Path(__file__).parent / "deadman.py"), f"{WORKDIR}/deadman.py")
            dm = await conn.run(
                f"cd {WORKDIR}; RUNPOD_POD_ID={pod.id} DEADMAN_TOL_S={DEADMAN_TOL_S} "
                f"DEADMAN_POLL_S=30 CTRL_HEARTBEAT={CTRL_HB} "
                f"setsid nohup python3 deadman.py > deadman.stdout 2>&1 < /dev/null & echo $!",
                timeout=30)
            print(f"DEADMAN launched pid={(dm.stdout or '').strip()} TOL={DEADMAN_TOL_S}s", flush=True)

            # poll for the sentinel (each poll ALSO refreshes the deadman heartbeat)
            deadline = time.time() + run_timeout
            last = ""
            while time.time() < deadline:
                await asyncio.sleep(45)
                st = await conn.run(
                    f"cd {WORKDIR}; date +%s > {CTRL_HB}; (cat CHAIN_DONE 2>/dev/null && echo _D); "
                    f"(cat CHAIN_FAIL 2>/dev/null && echo _F); "
                    f"tail -n 2 {cap}.log 2>/dev/null | tr '\\n' '|'", timeout=45)
                out = (st.stdout or "").strip()
                if out != last:
                    print(f"  [{int(time.time()-t0)}s] {out[-300:]}", flush=True); last = out
                if "_D" in out:
                    print("CHAIN DONE", flush=True); break
                if "_F" in out:
                    print("CHAIN FAILED", flush=True)
                    logs = [f"{cap}.log"] if args.skip_namd else [f"{equil}.log", f"{cap}.log"]
                    for lg in logs:
                        r = await conn.run(f"tail -n 20 {WORKDIR}/{lg}", timeout=30)
                        print(f"--- {lg} tail ---\n{(r.stdout or '')[-1200:]}", flush=True)
                    for lg in ("pip.log", "export.log"):
                        r = await conn.run(f"tail -n 40 {WORKDIR}/{lg}", timeout=30)
                        print(f"--- {lg} tail ---\n{(r.stdout or '')[-2000:]}", flush=True)
                    return 4
            else:
                print("TIMEOUT waiting for chain", flush=True); return 5

            # Compute + export are done (npz already on the volume). Disarm the pod-side
            # deadman BEFORE the (slow, minutes-long) Archive backup fetch: the poll loop
            # that refreshed the heartbeat has exited, so the heartbeat would go stale and
            # the deadman would kill the pod mid-fetch. The context-manager finally +
            # pod_watchdog still cover a controller death during this short wind-down.
            try:
                await conn.run("pkill -f deadman.py 2>/dev/null; true", timeout=20)
                print("deadman disarmed for fetch/reap wind-down", flush=True)
            except Exception as e:
                print(f"deadman disarm warn: {e}", flush=True)

            # ms/step + DCD sizes for disk projection
            caplog = (await conn.run(f"cat {WORKDIR}/{cap}.log", timeout=45)).stdout or ""
            ms = parse_ms_per_step(caplog)
            dcdsz = await conn.run(
                f"cd {WORKDIR}/output; stat -c '%s %n' {cap}.dcd {cap}.veldcd {cap}.forcedcd 2>/dev/null",
                timeout=30)
            summ = await conn.run(f"grep EXPORT_SUMMARY {WORKDIR}/export.log", timeout=30)
            print(f"MS_PER_STEP={ms}", flush=True)
            print(f"DCD_SIZES:\n{(dcdsz.stdout or '').strip()}", flush=True)
            print(f"{(summ.stdout or '').strip()}", flush=True)

            # The npz STAYS on the volume for the other computer to pull:
            print(f"NPZ_ON_VOLUME {VOLUME_ID}:{out_npz}", flush=True)
            print(f"MG_ON_VOLUME  {VOLUME_ID}:{WORKDIR}/{cap}.dna_chelated_mg.npz", flush=True)
            # ...and we fetch an Archive BACKUP copy (non-fatal: the volume copy is primary).
            local_npz = ARCHIVE_OUT / f"{cap}.dna.npz"
            try:
                await asyncio.wait_for(conn.sftp_get(out_npz, str(local_npz)), timeout=2400)
            except Exception as e:
                print(f"  (Archive backup fetch skipped: {e}; npz safe on volume)", flush=True)
            for extra in (f"{cap}.dna_chelated_mg.npz", "dataset_manifest.json", "export.log", f"{cap}.log"):
                try:
                    await asyncio.wait_for(
                        conn.sftp_get(f"{WORKDIR}/{extra}", str(ARCHIVE_OUT / Path(extra).name)),
                        timeout=600)
                except Exception as e:
                    print(f"  (optional fetch {extra} skipped: {e})", flush=True)
            print(f"FETCHED {local_npz} ({local_npz.stat().st_size/1e6:.1f} MB)", flush=True)
            print("RESULT_OK", flush=True)
    finally:
        # client.pod() already terminates; belt-and-suspenders ledger close + verify.
        try:
            if booked["id"]:
                ledger.close_pod(booked["id"])
            left = [p.id for p in await client.list_pods() if not p.is_destroyed]
            print(f"LIVE PODS AFTER: {left}", flush=True)
            if left:
                print("!! pods still alive — reap by hand: python reap.py --kill", flush=True)
        except Exception as e:
            print(f"reap-verify warn: {e}", flush=True)
        await client.aclose()
    print(f"TOTAL {int(time.time()-t0)}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
