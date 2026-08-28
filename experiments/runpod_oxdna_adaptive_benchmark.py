#!/usr/bin/env python3
"""Benchmark pinned upstream oxDNA against NADOC adaptive-memory oxDNA on one RunPod GPU."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shlex
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.runpod_api import RunpodClient, build_create_payload, resolve_api_key, termination_deadline
from backend.core.runpod_conn import RunpodConnection
from backend.core.runpod_oxdna import CampaignLedger, GPU_TARGETS, OXDNA_REV, OXDNA_URL, REMOTE_ROOT, budgeted_lifetime_s, engine_dir, render_build_script
from backend.core.runpod_preflight import fetch_gpu_stock

RATE_RE = re.compile(r"per step:\s*([0-9.eE+-]+)\s*ms")


async def upload_text(conn: RunpodConnection, text: str, remote: str) -> None:
    fd, name = tempfile.mkstemp(prefix="nadoc-oxdna-bench-")
    os.close(fd)
    path = Path(name)
    try:
        path.write_text(text)
        await conn.sftp_put(str(path), remote)
    finally:
        path.unlink(missing_ok=True)


def input_text(source: Path, *, adaptive: bool, steps: int) -> str:
    drop = {
        "topology", "conf_file", "steps", "lastconf_file", "trajectory_file",
        "energy_file", "print_conf_interval", "print_energy_every",
        "adaptive_neighbor_list", "adaptive_neighbor_initial_capacity",
        "adaptive_compact_cells",
        "external_forces", "external_forces_file", "refresh_vel",
        "thermostat", "bussi_tau",
    }
    kept = []
    for line in source.read_text().splitlines():
        key = line.partition("=")[0].strip()
        if key not in drop:
            kept.append(line)
    kept += [
        "topology = ../topology.top", "conf_file = ../conf.dat", f"steps = {steps}",
        f"print_conf_interval = {steps}", f"print_energy_every = {steps}",
        "lastconf_file = last_conf.dat", "trajectory_file = trajectory.dat",
        "energy_file = energy.dat",
        "external_forces = false", "refresh_vel = false", "thermostat = no",
    ]
    if adaptive:
        kept += [
            "adaptive_neighbor_list = true",
            "adaptive_neighbor_initial_capacity = 8",
            "adaptive_compact_cells = true",
        ]
    return "\n".join(kept) + "\n"


async def main_async(args) -> dict:
    resolved = resolve_api_key()
    if not resolved.value:
        raise RuntimeError("RunPod API key unavailable")
    target = GPU_TARGETS[0] if args.gpu == "h200" else GPU_TARGETS[1]
    stock = await fetch_gpu_stock(resolved.value)
    quote = stock.get(target.gpu_id) or {}
    rate = float(quote.get("on_demand") or 0.0)
    if rate <= 0:
        raise RuntimeError(f"no live {target.label} on-demand quote")
    client = RunpodClient(resolved.value, audit_dir=args.output.parent)
    ledger = CampaignLedger(args.ledger, cap_usd=args.budget)
    lifetime = budgeted_lifetime_s(ledger, rate, args.max_seconds)
    payload = build_create_payload(
        name=args.pod_name,
        gpu_type_ids=[target.gpu_id],
        network_volume_id="" if args.no_volume else args.volume,
        cloud_type="SECURE",
        terminate_after=termination_deadline(lifetime),
    )
    pod_id = None
    actual_rate = rate
    started = time.time()

    def created(info) -> None:
        nonlocal pod_id, actual_rate
        pod_id = info.id
        actual_rate = float(info.cost_per_hr or rate)
        ledger.open_pod(info.id, actual_rate, note=args.ledger_note)
        print(f"pod {info.id} created at ${actual_rate:.2f}/hour", flush=True)

    try:
        async with client.pod(payload, on_created=created, terminate_on_exit=True) as pod:
            conn = RunpodConnection(
                host=pod.public_ip,
                port=pod.ssh_port,
                pod_id=pod.id,
                client_keys=[str(Path.home() / ".ssh/id_ed25519")],
            )
            await conn.connect()
            try:
                remote = f"{REMOTE_ROOT}/{args.remote_name}"
                await conn.mkdir_p(remote)
                patch_remote = f"{REMOTE_ROOT}/adaptive-neighbor-lists.patch"
                await conn.sftp_put(str(ROOT / "tools/oxdna_memory/adaptive-neighbor-lists.patch"), patch_remote)
                await conn.sftp_put(str(args.input_dir / "topology.top"), f"{remote}/topology.top")
                await conn.sftp_put(str(args.input_dir / "conf.dat"), f"{remote}/conf.dat")
                await conn.mkdir_p(f"{remote}/baseline")
                await conn.mkdir_p(f"{remote}/adaptive")
                await upload_text(conn, input_text(args.input_dir / "input.txt", adaptive=False, steps=args.steps), f"{remote}/baseline/input.txt")
                await upload_text(conn, input_text(args.input_dir / "input.txt", adaptive=True, steps=args.steps), f"{remote}/adaptive/input.txt")

                arch = target.cuda_arch
                baseline = f"{REMOTE_ROOT}/engines/{OXDNA_REV}-upstream-sm{arch}"
                source = f"{REMOTE_ROOT}/source-{OXDNA_REV}-upstream"
                build = f"""set -euo pipefail
for d in /usr/local/cuda/bin /usr/local/cuda-12.8/bin /usr/local/cuda-12.9/bin /usr/local/cuda-13.0/bin; do test -x "$d/nvcc" && export PATH="$d:$PATH" && break; done
if test ! -x {shlex.quote(baseline + '/bin/oxDNA')}; then
  test -d {shlex.quote(source + '/.git')} || git clone {shlex.quote(OXDNA_URL)} {shlex.quote(source)}
  git -C {shlex.quote(source)} fetch --depth 1 origin {shlex.quote(OXDNA_REV)}
  git -C {shlex.quote(source)} checkout --detach {shlex.quote(OXDNA_REV)}
  git -C {shlex.quote(source)} reset --hard {shlex.quote(OXDNA_REV)}
  cmake -S {shlex.quote(source)} -B {shlex.quote(source + '/build-sm' + arch)} -DCMAKE_BUILD_TYPE=Release -DCUDA=ON -DCMAKE_CUDA_ARCHITECTURES={arch}
  cmake --build {shlex.quote(source + '/build-sm' + arch)} -j"$(nproc)" --target oxDNA
  mkdir -p {shlex.quote(baseline + '/bin')} {shlex.quote(baseline + '/lib')}
  install -m 0755 {shlex.quote(source + '/build-sm' + arch + '/bin/oxDNA')} {shlex.quote(baseline + '/bin/oxDNA')}
  install -m 0755 {shlex.quote(source + '/build-sm' + arch + '/src/liboxdna_common.so')} {shlex.quote(baseline + '/lib/liboxdna_common.so')}
fi
"""
                print("building/checking pinned upstream baseline", flush=True)
                built = await conn.run(f"bash -lc {shlex.quote(build)}", timeout=1800)
                if built.rc != 0:
                    combined = (built.stdout or "") + "\n--- stderr ---\n" + (built.stderr or "")
                    raise RuntimeError(f"baseline build failed: {combined[-12000:]}")
                adaptive_build = render_build_script(arch, patch_remote)
                print("building/checking adaptive-memory engine", flush=True)
                built = await conn.run(f"bash -lc {shlex.quote(adaptive_build)}", timeout=1800)
                if built.rc != 0:
                    combined = (built.stdout or "") + "\n--- stderr ---\n" + (built.stderr or "")
                    raise RuntimeError(f"adaptive build failed: {combined[-12000:]}")

                results = {}
                for label, binary in (
                    ("baseline", baseline + "/bin/oxDNA"),
                    ("adaptive", engine_dir(arch) + "/bin/oxDNA"),
                ):
                    command = f"cd {shlex.quote(remote + '/' + label)} && {shlex.quote(binary)} input.txt >stdout.log 2>stderr.log"
                    print(f"running {label} trial", flush=True)
                    run = await conn.run(command, timeout=900)
                    log = await conn.read_file(f"{remote}/{label}/stderr.log")
                    match = RATE_RE.search(log)
                    results[label] = {
                        "rc": run.rc,
                        "ms_per_step": float(match.group(1)) if match else None,
                        "adaptive_telemetry": "CUDA adaptive neighbour telemetry:" in log,
                        "error_tail": "\n".join(log.splitlines()[-30:]) if run.rc else "",
                    }
                    artifact_dir = args.output.parent / "artifacts" / label
                    artifact_dir.mkdir(parents=True, exist_ok=True)
                    for artifact in ("input.txt", "energy.dat", "last_conf.dat", "stderr.log"):
                        try:
                            await conn.sftp_get(
                                f"{remote}/{label}/{artifact}",
                                str(artifact_dir / artifact),
                            )
                        except Exception as exc:
                            results[label].setdefault("artifact_errors", []).append(
                                f"{artifact}: {exc}"
                            )
                if results["baseline"]["ms_per_step"] and results["adaptive"]["ms_per_step"]:
                    results["speedup"] = results["baseline"]["ms_per_step"] / results["adaptive"]["ms_per_step"]
                particle_count = int((args.input_dir / "topology.top").read_text().split()[0])
                return {
                    "pod_id": pod.id, "gpu": target.label, "cuda_arch": target.cuda_arch,
                    "source_revision": OXDNA_REV, "particles": particle_count, "steps": args.steps,
                    "quoted_rate_usd_per_hour": rate, "actual_rate_usd_per_hour": actual_rate,
                    "results": results,
                }
            finally:
                await conn.close()
    finally:
        if pod_id:
            ledger.close_pod(pod_id)
        await client.aclose()
        spent = ledger.spent_usd()
        print(f"pod terminated; campaign spend ${spent:.4f}/${args.budget:.2f}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--budget", type=float, default=3.0)
    parser.add_argument("--max-seconds", type=int, default=2100)
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--gpu", choices=("h200", "rtx6000"), default="rtx6000")
    parser.add_argument("--volume", default="77pnhye88p")
    parser.add_argument("--no-volume", action="store_true")
    parser.add_argument("--pod-name", default="nadoc-oxdna-adaptive-benchmark")
    parser.add_argument("--remote-name", default="bench-adaptive-vs-upstream")
    parser.add_argument("--ledger-note", default="adaptive vs upstream oxDNA benchmark")
    parser.add_argument("--input-dir", type=Path, default=ROOT / "workspace/runpod_oxdna_validation/bigo32-smoke-input")
    parser.add_argument("--output", type=Path, default=ROOT / "workspace/runpod_oxdna_benchmark/report.json")
    parser.add_argument("--ledger", type=Path, default=ROOT / "workspace/runpod_oxdna_benchmark/spend.json")
    args = parser.parse_args()
    if not 0 < args.budget <= 3.0:
        parser.error("budget must be in (0, 3]")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = asyncio.run(main_async(args))
    result["campaign_spent_usd"] = CampaignLedger(args.ledger, cap_usd=args.budget).spent_usd()
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
