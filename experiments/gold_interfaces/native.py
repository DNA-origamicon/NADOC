"""Bounded native validation. All logs, configs and checkpoints remain inspectable."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import time

import numpy as np

from backend.core.namd_gold_package import config, verify_package, sha


def read_binary(path):
    data = Path(path).read_bytes()
    count = int(np.frombuffer(data[:4], dtype="<i4")[0])
    if len(data) != 4+24*count:
        raise ValueError(f"Invalid NAMD binary array {path}")
    return np.frombuffer(data[4:], dtype="<f8").reshape(count, 3).copy()


def checkpoint_step(package, prefix, *, require_finite=True):
    for ext in ("coor", "vel", "xsc"):
        if not (package/"output"/f"{prefix}.{ext}").is_file():
            raise ValueError(f"Incomplete checkpoint: {prefix}.{ext}")
    if require_finite and not all(np.isfinite(read_binary(package/"output"/f"{prefix}.{ext}")).all()
               for ext in ("coor", "vel")):
        raise ValueError(f"Nonfinite checkpoint: {prefix}")
    rows = (package/"output"/f"{prefix}.xsc").read_text().splitlines()
    return int(next(r.split()[0] for r in rows if r.strip() and not r.startswith("#")))


def run(package, binary, *, prefix, steps, dt=1., minimize=0, restart=None, thermostat=True,
        timeout=180):
    package = Path(package).resolve()
    binary = Path(binary).resolve()
    manifest = verify_package(package, binary)
    step = checkpoint_step(package, restart) if restart else 0
    conf = package/f"{prefix}.conf"
    log = package/f"{prefix}.log"
    if conf.exists() or log.exists() or list((package/"output").glob(prefix+".*")):
        raise FileExistsError(f"Native run prefix already exists: {prefix}")
    text = config(manifest, steps=steps, minimize=minimize, timestep_fs=dt,
                  prefix=prefix, restart=restart, first_step=step, thermostat=thermostat)
    conf.write_text(text)
    record = {"prefix": prefix, "steps": steps, "dt_fs": dt, "minimize": minimize,
              "restart": restart, "first_step": step, "engine": str(binary),
              "engine_sha256": sha(binary), "config_sha256": sha(conf),
              "timeout_s": timeout, "status": "running"}
    if restart:
        record["input_checkpoint_sha256"] = {e: sha(package/"output"/f"{restart}.{e}")
                                             for e in ("coor", "vel", "xsc")}
    result_path = package/f"{prefix}.result.json"
    result_path.write_text(json.dumps(record, indent=2)+"\n")
    started = time.monotonic()
    with log.open("x") as stream:
        try:
            native = subprocess.run([str(binary), "+p2", "+devices", "0", conf.name],
                                    cwd=package, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
            record["returncode"] = native.returncode
        except subprocess.TimeoutExpired:
            record["returncode"] = None
            record["status"] = "timeout"
    record["wall_s"] = time.monotonic()-started
    text = log.read_text()
    record["resident"] = "Running with GPU-resident mode" in text
    record["normal_exit"] = "End of program" in text and "FATAL ERROR" not in text and record["returncode"] == 0
    if record["normal_exit"]:
        record["final_step"] = checkpoint_step(package, prefix, require_finite=False)
        xyz, vel = [read_binary(package/"output"/f"{prefix}.{ext}") for ext in ("coor", "vel")]
        record["finite_checkpoint"] = bool(np.isfinite(xyz).all() and np.isfinite(vel).all())
        record["step_matches"] = record["final_step"] == step+steps+minimize
        record["status"] = "passed" if all(record[k] for k in ("resident", "finite_checkpoint", "step_matches")) else "failed"
    else:
        record["status"] = "failed" if record["status"] != "timeout" else "timeout"
    speed = re.findall(r"([0-9.]+) ns/day", text)
    if speed:
        record["last_ns_day"] = float(speed[-1])
    record["physical_validation"] = "not established by runtime success"
    result_path.write_text(json.dumps(record, indent=2)+"\n")
    print(json.dumps(record), flush=True)
    if record["status"] != "passed":
        raise RuntimeError(f"Native gold validation failed; inspect {log}")
    return record


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("package", type=Path)
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--prefix", required=True)
    p.add_argument("--steps", type=int, required=True)
    p.add_argument("--dt", type=float, default=1.)
    p.add_argument("--minimize", type=int, default=0)
    p.add_argument("--restart")
    p.add_argument("--timeout", type=int, default=180)
    a = p.parse_args()
    run(a.package, a.binary, prefix=a.prefix, steps=a.steps, dt=a.dt,
        minimize=a.minimize, restart=a.restart, timeout=a.timeout)
