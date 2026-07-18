"""
API layer — single-file structural exports (extracted from crud.py).

This module hosts the routes that emit ONE structural/topology file (or a small
zip of them) describing the design for an external MD / analysis pipeline:

  - oxDNA: ``/design/oxdna/export`` (topology + conf + input zip) and
    ``/design/oxdna/run`` (try a local oxDNA minimisation, read positions back).
  - Atom-level single files: ``/design/export/pdb`` and ``/design/export/psf``
    (all-atom CHARMM36 PDB + NAMD PSF topology).
  - Design-intent maps: ``/design/export/identity[-tsv]``, ``/design/export/
    design-maps``, ``/design/export/basepairs[-tsv]``, ``/design/export/
    stacking[-tsv]`` — stable identity + intended base-pair / stacking tables.
  - ``/design/export/restraints-dry-implicit`` — NAMD extraBonds zip.
  - ``/design/debug/mrdna-roundtrip`` — zero-step mrdna round-trip RMSD check.

One reason to change: the set of single-file structural/topology exporters NADOC
emits for downstream MD/analysis. The *complete MD-engine package* exporters
(NAMD/GROMACS bundles) live in ``routes_export_md.py``; the atomistic / surface
*display* routes, the 3D-print STL/3MF exports, and the crossover
``/design/debug/strand-stats`` diagnostic are different concerns and stay in
crud.py.

The shared export/geometry resolvers ``_design_for_export`` /
``_geometry_for_design`` stay in crud.py (used across crud.py + assembly.py +
core) and are imported back here — same shared-kernel convention as
``routes_export_md.py`` / ``routes_camera_poses.py``.

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.api import state as design_state
# Shared export/geometry resolvers used by many routes across crud.py +
# assembly.py + core; they stay in crud.py and are imported back here (same
# convention as routes_export_md.py / routes_camera_poses.py).
from backend.api.crud import _design_for_export, _geometry_for_design

router = APIRouter()


class PdbVisualizationPosition(BaseModel):
    # Renderer keys can be numeric for imported caDNAno designs and extra-base
    # sentinels use string identifiers. Normalize them when building overrides.
    helix_id: str | int
    bp_index: int | str  # extra crossover bases use the crossover id here
    direction: str | int
    backbone_position: list[float] = Field(min_length=3, max_length=3)
    copy: int = 0


class PdbVisualizationExport(BaseModel):
    positions: list[PdbVisualizationPosition]
    visualization: "PdbVisualizationSource | None" = None
    coloring: "PdbVisualizationColoring | None" = None


class PdbVisualizationSource(BaseModel):
    engine: str | None = None
    mode: str | None = None
    job_id: str | None = None
    frame: int | None = None  # one-based UI frame number
    align: bool = True


class PdbVisualizationColorValue(BaseModel):
    helix_id: str | int
    bp_index: int | str
    direction: str | int
    value: float
    copy: int = 0


class PdbVisualizationColoring(BaseModel):
    attribute: str = "rmsf"
    title: str = "RMSF"
    unit: str = "nm"
    colormap: str = "viridis"
    palette: str | None = None
    lo: float
    hi: float
    values: list[PdbVisualizationColorValue]


PdbVisualizationExport.model_rebuild()


def _pdb_visualization_overrides(positions: list[PdbVisualizationPosition]):
    """Split renderer positions into regular, crossover-insert, and tail overrides."""
    import numpy as np

    def _direction(value: str | int) -> str:
        text = str(value).upper()
        if text in {"1", "+1", "FORWARD"}:
            return "FORWARD"
        if text in {"-1", "REVERSE"}:
            return "REVERSE"
        return text

    regular = {}
    crossover = {}
    extensions = {}
    for p in positions:
        helix_id = str(p.helix_id)
        xyz = np.asarray(p.backbone_position, dtype=float)
        if helix_id == "__xb__":
            crossover[(p.bp_index, int(p.direction))] = xyz
        elif helix_id.startswith("__ext_"):
            extensions[(helix_id[len("__ext_"):], int(p.bp_index))] = xyz
        else:
            key = (helix_id, int(p.bp_index), _direction(p.direction))
            if p.copy:
                key += (p.copy,)
            regular[key] = xyz
    return regular, crossover, extensions


def _pdb_coloring_values(coloring: PdbVisualizationColoring | None) -> dict[tuple, float]:
    if coloring is None:
        return {}
    out = {}
    for p in coloring.values:
        hid = str(p.helix_id)
        direction = str(p.direction).upper()
        if direction in {"1", "+1"}: direction = "FORWARD"
        elif direction == "-1": direction = "REVERSE"
        if hid == "__xb__": key = ("__xb__", str(p.bp_index), int(p.direction))
        elif hid.startswith("__ext_"): key = (hid, int(p.bp_index), direction)
        else:
            key = (hid, int(p.bp_index), direction)
            if p.copy: key += (int(p.copy),)
        out[key] = float(p.value)
    return out


# ── oxDNA export / run ────────────────────────────────────────────────────────


@router.post("/design/oxdna/export")
def export_oxdna() -> Response:
    """
    Export the active design as a ZIP archive containing oxDNA files:
      - topology.top
      - conf.dat
      - input.txt  (ready-to-run MC input; requires oxDNA binary)
      - README.txt (installation + run instructions)

    Returns the ZIP as a binary download.
    """
    import io
    import zipfile

    from backend.physics.oxdna_interface import (
        write_configuration,
        write_topology,
        write_oxdna_input,
    )

    design = _design_for_export()
    geometry = _geometry_for_design(design)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # topology.top
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmpdir:
            top_path  = pathlib.Path(tmpdir) / "topology.top"
            conf_path = pathlib.Path(tmpdir) / "conf.dat"
            inp_path  = pathlib.Path(tmpdir) / "input.txt"

            write_topology(design, top_path)
            write_configuration(design, geometry, conf_path)
            write_oxdna_input(top_path, conf_path, inp_path, steps=10_000, relaxation_steps=1_000)

            zf.write(top_path,  "topology.top")
            zf.write(conf_path, "conf.dat")
            zf.write(inp_path,  "input.txt")

        readme = (
            "# NADOC oxDNA Export\n\n"
            "## Install oxDNA\n\n"
            "```bash\n"
            "# Option A — conda (recommended)\n"
            "conda install -c bioconda oxdna\n\n"
            "# Option B — build from source\n"
            "git clone https://github.com/lorenzo-rovigatti/oxDNA\n"
            "cd oxDNA && mkdir build && cd build\n"
            "cmake .. -DCUDA=OFF && make -j4\n"
            "```\n\n"
            "## Run simulation\n\n"
            "```bash\n"
            "oxDNA input.txt\n"
            "```\n\n"
            "Output: `last_conf.dat` — final relaxed configuration.\n\n"
            "## Re-import (future feature)\n\n"
            "Once oxDNA runs, the relaxed positions in `last_conf.dat` can be\n"
            "read back with `backend.physics.oxdna_interface.read_configuration()`.\n"
        )
        zf.writestr("README.txt", readme)

    buf.seek(0)
    name = design.metadata.name or "design"
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}_oxdna.zip"'},
    )


@router.post("/design/oxdna/run")
def run_oxdna_simulation(steps: int = 10_000) -> dict:
    """
    Try to run an oxDNA energy minimisation on the current design.

    Requires the oxDNA binary to be on PATH (or set OXDNA_BIN env var).
    Returns {available: bool, message: str, positions: [...] | null}.

    If oxDNA is not installed, returns available=false with installation info.
    """
    import os
    import tempfile
    import pathlib

    from backend.physics.oxdna_interface import (
        run_oxdna,
        write_configuration,
        write_topology,
        write_oxdna_input,
        read_configuration,
    )

    oxdna_bin = os.environ.get("OXDNA_BIN", "oxDNA")
    design  = design_state.get_or_404()
    geometry = _geometry_for_design(design)

    with tempfile.TemporaryDirectory() as tmpdir:
        p = pathlib.Path(tmpdir)
        write_topology(design,   p / "topology.top")
        write_configuration(design, geometry, p / "conf.dat")
        write_oxdna_input(p / "topology.top", p / "conf.dat",
                          p / "input.txt", steps=steps, relaxation_steps=min(steps // 10, 1000))

        ret = run_oxdna(p / "input.txt", oxdna_bin=oxdna_bin, timeout=120)

        if ret is None:
            return {
                "available": False,
                "message": (
                    f"oxDNA binary not found (tried: {oxdna_bin!r}). "
                    "Install with: conda install -c bioconda oxdna  "
                    "or set OXDNA_BIN env var to the binary path. "
                    "Use 'Export oxDNA' to download files for manual simulation."
                ),
                "positions": None,
            }

        if ret != 0:
            return {
                "available": True,
                "message": f"oxDNA exited with code {ret}. Check topology/configuration.",
                "positions": None,
            }

        # Read back relaxed positions.
        last_conf = p / "last_conf.dat"
        if not last_conf.exists():
            return {
                "available": True,
                "message": "oxDNA finished but no last_conf.dat produced.",
                "positions": None,
            }

        pos_map = read_configuration(last_conf, design)
        positions = [
            {
                "helix_id":          k[0],
                "bp_index":          k[1],
                "direction":         k[2],
                "backbone_position": v.tolist(),
            }
            for k, v in pos_map.items()
        ]
        return {
            "available": True,
            "message":   f"oxDNA relaxation complete ({steps} steps).",
            "positions": positions,
        }


# ── Atom-level single files + design-intent maps (PDB/identity/basepairs/stacking) ──


@router.get("/design/export/pdb")
def export_pdb_file() -> Response:
    """Export the active design as an all-atom PDB file (heavy atoms, CHARMM36 names)."""
    from backend.core.atomistic_cache import build_atomistic_model_cached
    from backend.core.pdb_export import export_pdb

    design   = _design_for_export()
    pdb_text = export_pdb(
        design, model=build_atomistic_model_cached(design, fast_bridges=True),
        viewer_terminals=True,
    )
    name     = (design.metadata.name or "design").replace(" ", "_")
    return Response(
        content     = pdb_text.encode("utf-8"),
        media_type  = "chemical/x-pdb",
        headers     = {"Content-Disposition": f'attachment; filename="{name}.pdb"'},
    )


@router.post("/design/export/pdb/visualized")
def export_visualized_pdb_file(payload: PdbVisualizationExport) -> Response:
    """Export a PDB translated onto the simulation/FEM positions shown by the UI."""
    from backend.core.atomistic import build_atomistic_model
    from backend.core.pdb_export import export_pdb

    design = _design_for_export()

    # oxDNA has a validated, frame-aware all-atom reconstruction used by the
    # atomistic display. Use that exact source when possible. Merely translating
    # native residues onto CG backbone points leaves their native straight-axis
    # orientation intact, producing the visibly incorrect one-axis base stack.
    src = payload.visualization
    model = None
    if src and src.engine == "oxdna" and src.job_id:
        from backend.api.routes_oxdna import (
            _capture_bead_count, _capture_strand_length, _composite_inputs, _load_job,
            _relaxed_full_map, _rmsf_average_frame,
        )
        from backend.core.atomistic import build_atomistic_model
        from backend.core.oxdna_health import (
            build_display_model, composite_trajectory_atomistic,
        )

        job = _load_job(src.job_id)
        if src.mode == "rmsf":
            design, frame_map, _ = _rmsf_average_frame(job, src.align)
            model = build_display_model(design, frame_map) if frame_map is not None else None
            flat = None
        elif src.mode == "trajectory" and src.frame is not None:
            design, stages, ref = _composite_inputs(job)
            idx = max(0, src.frame - 1)
            frames = composite_trajectory_atomistic(
                design, stages, ref, [idx], align=src.align,
                n_trailing_extra=_capture_bead_count(job),
                trailing_extra_strand_length=_capture_strand_length(job)) if stages else {}
            flat = frames.get(str(idx))
        else:
            design, frame_map, _, _, _ = _relaxed_full_map(
                job, src.align, copies=True, include_extra_bases=True, include_extensions=True)
            model = build_display_model(design, frame_map) if frame_map is not None else None
            flat = None

        if model is None and flat is None:
            raise HTTPException(409, "The selected oxDNA frame is no longer available for PDB export.")
        if model is None:
            model = build_atomistic_model(design, fast_bridges=True)
            if len(flat) != len(model.atoms) * 3:
                raise HTTPException(409, "The selected oxDNA frame does not match its saved topology.")
            for i, atom in enumerate(model.atoms):
                atom.x, atom.y, atom.z = map(float, flat[i * 3:i * 3 + 3])
    # nuc_pos_override is intentionally the same axis-derived atomistic stamping
    # path used for relaxed CG display: it moves each residue to the selected CG
    # backbone position while preserving chemically sane DNA orientation.
    override, xb_override, ext_override = _pdb_visualization_overrides(payload.positions)
    if model is None and not payload.positions:
        # Native coordinates plus a scalar map can reuse the bounded atomistic
        # cache; an empty override used to trigger a complete rebuild.
        from backend.core.atomistic_cache import build_atomistic_model_cached
        model = build_atomistic_model_cached(design, fast_bridges=True)
    elif model is None:
        model = build_atomistic_model(
            design,
            nuc_pos_override=override,
            xb_pos_override=xb_override or None,
            ext_pos_override=ext_override or None,
            # Simulation beads define the rigid nucleotide positions, but oxDNA
            # does not place individual phosphate-linker atoms. Re-seat those
            # atoms between fixed sugar anchors, including 5'/3' extension joins.
            close_backbone=True,
        )
    coloring = payload.coloring
    pdb_text = export_pdb(
        design, model=model, viewer_terminals=True,
        scalar_by_key=_pdb_coloring_values(coloring),
        scalar_metadata=(coloring.model_dump(exclude={"values"}) if coloring else None),
    )
    name = (design.metadata.name or "design").replace(" ", "_")
    return Response(
        content=pdb_text.encode("utf-8"),
        media_type="chemical/x-pdb",
        headers={"Content-Disposition": f'attachment; filename="{name}.pdb"'},
    )


@router.get("/design/export/identity")
def export_identity_file() -> Response:
    """Export stable atom/nucleotide identity metadata for MD pipelines."""
    from backend.core.pdb_export import export_identity_json

    design = design_state.get_or_404()
    name = (design.metadata.name or "design").replace(" ", "_")
    identity_text = export_identity_json(design)
    return Response(
        content=identity_text.encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}.identity.json"'},
    )


@router.get("/design/export/identity-tsv")
def export_identity_tsv_file() -> Response:
    """Export a tab-separated atom identity table for MD analysis scripts."""
    from backend.core.pdb_export import export_identity_tsv

    design = design_state.get_or_404()
    name = (design.metadata.name or "design").replace(" ", "_")
    identity_text = export_identity_tsv(design)
    return Response(
        content=identity_text.encode("utf-8"),
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": f'attachment; filename="{name}.identity.tsv"'},
    )


@router.get("/design/export/design-maps")
def export_design_maps_file() -> Response:
    """Export intended base-pair and stacking maps for MD analysis."""
    from backend.core.pdb_export import export_design_maps_json

    design = design_state.get_or_404()
    name = (design.metadata.name or "design").replace(" ", "_")
    maps_text = export_design_maps_json(design)
    return Response(
        content=maps_text.encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}.design_maps.json"'},
    )


@router.get("/design/export/basepairs")
def export_basepair_map_file() -> Response:
    """Export intended Watson-Crick base-pair identity map."""
    from backend.core.pdb_export import export_basepair_map_json

    design = design_state.get_or_404()
    name = (design.metadata.name or "design").replace(" ", "_")
    map_text = export_basepair_map_json(design)
    return Response(
        content=map_text.encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}.basepairs.json"'},
    )


@router.get("/design/export/basepairs-tsv")
def export_basepair_map_tsv_file() -> Response:
    """Export intended Watson-Crick base-pair identity map as TSV."""
    from backend.core.pdb_export import export_basepair_map_tsv

    design = design_state.get_or_404()
    name = (design.metadata.name or "design").replace(" ", "_")
    map_text = export_basepair_map_tsv(design)
    return Response(
        content=map_text.encode("utf-8"),
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": f'attachment; filename="{name}.basepairs.tsv"'},
    )


@router.get("/design/export/stacking")
def export_stacking_map_file() -> Response:
    """Export intended strand-order stacking map."""
    from backend.core.pdb_export import export_stacking_map_json

    design = design_state.get_or_404()
    name = (design.metadata.name or "design").replace(" ", "_")
    map_text = export_stacking_map_json(design)
    return Response(
        content=map_text.encode("utf-8"),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}.stacking.json"'},
    )


@router.get("/design/export/stacking-tsv")
def export_stacking_map_tsv_file() -> Response:
    """Export intended strand-order stacking map as TSV."""
    from backend.core.pdb_export import export_stacking_map_tsv

    design = design_state.get_or_404()
    name = (design.metadata.name or "design").replace(" ", "_")
    map_text = export_stacking_map_tsv(design)
    return Response(
        content=map_text.encode("utf-8"),
        media_type="text/tab-separated-values",
        headers={"Content-Disposition": f'attachment; filename="{name}.stacking.tsv"'},
    )


@router.get("/design/export/restraints-dry-implicit")
def export_dry_implicit_restraints_file() -> Response:
    """ZIP archive of design-aware NAMD extraBonds files for dry/implicit tests."""
    import io
    import zipfile
    from backend.core.pdb_export import export_dry_implicit_restraints

    design = design_state.get_or_404()
    name = (design.metadata.name or "design").replace(" ", "_")
    restraint_files = export_dry_implicit_restraints(design)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, text in restraint_files.items():
            zf.writestr(filename, text)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}_dry_implicit_restraints.zip"'},
    )


@router.get("/design/debug/mrdna-roundtrip")
def debug_mrdna_roundtrip() -> Response:
    """Run a zero-step mrdna round-trip test on the active design.

    Builds the mrdna coarse model (dry_run=True, no simulation), reconstructs
    atomistic positions via nuc_pos_override_from_mrdna_coarse, and returns a
    zip archive containing:
      - before.pdb  — direct NADOC → atomistic path
      - after.pdb   — NADOC → mrdna CG → override → atomistic path
      - stats.txt   — P-atom RMSD, mean/max displacement, atom counts
    """
    import io
    import math
    import tempfile
    import zipfile
    import numpy as np
    import MDAnalysis as mda

    from backend.core.gromacs_package import _build_gromacs_input_pdb, _find_top_dir, _pick_ff
    from backend.core.mrdna_bridge import (
        mrdna_model_from_nadoc,
        nuc_pos_override_from_mrdna_coarse,
    )

    design = design_state.get_or_404()
    ff = _pick_ff(_find_top_dir())

    # ── Direct path: NADOC → atomistic (GROMACS CHARMM36 PDB) ────────────────
    before_pdb = _build_gromacs_input_pdb(design, ff)

    # ── mrdna path: dry_run → coarse PDB → override → atomistic ──────────────
    with tempfile.TemporaryDirectory(prefix="nadoc_roundtrip_") as tmpdir:
        import pathlib
        model = mrdna_model_from_nadoc(design)
        model.simulate(
            "roundtrip",
            directory=tmpdir,
            output_directory="output",
            dry_run=True,
            num_steps=0,
        )

        psf = pathlib.Path(tmpdir) / "roundtrip.psf"
        pdb = pathlib.Path(tmpdir) / "roundtrip.pdb"
        if not psf.exists():
            psf = pathlib.Path(tmpdir) / "roundtrip-0.psf"
            pdb = pathlib.Path(tmpdir) / "roundtrip-0.pdb"

        # Synthetic single-frame DCD from initial PDB
        dcd = pathlib.Path(tmpdir) / "roundtrip_frame0.dcd"
        u = mda.Universe(str(psf), str(pdb))
        with mda.Writer(str(dcd), n_atoms=u.atoms.n_atoms) as w:
            for _ in u.trajectory:
                w.write(u.atoms)

        override = nuc_pos_override_from_mrdna_coarse(
            design, str(psf), str(dcd), frame=0, sigma_nt=0.0
        )

    after_pdb = _build_gromacs_input_pdb(design, ff, nuc_pos_override=override)

    # ── Compute P-atom RMSD (parse both PDBs consistently) ───────────────────
    def _parse_pdb_atoms(pdb_text: str) -> dict:
        atoms = {}
        for line in pdb_text.splitlines():
            if line.startswith(("ATOM", "HETATM")):
                aname  = line[12:16].strip()
                chain  = line[21]
                resnum = line[22:26].strip()
                x      = float(line[30:38])
                y      = float(line[38:46])
                z      = float(line[46:54])
                atoms[(chain, resnum, aname)] = np.array([x, y, z])
        return atoms

    before_atoms = _parse_pdb_atoms(before_pdb)
    after_atoms  = _parse_pdb_atoms(after_pdb)

    p_disp: list[float] = []
    all_disp: list[float] = []
    common = set(before_atoms) & set(after_atoms)
    for k in common:
        d = float(np.linalg.norm(before_atoms[k] - after_atoms[k]))
        all_disp.append(d)
        if k[2] == "P":
            p_disp.append(d)

    rmsd_p   = math.sqrt(sum(x**2 for x in p_disp)   / len(p_disp))   if p_disp   else float("nan")
    rmsd_all = math.sqrt(sum(x**2 for x in all_disp) / len(all_disp)) if all_disp else float("nan")
    mean_p   = sum(p_disp) / len(p_disp) if p_disp else float("nan")
    max_p    = max(p_disp) if p_disp else float("nan")

    passed = rmsd_p < 2.0
    stats_txt = (
        f"NADOC mrdna Zero-Step Round-Trip Test\n"
        f"{'=' * 42}\n"
        f"Design:            {design.metadata.name or 'unnamed'}\n"
        f"Atoms in common:   {len(common)}\n"
        f"\n"
        f"RMSD all atoms:    {rmsd_all:.3f} Å\n"
        f"RMSD P atoms:      {rmsd_p:.3f} Å  ← primary metric\n"
        f"Mean P displace:   {mean_p:.3f} Å\n"
        f"Max  P displace:   {max_p:.3f} Å\n"
        f"\n"
        f"Threshold:         2.0 Å\n"
        f"Result:            {'PASS ✓' if passed else 'FAIL ✗'}\n"
        f"\n"
        f"Files\n"
        f"-----\n"
        f"before.pdb  — direct NADOC → atomistic\n"
        f"after.pdb   — NADOC → mrdna CG (0 steps) → atomistic\n"
        f"stats.txt   — this file\n"
    )

    name = (design.metadata.name or "design").replace(" ", "_")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}_roundtrip_before.pdb", before_pdb)
        zf.writestr(f"{name}_roundtrip_after.pdb",  after_pdb)
        zf.writestr("roundtrip_stats.txt", stats_txt)
    buf.seek(0)

    return Response(
        content    = buf.read(),
        media_type = "application/zip",
        headers    = {"Content-Disposition": f'attachment; filename="{name}_roundtrip.zip"'},
    )


# ── PSF topology ──────────────────────────────────────────────────────────────


@router.get("/design/export/psf")
def export_psf_file() -> Response:
    """Export the active design as a NAMD-compatible PSF topology file."""
    from backend.core.pdb_export import export_psf

    design   = _design_for_export()
    psf_text = export_psf(design)
    name     = (design.metadata.name or "design").replace(" ", "_")
    return Response(
        content     = psf_text.encode("utf-8"),
        media_type  = "text/plain",
        headers     = {"Content-Disposition": f'attachment; filename="{name}.psf"'},
    )
