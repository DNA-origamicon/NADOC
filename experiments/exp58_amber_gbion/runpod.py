#!/usr/bin/env python3
"""Bounded RunPod launcher for the native Amber26 GBION duplex gate."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.runpod_api import RunpodClient, termination_deadline  # noqa: E402
from experiments.exp43_runpod_bench.campaign_common import (  # noqa: E402
    confirmed_pod,
    container_payload,
)
from experiments.exp43_runpod_bench.runpod_confirm import (  # noqa: E402
    ConfirmationLog,
    Receipt,
    guarded_step,
)
from experiments.exp43_runpod_bench.spend_ledger import SpendLedger  # noqa: E402
from experiments.exp58_amber_gbion.model import (  # noqa: E402
    EXPECTED_AMBER26_MD5,
    EXPECTED_AMBER26_SHA256,
    require_amber26_archive,
)


HERE = Path(__file__).resolve().parent
ARCHIVE = Path(
    os.environ.get(
        "NADOC_RUNPOD_ARCHIVE",
        "/media/jojo/Archive/nadoc_amber_exp58/duplex_runpod",
    )
)
REMOTE = "/root/nadoc-amber-gbion"
AMBER_TARBALL = Path(
    os.environ.get("NADOC_AMBER26_TARBALL", "/home/jojo/Downloads/pmemd26.tar.bz2")
)
INPUT_DESIGN = Path(
    os.environ.get(
        "NADOC_AMBER_GBION_DESIGN",
        "/media/jojo/Archive/nadoc_openmm_exp57/duplex_runpod/design.nadoc",
    )
)
BUDGET_USD = 5.0
TEARDOWN_RESERVE_USD = 0.25
PROVIDER_LIFETIME_S = 4 * 60 * 60
CONTROLLER_TIMEOUT_S = 3.75 * 60 * 60
POLL_S = 20
POD_NAME = "nadoc-exp58-amber26-gbion"
# Amber's portable CUDA build emits every large translation unit for eight GPU
# architectures and two precision modes.  The 6HB follow-up proved that even four jobs
# can overlap the two coarse-grid units and exceed 251 GiB.  Keep the generic portable
# launcher serial; the Ada-only 6HB launcher uses its source-level SM8.9 patch and four.
AMBER_BUILD_JOBS = 1

GPU_CANDIDATES = (
    ("NVIDIA GeForce RTX 4090", "RTX 4090", 0.69),
    ("NVIDIA RTX 6000 Ada Generation", "RTX 6000 Ada", 0.77),
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("exp58-amber-gbion")
for noisy in ("asyncssh", "httpx", "httpcore"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


def digest(path: Path, algorithm: str) -> str:
    result = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def verify_inputs() -> dict:
    amber = require_amber26_archive(AMBER_TARBALL)
    md5 = digest(amber, "md5")
    sha = digest(amber, "sha256")
    if md5 != EXPECTED_AMBER26_MD5 or sha != EXPECTED_AMBER26_SHA256:
        raise RuntimeError(
            f"Amber26 archive checksum mismatch (md5={md5}, sha256={sha}); no pod created"
        )
    if not INPUT_DESIGN.is_file():
        raise FileNotFoundError(f"duplex design is missing: {INPUT_DESIGN}")
    return {
        "amber26": str(amber.resolve()),
        "amber26_md5": md5,
        "amber26_sha256": sha,
        "design": str(INPUT_DESIGN.resolve()),
    }


def make_source_tar(path: Path) -> None:
    with tarfile.open(path, "w:gz", compresslevel=1) as archive:
        archive.add(ROOT / "backend" / "__init__.py", arcname="backend/__init__.py")
        archive.add(ROOT / "backend" / "core", arcname="backend/core")
        archive.add(
            HERE / "__init__.py", arcname="experiments/exp58_amber_gbion/__init__.py"
        )
        archive.add(HERE / "model.py", arcname="experiments/exp58_amber_gbion/model.py")
        experiments_init = ROOT / "experiments" / "__init__.py"
        if experiments_init.is_file():
            archive.add(experiments_init, arcname="experiments/__init__.py")


def payload(gpu_id: str, label: str, deadline: str) -> dict:
    result = container_payload(POD_NAME, [gpu_id], disk_gb=70)
    result["terminateAfter"] = deadline
    # Amber26's own CMake guard explicitly supports CUDA 12.7 <= v < 12.9.
    result["allowedCudaVersions"] = ["12.8"]
    result["env"] = {
        "NADOC_EXPERIMENT": "exp58-amber26-gbion",
        "NADOC_BUDGET_USD": str(BUDGET_USD),
        "NADOC_GPU_LABEL": label,
    }
    return result


def chain_text() -> str:
    return f"""#!/usr/bin/env bash
set -uo pipefail
cd {REMOTE}
chain_rc=0
(
  set -euo pipefail
  echo 'PHASE system_dependencies'
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends build-essential gfortran cmake flex bison patch curl ca-certificates bzip2 zlib1g-dev libbz2-dev libnetcdf-dev libnetcdff-dev
  command -v nvcc
  nvcc --version

  echo 'PHASE ambertools26_install'
  curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest | tar -xj -C /usr/local/bin --strip-components=1 bin/micromamba
  export MAMBA_ROOT_PREFIX=/opt/micromamba
  micromamba create -y -p /opt/ambertools26 -c conda-forge \
    ambertools=26.0 netcdf4 pydantic=2.12.5
  /opt/ambertools26/bin/tleap -h >/dev/null 2>&1 || true
  /opt/ambertools26/bin/python -c 'import netCDF4, numpy, parmed, pydantic; print("AmberTools Python dependencies ready")'

  echo 'PHASE amber26_extract'
  tar -xjf pmemd26.tar.bz2
  mkdir -p amber26-build
  cd amber26-build
  echo 'PHASE amber26_cmake'
  cmake ../pmemd26_src -Wno-dev \
    -DCMAKE_INSTALL_PREFIX=/opt/amber26 \
    -DCOMPILER=GNU -DMPI=FALSE -DCUDA=TRUE -DINSTALL_TESTS=TRUE \
    -DDOWNLOAD_MINICONDA=FALSE -DBUILD_PYTHON=FALSE \
    -DBUILD_PERL=FALSE -DBUILD_GUI=FALSE \
    -DPMEMD_ONLY=TRUE -DCHECK_UPDATES=FALSE 2>&1 | tee {REMOTE}/cmake.log
  echo 'PHASE amber26_compile'
  cmake --build . --target install -j {AMBER_BUILD_JOBS} 2>&1 | tee {REMOTE}/build.log
  test -x /opt/amber26/bin/pmemd.cuda
  test -x /opt/amber26/bin/pmemd

  echo 'PHASE native_validation'
  cd {REMOTE}
  export AMBERHOME=/opt/amber26
  export TLEAP=/opt/ambertools26/bin/tleap
  export NADOC_REMOTE_ROOT={REMOTE}
  export NADOC_OUTPUT_DIR={REMOTE}/output
  export PYTHONPATH={REMOTE}
  /opt/ambertools26/bin/python runpod_worker.py
) || chain_rc=$?
echo "$chain_rc" > chain.exit
exit "$chain_rc"
"""


async def launch_receipt(conn, pod_id: str, pid: int) -> Receipt:
    await asyncio.sleep(10)
    alive = await conn.pid_alive(pid)
    phase = await conn.run(
        f"tail -n 80 {REMOTE}/nadoc_chain.out 2>/dev/null | "
        "grep 'PHASE ' | tail -n 1 || true",
        retries=2,
    )
    size = await conn.run(
        f"stat -c %s {REMOTE}/nadoc_chain.out 2>/dev/null || echo 0", retries=2
    )
    evidence = {
        "pid": pid,
        "alive": alive,
        "phase": (phase.stdout or "").strip(),
        "log_bytes": int((size.stdout or "0").strip() or 0),
    }
    return Receipt("launch", pod_id, alive, evidence, time.time())


async def download_if_present(conn, remote: str, local: str | None = None) -> None:
    check = await conn.run(f"test -f {REMOTE}/{remote}")
    if check.rc == 0:
        target = ARCHIVE / (local or Path(remote).name)
        await asyncio.wait_for(
            conn.sftp_get(f"{REMOTE}/{remote}", str(target)), timeout=1200
        )


async def main() -> None:
    # All local/license/budget checks occur before the first provider call.
    inputs = verify_inputs()
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    confirmations = ConfirmationLog(ARCHIVE)
    confirmations.require_clean()
    ledger = SpendLedger(ARCHIVE / "spend.json")
    if ledger.spent() >= BUDGET_USD - TEARDOWN_RESERVE_USD:
        raise RuntimeError(f"exp58 budget unavailable: ${ledger.spent():.4f} already spent")
    key_path = Path.home() / ".runpod_key"
    key = os.environ.get("RUNPOD_API_KEY") or (
        key_path.read_text().strip() if key_path.is_file() else ""
    )
    if not key:
        raise RuntimeError("RunPod key is unavailable; no pod created")

    source_tar = ARCHIVE / "nadoc-source.tar.gz"
    make_source_tar(source_tar)
    chain = ARCHIVE / "nadoc_chain.sh"
    chain.write_text(chain_text())
    client = RunpodClient(key, audit_dir=ARCHIVE)
    # RunPod supports concurrent isolated pods. Refuse only a stale/live pod owned
    # by this campaign; never block on or terminate another agent's named workload.
    existing = await client.list_pods()
    ledger_owned_ids = set(ledger.live_pods())
    owned_live = [
        {"id": pod.id, "name": pod.raw.get("name")}
        for pod in existing
        if not pod.is_terminated
        and (pod.id in ledger_owned_ids or pod.raw.get("name") == POD_NAME)
    ]
    if owned_live:
        await client.aclose()
        raise RuntimeError(f"an exp58-owned RunPod pod is already live: {owned_live}")

    deadline = termination_deadline(PROVIDER_LIFETIME_S)
    payloads = [payload(gpu, label, deadline) for gpu, label, _ in GPU_CANDIDATES]
    summary = {
        "budget_usd": BUDGET_USD,
        "teardown_reserve_usd": TEARDOWN_RESERVE_USD,
        "provider_deadline": deadline,
        "inputs": inputs,
    }
    run_started = time.time()
    try:
        async with confirmed_pod(
            client,
            ledger,
            confirmations,
            payloads[0],
            "exp58 native Amber26 GBION duplex",
            fallbacks=payloads[1:],
            usd_hr_hint=max(rate for _, _, rate in GPU_CANDIDATES),
            wait_timeout_s=900,
        ) as (pod, conn):
            rate = float(pod.cost_per_hr or max(rate for _, _, rate in GPU_CANDIDATES))
            gpu = await conn.run(
                "nvidia-smi --query-gpu=name,memory.total,driver_version "
                "--format=csv,noheader",
                timeout=30,
            )
            summary.update(
                {"pod_id": pod.id, "usd_per_hour": rate, "gpu": (gpu.stdout or "").strip()}
            )
            log.info("pod=%s rate=$%.3f/hr gpu=%s", pod.id, rate, summary["gpu"])
            await conn.mkdir_p(f"{REMOTE}/output")
            transfers = (
                (source_tar, f"{REMOTE}/nadoc-source.tar.gz"),
                (HERE / "runpod_worker.py", f"{REMOTE}/runpod_worker.py"),
                (AMBER_TARBALL, f"{REMOTE}/pmemd26.tar.bz2"),
                (INPUT_DESIGN, f"{REMOTE}/input.nadoc"),
                (chain, f"{REMOTE}/nadoc_chain.sh"),
            )
            for local, remote in transfers:
                log.info("uploading %s (%d bytes)", local.name, local.stat().st_size)
                await asyncio.wait_for(conn.sftp_put(str(local), remote), timeout=2400)
            unpack = await conn.run(
                f"cd {REMOTE} && tar -xzf nadoc-source.tar.gz", timeout=600
            )
            if unpack.rc != 0:
                raise RuntimeError(f"NADOC source unpack failed: {unpack.stderr[-1000:]}")
            pid = await conn.launch_detached(f"{REMOTE}/nadoc_chain.sh", REMOTE)
            summary["chain_pid"] = pid
            async with guarded_step("launch", pod.id, confirmations) as step:
                step.receipt(await launch_receipt(conn, pod.id, pid))

            last_phase = ""
            while True:
                elapsed = time.time() - run_started
                current_spend = ledger.spent()
                if current_spend >= BUDGET_USD - TEARDOWN_RESERVE_USD:
                    raise RuntimeError(
                        f"controller budget stop at ${current_spend:.3f}; "
                        f"reserve=${TEARDOWN_RESERVE_USD:.2f}"
                    )
                if elapsed >= CONTROLLER_TIMEOUT_S:
                    raise RuntimeError("controller timeout before exp58 completed")
                exit_result = await conn.run(
                    f"cat {REMOTE}/chain.exit 2>/dev/null || true", retries=2
                )
                exit_text = (exit_result.stdout or "").strip()
                phase_result = await conn.run(
                    f"cat {REMOTE}/output/status.json 2>/dev/null || "
                    f"tail -n 120 {REMOTE}/nadoc_chain.out 2>/dev/null | "
                    "grep 'PHASE ' | tail -n 1 || true",
                    retries=2,
                )
                phase_text = (phase_result.stdout or "").strip()
                if phase_text and phase_text != last_phase:
                    log.info("remote progress: %s cost=$%.3f", phase_text[-500:], current_spend)
                    last_phase = phase_text
                if exit_text:
                    if exit_text != "0":
                        tail = await conn.run(
                            f"tail -c 20000 {REMOTE}/nadoc_chain.out 2>/dev/null || true",
                            retries=2,
                        )
                        raise RuntimeError(
                            f"remote chain failed rc={exit_text}: "
                            + (tail.stdout or "")[-6000:]
                        )
                    break
                if not await conn.pid_alive(pid):
                    tail = await conn.run(
                        f"tail -c 20000 {REMOTE}/nadoc_chain.out 2>/dev/null || true",
                        retries=2,
                    )
                    raise RuntimeError(
                        "remote chain died without exit sentinel: "
                        + (tail.stdout or "")[-6000:]
                    )
                await asyncio.sleep(POLL_S)

            for remote in (
                "output/result.json",
                "output/status.json",
                "output/gbion.parm7",
                "output/gbion.rst7",
                "output/disang_NaCl.txt",
                "output/gb_benchmark.rst7",
                "output/gb_production.rst7",
                "output/gb_production.nc",
                "output/gb_production.mdout",
                "output/explicit.parm7",
                "output/explicit.rst7",
                "output/explicit_benchmark.mdout",
                "cmake.log",
                "build.log",
                "nadoc_chain.out",
            ):
                await download_if_present(conn, remote)
            result = json.loads((ARCHIVE / "result.json").read_text())
            summary.update(
                {
                    "completed": True,
                    "basic_validation_passed": result["basic_validation_passed"],
                    "gbion_ns_per_day": result["gbion"]["benchmark"]["wall_ns_per_day"],
                    "same_gpu_speedup": result["speedup_vs_same_gpu_explicit"],
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
    # confirmed_pod has now proved termination and closed the ledger row.
    summary["estimated_cost_usd"] = ledger.spent()
    (ARCHIVE / "controller_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
