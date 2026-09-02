"""Pure workspace path/file helpers — HTTP-free filesystem logic for the
assembly workspace library.

Lives in `backend/core` (never imports `backend/api`): the dependency arrow is
api → core. The api route handlers (`# ── Workspace library` in assembly.py)
keep their decorators + `assembly_state` interaction and delegate the path
resolution, dedup, and on-disk reference patching here.

One reason to change: how workspace-relative paths are resolved/sanitized and
how a file/folder rename or move cascades into the `PartSourceFile.path`
references stored inside on-disk `.nass` files.

`safe_workspace_path` raises `ValueError` (not `HTTPException`) so this module
stays api-free; the api wrapper translates it to a 400.
"""

from __future__ import annotations

import json
from pathlib import Path

from backend.core.models import Assembly, PartSourceFile


# Workspace roots owned by NADOC's engines or development tooling.  They live beside
# user documents for compatibility and persistence, but are not part of the user's
# design library and must not be advertised by the welcome screen or its event feed.
INTERNAL_WORKSPACE_ROOTS = frozenset(
    {
        "autorefine",
        "benchmark_runs",
        "bench_fixtures",
        "blade_jobs",
        "builder_tests",
        "cando_autorefine",
        "cando_jobs",
        "lammps_jobs",
        "live_sessions",
        "logs",
        "md_chains",
        "md_jobs",
        "mrdna_jobs",
        "oxdna_jobs",
        "playwright_tests",
        "propagator_pilot",
        "snupi_jobs",
    }
)


def is_internal_workspace_path(rel_path: str | Path) -> bool:
    """Return whether a workspace-relative path belongs to an internal tree."""
    parts = Path(rel_path).parts
    if not parts:
        return False
    root = parts[0]
    return root.startswith((".", "__")) or root.endswith("_jobs") or root in INTERNAL_WORKSPACE_ROOTS


def safe_workspace_path(rel_path: str, workspace_dir: Path) -> Path:
    """Resolve rel_path within workspace_dir, rejecting path-traversal attempts.

    Raises ValueError if the resolved path escapes the workspace.
    """
    workspace_dir.mkdir(parents=True, exist_ok=True)
    resolved = (workspace_dir / rel_path).resolve()
    if not resolved.is_relative_to(workspace_dir.resolve()):
        raise ValueError("Invalid path: outside workspace")
    return resolved


def dedup_filename(stem: str, suffix: str, workspace_dir: Path) -> str:
    """Return a filename that does not already exist in workspace_dir."""
    workspace_dir.mkdir(parents=True, exist_ok=True)
    candidate = f"{stem}{suffix}"
    if not (workspace_dir / candidate).exists():
        return candidate
    n = 2
    while (workspace_dir / f"{stem}_{n}{suffix}").exists():
        n += 1
    return f"{stem}_{n}{suffix}"


def remap_source_path(sp: str, old_ref: str, new_ref: str) -> str | None:
    """Remap a single PartSourceFile.path under a rename/move.

    old_ref / new_ref:
      - file rename/move  → plain paths, e.g. "parts/2hb.nadoc"
      - folder rename/move → paths ending with "/", e.g. "old_dir/" → "new_dir/"

    Returns the new path, or None if `sp` is not affected.
    """
    if old_ref.endswith("/"):
        return (new_ref + sp[len(old_ref) :]) if sp.startswith(old_ref) else None
    return new_ref if sp == old_ref else None


def patch_nass_files(workspace_dir: Path, old_ref: str, new_ref: str) -> list[str]:
    """Cascade-update PartSourceFile.path across all on-disk .nass files.

    Returns the workspace-relative paths of the .nass files that were patched.
    Pure filesystem side effect; does not touch in-memory state.
    """
    patched: list[str] = []
    for nass_file in workspace_dir.rglob("*.nass"):
        try:
            raw = nass_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            changed = False
            # v1 (legacy) shape: per-instance ``source`` dicts in ``instances``.
            for inst in data.get("instances", []):
                src = inst.get("source", {})
                if src.get("type") == "file":
                    new_sp = remap_source_path(src.get("path", ""), old_ref, new_ref)
                    if new_sp is not None:
                        src["path"] = new_sp
                        changed = True
            # v2 (current) shape: deduplicated ``sources`` map keyed by src_key;
            # patch the path field of each file-source.  The src_key string itself
            # encodes the path too, but the loader resolves the source by reading
            # the ``path`` field — leaving the stale key in place is harmless.
            sources_map = data.get("sources")
            if isinstance(sources_map, dict):
                for src in sources_map.values():
                    if isinstance(src, dict) and src.get("type") == "file":
                        new_sp = remap_source_path(
                            src.get("path", ""), old_ref, new_ref
                        )
                        if new_sp is not None:
                            src["path"] = new_sp
                            changed = True
            if changed:
                nass_file.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                patched.append(str(nass_file.relative_to(workspace_dir)))
        except Exception:
            continue
    return patched


def patch_assembly_instances(
    assembly: Assembly, old_ref: str, new_ref: str
) -> Assembly | None:
    """Return a copy of `assembly` with file-source paths remapped under a
    rename/move, or None if nothing changed.

    Pure transform: the caller (api layer) decides whether to commit the result
    via `assembly_state.set_assembly_silent`.
    """
    new_insts = list(assembly.instances)
    changed = False
    for idx, inst in enumerate(new_insts):
        if inst.source.type == "file":
            new_sp = remap_source_path(inst.source.path, old_ref, new_ref)
            if new_sp is not None:
                new_insts[idx] = inst.model_copy(
                    update={"source": PartSourceFile(path=new_sp)}
                )
                changed = True
    if not changed:
        return None
    return assembly.model_copy(update={"instances": new_insts})
