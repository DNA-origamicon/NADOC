"""Stage and submit the isolated 5 ns GPU junction continuation to Alpine."""

import asyncio
import hashlib
import json
from pathlib import Path
import shlex
import tarfile
from datetime import datetime, timezone
from backend.core.alpine_worker import WorkerClient
from backend.core.cluster_config import load_profiles

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "experiments/strep_biotin_namd/ws/junction_gpu_final"
OUT = ROOT / "experiments/strep_biotin_namd/ws/junction_alpine_5ns"


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "submission.json").exists():
        raise RuntimeError("Submission already recorded; do not duplicate the job.")
    profile = load_profiles(ROOT / "workspace")["alpine"]
    worker = WorkerClient()
    if not worker.is_connected():
        raise RuntimeError("Existing Alpine session is not connected")
    remote = f"/scratch/alpine/{worker.user}/nadoc_validation/biotin_dna_5ns_20260916"
    conf = (SOURCE / "check.conf").read_text()
    conf = conf.replace(str(SOURCE / "forcefield") + "/", "forcefield/")
    conf = conf[: conf.index("minimize 2000")]
    conf = conf.replace("temperature 300\n", "")
    conf = conf.replace("outputName check", "outputName continuation")
    conf = conf.replace("DCDfile check.dcd", "DCDfile continuation.dcd")
    conf = conf.replace("DCDfreq 100\n", "DCDfreq 10000\n")
    conf = conf.replace("restartfreq 1000\n", "restartfreq 100000\n")
    conf = conf.replace("outputEnergies 100\n", "outputEnergies 1000\n")
    conf += "\nbinCoordinates check.coor\nbinVelocities check.vel\nextendedSystem check.xsc\nfirsttimestep 22000\nrun 5000000\n"
    (OUT / "continuation.conf").write_text(conf)
    modules = "\n".join(
        "module load " + shlex.quote(m) for m in profile.modules_for(True)
    )
    batch = f"""#!/bin/bash
#SBATCH --job-name=biotin_dna_5ns
#SBATCH --account=ucb-general
#SBATCH --partition=ah200
#SBATCH --qos=gpu-normal
#SBATCH --gres=gpu:h200:1
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=16G
#SBATCH --time=08:00:00
#SBATCH --output=slurm-%j.out
set -euo pipefail
cd {shlex.quote(remote)}
module purge
{modules}
nvidia-smi --query-gpu=name,uuid,driver_version --format=csv
sha256sum -c inputs.sha256
{shlex.quote(profile.namd_command(True))} +p8 +devices 0 continuation.conf > namd.log 2>&1
grep -q 'Running with GPU-resident mode' namd.log
grep -q 'WRITING COORDINATES TO OUTPUT FILE AT STEP 5022000' namd.log
printf '%s\\n' 'Completed 5 ns GPU continuation' > completed.txt
"""
    (OUT / "submit.sbatch").write_text(batch)
    inputs = {
        p.name: p
        for p in [
            SOURCE / n
            for n in (
                "system.psf",
                "system.pdb",
                "check.coor",
                "check.vel",
                "check.xsc",
            )
        ]
    }
    inputs.update(
        {
            "forcefield/" + p.name: p
            for p in (SOURCE / "forcefield").iterdir()
            if p.is_file()
        }
    )
    inputs.update({n: OUT / n for n in ("continuation.conf", "submit.sbatch")})
    hashes = {
        name: hashlib.sha256(p.read_bytes()).hexdigest() for name, p in inputs.items()
    }
    (OUT / "inputs.sha256").write_text(
        "".join(f"{sha}  {name}\n" for name, sha in hashes.items())
    )
    inputs["inputs.sha256"] = OUT / "inputs.sha256"
    archive = OUT / "inputs.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, p in inputs.items():
            tar.add(p, arcname=name)
    result = await worker.run(
        "mkdir -p "
        + shlex.quote(str(Path(remote).parent))
        + " && mkdir "
        + shlex.quote(remote)
    )
    if result.rc:
        raise RuntimeError(result)
    await worker.sftp_put(str(archive), remote + "/inputs.tar.gz")
    result = await worker.run(
        f"cd {shlex.quote(remote)} && tar xzf inputs.tar.gz && sha256sum -c inputs.sha256 && sbatch --test-only submit.sbatch",
        timeout=60,
    )
    (OUT / "preflight.json").write_text(json.dumps(vars(result), indent=2))
    if result.rc:
        raise RuntimeError(result)
    result = await worker.run(
        f"cd {shlex.quote(remote)} && sbatch --parsable submit.sbatch", timeout=60
    )
    if result.rc:
        raise RuntimeError(result)
    job_id = result.stdout.strip().split(";")[0]
    if not job_id.isdigit():
        raise RuntimeError(result)
    record = {
        "job_id": job_id,
        "remote_dir": remote,
        "submitted_utc": datetime.now(timezone.utc).isoformat(),
        "additional_ns": 5,
        "first_step": 22000,
        "final_step": 5022000,
        "timestep_fs": 1,
        "ensemble": "NVT 300 K",
        "gpu": "H200, GPUresident on",
        "source": "junction_gpu_final validated 20 ps checkpoint",
        "parameter_qualification": "experimental transfer; this tests stability, not QM accuracy",
        "input_sha256": hashes,
    }
    (OUT / "submission.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))
    print(await worker.run(f'squeue -j {job_id} -o "%.18i %.12P %.25j %.8T %.10M %R"'))


if __name__ == "__main__":
    asyncio.run(main())
