"""Install NADOC's optional, pinned Blender/Cycles OptiX runtime (Linux x64)."""
import hashlib
import argparse
import json
from pathlib import Path
import platform
import shutil
import tarfile
import tempfile
import urllib.request

VERSION = "4.5.9"
SHA256 = "dcdc3eca6c9825bb35a8033b689c053f3cb5a9b0cd2a61b2eac2a49436b4ad3d"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", help="Use an existing Blender executable (including native Windows Blender from WSL)")
    args = parser.parse_args()
    if args.executable:
        executable = Path(args.executable).expanduser().resolve(strict=True)
        config = Path.home() / ".local/share/nadoc/renderers/optix.json"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps({"blender": str(executable)}, indent=2) + "\n")
        print(f"Configured {executable}; OptiX availability is checked on export.")
        return
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "AMD64"):
        raise SystemExit("Install Blender 4.5+ for your platform and set NADOC_BLENDER to its executable.")
    parent = Path.home() / ".local/share/nadoc/renderers"
    target = parent / f"blender-{VERSION}-linux-x64"
    if (target / "blender").is_file():
        print(target / "blender")
        return
    parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(parent).free < 3 * 1024**3:
        raise SystemExit("OptiX runtime installation needs 3 GiB free.")
    with tempfile.TemporaryDirectory(prefix="nadoc-blender-install-", dir=parent) as work:
        archive = Path(work) / "blender.tar.xz"
        url = f"https://download.blender.org/release/Blender4.5/{target.name}.tar.xz"
        print(f"Downloading pinned Blender {VERSION} from blender.org", flush=True)
        urllib.request.urlretrieve(url, archive)
        with archive.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != SHA256:
                raise SystemExit("Blender archive checksum mismatch.")
        with tarfile.open(archive) as bundle:
            bundle.extractall(work, filter="data")
        shutil.move(str(Path(work) / target.name), target)
    print(target / "blender")


if __name__ == "__main__":
    main()
