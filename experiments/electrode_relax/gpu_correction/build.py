"""Build an isolated GPU plugin against the installed NAMD ABI; never install."""

import argparse, subprocess, shlex, hashlib, json, shutil
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--source", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
p.add_argument("--fused", action="store_true")
p.add_argument("--warp-reduction", action="store_true")
a = p.parse_args()
b = a.source.resolve() / "Linux-x86_64-g++"
out = a.output.resolve()
out.mkdir(exist_ok=False, parents=True)
plan = (
    subprocess.check_output(
        ["make", "-n", "-W", "src/GlobalMasterTcl.C", "namd3"], cwd=b, text=True
    )
    .replace("\\\n", " ")
    .splitlines()
)
line = next(x for x in plan if x.startswith("g++ ") and "GlobalMasterTcl.o" in x)
flags = [x for x in shlex.split(line) if x.startswith(("-I", "-D"))]
if a.fused:
    flags.append("-DNADOC_FUSED")
if a.warp_reduction:
    flags.append("-DNADOC_WARP_REDUCTION")
shutil.copy2(Path(__file__).resolve().parents[3] / "backend/core/native/electrode_gpu.cu", out / "correction.cu")
# CUDA 12.0 requires a supported host compiler; do not override its version guard.
cmd = [
    "/home/jojo/cuda12.0/bin/nvcc",
    "-ccbin",
    "/usr/bin/g++-12",
    "-std=c++17",
    "-O3",
    "-arch=sm_86",
    *flags,
    "-Xcompiler",
    "-fPIC",
    "-shared",
    str(out / "correction.cu"),
    "-o",
    str(out / "electrode.so"),
]
with (out / "build.log").open("w") as f:
    subprocess.run(cmd, cwd=b, stdout=f, stderr=subprocess.STDOUT, check=True)
(out / "provenance.json").write_text(
    json.dumps(
        dict(
            correction_sha256=hashlib.sha256(
                (out / "correction.cu").read_bytes()
            ).hexdigest(),
            compiler=subprocess.check_output([cmd[0], "--version"], text=True),
            command=cmd,
            source=str(a.source.resolve()),
            plugin_sha256=hashlib.sha256(
                (out / "electrode.so").read_bytes()
            ).hexdigest(),
            installed_engine_sha256=hashlib.sha256(
                (b / "namd3").read_bytes()
            ).hexdigest(),
        ),
        indent=2,
    )
    + "\n"
)
print(out / "electrode.so")
