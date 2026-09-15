"""Stage this frozen audit under workspace/validation; never alter the installed engine."""

from pathlib import Path
import argparse, hashlib, json, shutil, subprocess, tarfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DEST = REPO / "workspace/validation/physics_ab_20260913"
p = argparse.ArgumentParser()
p.add_argument("--build", action="store_true")
args = p.parse_args()
for relative, digest in json.loads(
    (HERE / "application_source_hashes.json").read_text()
).items():
    if hashlib.sha256((REPO / relative).read_bytes()).hexdigest() != digest:
        raise SystemExit(
            "Application renderer differs from audit baseline: " + relative
        )
source = Path.home() / ".local/share/nadoc/engines/oxdna/source"
expected = json.loads((HERE / "baseline_provenance.json").read_text())
revision = subprocess.check_output(
    ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
).strip()
if revision != expected["source_revision"]:
    raise SystemExit("Managed source revision differs from frozen audit baseline")
patch = subprocess.check_output(["git", "-C", str(source), "diff", "--no-color"])
if patch != (HERE / "baseline_source.patch").read_bytes():
    raise SystemExit(
        "Managed source patch differs; create a new audit directory and provenance record"
    )
DEST.mkdir(parents=True, exist_ok=True)
if not (DEST / "source").exists():
    shutil.copytree(
        source,
        DEST / "source",
        ignore=shutil.ignore_patterns(".git", "build*", "__pycache__"),
    )
for f in HERE.iterdir():
    if (
        f.suffix in [".py", ".sbatch", ".json", ".patch"]
        and f.name != "prepare_local.py"
    ):
        target = DEST / f.name
        if target.exists() and target.read_bytes() != f.read_bytes():
            raise SystemExit(
                "Refusing to overwrite existing audit file: " + str(target)
            )
        if not target.exists():
            shutil.copy2(f, target)
if not (DEST / "fixtures").exists():
    with tarfile.open(HERE / "fixtures.tar.gz") as t:
        t.extractall(DEST, filter="data")
for relative, digest in json.loads((HERE / "fixture_hashes.json").read_text()).items():
    if hashlib.sha256((DEST / relative).read_bytes()).hexdigest() != digest:
        raise SystemExit("Fixture mismatch: " + relative)
if args.build:
    subprocess.run(
        [
            "cmake",
            "-S",
            str(DEST / "source"),
            "-B",
            str(DEST / "build"),
            "-DCMAKE_BUILD_TYPE=Release",
            "-DCUDA=ON",
            "-DPython=OFF",
            "-DCUDA_COMMON_ARCH=OFF",
            "-DCMAKE_CUDA_ARCHITECTURES=75",
        ],
        check=True,
    )
    subprocess.run(
        [str(REPO / ".venv/bin/python"), str(DEST / "make_variants.py")], check=True
    )
print(DEST)
