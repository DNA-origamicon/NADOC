"""Surface capture-strand builder (oxDNA immobilization feature).

Sim-only ssDNA **capture strands** dispersed on the hard surface, complementary to the
origami overhangs, so the origami hybridizes and immobilizes on the surface.

This module is the ISOLATED, PURE builder.  Given the resolved surface-strand spec, the
origami's oxDNA configuration (particle CMs + counts) and the surface plane, it produces:

  1. topology rows       — (strand_idx_1based, base, n3, n5), appended AFTER the origami
  2. configuration lines — the 15-float oxDNA conf line per capture bead
  3. attach-end traps    — the particle index + rest position for one stiff trap per strand

Everything is APPENDED after the origami particles, so the origami topology/config is
provably untouched (`append_capture_strands` only ever adds lines + bumps the two header
counts).  Nothing here reaches `_walk_strand_nucleotides`, so the origami's own build,
fingerprint, health, and shape paths are unchanged.

Geometry (Phase 2 decisions — see memory/project_surface_strands.md):
  * ssDNA coil seed standing normal to the surface, FENE-safe rise (0.68 nm/nt).
  * attach end (5′ or 3′) pinned at the surface by a stiff `trap` ≈ a covalent C-C bond.
  * random dispersion reproducible from the seed; 2 nm minimum centre-to-centre spacing.

The placement PRNG (mulberry32) mirrors frontend/src/scene/surface_strands_math.js so the
in-app count preview and the built layout agree for a given seed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from backend.core.constants import (
    NM_TO_OXDNA,
    SSDNA_CONTOUR_PER_NT_NM,
    BDNA_RISE_PER_BP,
    BDNA_TWIST_PER_BP_RAD,
    BDNA_MINOR_GROOVE_ANGLE_RAD,
    HELIX_RADIUS,
)

# ── Constants ────────────────────────────────────────────────────────────────────
NM2_PER_UM2 = 1.0e6
MIN_SPACING_NM = 2.0            # matches the frontend placement math
_RISE_OXDNA = SSDNA_CONTOUR_PER_NT_NM * NM_TO_OXDNA   # ssDNA contour reference (unused in B-form seed)

# B-form seed geometry (user decision 2026-07-17): capture strands stand as a B-DNA helix so
# the seed is FENE-safe and consistent with the origami build.  These replicate
# backend/core/geometry.py's FORWARD-nucleotide formula with the LOCKED B-DNA constants — do
# not diverge (see _PHASE_* banner in cadnano.py / lattice.py).  Native NADOC HC FORWARD phase.
_BFORM_PHASE0 = math.radians(90.0) + BDNA_TWIST_PER_BP_RAD / 2.0   # lattice._lattice_phase_offset(FORWARD, HC)

# Attach-end tether stiffness ≈ a covalent C-C bond.  A C-C stretch constant ~400 N/m
# = 4e5 pN/nm; the oxDNA trap-stiffness unit = force_unit/length_unit = 48.63 pN /
# 0.8518 nm ≈ 57.1 pN/nm, so k ≈ 4e5 / 57.1 ≈ 7000 oxDNA units (~7× DEFAULT_ANCHOR_STIFF).
CAPTURE_TRAP_STIFF = 7000.0

_VALID_SHAPES = ("circle", "square")
_VALID_ENDS = ("5'", "3'")


# ── Deterministic PRNG (ported from mulberry32 in surface_strands_math.js) ─────────
def _imul(a: int, b: int) -> int:
    """32-bit multiply matching JS ``Math.imul`` (low 32 bits of the product)."""
    return ((a & 0xFFFFFFFF) * (b & 0xFFFFFFFF)) & 0xFFFFFFFF


def mulberry32(seed: int):
    """A deterministic PRNG in [0, 1) — bit-for-bit port of the frontend mulberry32 so a
    seed reproduces the same dispersion in-app (preview) and in the build."""
    a = seed & 0xFFFFFFFF

    def _next() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = _imul(a ^ (a >> 15), a | 1)
        t = ((t + _imul(t ^ (t >> 7), t | 61)) ^ t) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    return _next


def sanitize_sequence(seq: str) -> str:
    return "".join(c for c in (seq or "").upper() if c in "ACGT")


# ── Coverage-patch area / count / placement (mirror of the JS math) ────────────────
def coverage_area_nm2(shape: str, size_nm: float) -> float:
    """Patch area in nm². ``size_nm`` = circle DIAMETER / square WIDTH."""
    s = float(size_nm)
    if s <= 0:
        return 0.0
    if shape == "square":
        return s * s
    r = s / 2.0
    return math.pi * r * r


def strand_count(shape: str, size_nm: float, density_per_um2: float) -> int:
    area = coverage_area_nm2(shape, size_nm)
    d = float(density_per_um2)
    if area <= 0 or d <= 0:
        return 0
    return round(d * area / NM2_PER_UM2)


def placement_points_nm(
    shape: str,
    size_nm: float,
    seed: int,
    *,
    density_per_um2: float | None = None,
    count: int | None = None,
    offset_x_nm: float = 0.0,
    offset_y_nm: float = 0.0,
    min_spacing_nm: float = MIN_SPACING_NM,
) -> list[tuple[float, float]]:
    """Deterministic in-plane (x, y) placement points in nm, centred on the offset.
    2 nm min centre-to-centre by rejection; best-effort (returns fewer if saturated)."""
    target = count if count is not None else strand_count(shape, size_nm, density_per_um2 or 0.0)
    s = float(size_nm)
    if target <= 0 or s <= 0:
        return []
    half = s / 2.0
    min2 = max(0.0, float(min_spacing_nm)) ** 2
    rnd = mulberry32(int(seed) & 0xFFFFFFFF)
    placed: list[tuple[float, float]] = []
    consec = 0
    MAX_CONSEC = 80
    while len(placed) < target and consec < MAX_CONSEC:
        if shape == "square":
            u = (rnd() - 0.5) * s
            v = (rnd() - 0.5) * s
        else:
            r = half * math.sqrt(rnd())
            th = 2.0 * math.pi * rnd()
            u = r * math.cos(th)
            v = r * math.sin(th)
        ok = True
        if min2 > 0:
            for (pu, pv) in placed:
                if (pu - u) ** 2 + (pv - v) ** 2 < min2:
                    ok = False
                    break
        if not ok:
            consec += 1
            continue
        consec = 0
        placed.append((u, v))
    return [(u + float(offset_x_nm), v + float(offset_y_nm)) for (u, v) in placed]


# ── Spec normalization ─────────────────────────────────────────────────────────────
@dataclass
class CaptureSpec:
    """A validated surface-strand spec (backend mirror of surfaceStrandsSpec)."""

    sequence: str
    attach_end: str = "5'"
    shape: str = "circle"
    size_nm: float = 100.0
    density_per_um2: float = 0.0
    offset_x_nm: float = 0.0
    offset_y_nm: float = 0.0
    seed: int = 1
    subject_to_field: bool = True

    @classmethod
    def from_payload(cls, d: dict | None) -> "CaptureSpec | None":
        if not d or not d.get("enabled", True):
            return None
        seq = sanitize_sequence(d.get("sequence", ""))
        if not seq:
            return None
        shape = d.get("shape") if d.get("shape") in _VALID_SHAPES else "circle"
        end = d.get("attachEnd") or d.get("attach_end")
        end = end if end in _VALID_ENDS else "5'"
        return cls(
            sequence=seq,
            attach_end=end,
            shape=shape,
            size_nm=max(0.0, float(d.get("sizeNm", d.get("size_nm", 0)) or 0)),
            density_per_um2=max(0.0, float(d.get("densityPerUm2", d.get("density_per_um2", 0)) or 0)),
            offset_x_nm=float(d.get("offsetXNm", d.get("offset_x_nm", 0)) or 0),
            offset_y_nm=float(d.get("offsetYNm", d.get("offset_y_nm", 0)) or 0),
            seed=int(d.get("seed", 1) or 0) & 0xFFFFFFFF,
            subject_to_field=bool(d.get("subjectToField", d.get("subject_to_field", True))),
        )


# ── 3D geometry: an in-plane basis ⟂ the surface normal ────────────────────────────
def _normalize(v) -> np.ndarray:
    a = np.array(v, dtype=float)
    n = np.linalg.norm(a)
    return a / n if n > 1e-14 else np.array([0.0, 1.0, 0.0])


def plane_basis(normal) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(dir_hat, u, v): unit surface normal + two deterministic in-plane axes ⟂ it.
    ``u`` maps the placement/offset X, ``v`` maps Y."""
    d = _normalize(normal)
    ref = np.array([1.0, 0.0, 0.0]) if abs(d[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(d, ref)
    u /= np.linalg.norm(u) + 1e-14
    v = np.cross(d, u)
    v /= np.linalg.norm(v) + 1e-14
    return d, u, v


# ── The build ──────────────────────────────────────────────────────────────────────
@dataclass
class CaptureBuild:
    """Result of building capture strands, ready to append after the origami."""

    topology_rows: list[tuple[int, str, int, int]] = field(default_factory=list)
    conf_lines: list[str] = field(default_factory=list)
    # (particle_index, [x, y, z] oxDNA-unit rest position) for one stiff trap per strand
    trap_anchors: list[tuple[int, list[float]]] = field(default_factory=list)
    n_strands: int = 0
    n_beads: int = 0
    max_extent_oxdna: float = 0.0          # farthest capture-bead coordinate (for box sizing)
    min_dist_to_origami_nm: float | None = None   # closest capture-bead ↔ origami-bead (clash probe)


def _conf_line(pos: np.ndarray, a1: np.ndarray, a3: np.ndarray) -> str:
    a1 = a1 / (np.linalg.norm(a1) + 1e-14)
    a3 = a3 / (np.linalg.norm(a3) + 1e-14)
    return (
        f"{pos[0]:.6f} {pos[1]:.6f} {pos[2]:.6f}  "
        f"{a1[0]:.6f} {a1[1]:.6f} {a1[2]:.6f}  "
        f"{a3[0]:.6f} {a3[1]:.6f} {a3[2]:.6f}  "
        "0.000000 0.000000 0.000000  0.000000 0.000000 0.000000"
    )


def build_capture_strands(
    spec: CaptureSpec,
    *,
    origami_cm_oxdna: list[list[float]],
    n_particles_origami: int,
    n_strands_origami: int,
    surface: dict,
) -> CaptureBuild:
    """Build capture strands standing off the surface, ready to append.

    Parameters
    ----------
    spec                : validated CaptureSpec.
    origami_cm_oxdna    : origami particle CMs (oxDNA units, topology order) — for the
                          in-plane centroid, the plane level, and the clash probe.
    n_particles_origami : origami particle count (== len(origami_cm_oxdna)); capture
                          particle indices start here.
    n_strands_origami   : origami strand count; capture strand_idx starts at +1.
    surface             : {"dir": [x,y,z], "offset_nm": clearance, ...} — the hard plane.

    Returns a :class:`CaptureBuild`.  Empty when the spec produces no strands.
    """
    out = CaptureBuild()
    seq = spec.sequence
    L = len(seq)
    if L == 0:
        return out

    pts = placement_points_nm(
        spec.shape, spec.size_nm, spec.seed,
        density_per_um2=spec.density_per_um2,
        offset_x_nm=spec.offset_x_nm, offset_y_nm=spec.offset_y_nm,
    )
    if not pts:
        return out

    cm = np.array(origami_cm_oxdna, dtype=float) if origami_cm_oxdna else np.zeros((1, 3))
    d_hat, e1, e2 = plane_basis(surface.get("dir"))     # d_hat = normal; e1,e2 = in-plane basis
    offset_oxdna = float(surface.get("offset_nm", 0.0)) * NM_TO_OXDNA

    # Plane level = origami min projection minus the clearance (where the repulsion plane ends
    # up sitting).  Attach beads sit here; the B-form helix rises along +normal.  Absolute
    # surface placement is the user's responsibility (they set the offset to avoid clashes).
    wall_proj = float((cm @ d_hat).min()) - offset_oxdna
    centroid = cm.mean(axis=0)
    centroid_on_plane = centroid - (float(centroid @ d_hat) - wall_proj) * d_hat

    rise_ox = BDNA_RISE_PER_BP * NM_TO_OXDNA
    radius_ox = HELIX_RADIUS * NM_TO_OXDNA
    twist = BDNA_TWIST_PER_BP_RAD
    groove = BDNA_MINOR_GROOVE_ANGLE_RAD

    p_base = n_particles_origami       # running global particle index
    min_d2 = math.inf
    max_extent = 0.0

    for j, (px_nm, py_nm) in enumerate(pts):
        strand_idx = n_strands_origami + 1 + j
        attach = (centroid_on_plane
                  + (px_nm * NM_TO_OXDNA) * e1
                  + (py_nm * NM_TO_OXDNA) * e2)
        # B-form helical frames along the axis (m=0 at the plane) — replicates
        # geometry.py's FORWARD nucleotide (backbone at HELIX_RADIUS, a1 = base-pair vector).
        frames: list[tuple[np.ndarray, np.ndarray]] = []   # (backbone_pos, a1)
        for m in range(L):
            axis_pt = attach + (m * rise_ox) * d_hat
            fa = _BFORM_PHASE0 + m * twist
            ra = fa + groove
            fwd_radial = math.cos(fa) * e1 + math.sin(fa) * e2
            rev_radial = math.cos(ra) * e1 + math.sin(ra) * e2
            backbone = axis_pt + radius_ox * fwd_radial
            a1 = rev_radial - fwd_radial
            a1 = a1 / (np.linalg.norm(a1) + 1e-14)
            frames.append((backbone, a1))

        # 5′→3′ order + a3 sign per tethered end: 5′ tether → chain ascends (a3 = +normal),
        # attach bead is m=0 (plane); 3′ tether → chain descends (a3 = −normal), attach is m=L−1.
        if spec.attach_end == "5'":
            ordered = frames
            a3 = d_hat
            attach_local = 0
        else:
            ordered = list(reversed(frames))
            a3 = -d_hat
            attach_local = L - 1

        for k in range(L):
            backbone, a1 = ordered[k]
            n3 = (p_base + k + 1) if k + 1 < L else -1   # next in 5′→3′ is the 3′ neighbour
            n5 = (p_base + k - 1) if k - 1 >= 0 else -1
            out.topology_rows.append((strand_idx, seq[k], n3, n5))
            out.conf_lines.append(_conf_line(backbone, a1, a3))
            extent = float(np.max(np.abs(backbone)))
            if extent > max_extent:
                max_extent = extent
            if origami_cm_oxdna:
                dd = cm - backbone
                m2 = float(np.min(np.einsum("ij,ij->i", dd, dd)))
                if m2 < min_d2:
                    min_d2 = m2

        attach_gi = p_base + attach_local
        out.trap_anchors.append((attach_gi, [float(x) for x in ordered[attach_local][0]]))
        p_base += L

    out.n_strands = len(pts)
    out.n_beads = len(out.conf_lines)
    out.max_extent_oxdna = max_extent
    if min_d2 < math.inf:
        out.min_dist_to_origami_nm = math.sqrt(min_d2) / NM_TO_OXDNA
    return out


def capture_trap_text(build: CaptureBuild, stiff: float = CAPTURE_TRAP_STIFF) -> str:
    """External-forces text: one static ``trap`` pinning each strand's attach-end bead to
    its seed position (oxDNA units).  Same block shape as oxDNA anchor traps."""
    blocks: list[str] = []
    for particle, pos0 in build.trap_anchors:
        x, y, z = float(pos0[0]), float(pos0[1]), float(pos0[2])
        blocks.append(
            "{\n"
            "type = trap\n"
            f"particle = {particle}\n"
            f"pos0 = {x:.6g},{y:.6g},{z:.6g}\n"
            f"stiff = {stiff:.6g}\n"
            "rate = 0\n"
            "dir = 1,0,0\n"
            "}\n"
        )
    return "\n".join(blocks)


# ── Validation oracle (headless) ───────────────────────────────────────────────────
# FENE bond-length window in oxDNA units (r0=0.7564, delta=0.25).  A backbone bond outside
# [rmin, rmax] blows the run up on step 0 — a too-SHORT bond is as fatal as a too-long one.
_FENE_MIN_UNITS = 0.5064
_FENE_MAX_UNITS = 1.0064


def _read_top_rows(top_path: str | Path) -> tuple[int, int, list[tuple[int, str, int, int]]]:
    lines = Path(top_path).read_text(encoding="utf-8").splitlines()
    n_part, n_str = (int(x) for x in lines[0].split())
    rows = []
    for ln in lines[1:]:
        p = ln.split()
        if len(p) >= 4:
            rows.append((int(p[0]), p[1], int(p[2]), int(p[3])))
    return n_part, n_str, rows


def validate_capture_build(
    top_path: str | Path,
    conf_path: str | Path,
    *,
    n_origami_strands: int,
    trap_particles: list[int] | None = None,
    min_spacing_nm: float = MIN_SPACING_NM,
) -> dict:
    """Physical-invariant ORACLE for a built capture-strand system — reads the on-disk
    topology + configuration (independent of the build code, so it catches build bugs) and
    checks every invariant that must hold for oxDNA to run and for the strands to behave.

    Reusable by tests and the sim-coverage/automation loop.  Returns
    ``{ok: bool, checks: {name: bool}, failures: [str], n_capture_strands, n_capture_beads}``.

    Checks: header/particle-count consistency; capture topology threading (per-strand chain,
    5′/3′ terminals); FENE-safe backbone bonds on every capture strand; ≥ min-spacing between
    attach points; finite coordinates; trap indices (if given) inside the capture range.
    """
    from backend.physics.oxdna_interface import oxdna_backbone_site, read_cm_positions_oxdna

    checks: dict[str, bool] = {}
    failures: list[str] = []

    n_part, n_str, rows = _read_top_rows(top_path)
    conf_lines = Path(conf_path).read_text().splitlines()[3:]
    cm = read_cm_positions_oxdna(conf_path)

    checks["count_consistent"] = (len(rows) == n_part == len(conf_lines) == len(cm))
    if not checks["count_consistent"]:
        failures.append(f"count mismatch: header={n_part} rows={len(rows)} conf={len(conf_lines)}")

    # Group capture particles (strand_idx > n_origami_strands) by strand, in file order.
    cap_by_strand: dict[int, list[int]] = {}
    for gi, (si, _base, _n3, _n5) in enumerate(rows):
        if si > n_origami_strands:
            cap_by_strand.setdefault(si, []).append(gi)
    n_cap_strands = len(cap_by_strand)
    n_cap_beads = sum(len(v) for v in cap_by_strand.values())

    # Topology threading: each capture strand is a valid 5′→3′ chain.
    threading_ok = True
    for si, idxs in cap_by_strand.items():
        for k, gi in enumerate(idxs):
            _s, _b, n3, n5 = rows[gi]
            exp_n3 = idxs[k + 1] if k + 1 < len(idxs) else -1
            exp_n5 = idxs[k - 1] if k - 1 >= 0 else -1
            if n3 != exp_n3 or n5 != exp_n5:
                threading_ok = False
    checks["threading_valid"] = threading_ok
    if not threading_ok:
        failures.append("capture-strand 3′/5′ neighbour threading is broken")

    # FENE-safe backbone bonds on every capture strand.
    def _site(gi: int):
        f = [float(x) for x in conf_lines[gi].split()]
        return oxdna_backbone_site(np.array(f[:3]) / NM_TO_OXDNA, np.array(f[3:6]), np.array(f[6:9]))

    fene_ok = True
    for idxs in cap_by_strand.values():
        sites = [_site(gi) for gi in idxs]
        for k in range(1, len(sites)):
            d_units = float(np.linalg.norm(sites[k] - sites[k - 1])) * NM_TO_OXDNA
            if not (_FENE_MIN_UNITS < d_units < _FENE_MAX_UNITS):
                fene_ok = False
    checks["fene_safe"] = fene_ok
    if not fene_ok:
        failures.append("a capture-strand backbone bond is outside the FENE window")

    # Finite coordinates.
    finite_ok = all(np.all(np.isfinite(p)) for p in cm)
    checks["finite_coords"] = finite_ok
    if not finite_ok:
        failures.append("non-finite coordinate in the configuration")

    # Minimum spacing between attach points (first bead of each capture strand).
    attach_pts = [np.array(cm[idxs[0]]) for idxs in cap_by_strand.values()]
    spacing_ok = True
    for i in range(len(attach_pts)):
        for j in range(i + 1, len(attach_pts)):
            d_nm = float(np.linalg.norm(attach_pts[i] - attach_pts[j])) / NM_TO_OXDNA
            if d_nm < min_spacing_nm - 1e-6:
                spacing_ok = False
    checks["min_spacing"] = spacing_ok
    if not spacing_ok:
        failures.append(f"two attach points are closer than {min_spacing_nm} nm")

    # Trap indices (if provided) inside the appended capture range.
    if trap_particles is not None:
        lo = n_part - n_cap_beads
        traps_ok = all(lo <= p < n_part for p in trap_particles) and len(trap_particles) == n_cap_strands
        checks["traps_in_range"] = traps_ok
        if not traps_ok:
            failures.append("capture trap particle indices out of range or miscounted")

    return {
        "ok": len(failures) == 0,
        "checks": checks,
        "failures": failures,
        "n_capture_strands": n_cap_strands,
        "n_capture_beads": n_cap_beads,
    }


def _read_top_header(top_path: str | Path) -> tuple[int, int]:
    first = Path(top_path).read_text(encoding="utf-8").splitlines()[0].split()
    return int(first[0]), int(first[1])


def _read_conf_box(conf_path: str | Path) -> float:
    for ln in Path(conf_path).read_text().splitlines()[:3]:
        if ln.strip().startswith("b"):
            return float(ln.split("=")[1].split()[0])
    return 0.0


def append_capture_strands(
    top_path: str | Path,
    conf_path: str | Path,
    spec: CaptureSpec,
    surface: dict,
    *,
    box_margin_oxdna: float = 20.0 * NM_TO_OXDNA,
) -> dict:
    """Append capture strands to an existing origami topology + configuration IN PLACE.

    The origami portion of both files is preserved byte-for-byte; only the two header
    counts change and new rows/lines are appended.  Grows the box if a capture strand
    reaches past it.  Returns ``{n_strands, n_beads, trap_anchors, trap_text, min_dist_to_
    origami_nm, box_nm_grown}`` (empty-ish when the spec builds nothing)."""
    top_path, conf_path = Path(top_path), Path(conf_path)
    n_particles, n_strands = _read_top_header(top_path)

    from backend.physics.oxdna_interface import read_cm_positions_oxdna
    cm = read_cm_positions_oxdna(conf_path)

    build = build_capture_strands(
        spec,
        origami_cm_oxdna=cm,
        n_particles_origami=n_particles,
        n_strands_origami=n_strands,
        surface=surface,
    )
    if build.n_beads == 0:
        return {"n_strands": 0, "n_beads": 0, "trap_anchors": [], "trap_text": "",
                "min_dist_to_origami_nm": None, "box_nm_grown": None}

    # ── topology: bump header, append rows ──
    top_lines = top_path.read_text(encoding="utf-8").splitlines()
    top_lines[0] = f"{n_particles + build.n_beads} {n_strands + build.n_strands}"
    for si, base, n3, n5 in build.topology_rows:
        top_lines.append(f"{si} {base} {n3} {n5}")
    top_path.write_text("\n".join(top_lines) + "\n", encoding="utf-8")

    # ── configuration: grow box if needed, append lines ──
    conf_lines = conf_path.read_text().splitlines()
    old_box = _read_conf_box(conf_path)
    new_box = max(old_box, 2.0 * build.max_extent_oxdna + box_margin_oxdna)
    box_grown = None
    if new_box > old_box + 1e-6:
        conf_lines[1] = f"b = {new_box:.6f} {new_box:.6f} {new_box:.6f}"
        box_grown = new_box / NM_TO_OXDNA
    conf_lines.extend(build.conf_lines)
    conf_path.write_text("\n".join(conf_lines) + "\n", encoding="utf-8")

    return {
        "n_strands": build.n_strands,
        "n_beads": build.n_beads,
        "trap_anchors": build.trap_anchors,
        "trap_text": capture_trap_text(build),
        "min_dist_to_origami_nm": build.min_dist_to_origami_nm,
        "box_nm_grown": box_grown,
    }
