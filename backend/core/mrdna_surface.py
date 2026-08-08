"""mrDNA hard surface — a one-sided repulsion plane in an ARBD CG run.

A *surface* (repulsion plane) is a JOB-REQUEST annotation (never a ``Design`` edit —
Three-Layer Law): the user supplies the SHARED cross-engine surface descriptor
``{"dir": [x, y, z], "offset_nm": d, "stiff": s}`` — the very same dict LAMMPS uses and
the oxDNA floor card emits (``surface_anchor_forces_text`` /
``wall_position_from_extent`` / ``repulsion_plane_block``).  ``dir`` is the allowed-side
normal (the structure sits on the ``+dir̂`` side); ``offset_nm`` is the clearance the
plane sits *below* the structure's lowest bead along ``dir̂``; ``stiff`` is the wall
spring constant (ARBD units, kcal·mol⁻¹·Å⁻²).

We realise it as a **one-sided harmonic wall** delivered through ARBD's per-``ParticleType``
**grid potential** (``add_grid_potential`` / ``gridFile``) — the exact mechanism M2's
uniform field uses, only with a different potential shape::

    U(r) = ½ · stiff · min(0, s)²      where  s = dir̂·r − plane_c

Its negative gradient ``−∇U = −stiff·min(0, s)·dir̂`` is **zero on the allowed side**
(``s ≥ 0``) and pushes a bead that crosses to the forbidden side back **along ``+dir̂``**
(repulsion growing with penetration) — oxDNA's ``repulsion_plane`` energetics, on a grid.
Unlike the field's linear ramp (exact under trilinear interpolation at any resolution),
the quadratic wall needs a modest grid resolution near the plane, so the grid is sampled
at ``SURFACE_GRID_SPACING_A``.

**Composition with a field (the deposition case).**  A deposition run carries a field
*and* a surface at once.  ARBD superposes multiple ``gridFile`` entries additively, so
this module **appends** its wall grid via ``add_grid_potential`` rather than overwriting
``grid_potentials`` — but the field module (:mod:`backend.core.mrdna_field`) *overwrites*,
so the surface must be installed **after** the field (the runner does exactly that).  A
field pressing straight into the surface is held by the plane's reaction, so it needs no
strand anchor — the engine-agnostic rule in :mod:`backend.core.field_anchor`.

mrDNA regenerates beads (``clear_beads()`` + ``generate_bead_model()``) between resolution
stages, rebuilding the ``ParticleType`` objects and wiping the grids.
:func:`install_surface_force` wraps ``generate_bead_model`` so the wall is re-applied after
every regeneration (same discipline as the field / anchors).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:  # pragma: no cover
    from backend.core.models import Design

logger = logging.getLogger(__name__)

#: Å per nm (bead positions and offsets are in Å, the descriptor's offset is in nm).
_A_PER_NM: float = 10.0

#: Å of padding around the bead bounding box for the wall grid.  ARBD zeroes a grid
#: potential outside its extent (Dirichlet) — a bead reaching the boundary would fall
#: through the wall — so the grid must comfortably enclose the structure plus its
#: deposition motion (the field presses it toward the plane, so the drift is bounded).
GRID_MARGIN_A: float = 300.0

#: Target grid spacing (Å) along each axis.  Unlike the field's linear ramp, a harmonic
#: wall is quadratic, so trilinear interpolation is only approximate; ~10 Å keeps the
#: wall crisp relative to a ~2 nm CG bead.  Samples per axis are derived from the box
#: extent and capped so a large structure can't blow up the grid file.
GRID_SPACING_A: float = 10.0
GRID_MIN_SAMPLES: int = 8
GRID_MAX_SAMPLES: int = 128


def _model_beads(model) -> list:
    """Flat DNA-bead list (same order/scope :mod:`backend.core.mrdna_field` uses —
    orientation beads are already omitted by ``segment.beads``)."""
    return [b for s in model.segments for b in getattr(s, "beads", [])]


def parse_surface(surface) -> Optional[tuple[np.ndarray, float, float]]:
    """``{"dir", "offset_nm", "stiff"}`` → ``(unit_dir, offset_nm, stiff)`` or ``None``.

    ``None`` / empty / zero-stiffness / zero-direction all return ``None`` (a no-op
    surface), mirroring ``mrdna_field.parse_field``."""
    if not surface:
        return None
    stiff = float(surface.get("stiff", 0.0) or 0.0)
    d = np.asarray(surface.get("dir", (0.0, 0.0, 0.0)), dtype=float)
    dnorm = float(np.linalg.norm(d))
    if stiff <= 0.0 or dnorm == 0.0:
        return None
    offset_nm = float(surface.get("offset_nm", 0.0) or 0.0)
    return d / dnorm, offset_nm, stiff


def wall_plane_offset(model, dhat: np.ndarray, offset_nm: float) -> float:
    """The plane scalar ``plane_c`` (Å) so the wall sits ``offset_nm`` below the
    structure's lowest bead along ``dir̂`` — every bead starts on the allowed side
    (``dir̂·r ≥ plane_c``).  Generalises oxDNA ``wall_position_from_extent``:
    ``plane_c = min_proj − offset`` gives ``s = dir̂·r − plane_c ≥ offset ≥ 0``."""
    beads = _model_beads(model)
    if not beads:
        return 0.0
    proj = np.array([b.get_collapsed_position() for b in beads], dtype=float) @ dhat
    return float(proj.min()) - offset_nm * _A_PER_NM


def _grid_samples(lo: np.ndarray, hi: np.ndarray) -> tuple[int, int, int]:
    """Per-axis sample counts from the box extent at ``GRID_SPACING_A`` (clamped)."""
    out = []
    for i in range(3):
        n = int(np.ceil((hi[i] - lo[i]) / GRID_SPACING_A)) + 1
        out.append(int(np.clip(n, GRID_MIN_SAMPLES, GRID_MAX_SAMPLES)))
    return out[0], out[1], out[2]


def _write_wall_grid(
    path: Path,
    dhat: np.ndarray,
    plane_c: float,
    stiff: float,
    lo: np.ndarray,
    hi: np.ndarray,
    samples: tuple[int, int, int],
) -> None:
    """A one-sided harmonic potential ``U = ½·stiff·min(0, dir̂·r − plane_c)²`` over the
    ``lo``→``hi`` box, so ``−∇U`` repels beads on the forbidden side back along ``+dir̂``
    and vanishes on the allowed side — ARBD's ``gridFile`` idiom for a repulsion plane."""
    from mrdna.arbdmodel.grid import writeDx  # noqa: PLC0415

    nx, ny, nz = samples
    ax = np.linspace(lo[0], hi[0], nx)
    ay = np.linspace(lo[1], hi[1], ny)
    az = np.linspace(lo[2], hi[2], nz)
    X, Y, Z = np.meshgrid(ax, ay, az, indexing="ij")
    s = dhat[0] * X + dhat[1] * Y + dhat[2] * Z - plane_c
    below = np.minimum(s, 0.0)
    U = 0.5 * float(stiff) * below * below
    delta = [
        float((hi[0] - lo[0]) / (nx - 1)),
        float((hi[1] - lo[1]) / (ny - 1)),
        float((hi[2] - lo[2]) / (nz - 1)),
    ]
    writeDx(str(path), U, [float(lo[0]), float(lo[1]), float(lo[2])], delta)


def _attach_wall_grid(model, grid_path: Path) -> list[str]:
    """Append the (already-written) wall grid to every DNA bead type on the current
    cloud via ``add_grid_potential`` — so it **superposes** with any field grid already
    present rather than clobbering it.  Returns the type names given the wall."""
    types: dict[int, object] = {}
    for b in _model_beads(model):
        types.setdefault(id(b.type_), b.type_)
    applied: list[str] = []
    for t in types.values():
        t.add_grid_potential(str(grid_path), 1, "dirichlet")
        applied.append(t.name)
    return applied


def surface_grid_path(out_dir: Path) -> Path:
    """The single wall grid for a run (the wall is the SAME potential in space for every
    bead, so one grid is shared by all types)."""
    return Path(out_dir) / "surface.dx"


def apply_surface_force(
    design: "Design", model, surface, *, out_dir: Path
) -> list[str]:
    """Write the wall grid from the CURRENT bead cloud and attach it to every DNA bead
    type.  The plane is placed ``offset_nm`` below the structure's lowest bead along
    ``dir̂`` at this moment; :func:`install_surface_force` calls this ONCE (the plane is
    fixed in the lab frame thereafter).  Returns the type names given the wall ([] for a
    no-op surface or empty model)."""
    parsed = parse_surface(surface)
    beads = _model_beads(model)
    if parsed is None or not beads:
        return []
    dhat, offset_nm, stiff = parsed

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pos = np.array([b.get_collapsed_position() for b in beads], dtype=float)
    lo = pos.min(axis=0) - GRID_MARGIN_A
    hi = pos.max(axis=0) + GRID_MARGIN_A
    plane_c = float((pos @ dhat).min()) - offset_nm * _A_PER_NM

    g = surface_grid_path(out_dir)
    _write_wall_grid(g, dhat, plane_c, stiff, lo, hi, _grid_samples(lo, hi))
    return _attach_wall_grid(model, g)


def install_surface_force(design: "Design", model, surface, *, out_dir: Path) -> int:
    """Wire a hard surface into a model so its wall grid survives bead regeneration.

    The wall grid is written ONCE from the initial bead cloud — the plane is FIXED in the
    lab frame (like the field's dead load), so ``multiresolution_simulation``'s bead
    regeneration (fresh ``ParticleType`` objects) must **re-attach the same grid**, never
    recompute the plane from moved (relaxed/deposited) positions.  We wrap
    ``generate_bead_model`` to re-attach after every regeneration.

    MUST be installed AFTER any field (:mod:`backend.core.mrdna_field`), which *overwrites*
    ``grid_potentials`` — installing the surface last makes its regen wrapper the outer
    one, so on every regeneration the field re-applies (overwrite) first and the surface
    re-appends after, keeping both grids.  Returns the number of bead types given the wall
    on the current bead cloud."""
    if parse_surface(surface) is None:
        return 0

    names = apply_surface_force(design, model, surface, out_dir=out_dir)
    grid = surface_grid_path(out_dir)

    orig = model.generate_bead_model

    def _wrapped(*args, **kwargs):
        orig(*args, **kwargs)
        n = len(_attach_wall_grid(model, grid))
        logger.info(
            "mrdna surface: re-attached wall grid to %d bead type(s) after regen", n
        )

    model.generate_bead_model = _wrapped

    logger.info(
        "mrdna surface: applied wall grid to %d bead type(s) (%s)",
        len(names),
        ", ".join(names) or "none",
    )
    return len(names)
