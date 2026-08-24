"""Unified simulation-job node shape — merge oxDNA + LAMMPS jobs into ONE list.

Phase C of the simulate-panel overhaul (``project_simulate_panel_overhaul``): the
Simulate front door shows a single hierarchical job list + master status card, so a
run must look the same whether it ran on GPU-oxDNA or CPU-LAMMPS (the auto engine-policy
picks the engine; the user shouldn't have to know which).  This module normalizes the
two very different job models — ``OxdnaJob`` (staged relaxation with parent/child
field-run branches) and the lean flat ``LammpsJob`` — into ONE common **node** dict the
frontend renders identically through the shared ``job_tree`` + ``jobs_panel_model``.

Pure + read-only.  Layer: normalizes/merges STATUS only — it never writes positions or
counts back into Design topology (Three-Layer Law; oxDNA/LAMMPS output is Physical /
display state).  The route (``routes_simulate.list_simulate_jobs``) does the I/O
(reconcile + fingerprint + on-disk size) and hands enriched job dicts here; keeping the
normalization pure means it's testable without a workspace.

A node is intentionally the FULL job dict plus a small overlay
(``engine``/``kind``/``production_state``/``is_child``/``viewable``/``n_units``), so the
existing frontend pure label fns (``jobDisplayName``/``runRowLabel``/``runChildTitle``/
``productionState``) keep working on a node verbatim.  Health / progress / trajectory
payloads are DELIBERATELY excluded — the master card fetches those lazily for the
selected node only, via each engine's existing endpoints.
"""

from __future__ import annotations

_ACTIVE = {"queued", "preparing", "running"}


def _production_state(stages: list[dict]) -> str:
    """oxDNA production sub-state — mirrors the frontend ``productionState``: reflects
    the LATEST production stage (jobs can have several)."""
    prods = [s for s in stages if s.get("kind") == "production"]
    if not prods:
        return "none"
    st = prods[-1].get("status")
    if st == "done":
        return "done"
    if st == "failed":
        return "failed"
    if st in ("running", "pending"):
        return "running"
    return "none"


def _oxdna_viewable(stages: list[dict]) -> bool:
    """oxDNA has trajectory data to view once any stage has started (mirrors the
    frontend ``hasTrajectory``)."""
    return any(s.get("status") in ("done", "running") for s in stages)


def _lammps_viewable(d: dict) -> bool:
    """A LAMMPS run is viewable once it's finished (not active) and wrote ≥1 frame —
    mirrors the frontend ``lammps_jobs_logic.jobIsViewable``."""
    return d.get("status") not in _ACTIVE and (d.get("frames") or 0) > 0


def normalize_oxdna_job(d: dict) -> dict:
    """An oxDNA job dict (already stamped with ``out_of_date``/``size_bytes`` by the
    route) → a unified node.  A root relaxation is ``kind='relax'``; a field/production
    child (has ``parent_job_id``) is ``kind='run'`` and renders indented under its
    parent (``job_tree`` keys off ``parent_job_id``)."""
    stages = d.get("stages") or []
    parent = d.get("parent_job_id")
    return {
        **d,
        "engine": "oxdna",
        "kind": "run" if parent else "relax",
        "is_child": bool(parent),
        "production_state": _production_state(stages),
        "n_units": d.get("n_nucleotides", 0),
        "viewable": _oxdna_viewable(stages),
    }


def normalize_lammps_job(d: dict) -> dict:
    """A LAMMPS job dict → a unified node.  A LAMMPS run is a flat ROOT node (a peer of
    an oxDNA run, not a stage of one); its ``parent_job_id`` is null today so it renders
    at depth 0.  ``production_state`` is null (only oxDNA has one — ``statusKeyFor``
    ignores it for LAMMPS)."""
    return {
        **d,
        "engine": "lammps",
        "kind": "lammps",
        "is_child": False,
        "production_state": None,
        "n_units": d.get("n_atoms", 0),
        "viewable": _lammps_viewable(d),
    }


def normalize_mrdna_job(d: dict) -> dict:
    """An mrDNA job dict → a unified node.  mrDNA runs are FLAT roots (coarse/fine
    relaxations, no parent/child branches), so ``kind='relax'`` and ``is_child`` is
    always False.  ``production_state`` is null (only oxDNA has one)."""
    return {
        **d,
        "engine": "mrdna",
        "kind": "relax",
        "is_child": False,
        "production_state": None,
        "n_units": d.get("n_nucleotides", 0),
        "viewable": d.get("status") == "completed",
    }


def normalize_cando_job(d: dict) -> dict:
    """A CanDo FEM job dict → a unified node.  Flat roots like mrDNA (a single
    linear/nonlinear solve per run)."""
    return {
        **d,
        "engine": "cando",
        "kind": "relax",
        "is_child": False,
        "production_state": None,
        "n_units": d.get("n_nucleotides", 0),
        "viewable": d.get("status") == "completed",
    }


def normalize_snupi_job(d: dict) -> dict:
    """A SNUPI FEM job dict → a unified node.  Flat roots like CanDo/mrDNA (a single
    linear/nonlinear solve per run); SNUPI is the same in-process FEM with the SNUPI
    material law."""
    return {
        **d,
        "engine": "snupi",
        "kind": "relax",
        "is_child": False,
        "production_state": None,
        "n_units": d.get("n_nucleotides", 0),
        "viewable": d.get("status") == "completed",
    }


def normalize_blade_job(d: dict) -> dict:
    """A BLADE job dict → a unified node.  Flat root like CanDo/SNUPI (one relax per run),
    but unlike them BLADE's compute is an external OpenMM subprocess in the gpu env, not an
    in-process solve — that difference is the runner's problem, not the job list's."""
    return {
        **d,
        "engine": "blade",
        "kind": "relax",
        "is_child": False,
        "production_state": None,
        "n_units": d.get("n_nucleotides", 0),
        "viewable": d.get("status") == "completed",
    }


def normalize_md_job(d: dict) -> dict:
    """A NAMD (MD) job dict → a unified node.  Like oxDNA, a relaxation is a root and a
    production/refit child (``parent_job_id``) renders indented under it.  ``engine`` is
    ``'namd'`` to match the frontend selector key + its label functions.  Production
    sub-state is left null — the frontend only reads ``production_state`` for oxDNA;
    NAMD's own child labels distinguish production rows."""
    parent = d.get("parent_job_id")
    return {
        **d,
        "engine": "namd",
        "kind": "run" if parent else "relax",
        "is_child": bool(parent),
        "production_state": None,
        "n_units": d.get("n_nucleotides", 0),
        "viewable": d.get("status") == "completed",
    }


def _norm_path(p) -> str:
    """Normalize a design_source_path for comparison — forward slashes, no trailing
    ``/`` (mirrors the frontend ``normalizeWorkspacePath`` so the server-side filter
    matches ``filterJobsForPart`` exactly)."""
    if not p:
        return ""
    value = str(p).replace("\\", "/").rstrip("/")
    while value.startswith("./"):
        value = value[2:]
    # File-open responses use workspace-relative paths (`workspace/foo.nadoc`),
    # historical jobs store paths relative to the workspace root (`foo.nadoc`),
    # and desktop/file-handle paths may be absolute (`.../workspace/foo.nadoc`).
    # All three identify the same design and must share one job list.
    marker = "/workspace/"
    if marker in value:
        value = value.rsplit(marker, 1)[1]
    elif value.startswith("workspace/"):
        value = value[len("workspace/"):]
    return value


def filter_nodes(nodes: list[dict], design_source_path, show_all: bool) -> list[dict]:
    """Nodes to show for the active design.  With ``show_all`` every node passes;
    otherwise only nodes whose ``design_source_path`` matches the active design's path
    (no path known → nothing, rather than leaking other designs' jobs)."""
    if show_all:
        return nodes
    cur = _norm_path(design_source_path)
    if not cur:
        return []
    return [n for n in nodes if _norm_path(n.get("design_source_path")) == cur]
