"""Build the isolated CPD interaction against NADOC's installed oxDNA ABI."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def build(source, library, output):
    source, library, output = map(
        lambda p: Path(p).resolve(), (source, library, output)
    )
    output.mkdir(parents=True, exist_ok=True)
    cpp = Path(__file__).with_name("CpdDNA2.cpp").resolve()
    command = [
        os.environ.get("CXX", "c++"),
        "-std=c++17",
        "-O2",
        "-fPIC",
        "-shared",
        "-include",
        "string",
        "-I" + str(source / "src"),
        "-I" + str(source / "src/extern"),
        str(cpp),
        "-L" + str(library),
        "-Wl,-rpath," + str(library),
        "-loxdna_common",
        "-o",
        str(output / "CpdDNA2.so"),
    ]
    subprocess.run(command, check=True)

    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    manifest = {
        "command": command,
        "source_sha256": digest(cpp),
        "library_sha256": digest(library / "liboxdna_common.so"),
        "plugin_sha256": digest(output / "CpdDNA2.so"),
        "backend": "CPU",
    }
    (output / "build.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    root = Path.home() / ".local/share/nadoc/engines/oxdna"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cpu-only", action="store_true", help="Explicitly build CPU-only support")
    parser.add_argument("--source", type=Path, default=root / "source")
    parser.add_argument("--library", type=Path, default=root / "current/lib")
    parser.add_argument("--output", type=Path, default=root / "cpd-v1")
    args = parser.parse_args()
    manifest = build(args.source, args.library, args.output)
    if not args.cpu_only:
        from build_cuda import build_cuda
        manifest = build_cuda(args.source, args.library, args.output)
    print(json.dumps(manifest, indent=2))
