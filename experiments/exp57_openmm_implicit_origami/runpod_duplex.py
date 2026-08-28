#!/usr/bin/env python3
"""Rent one bounded RunPod GPU and execute the exp57 duplex validation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.runpod_api import RunpodClient, termination_deadline
from experiments.exp43_runpod_bench.campaign_common import (
    confirmed_pod,
    container_payload,
)
from experiments.exp43_runpod_bench.runpod_confirm import (
    ConfirmationLog,
    Receipt,
    guarded_step,
)
from experiments.exp43_runpod_bench.spend_ledger import SpendLedger

HERE = Path(__file__).resolve().parent
ARCHIVE = Path(
    os.environ.get(
        "NADOC_RUNPOD_ARCHIVE",
        "/media/jojo/Archive/nadoc_openmm_exp57/duplex_runpod",
    )
)
REMOTE = os.environ.get("NADOC_RUNPOD_REMOTE", "/root/nadoc-openmm-duplex")
WORKER_PATH = Path(
    os.environ.get("NADOC_RUNPOD_WORKER", HERE / "runpod_duplex_worker.py")
).resolve()
INPUT_DESIGN = os.environ.get("NADOC_RUNPOD_INPUT_DESIGN")
BUDGET_USD = float(os.environ.get("NADOC_RUNPOD_BUDGET_USD", "5.0"))
TEARDOWN_RESERVE_USD = 0.25
PROVIDER_LIFETIME_S = 2 * 60 * 60
POLL_S = 15
CONTROLLER_TIMEOUT_S = 90 * 60

# One cheap, fast small-system card plus one same-generation fallback.  The
# provider expiry limits either to far below $5 even if the controller disappears.
GPU_CANDIDATES = (
    ("NVIDIA GeForce RTX 4090", "RTX 4090", 0.69),
    ("NVIDIA RTX 6000 Ada Generation", "RTX 6000 Ada", 0.77),
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("exp57-runpod-duplex")
for noisy in ("asyncssh", "httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def _make_source_tar(path: Path) -> None:
    with tarfile.open(path, "w:gz") as archive:
        archive.add(ROOT / "backend" / "__init__.py", arcname="backend/__init__.py")
        archive.add(ROOT / "backend" / "core", arcname="backend/core")


def _payload(gpu_id: str, label: str, deadline: str) -> dict:
    payload = container_payload(
        "nadoc-exp57-openmm-duplex",
        [gpu_id],
        disk_gb=35,
    )
    payload["terminateAfter"] = deadline
    # pip currently resolves the CUDA-12 extra to NVRTC 12.9.  A 12.8-era
    # driver rents successfully but fails Context creation with PTX error 222.
    payload["allowedCudaVersions"] = ["12.9", "13.0"]
    payload["env"] = {
        "NADOC_EXPERIMENT": "exp57-openmm-duplex",
        "NADOC_BUDGET_USD": str(BUDGET_USD),
        "NADOC_GPU_LABEL": label,
    }
    return payload


async def _launch_receipt(conn, pod_id: str) -> Receipt:
    await asyncio.sleep(8)
    proc = await conn.run(
        "pgrep -af '[n]adoc_chain.sh|[r]unpod_.*_worker.py' || true", retries=2
    )
    size = await conn.run(
        f"stat -c %s {REMOTE}/nadoc_chain.out 2>/dev/null || echo 0", retries=2
    )
    alive = bool((proc.stdout or "").strip())
    log_bytes = int((size.stdout or "0").strip() or 0)
    return Receipt(
        "launch",
        pod_id,
        # A freshly created venv can keep the chain quiet for several seconds.
        # The detached process identity is the launch proof; log growth is
        # subsequently enforced by phase/exit/process monitoring.
        alive,
        {
            "processes": (proc.stdout or "")[:400],
            "log_bytes": log_bytes,
        },
        time.time(),
    )


async def _download_if_present(conn, remote_name: str, local_name: str | None = None):
    exists = await conn.run(f"test -f {REMOTE}/output/{remote_name}")
    if exists.rc == 0:
        await asyncio.wait_for(
            conn.sftp_get(
                f"{REMOTE}/output/{remote_name}",
                str(ARCHIVE / (local_name or remote_name)),
            ),
            timeout=600,
        )


async def main() -> None:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    source_tar = ARCHIVE / "backend-core.tar.gz"
    _make_source_tar(source_tar)
    key = os.environ.get("RUNPOD_API_KEY") or (Path.home() / ".runpod_key").read_text().strip()
    ledger = SpendLedger(ARCHIVE / "spend.json")
    if ledger.spent() >= BUDGET_USD - TEARDOWN_RESERVE_USD:
        raise RuntimeError(f"exp57 budget already exhausted: ${ledger.spent():.2f}")
    clog = ConfirmationLog(ARCHIVE)
    clog.require_clean()
    client = RunpodClient(key, audit_dir=ARCHIVE)
    deadline = termination_deadline(PROVIDER_LIFETIME_S)
    payloads = [_payload(gpu, label, deadline) for gpu, label, _ in GPU_CANDIDATES]
    run_started = time.time()
    summary = {"budget_usd": BUDGET_USD, "provider_deadline": deadline}
    try:
        async with confirmed_pod(
            client,
            ledger,
            clog,
            payloads[0],
            "exp57 OpenMM duplex",
            fallbacks=payloads[1:],
            usd_hr_hint=max(rate for _, _, rate in GPU_CANDIDATES),
        ) as (pod, conn):
            rate = float(pod.cost_per_hr or max(r for _, _, r in GPU_CANDIDATES))
            summary.update({"pod_id": pod.id, "usd_per_hour": rate})
            gpu = await conn.run(
                "nvidia-smi --query-gpu=name,memory.total,driver_version "
                "--format=csv,noheader",
                timeout=30,
            )
            summary["gpu"] = (gpu.stdout or "").strip()
            log.info("pod %s up at $%.3f/hr: %s", pod.id, rate, summary["gpu"])

            await conn.mkdir_p(f"{REMOTE}/output")
            await conn.sftp_put(str(source_tar), f"{REMOTE}/backend-core.tar.gz")
            await conn.sftp_put(
                str(WORKER_PATH),
                f"{REMOTE}/{WORKER_PATH.name}",
            )
            # Variant workers can reuse the proven timing and CUDA helpers.
            default_worker = (HERE / "runpod_duplex_worker.py").resolve()
            if WORKER_PATH != default_worker:
                await conn.sftp_put(
                    str(default_worker), f"{REMOTE}/runpod_duplex_worker.py"
                )
            if INPUT_DESIGN:
                await conn.sftp_put(str(Path(INPUT_DESIGN).resolve()), f"{REMOTE}/input.nadoc")
            unpack = await conn.run(
                f"cd {REMOTE} && tar -xzf backend-core.tar.gz", timeout=300
            )
            if unpack.rc != 0:
                raise RuntimeError(f"source unpack failed: {unpack.stderr[:300]}")

            chain = ARCHIVE / "nadoc_chain.sh"
            chain.write_text(
                "#!/usr/bin/env bash\n"
                "set -uo pipefail\n"
                f"cd {REMOTE}\n"
                "python -m venv .venv\n"
                "venv_rc=$?\n"
                "if [ $venv_rc -eq 0 ]; then\n"
                ".venv/bin/python -m pip install --no-cache-dir "
                "'openmm[cuda12]==8.6.0' 'numpy==2.4.3' "
                "'scipy==1.17.1' 'pydantic==2.12.5'\n"
                "  install_rc=$?\n"
                "else\n"
                "  install_rc=$venv_rc\n"
                "fi\n"
                "if [ $install_rc -eq 0 ]; then\n"
                f"  NADOC_OUTPUT_DIR={REMOTE}/output PYTHONPATH=. "
                f".venv/bin/python {WORKER_PATH.name}\n"
                "  worker_rc=$?\n"
                "else\n"
                "  worker_rc=$install_rc\n"
                "fi\n"
                "echo $worker_rc > chain.exit\n"
                "exit $worker_rc\n"
            )
            await conn.sftp_put(str(chain), f"{REMOTE}/nadoc_chain.sh")
            pid = await conn.launch_detached(f"{REMOTE}/nadoc_chain.sh", REMOTE)
            summary["chain_pid"] = pid
            async with guarded_step("launch", pod.id, clog) as step:
                step.receipt(await _launch_receipt(conn, pod.id))

            last_phase = None
            while True:
                elapsed = time.time() - run_started
                cost = elapsed / 3600.0 * rate
                if cost >= BUDGET_USD - TEARDOWN_RESERVE_USD:
                    raise RuntimeError(
                        f"controller budget stop at ${cost:.2f} (reserve ${TEARDOWN_RESERVE_USD})"
                    )
                if elapsed >= CONTROLLER_TIMEOUT_S:
                    raise RuntimeError("controller timeout before duplex validation completed")

                exit_result = await conn.run(
                    f"cat {REMOTE}/chain.exit 2>/dev/null || true", retries=2
                )
                exit_text = (exit_result.stdout or "").strip()
                status_result = await conn.run(
                    f"cat {REMOTE}/output/status.json 2>/dev/null || true", retries=2
                )
                if (status_result.stdout or "").strip():
                    try:
                        status = json.loads(status_result.stdout)
                    except json.JSONDecodeError:
                        status = {}
                    phase = status.get("phase")
                    if phase and phase != last_phase:
                        log.info("phase=%s cost=$%.3f", phase, cost)
                        last_phase = phase
                if exit_text:
                    if exit_text != "0":
                        tail = await conn.run(
                            f"tail -c 12000 {REMOTE}/nadoc_chain.out 2>/dev/null || true",
                            retries=2,
                        )
                        raise RuntimeError(
                            f"remote chain failed rc={exit_text}: {(tail.stdout or '')[-3000:]}"
                        )
                    break
                if not await conn.pid_alive(pid):
                    tail = await conn.run(
                        f"tail -c 12000 {REMOTE}/nadoc_chain.out 2>/dev/null || true",
                        retries=2,
                    )
                    raise RuntimeError(
                        "remote chain died without an exit sentinel: "
                        + (tail.stdout or "")[-3000:]
                    )
                await asyncio.sleep(POLL_S)

            for name in (
                "result.json",
                "status.json",
                "design.nadoc",
                "implicit.dcd",
                "implicit-final.cif",
                "implicit-final.chk",
                "implicit-final-state.xml",
                "explicit.dcd",
                "explicit-final.cif",
                "explicit-final.chk",
                "explicit-final-state.xml",
            ):
                await _download_if_present(conn, name)
            await conn.sftp_get(
                f"{REMOTE}/nadoc_chain.out", str(ARCHIVE / "chain.log")
            )
            result = json.loads((ARCHIVE / "result.json").read_text())
            summary.update(
                {
                    "completed": True,
                    "basic_stability_passed": result["basic_stability_passed"],
                    "implicit_speedup_vs_same_gpu_explicit": result.get(
                        "implicit_speedup_vs_same_gpu_explicit"
                    ),
                }
            )
    except Exception as exc:
        summary.update({"completed": False, "error": str(exc)})
        raise
    finally:
        summary["wall_seconds"] = time.time() - run_started
        summary["estimated_cost_usd"] = ledger.spent()
        (ARCHIVE / "controller_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n"
        )
        await client.aclose()

    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
