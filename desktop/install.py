"""Register an unpacked NADOC release without sudo or modifying any user designs."""
import argparse
import hashlib
import shlex
import os
from pathlib import Path
import shutil


def configure_shared_library(destination: Path, shared: Path):
    """Explicitly bind this installation's trusted library to an existing folder.

    Existing workspace containment rules still accept only the exact configured
    target. No molecular files are copied, migrated or rewritten.
    """
    shared = shared.expanduser().resolve(strict=True)
    if not shared.is_dir():
        raise ValueError("Shared library must be an existing directory")
    trusted = destination / "resources/payload/workspace/Shared Designs"
    if trusted.exists() or trusted.is_symlink():
        raise FileExistsError("Installation already has a shared library binding")
    trusted.parent.mkdir(parents=True, exist_ok=True)
    trusted.symlink_to(shared, target_is_directory=True)


def prepare_linux_sandbox(destination: Path):
    """Prepare an exact-executable Ubuntu userns rule; applying it needs admin auth."""
    executable = str((destination / "NADOC").resolve(strict=True))
    if any(c in executable for c in '\n\r\x00"\\*?[]{}'):
        raise ValueError("Installation path contains AppArmor pattern characters")
    name = "nadoc-desktop-" + hashlib.sha256(executable.encode()).hexdigest()[:12]
    profile = destination / "nadoc.apparmor"
    profile.write_text('# Allow Chromium user namespaces for this NADOC executable only.\n'
                       'abi <abi/4.0>,\ninclude <tunables/global>\n'
                       f'profile {name} "{executable}" flags=(unconfined) {{\n  userns,\n}}\n')
    system_profile = "/etc/apparmor.d/" + name
    setup = destination / "enable-sandbox.sh"
    setup.write_text('#!/bin/sh\nset -eu\n'
                     f'/usr/bin/install -o root -g root -m 0644 -- {shlex.quote(str(profile))} {shlex.quote(system_profile)}\n'
                     f'/usr/sbin/apparmor_parser -r {shlex.quote(system_profile)}\n')
    setup.chmod(0o755)
    return setup


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--shared-designs", type=Path, help="Explicit trusted shared-library folder for linked external workspaces")
    args = parser.parse_args()
    if args.shared_designs is not None and not args.shared_designs.expanduser().is_dir():
        parser.error("Shared library must be an existing directory")
    source = Path(__file__).resolve().parent
    dest = args.destination.expanduser().resolve()
    if dest.is_relative_to(source) or source.is_relative_to(dest):
        parser.error("Installation and source release must be separate directories")
    if not (source / "NADOC.sh").is_file():
        parser.error("Run install.py from the built release directory")
    if dest.exists():
        parser.error("Destination already exists; choose a new version directory")
    apps = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "applications"
    entry = apps / "nadoc.desktop"
    if entry.exists():
        parser.error("nadoc.desktop already exists; preserve the existing installation")
    shutil.copytree(source, dest, symlinks=True)
    if args.shared_designs is not None:
        configure_shared_library(dest, args.shared_designs)
    setup = prepare_linux_sandbox(dest)
    apps.mkdir(parents=True, exist_ok=True)
    escaped = str(dest / "NADOC.sh").replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%')
    entry.write_text(f'[Desktop Entry]\nType=Application\nName=NADOC\nComment=DNA origami design\nExec="{escaped}"\nIcon={dest / "nadoc.svg"}\nTerminal=false\nCategories=Science;Education;\nStartupWMClass=NADOC\n')
    print(f"Ubuntu user-namespace restrictions may require: sudo {shlex.quote(str(setup))}")
    print(f"Installed {dest}\nApplication menu: {entry}")


if __name__ == "__main__":
    main()
