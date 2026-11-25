"""Create a shared design folder without initializing a nested Git repository.

Normal NADOC clones already include this folder. This helper only creates a
missing folder; custom workspace locations require explicit Git storage setup.
"""

import argparse
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FOLDER = "Shared Designs"


def setup(workspace: Path) -> Path:
    destination = workspace.resolve() / FOLDER
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Refusing to replace existing workspace: {destination}")
    template = ROOT / "scripts" / "shared_design_workspace"
    # Read all inputs before creating anything; preserve existing folders.
    files = {name: (template / name).read_bytes() for name in ("README.md", ".gitignore", "AGENTS.md")}
    destination.mkdir(parents=True)
    for name, content in files.items():
        with (destination / name).open("xb") as stream:
            stream.write(content)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path(os.environ.get("NADOC_WORKSPACE", ROOT / "workspace")))
    args = parser.parse_args()
    print(setup(args.workspace))
    print("Folder ready. Use the main NADOC repository to commit and push shared designs.")


if __name__ == "__main__":
    main()
