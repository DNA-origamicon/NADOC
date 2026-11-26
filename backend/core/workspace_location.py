"""Machine-local workspace storage and the explicitly trusted shared library."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SHARED_FOLDER = "Shared Designs"


def default_workspace() -> Path:
    """Explicit environment, local storage link, then the checkout workspace."""
    if os.environ.get("NADOC_WORKSPACE"):
        return Path(os.environ["NADOC_WORKSPACE"])
    local = PROJECT_ROOT / ".nadoc-workspace"
    if local.is_symlink():
        if not local.is_dir():
            raise RuntimeError("Configured .nadoc-workspace storage is unavailable")
        return local.resolve()
    return PROJECT_ROOT / "workspace"


def linked_shared_root(workspace: Path) -> Path | None:
    """Trust only a root link to this checkout's tracked Shared Designs folder."""
    link = workspace / SHARED_FOLDER
    tracked = PROJECT_ROOT / "workspace" / SHARED_FOLDER
    if link.is_symlink() and tracked.is_dir() and link.resolve() == tracked.resolve():
        return tracked.resolve()
    return None
