"""Optional pose fitting after import; unsupported fits preserve the import."""

from backend.core.origami_relax import relax_origami


def relax_imported_design(design, *, enabled=False):
    if not enabled:
        return design, None
    try:
        relaxed, report = relax_origami(design)
    except ValueError as exc:
        return design, {"status": "skipped", "message": str(exc)}
    return relaxed, {**report, "status": "applied"}
