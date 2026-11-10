"""Build the local CPU submodel adapter beside, never over, the installed engine.

Usage: uv run python -m scripts.build_oxdna_submodel
Requires the source/library from scripts/build-oxdna.sh and a C++ compiler.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from tools.oxdna_submodel.build_md import build as build_md
from tools.oxdna_submodel.build_plugins import build as build_plugins


def build():
    root = Path(os.environ.get("NADOC_OXDNA_ROOT", Path.home()/".local/share/nadoc/engines/oxdna"))
    source = Path(os.environ.get("NADOC_OXDNA_SOURCE", root/"source")).resolve()
    library = (root/"current/lib").resolve()
    destination = Path(os.environ.get("NADOC_OXDNA_SUBMODEL_ROOT", Path.home()/".local/share/nadoc/engines/oxdna-submodel"))
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="build-", dir=destination) as scratch:
        scratch = Path(scratch)
        # Keep ABI/numerical compiler flags consistent with the installed native build.
        flags = sorted(source.glob("build-nadoc-*/src/CMakeFiles/oxdna_common.dir/flags.make"))
        if flags:
            for line in flags[0].read_text().splitlines():
                if line.startswith("CXX_FLAGS = "):
                    os.environ["CXXFLAGS"] = line.split(" = ", 1)[1]
        dependencies = subprocess.check_output(["ldd", str(library/"liboxdna_common.so")], text=True)
        runtime = [line.split("=>",1)[1].split()[0] for line in dependencies.splitlines()
                   if "libcudart.so" in line and "=>" in line and "not found" not in line]
        build_md(source, library, scratch/"md", runtime)
        build_plugins(source, library, scratch/"mc")
        manifest = json.loads((scratch/"md/build.json").read_text())
        manifest["interaction_sha256"] = hashlib.sha256((scratch/"mc/SubmodelDNA2.so").read_bytes()).hexdigest()
        version = destination/hashlib.sha256((manifest["binary_sha256"]+manifest["interaction_sha256"]).encode()).hexdigest()[:16]
        if version.exists():
            raise FileExistsError(f"Build already exists: {version}")
        shutil.copytree(scratch, version)
        # Both adapters link against the exact installed library; MC uses its normal executable.
        manifest.update(mc_binary=str((root/"current/bin/oxDNA").resolve()), version=2)
        (version/"installation.json").write_text(json.dumps(manifest, indent=2))
        temporary = destination/"current.new"
        temporary.symlink_to(version.name)
        temporary.replace(destination/"current")
        print(version)


if __name__ == "__main__":
    build()
