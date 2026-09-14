"""Portable native campaign runner; only derived metrics need downloading."""

from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import time

from collect_fixed_gold_metrics import _forces, _stage

ROOT = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument("--index", type=int, required=True)
parser.add_argument("--backend", choices=["CPU", "CUDA"], required=True)
parser.add_argument("--binary")
parser.add_argument("--interpose", action="store_true")
args = parser.parse_args()
plan = json.loads((ROOT / "campaign.json").read_text())
case = plan["cases"][args.index]
d = ROOT / ("runs_" + args.backend) / case["name"]
d.mkdir(parents=True, exist_ok=True)
settings = dict(case["settings"], backend=args.backend)
(d / "input").write_text("".join("%s = %s\n" % (k, v) for k, v in settings.items()))
binary = args.binary or str(ROOT / "engines" / case["variant"] / "bin/oxDNA")
env = dict(os.environ, OMP_NUM_THREADS="1")
if args.interpose:
    env["LD_PRELOAD"] = str(ROOT / "cpu_libraries" / (case["variant"] + ".so"))
report = dict(
    case=case["name"],
    geometry=case["geometry"],
    arm=case["arm"],
    backend=args.backend,
    seed=case["seed"],
    variant=case["variant"],
    state="running",
    binary_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest(),
)
report["input_sha256"] = hashlib.sha256((d / "input").read_bytes()).hexdigest()
library = Path(binary).parent.parent / "lib/liboxdna_common.so"
if library.exists():
    report["library_sha256"] = hashlib.sha256(library.read_bytes()).hexdigest()
status = ROOT / ("status_" + args.backend)
status.mkdir(exist_ok=True)
target = status / (str(args.index) + ".json")
temporary = target.with_suffix(".json.tmp")
temporary.write_text(json.dumps(report, indent=2))
temporary.replace(target)
try:
    start = time.monotonic()
    with (d / "run.log").open("w") as log:
        p = subprocess.run(
            [binary, "input"],
            cwd=str(d),
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            timeout=plan.get("timeout", 1200),
        )
    report["wall_seconds"] = time.monotonic() - start
    output = (d / "run.log").read_text(errors="replace")
    timer = re.search(r"Total Running Time: ([\d.eE+-]+) s", output)
    report["native_seconds"] = float(timer.group(1)) if timer else None
    if p.returncode:
        raise RuntimeError(output[-1800:])
    common = ROOT / "fixtures" / case["geometry"]
    anchors, tethers = _forces((common / "forces.txt").read_text())
    springs = [
        (int(v[0]), int(v[1]), float(v[2]))
        for v in [
            line.split() for line in (common / "anm.par").read_text().splitlines()[1:]
        ]
        if len(v) >= 5
    ]
    read = lambda path: Path(path).read_text()
    values = _stage(
        read,
        str(d) + "/",
        case["particles"],
        case["protein"],
        case["radius_nm"],
        anchors,
        tethers,
        springs,
        True,
    )
    report["metrics"] = values
    report["state"] = "completed"
except Exception as exc:
    report["state"] = "failed"
    report["error"] = str(exc)
finally:
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2))
    temporary.replace(target)
print(case["name"], report["state"], report.get("wall_seconds"), flush=True)
if report["state"] != "completed":
    raise SystemExit(1)
