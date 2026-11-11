"""Initialize an empty, independent design repository in the NADOC Library.

Does not commit, push, create molecular documents, or modify existing folders.
For subsequent machines, clone the repository at the same workspace-relative path.
"""

import argparse
import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
FOLDER = "Shared Designs"


def setup(workspace: Path) -> Path:
    destination = workspace.resolve() / FOLDER
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Refusing to replace existing workspace: {destination}")
    template = ROOT / "scripts" / "shared_design_workspace"
    # Read all inputs before creating anything. Git's default branch is kept;
    # no commits, remotes, hooks, credentials or main-repository settings change.
    files = {name: (template / name).read_bytes() for name in ("README.md", ".gitignore", "AGENTS.md")}
    destination.mkdir(parents=True)
    subprocess.run(["git", "init", "--quiet", str(destination)], check=True)
    for name, content in files.items():
        with (destination / name).open("xb") as stream:
            stream.write(content)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path(os.environ.get("NADOC_WORKSPACE", ROOT / "workspace")))
    args = parser.parse_args()
    print(setup(args.workspace))
    print("Local repository ready. No remote configured and no commits created.")


if __name__ == "__main__":
    main()
