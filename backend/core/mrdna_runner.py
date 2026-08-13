"""
mrDNA Runner — background execution of a single coarse ARBD relaxation.

Sibling of ``oxdna_runner.py``, simplified: a mrDNA job has ONE stage (the
coarse ARBD relaxation).  Unlike oxDNA — where NADOC spawns the ``oxDNA`` binary
directly and owns the subprocess — mrDNA's relaxation runs inside a blocking
``SegmentModel.simulate(...)`` call that itself spawns ARBD.  So the runner:

  1. prepare: write a self-contained ``design.json`` snapshot into the job dir.
  2. build the parameterized mrDNA model (T0 crossover potentials) from the
     snapshot and call ``model.simulate(coarse_steps, fine_steps=0)`` INTO the
     job dir (persistent — not ``/tmp`` — so the relaxed display survives a
     restart).
  3. extract the relaxed per-nucleotide positions (per-helix coarse spline) +
     the CG bead cloud and cache them as ``display.json`` / ``beads.json``.
  4. mark the job completed.

The long-running work runs in a background daemon thread, exactly like the oxDNA
/ NAMD runners, so the sidebar keeps polling job/progress while ARBD runs.
Stopping kills the detached ARBD child (found by scanning /proc for the job dir),
which unblocks ``simulate()`` so the thread finishes and marks the job stopped.

mrDNA output is Physical-layer only — never written back into Design topology.
"""

from __future__ import annotations

import json
import logging
import os
import signal
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from backend.core.models import Design
from backend.core.mrdna_job import MrdnaJob, MrdnaStatus

logger = logging.getLogger(__name__)

_SIM_STEM = "mrdna_relax"  # model.simulate(output_name=...) base name


def _mrdna_box_dimensions(
    design: Design, margin_angstrom: float = 5000.0
) -> tuple[float, float, float]:
    """Centered ARBD box with enough clearance to prevent resolution-handoff PBCs."""
    import numpy as np

    points = [
        np.asarray(point, dtype=float) * 10.0
        for helix in design.helices
        for point in (helix.axis_start.to_array(), helix.axis_end.to_array())
    ]
    if not points:
        return (5000.0, 5000.0, 5000.0)
    max_abs = np.abs(np.asarray(points)).max(axis=0)
    return tuple(np.maximum(5000.0, 2.0 * (max_abs + margin_angstrom)))


# ── Global task registry ──────────────────────────────────────────────────────


@dataclass
class _RunningHandle:
    thread: threading.Thread
    cancelled: bool = False


_RUNNING: dict[str, _RunningHandle] = {}


def is_running(job_id: str) -> bool:
    handle = _RUNNING.get(job_id)
    return handle is not None and handle.thread.is_alive()


def _external_arbd_pid(job: MrdnaJob, workspace_dir: Path) -> Optional[int]:
    """PID of an ARBD process for this job found by scanning /proc for the job dir
    in an arbd command line — or None.  Matching by the job dir is self-verifying,
    so the PID is safe to signal (used to stop a detached run after a restart, and
    to keep reconcile from mislabelling a still-running orphan ``stopped``)."""
    job_dir = job.job_dir(workspace_dir).resolve()
    needle = str(job_dir).encode()
    try:
        proc_dirs = list(Path("/proc").iterdir())
    except OSError:
        return None
    for proc_dir in proc_dirs:
        if not proc_dir.name.isdigit():
            continue
        try:
            cmdline = (proc_dir / "cmdline").read_bytes()
        except OSError:
            continue
        # mrDNA chdirs into the job directory and launches ARBD with RELATIVE config
        # paths, so the job path is normally absent from cmdline. Match either the
        # absolute command or the process cwd; both are self-verifying.
        cwd_match = False
        try:
            cwd_match = (proc_dir / "cwd").resolve() == job_dir
        except OSError:
            pass
        if (needle in cmdline or cwd_match) and b"arbd" in cmdline.lower():
            try:
                return int(proc_dir.name)
            except ValueError:
                return None
    return None


# ── Availability probe ────────────────────────────────────────────────────────


def mrdna_available() -> dict:
    """Probe for a usable mrDNA + ARBD install (mirror /oxdna/available).

    mrDNA relaxation needs BOTH the mrdna Python package (build the model) AND the
    ARBD binary (run it on the GPU).  ``available`` is true only when both resolve.
    """
    from backend.core.mrdna_bridge import find_arbd, find_mrdna

    mrdna = find_mrdna()
    arbd = find_arbd()
    return {
        "available": bool(mrdna) and bool(arbd),
        "mrdna": mrdna,
        "arbd": arbd,
        "recommended_device": os.environ.get("MRDNA_DEVICE", "0"),
    }


# ── Prepare: write the self-contained job dir ─────────────────────────────────


def prepare_mrdna_job(design: Design, job: MrdnaJob, workspace_dir: Path) -> None:
    """Write a self-contained ``design.json`` snapshot into the job dir, so the
    runner (and every display read) is decoupled from live editor state."""
    design = design.without_reference_geometry()
    jd = job.job_dir(workspace_dir)
    jd.mkdir(parents=True, exist_ok=True)
    (jd / "design.json").write_text(design.model_dump_json())


def _load_snapshot_design(job_dir: Path) -> Optional[Design]:
    snap = job_dir / "design.json"
    if not snap.exists():
        return None
    try:
        return Design.model_validate_json(snap.read_text())
    except Exception:  # noqa: BLE001
        return None


def _psf_is_cg(psf: Path) -> bool:
    """True if a PSF is a mrDNA CG bead model (has 'DNA' beads), not an atomic
    model — used to skip the atomistic tail multiresolution writes."""
    try:
        with psf.open("rb") as fh:
            return b"DNA" in fh.read(300_000)
    except OSError:
        return False


def _sim_paths(job_dir: Path) -> tuple[Path, Path]:
    """(PSF, DCD) of the structure to extract the display from.

    A FINE (multiresolution) run writes numbered stages ``{stem}-N.psf`` (coarse
    N=0 → fine 1 bp/bead N=1 → fine frozen-twist N=2, + an atomic tail); we take the
    highest-numbered CG stage (the relaxed fine structure).  A COARSE run writes the
    single-stage ``{stem}.psf``.  Auto-resolves so both extract the same way."""
    numbered = []
    for psf in job_dir.glob(f"{_SIM_STEM}-*.psf"):
        tail = psf.stem.rsplit("-", 1)[-1]
        if tail.isdigit():
            numbered.append((int(tail), psf))
    for _n, psf in sorted(numbered, reverse=True):
        dcd = job_dir / "output" / f"{psf.stem}.dcd"
        if dcd.exists() and _psf_is_cg(psf):
            return psf, dcd
    return job_dir / f"{_SIM_STEM}.psf", job_dir / "output" / f"{_SIM_STEM}.dcd"


def _coarse_sim_paths(job_dir: Path) -> tuple[Path, Path]:
    """(PSF, DCD) of the LOWEST-numbered CG stage — the coarse (5 bp/bead) relaxation
    of a multiresolution run, whose initial structure is still in the clean NADOC
    design frame.  The DISPLAY falls back to this when the fine stage's bead→helix
    assignment collapses a helix on a tightly-packed bundle (see
    ``_override_has_collapsed_helix``).  For a single-stage coarse run this is the
    same file ``_sim_paths`` returns."""
    numbered = []
    for psf in job_dir.glob(f"{_SIM_STEM}-*.psf"):
        tail = psf.stem.rsplit("-", 1)[-1]
        if tail.isdigit():
            numbered.append((int(tail), psf))
    for _n, psf in sorted(numbered):  # ascending → coarse first
        dcd = job_dir / "output" / f"{psf.stem}.dcd"
        if dcd.exists() and _psf_is_cg(psf):
            return psf, dcd
    return job_dir / f"{_SIM_STEM}.psf", job_dir / "output" / f"{_SIM_STEM}.dcd"


def _override_has_collapsed_helix(
    design: Design, override: dict, frac: float = 0.45
) -> bool:
    """True when the display reconstruction squashed any helix into a small blob —
    the tight-bundle failure mode where the fine stage's nearest-design-axis bead
    assignment dumps one helix's beads onto its neighbour, so that helix reconstructs
    from a handful of points and its spline collapses into a bead 'ring' in the view.

    Detected by the per-helix 3-D bounding-box diagonal vs the expected contour
    length (``length_bp × rise``).  Uses the SPATIAL extent, not the axial projection,
    on purpose: a genuinely *bent* helix (a curved design's programmed loop/skip bend)
    has a short axial projection but still spans a large arc — its bounding diagonal
    stays high (a 180° semicircle is still ~64%), so this does NOT false-fire on
    curvature and drop the fine reconstruction the curvature readout depends on.
    Only a true collapse (blob ≪ half the contour) trips it."""
    import numpy as np
    from collections import defaultdict

    from backend.core.constants import BDNA_RISE_PER_BP

    by_h: dict[str, list] = defaultdict(list)
    for (h_id, _bp, _d), pos in override.items():
        by_h[h_id].append(pos)
    hmap = {h.id: h for h in design.helices}
    for h_id, ps in by_h.items():
        helix = hmap.get(h_id)
        if helix is None or helix.length_bp < 6:
            continue
        arr = np.asarray(ps)
        diag = float(np.linalg.norm(arr.max(axis=0) - arr.min(axis=0)))
        expected = helix.length_bp * BDNA_RISE_PER_BP
        if diag < frac * expected:
            return True
    return False


def _count_stretched_backbone_bonds(override: dict, thr_nm: float = 1.3) -> int:
    """Number of CONSECUTIVE same-helix/same-direction backbone bonds longer than
    ``thr_nm`` in a display override.  The canonical backbone P–P step follows the
    helical path (√(rise² + twist-chord²) ≈ 0.67 nm), so > ~1.3 nm (≈2×) is a
    reconstruction JUMP — the partial-mis-assignment failure mode where the fine
    stage assigns only a sparse, gappy set of beads to a helix and the spline leaps
    across the gaps (the '6hb_2xT overstretched bonds' report).  A local metric,
    insensitive to global BEND, so it does NOT penalise a genuinely curved design."""
    import numpy as np
    from collections import defaultdict

    by_hd: dict[tuple, dict] = defaultdict(dict)
    for (h_id, bp, d), pos in override.items():
        by_hd[(h_id, d)][bp] = pos
    n = 0
    for bpmap in by_hd.values():
        bps = sorted(bpmap)
        for a, b in zip(bps, bps[1:]):
            if (
                b - a == 1
                and float(np.linalg.norm(np.asarray(bpmap[b]) - np.asarray(bpmap[a])))
                > thr_nm
            ):
                n += 1
    return n


def _reconstruction_badness(design: Design, override: dict) -> int:
    """A single 'how wrong does this display reconstruction look' score: a big
    penalty for any collapsed helix (bead ring) plus the count of stretched backbone
    bonds (jumps).  Used to choose the cleaner CG stage — see ``_display_positions``."""
    collapsed = 1 if _override_has_collapsed_helix(design, override) else 0
    return collapsed * 1000 + _count_stretched_backbone_bonds(override)


# ── Extraction: relaxed positions + CG bead cloud ─────────────────────────────

# Bumped when the display reconstruction changes so stale ``display.json`` caches
# from an older algorithm auto-regenerate on the next read (see ``load_display``).
# v2 = actual-relaxed-axis reconstruction (v1 re-idealised → structures barely moved).
# v3 = also emit crossover extra-base (__xb__) positions so the inserts follow the shape.
# v4 = coarse-stage fallback when the fine reconstruction collapses a tight-bundle helix.
# v5 = fallback also fires on stretched backbone bonds (partial mis-assignment jumps).
# v6 = beadless helix ends extrapolate straight instead of clipping to the spline
#      endpoint (clipping pinned the tail into a flat HELIX_RADIUS ring, invisible to
#      both fallback detectors — see mrdna_bridge._relaxed_axis_at_bp).
# v7 = unpaired (ssDNA) nucleotides — incl. single-stranded scaffold crossovers at the
#      helix ends — placed at relaxed NAS-bead positions (nuc_pos_override_ssdna_from_arbd)
#      instead of the phantom-duplex dsDNA axis, so far-end crossover bonds don't stretch.
# v8 = strand-extension tails (5′/3′ ssDNA) are real beads in the model, and their
#      relaxed positions are emitted under the shared ``__ext_<id>`` geometry key.
# v9 = unwrap bonded ARBD coordinates across periodic faces before reconstruction.
_DISPLAY_VERSION = 18


def _add_missing_overhang_records(
    design: Design, records: list[dict], *, replace_out_of_span: bool = False
) -> None:
    """Root-anchor overhang domains absent from an older mrDNA topology.

    Pre-v12 jobs skipped occupied domains outside their child helix's stored bp
    span.  Never borrow another overhang's simulated coordinates from that helix:
    translate the missing domain's authoritative design geometry by its actual
    adjacent strand root displacement.  This preserves every internal and junction
    bond while allowing relaxed/deviation/RMSF views of archived jobs.
    """
    import numpy as np

    from backend.core.design_geometry import _geometry_for_helices

    key = lambda p: (p["helix_id"], p["bp_index"], p["direction"], p.get("copy", 0))
    live = {key(p): p for p in records}
    reference = _geometry_for_helices(design, None, junction_balance=True)
    ref = {key(p): p for p in reference}

    def domain_keys(domain) -> list[tuple]:
        step = 1 if domain.end_bp >= domain.start_bp else -1
        return [
            (domain.helix_id, bp, domain.direction.value, 0)
            for bp in range(domain.start_bp, domain.end_bp + step, step)
        ]

    for strand in design.strands:
        for di, domain in enumerate(strand.domains):
            if domain.overhang_id is None:
                continue
            helix = next((h for h in design.helices if h.id == domain.helix_id), None)
            outside = helix is not None and any(
                not (helix.bp_start <= k[1] < helix.bp_start + helix.length_bp)
                for k in domain_keys(domain)
            )
            missing = [
                k for k in domain_keys(domain)
                if k in ref and (k not in live or (replace_out_of_span and outside))
            ]
            if not missing:
                continue
            root = None
            if di > 0:
                prior = domain_keys(strand.domains[di - 1])
                root = prior[-1] if prior else None
            elif di + 1 < len(strand.domains):
                following = domain_keys(strand.domains[di + 1])
                root = following[0] if following else None
            if root not in live or root not in ref:
                continue
            displacement = np.asarray(live[root]["backbone_position"]) - np.asarray(
                ref[root]["backbone_position"]
            )
            for k in missing:
                source = ref[k]
                out = {
                    "helix_id": k[0],
                    "bp_index": k[1],
                    "direction": k[2],
                    "copy": k[3],
                    "backbone_position": (
                        np.asarray(source["backbone_position"]) + displacement
                    ).tolist(),
                }
                normal = source.get("base_normal")
                tangent = source.get("axis_tangent")
                if normal is not None:
                    out.update(nx=normal[0], ny=normal[1], nz=normal[2])
                if tangent is not None:
                    out.update(tx=tangent[0], ty=tangent[1], tz=tangent[2])
                if k in live:
                    live[k].clear()
                    live[k].update(out)
                else:
                    records.append(out)
                live[k] = out


def _expanded_nucleotide_records(design: Design, override: dict) -> list[dict]:
    """Expand a label-keyed mrDNA reconstruction to every rendered loop copy.

    mrDNA has one reconstructed point per ``(helix, bp, direction)`` while NADOC
    legitimately renders multiple nucleotides at a loop insertion.  Preserve each
    copy's design-space offset about the coincident label's centroid instead of
    stacking every copy at the one reconstructed point.
    """
    from collections import defaultdict

    import numpy as np

    from backend.core.geometry import nucleotide_positions

    records: list[dict] = []
    emitted: set[tuple] = set()
    for helix in design.helices:
        nucs = list(nucleotide_positions(helix))
        groups: dict[tuple, list] = defaultdict(list)
        for nuc in nucs:
            groups[(nuc.helix_id, nuc.bp_index, nuc.direction.value)].append(nuc)
        for key, copies in groups.items():
            if key not in override:
                continue
            emitted.add(key)
            ideal_center = np.mean([n.position for n in copies], axis=0)
            relaxed_center = np.asarray(override[key], dtype=float)
            for copy, nuc in enumerate(copies):
                pos = relaxed_center + (nuc.position - ideal_center)
                records.append(
                    {
                        "helix_id": key[0],
                        "bp_index": key[1],
                        "direction": key[2],
                        "copy": copy,
                        "backbone_position": pos.tolist(),
                    }
                )
    for key, pos in override.items():
        if isinstance(key[0], str) and key[0].startswith("__ext_"):
            records.append(
                {
                    "helix_id": key[0],
                    "bp_index": key[1],
                    "direction": key[2],
                    "copy": 0,
                    "backbone_position": np.asarray(pos).tolist(),
                }
            )
        elif key not in emitted:
            records.append(
                {
                    "helix_id": key[0],
                    "bp_index": key[1],
                    "direction": key[2],
                    "copy": 0,
                    "backbone_position": np.asarray(pos).tolist(),
                }
            )
    return records


def _add_relaxed_frames(positions: list[dict]) -> None:
    """Add slab normals/tangents derived from the relaxed duplex geometry."""
    import numpy as np

    by_key = {
        (p["helix_id"], p["bp_index"], p["direction"], p.get("copy", 0)): p
        for p in positions
        if not str(p["helix_id"]).startswith("__")
    }
    centers: dict[tuple, np.ndarray] = {}
    for (hid, bp, direction, copy), p in by_key.items():
        other = "REVERSE" if direction == "FORWARD" else "FORWARD"
        mate = by_key.get((hid, bp, other, copy)) or by_key.get((hid, bp, other, 0))
        if mate is not None:
            centers[(hid, bp, copy)] = 0.5 * (
                np.asarray(p["backbone_position"]) + np.asarray(mate["backbone_position"])
            )
    for key, p in by_key.items():
        hid, bp, direction, copy = key
        other = "REVERSE" if direction == "FORWARD" else "FORWARD"
        mate = by_key.get((hid, bp, other, copy)) or by_key.get((hid, bp, other, 0))
        if mate is None:
            continue
        normal = np.asarray(mate["backbone_position"]) - np.asarray(p["backbone_position"])
        nn = np.linalg.norm(normal)
        same_helix = sorted(k for k in centers if k[0] == hid and k[2] == copy)
        # An inserted copy exists at only one bp.  Its local axis is the parent
        # helix's copy-0 axis, not an undefined one-point curve.
        if len(same_helix) < 2:
            same_helix = sorted(k for k in centers if k[0] == hid and k[2] == 0)
        before = [k for k in same_helix if k[1] < bp]
        after = [k for k in same_helix if k[1] > bp]
        if before and after:
            tangent = centers[after[0]] - centers[before[-1]]
        elif after:
            tangent = centers[after[0]] - centers[(hid, bp, copy)]
        elif before:
            tangent = centers[(hid, bp, copy)] - centers[before[-1]]
        else:
            continue
        tn = np.linalg.norm(tangent)
        if nn > 1e-9 and tn > 1e-9:
            normal /= nn
            tangent /= tn
            p.update(nx=float(normal[0]), ny=float(normal[1]), nz=float(normal[2]))
            p.update(tx=float(tangent[0]), ty=float(tangent[1]), tz=float(tangent[2]))


def _display_positions(design: Design, job_dir: Path) -> tuple[list[dict], int]:
    """Per-nucleotide relaxed backbone positions (applyFemPositions list) from the
    DISPLAY reconstruction (actual relaxed axis) + intra-helix gap-fill so every
    nucleotide moves consistently.  Returns ``(positions, n_override)``; nm."""
    from backend.core.mrdna_decoder import decode_mrdna_frame
    from backend.core.mrdna_manifest import MrdnaNucleotideManifest

    # Manifest-backed jobs use the one identity-preserving decoder. Jobs without
    # a manifest are unsupported by policy and must never fall into the legacy
    # proximity/alias reconstruction below.
    MrdnaNucleotideManifest.load_required(job_dir)
    psf, dcd = _sim_paths(job_dir)
    decoded = decode_mrdna_frame(job_dir, psf, dcd, design=design, frame=-1)
    if not decoded["quality"]["usable"]:
        raise RuntimeError(
            "mrDNA decoded frame failed structural validation: "
            f"{len(decoded['quality']['missing_identities'])} missing, "
            f"{len(decoded['quality']['bond_errors'])} bond error(s)"
        )
    return decoded["positions"], len(decoded["positions"])


def extract_mrdna_results(design: Design, job_dir: Path) -> dict:
    """Read the coarse ARBD output and return the cached display payload:

    ``{"positions": [...applyFemPositions...], "beads": [[x,y,z]...],
       "edges": [[i,j]...], "n_override": int, "n_beads": int}``.  All lengths nm.
    """
    psf, dcd = _sim_paths(job_dir)
    positions, n_override = _display_positions(design, job_dir)
    beads, edges = _extract_beads_aligned(str(psf), str(dcd))
    return {
        "positions": positions,
        "beads": beads,
        "edges": edges,
        "n_override": n_override,
        "n_beads": len(beads),
    }


def load_display(job_dir: Path) -> Optional[dict]:
    """Load or regenerate a manifest-decoded relaxed-display payload."""
    from backend.core.mrdna_manifest import MrdnaNucleotideManifest

    MrdnaNucleotideManifest.load_required(job_dir)
    cached = load_cached(job_dir, "display.json")
    if cached and cached.get("version") == _DISPLAY_VERSION and cached.get("positions"):
        return cached
    design = _load_snapshot_design(job_dir)
    psf, dcd = _sim_paths(job_dir)
    if design is None or not (psf.exists() and dcd.exists()):
        return cached  # can't recompute (e.g. archived without outputs) — serve old
    positions, _ = _display_positions(design, job_dir)
    out = {"version": _DISPLAY_VERSION, "positions": positions}
    try:
        (job_dir / "display.json").write_text(json.dumps(out))
    except Exception:  # noqa: BLE001
        pass
    return out


def mrdna_trajectory_rmsf(
    design: Design, job_dir: Path, *, max_frames: int = 40
) -> Optional[dict]:
    """Per-nucleotide RMSF (nm) from the CG relaxation TRAJECTORY — the mrDNA flexibility
    contribution to the cross-engine comparison card (M5).

    Reconstructs the per-nucleotide relaxed backbone frame at each DCD timestep (the SAME
    actual-relaxed-axis reconstruction the display uses, per frame) and feeds the ensemble to
    the shared ``rmsf_from_ensemble`` (Kabsch-aligned to strip the CG bundle's box diffusion/
    tumbling, so what's left is site fluctuation).  Returns the ``rmsf_from_ensemble`` payload
    (``{positions:[{helix_id,bp_index,direction,copy,rmsf_nm,...}], n_frames, ...}``) or None
    when there is no trajectory / fewer than two frames.  Frames are evenly subsampled to
    ``max_frames`` (each reconstruction re-reads the DCD, so this bounds the cost).

    Physical-layer / read-only: reads positions off the trajectory, never mutates topology.
    """
    from backend.core.mrdna_decoder import decode_mrdna_frame
    from backend.core.mrdna_manifest import MrdnaNucleotideManifest
    from backend.core.shape_metrics import rmsf_from_ensemble

    MrdnaNucleotideManifest.load_required(job_dir)
    psf, dcd = _sim_paths(job_dir)
    if not (psf.exists() and dcd.exists()):
        return None

    import MDAnalysis as mda

    n = len(mda.Universe(str(psf), str(dcd)).trajectory)
    if n < 2:
        return None
    if n <= max_frames:
        idxs = list(range(n))
    else:
        idxs = sorted(
            {round(i * (n - 1) / (max_frames - 1)) for i in range(max_frames)}
        )

    frames: list[list[dict]] = []
    for i in idxs:
        decoded = decode_mrdna_frame(job_dir, psf, dcd, design=design, frame=i)
        if not decoded["quality"]["usable"]:
            raise RuntimeError(
                f"mrDNA trajectory frame {i} failed structural validation"
            )
        frames.append(decoded["positions"])
    if len([f for f in frames if f]) < 2:
        return None
    return rmsf_from_ensemble(frames, align=True)


def _extract_beads_aligned(
    psf: str, dcd: str
) -> tuple[list[list[float]], list[list[int]]]:
    """The coarse DNA bead cloud (last DCD frame), rigid-body (Kabsch) aligned onto
    the initial coarse PDB — which mrDNA writes in the NADOC coordinate frame — so
    the beads overlay the design, PLUS the CG bond connectivity (backbone chain +
    crossover links) read from the coarse PSF and remapped into the DNA-bead index
    space.  Returns ``(positions_nm, edges)`` where each edge is ``[i, j]`` into the
    positions list."""
    import numpy as np

    from backend.core.mrdna_bridge import _ensure_mrdna, _unwrapped_universe_positions

    _ensure_mrdna()
    import MDAnalysis as mda

    init_pdb = psf.replace(".psf", ".pdb")
    u_init = mda.Universe(psf, init_pdb)
    names = np.array([a.name for a in u_init.atoms])
    dna = np.where(names == "DNA")[0]
    ref = u_init.atoms.positions[dna].astype(float)  # NADOC frame, Å

    edges = _psf_dna_edges(psf, u_init=u_init, dna=dna)

    u = mda.Universe(psf, dcd)
    u.trajectory[-1]
    sim = _unwrapped_universe_positions(u, u_init.atoms.positions)[dna].astype(float)

    if len(ref) >= 3 and len(sim) == len(ref):
        aligned = _kabsch_apply(sim, ref)
    else:
        aligned = sim
    return (aligned / 10.0).tolist(), edges  # Å → nm


def _psf_dna_edges(psf: str, *, u_init=None, dna=None) -> list[list[int]]:
    """CG bond edges (backbone chain + crossover links) between DNA beads, read from
    the coarse PSF and remapped into the DNA-bead index space (bonds to non-DNA
    beads — orientation/ssDNA — are dropped, since only DNA beads are rendered).
    ``u_init``/``dna`` may be passed to reuse an already-loaded Universe."""
    import numpy as np

    from backend.core.mrdna_bridge import _ensure_mrdna

    _ensure_mrdna()
    import MDAnalysis as mda

    if u_init is None:
        u_init = mda.Universe(psf, psf.replace(".psf", ".pdb"))
    if dna is None:
        names = np.array([a.name for a in u_init.atoms])
        dna = np.where(names == "DNA")[0]

    global_to_local = {int(g): i for i, g in enumerate(dna)}
    edges: list[list[int]] = []
    try:
        for a, b in u_init.bonds.indices:
            a, b = int(a), int(b)
            if a in global_to_local and b in global_to_local:
                edges.append([global_to_local[a], global_to_local[b]])
    except Exception:  # noqa: BLE001 — no bonds parsed → just no connections
        edges = []
    return edges


def load_beads_with_edges(job_dir: Path) -> Optional[dict]:
    """Load the cached beads payload, backfilling ``edges`` from the coarse PSF for
    jobs completed before the connections feature (their beads.json has no edges).
    Returns None if there is no cached bead cloud."""
    cached = load_cached(job_dir, "beads.json")
    if not cached or not cached.get("beads"):
        return None
    if cached.get("edges"):
        return cached
    psf, _ = _sim_paths(job_dir)
    edges: list[list[int]] = []
    if psf.exists():
        try:
            edges = _psf_dna_edges(str(psf))
        except Exception:  # noqa: BLE001
            edges = []
    cached["edges"] = edges
    try:
        (job_dir / "beads.json").write_text(json.dumps(cached))
    except Exception:  # noqa: BLE001 — display still works from the in-memory copy
        pass
    return cached


def load_curvature(job_dir: Path) -> Optional[dict]:
    """Designed-vs-simulated curvature report, computing + caching it on first read
    for jobs completed before the curvature feature (or when the display cache was
    regenerated).  Returns None if there's no design snapshot to compute from."""
    cached = load_cached(job_dir, "curvature.json")
    if cached:
        return cached
    design = _load_snapshot_design(job_dir)
    if design is None:
        return None
    disp = load_display(job_dir)
    positions = disp.get("positions") if disp else None
    from backend.core.mrdna_curvature import curvature_report

    report = curvature_report(design, positions)
    try:
        (job_dir / "curvature.json").write_text(json.dumps(report))
    except Exception:  # noqa: BLE001
        pass
    return report


def _kabsch_apply(mobile: "any", target: "any") -> "any":
    """Rigid-body superpose ``mobile`` onto ``target`` (both (N,3)); return the
    transformed ``mobile``.  Best-fit rotation + translation (no scaling)."""
    import numpy as np

    mc = mobile.mean(axis=0)
    tc = target.mean(axis=0)
    H = (mobile - mc).T @ (target - tc)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    D = np.diag([1.0, 1.0, d])
    R = Vt.T @ D @ U.T
    return (mobile - mc) @ R.T + tc


def load_cached(job_dir: Path, name: str) -> Optional[dict]:
    """Load a cached ``display.json`` / ``beads.json`` payload, or None."""
    p = job_dir / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:  # noqa: BLE001
        return None


# ── MD seeding: completed fine-stage job → atomistic nuc_pos_override ──────────
#
# The DISPLAY path (nuc_pos_override_display_from_coarse) is for the viewer; it
# shows the actual relaxed shape but EXCLUDES nothing and re-anchors to the coarse
# axis.  Seeding an atomistic MD run is a different job with different correctness
# needs, so it uses a different override: nuc_pos_override_from_arbd_strands (the
# Phase-3b per-helix spline over the FINE stage), which INCLUDES crossover-junction
# nucleotides at the CG-realistic ~0.3-0.5 nm gap.  That gap is exactly what lets
# downstream GROMACS EM converge without the ~0.05 nm ideal-B-DNA crossover clash
# (the 10¹² kJ/mol LJ spike).  Both are Physical-layer only — never write topology.


def resolve_md_seed_inputs(
    job: MrdnaJob, workspace_dir: Path
) -> tuple[Design, Path, Path]:
    """Gate + resolve the inputs to seed an atomistic MD run from a COMPLETED
    fine-stage mrDNA job: the design snapshot the relaxation ran on, plus the
    fine-stage ``(PSF, DCD)``.

    Every failure raises ``ValueError`` with a UI-ready message:
      - the job must be ``completed`` — a running/failed/stopped job has no trusted
        relaxed output to seed from;
      - the job must have run the FINE stage (``fine_steps > 0``).  The coarse stage
        carries one bead per *base pair* with no per-strand backbone, so it cannot
        seed atomistic coordinates; only the fine stage (1 DNA bead/bp at the
        FORWARD backbone) drives ``nuc_pos_override_from_arbd_strands``;
      - the snapshot ``design.json`` and the on-disk fine ``{stem}-N.psf`` + DCD
        must exist (``_sim_paths`` falls back to the single-stage coarse file when
        no numbered fine stage is present, which we reject here).
    """
    if job.status != MrdnaStatus.completed:
        raise ValueError(
            f"mrDNA job is {job.status.value}; only a completed job can seed an MD run."
        )
    if job.fine_steps <= 0:
        raise ValueError(
            "This mrDNA job is coarse-only (fine_steps = 0).  MD seeding needs the "
            "fine stage (1 bead per base pair backbone) — re-run the relaxation with "
            "fine steps before seeding an MD run."
        )
    jd = job.job_dir(workspace_dir)
    design = _load_snapshot_design(jd)
    if design is None:
        raise ValueError("mrDNA job design snapshot (design.json) is missing.")
    psf, dcd = _sim_paths(jd)
    if "-" not in psf.stem:
        raise ValueError(
            "mrDNA job has no fine-stage output on disk (only a coarse stage was "
            "found); the fine stage is required to seed an MD run."
        )
    if not (psf.exists() and dcd.exists()):
        raise ValueError(
            "mrDNA job fine-stage output (PSF/DCD) not found; the relaxation may not "
            "have finished the fine stage."
        )
    return design, psf, dcd


def build_md_seed_override(design: Design, psf: Path, dcd: Path) -> dict:
    """Atomistic ``nuc_pos_override`` from a fine-stage mrDNA ``(PSF, DCD)`` — the dict
    consumed by ``build_gromacs_package(nuc_pos_override=...)``.  Keyed
    ``(helix_id, bp_index, direction) → position`` in nm.  Physical-layer only.

    Two sources, merged:
      - dsDNA in-helix base pairs → per-helix Phase-3b spline (crossovers INCLUDED);
      - ssDNA / overhang nucleotides → relaxed ``NAS`` beads (spline) with a
        root-anchored fallback, so sticky ends follow the relaxed body instead of
        seeding at the detached design-axis extrapolation (the ss clash source).
    ss entries take precedence at any shared (interior-unpaired) key."""
    from backend.core.mrdna_bridge import (
        _ensure_mrdna,
        nuc_pos_override_from_arbd_strands,
        nuc_pos_override_ssdna_from_arbd,
    )

    _ensure_mrdna()
    ds = nuc_pos_override_from_arbd_strands(design, str(psf), str(dcd))
    ss = nuc_pos_override_ssdna_from_arbd(design, str(psf), str(dcd), ds)
    return {**ds, **ss}


def assert_mrdna_namd_seed_available(job_id: str, workspace_dir: Path) -> None:
    """Cheap precheck that a NAMD seed CAN be built from this mrDNA job — mirrors
    ``oxdna_runner.assert_namd_seed_available``.  Reuses ``resolve_md_seed_inputs``
    (completed + fine-stage + snapshot/PSF/DCD present) WITHOUT the expensive override
    build, so the create-job route can reject a bad ``mrdna_job_id`` with a fast 400.
    Raises ``FileNotFoundError`` (the error the MD route catches) on any gating fail."""
    job = MrdnaJob.load(job_id, workspace_dir)  # FileNotFoundError if unknown
    job = reconcile_mrdna_status(job, workspace_dir)
    try:
        resolve_md_seed_inputs(job, workspace_dir)
    except ValueError as exc:
        raise FileNotFoundError(str(exc)) from exc


def build_namd_seed_from_mrdna(job_id: str, workspace_dir: Path):
    """Build a NAMD starting-structure seed from a completed fine-stage mrDNA job —
    the mrDNA sibling of ``oxdna_runner.build_namd_seed``.

    Reads the job's OWN ``design.json`` snapshot (never the live editor design) and
    reconstructs an atomistic model whose backbone follows the mrDNA-relaxed CG
    structure (``build_md_seed_override`` → ``build_atomistic_model``), then recenters
    it on the origin (a relaxed structure can sit far off-origin; the PDB's 8-char
    coordinate fields overflow past ~±1000 Å otherwise).  Returns the shared
    ``NamdSeed`` artifact.  Physical-layer only — a NAMD INPUT, never topology."""
    from backend.core.oxdna_runner import NamdSeed
    from backend.core.atomistic import build_atomistic_model

    job = MrdnaJob.load(job_id, workspace_dir)
    job = reconcile_mrdna_status(job, workspace_dir)
    design, psf, dcd = resolve_md_seed_inputs(job, workspace_dir)  # gates; ValueError
    override = build_md_seed_override(design, psf, dcd)
    model = build_atomistic_model(design, nuc_pos_override=override)

    if model.atoms:
        import numpy as np

        cx, cy, cz = np.mean([[a.x, a.y, a.z] for a in model.atoms], axis=0).tolist()
        for a in model.atoms:
            a.x -= cx
            a.y -= cy
            a.z -= cz

    return NamdSeed(
        design=design,
        atomistic_model=model,
        stage_name="mrdna_fine",
        conf_path=dcd,
        source_job_id=job_id,
    )


# ── Progress (time-based estimate; the bar for a short coarse run) ─────────────


def _estimate_seconds(job: MrdnaJob) -> float:
    """Rough wall-clock estimate for the coarse ARBD run, scaled by system size and
    step count.  Only drives the progress bar (capped < 1.0 until the thread ends);
    the true completion signal is the runner thread finishing."""
    beads = max(1.0, job.n_nucleotides / 2.0)  # ≈ base pairs ≈ coarse beads
    # Reference: ~635 beads · 1e5 coarse steps ≈ 21 s on an RTX 3080 Ti; be generous.
    est = 8.0 + (beads / 635.0) * (job.coarse_steps / 1e5) * 30.0
    # The FINE stage (2 bp/bead + orientation) is ~3× the per-step cost of coarse.
    if job.fine_steps > 0:
        est += (beads / 635.0) * (job.fine_steps / 1e5) * 90.0
    return max(10.0, est)


def job_progress(job: MrdnaJob, workspace_dir: Path) -> dict:
    """Overall progress fraction + ETA for the panel."""
    stage = job.stages[0] if job.stages else None
    overall = 0.0
    eta_seconds: float | None = None
    if job.status == MrdnaStatus.completed:
        overall = 1.0
    elif job.status in (MrdnaStatus.failed, MrdnaStatus.stopped):
        overall = 0.0
    stage_name = stage.name if stage else None
    stage_fraction = 0.0
    if job.status == MrdnaStatus.running and stage and stage.started_at:
        actual = _multiresolution_progress(job, workspace_dir)
        if actual is not None:
            overall, stage_name, stage_fraction = actual
        else:
            elapsed = time.time() - stage.started_at
            est = _estimate_seconds(job)
            overall = min(0.97, elapsed / est)
            stage_fraction = overall
            eta_seconds = max(0.0, est - elapsed)
    return {
        "overall": overall,
        "status": job.status.value,
        "stage_status": stage.status if stage else None,
        "stage_name": stage_name,
        "stage_fraction": stage_fraction,
        "eta_seconds": eta_seconds,
        "sim_seconds": job.sim_seconds,
    }


def _dcd_frame_count(path: Path) -> int:
    """Read the DCD NSET header while ARBD is writing it (no trajectory scan)."""
    try:
        with path.open("rb") as fh:
            header = fh.read(12)
        if len(header) < 12 or header[4:8] != b"CORD":
            return 0
        return max(0, struct.unpack("<i", header[8:12])[0])
    except (OSError, struct.error):
        return 0


def _multiresolution_progress(
    job: MrdnaJob, workspace_dir: Path
) -> Optional[tuple[float, str, float]]:
    """Actual Fine-job progress from frames written by its three ARBD phases."""
    if job.fine_steps <= 0:
        return None
    jd = job.job_dir(workspace_dir)
    phases = [
        ("coarse", job.coarse_steps, min(job.output_period, job.coarse_steps)),
        ("fine (twist)", job.fine_steps, max(1, job.fine_steps // 2)),
        ("fine (frozen twist)", job.fine_steps, max(1, job.fine_steps // 2)),
    ]
    total_steps = float(sum(p[1] for p in phases))
    completed = 0.0
    active_name = phases[0][0]
    active_fraction = 0.0
    saw_output = False
    for idx, (name, steps, period) in enumerate(phases):
        frames = _dcd_frame_count(jd / "output" / f"{_SIM_STEM}-{idx}.dcd")
        if frames <= 0:
            break
        saw_output = True
        intervals = max(1, (steps + period - 1) // period)
        frac = min(1.0, max(0.0, (frames - 1) / intervals))
        completed += steps * frac
        active_name, active_fraction = name, frac
        if frac < 1.0:
            break
    if not saw_output:
        return None
    # ARBD frames can reach their target before mrDNA has read the restart and
    # generated the next resolution. Keep the bar below 100 until extraction ends.
    return min(0.99, completed / total_steps), active_name, active_fraction


# ── Execution ─────────────────────────────────────────────────────────────────


def _run_job(job: MrdnaJob, workspace_dir: Path) -> None:
    """Thread body: build the model, run the coarse ARBD sim, extract + cache."""
    jd = job.job_dir(workspace_dir)
    handle = _RUNNING.get(job.job_id)

    def _cancelled() -> bool:
        return handle is not None and handle.cancelled

    try:
        design = _load_snapshot_design(jd)
        if design is None:
            raise RuntimeError("job design snapshot (design.json) missing")

        from backend.core.mrdna_bridge import ensure_wsl_cuda_libs

        ensure_wsl_cuda_libs()

        # Build the parameterized mrDNA model (same T0 crossover potentials the
        # one-shot /ws/mrdna-relax used).
        from backend.parameterization.mrdna_inject import (
            CrossoverPotentialOverride,
            mrdna_model_from_nadoc_parameterized,
        )

        override = CrossoverPotentialOverride.from_database("T0")
        model = mrdna_model_from_nadoc_parameterized(design, override)
        from backend.core.mrdna_manifest import (
            bind_manifest_to_mrdna_particles,
            build_mrdna_nucleotide_manifest,
        )

        if not job.design_fingerprint:
            raise RuntimeError("mrDNA job is missing its design fingerprint")
        manifest = build_mrdna_nucleotide_manifest(
            design, design_fingerprint=job.design_fingerprint
        )
        manifest = bind_manifest_to_mrdna_particles(manifest, model)
        manifest.write(jd)
        # Presence means this job was built after out-of-span extruded overhangs
        # became real mrDNA sites. Archived jobs without it use the root-anchored
        # display fallback instead of misreading unrelated NAS beads.
        (jd / "extended_overhang_topology.v1").touch()
        # mrDNA's multiresolution driver passes each ARBD restart directly into
        # the next resolution without unwrapping. Its 5000 Å default box is only
        # slightly longer than VoltronCoreArm, so routine relaxation crossed a
        # face and generated box-length bonds in the fine input.
        model.dimensions = _mrdna_box_dimensions(design)

        # Anchors (job-request annotation, never a topology edit): pin the beads
        # covering the chosen scopes so an unanchored uniform force / drift can't
        # stream the structure.  Survives the bead regeneration a fine (multi-
        # resolution) run does between stages.  See backend/core/mrdna_anchors.py.
        n_held = 0
        if job.anchors:
            from backend.core.mrdna_anchors import install_anchor_restraints

            n_held = install_anchor_restraints(design, model, job.anchors)
            logger.info(
                "mrdna job %s: installed anchors on %d bead(s)", job.job_id, n_held
            )

        # E-field (job-request annotation, never a topology edit): a constant per-bead
        # force from the shared {field_pN, dir} descriptor, applied via ARBD force grids
        # scaled by each bead's nucleotide content.  Needs the anchors above to hold
        # against COM drift.  Survives the fine-run bead regeneration.  See
        # backend/core/mrdna_field.py.
        if job.e_field:
            # An unanchored field (no anchor chips, or a scope resolving to no beads)
            # just streams the structure down-field (COM drift).  Anchors are
            # recommended but no longer required — the UI warns; the run proceeds.
            if n_held == 0:
                logger.warning(
                    "mrdna job %s: E-field with no held beads — the structure will "
                    "drift down-field (COM drift).",
                    job.job_id,
                )
            from backend.core.mrdna_field import install_field_force

            n_types = install_field_force(design, model, job.e_field, out_dir=jd)
            logger.info(
                "mrdna job %s: installed E-field on %d bead type(s)",
                job.job_id,
                n_types,
            )

        # Hard surface (job-request annotation, never a topology edit): a one-sided
        # repulsion plane from the shared {dir, offset_nm, stiff} descriptor, applied via
        # an ARBD grid potential.  Installed AFTER the field so its regen wrapper is the
        # outer one — on every bead regeneration the field re-applies (overwrite) first
        # and the surface re-appends after, so both grids survive.  See
        # backend/core/mrdna_surface.py.
        if job.surface:
            from backend.core.mrdna_surface import install_surface_force

            n_surf = install_surface_force(design, model, job.surface, out_dir=jd)
            logger.info(
                "mrdna job %s: installed hard surface on %d bead type(s)",
                job.job_id,
                n_surf,
            )

        if _cancelled():
            raise _Cancelled()

        # Mark the stage running now (progress ETA counts from here).
        job.status = MrdnaStatus.running
        job.stages[0].status = "running"
        job.stages[0].started_at = time.time()
        job.save(workspace_dir)

        (jd / "output").mkdir(parents=True, exist_ok=True)
        gpu = int(job.device) if str(job.device).isdigit() else 0
        t0 = time.monotonic()
        if job.fine_steps > 0:
            # CURVATURE path: the real mrDNA multiresolution pipeline — coarse
            # (5 bp/bead) → fine (1 bp/bead + local twist) → frozen-twist.  The fine
            # stage is what develops loop/skip curvature; it writes numbered CG stages
            # {stem}-N (+ an atomic tail we ignore).  NOTE: `model.simulate(coarse_steps=
            # …)` does NOT do this — it silently runs a single coarse pass (the
            # coarse_steps/fine_steps kwargs are swallowed by ArbdEngine).
            from mrdna import multiresolution_simulation

            try:
                multiresolution_simulation(
                    model,
                    _SIM_STEM,
                    directory=str(jd),
                    gpu=gpu,
                    coarse_steps=float(job.coarse_steps),
                    fine_steps=float(job.fine_steps),
                    coarse_output_period=float(
                        min(job.output_period, job.coarse_steps)
                    ),
                    fine_output_period=float(max(1, job.fine_steps // 2)),
                )
            except Exception as exc:  # noqa: BLE001
                # The fine CG stages are written BEFORE the atomistic tail; if that
                # tail (or a post-fine step) fails but the fine CG output exists,
                # proceed with it rather than failing the whole job.
                if _cancelled():
                    raise
                psf, _dcd = _sim_paths(jd)
                if "-" not in psf.stem or not psf.exists():
                    raise
                logger.warning(
                    "mrdna job %s: multiresolution tail failed (%s); "
                    "using the completed fine CG stage",
                    job.job_id,
                    exc,
                )
        else:
            # COARSE path: a single 5 bp/bead pass (fast, global shape, no twist ⇒ no
            # curvature).  The correct step kwarg is `num_steps` (not coarse_steps).
            model.simulate(
                output_name=_SIM_STEM,
                directory=str(jd),
                num_steps=float(job.coarse_steps),
                timestep=200e-6,
                output_period=float(job.output_period),
                gpu=gpu,
            )
        sim_seconds = time.monotonic() - t0

        if _cancelled():
            raise _Cancelled()

        # Fine/multiresolution runs regenerate beads. Persist bindings for the
        # actual final topology that wrote the selected PSF/DCD, not the launch
        # topology retained only for setup diagnostics. mrDNA's optional atomic
        # tail clears the CG beads before returning, so deterministically rebuild
        # the same frozen-twist 1-bp topology that wrote the final CG PSF. Splines
        # already contain the final relaxed coordinates; this does not rerun or
        # alter the saved trajectory.
        if job.fine_steps > 0:
            _restore_final_binding_topology(model)
        manifest = bind_manifest_to_mrdna_particles(manifest, model)
        if any(not record.particle_bindings for record in manifest.records):
            missing = sum(not record.particle_bindings for record in manifest.records)
            raise RuntimeError(
                f"mrDNA final topology left {missing} nucleotide identities unbound"
            )
        manifest.write(jd)

        payload = _finalize_outputs(job, design, workspace_dir, sim_seconds)
        logger.info(
            "mrdna job %s completed in %.1fs (%d beads)",
            job.job_id,
            sim_seconds,
            payload["n_beads"],
        )

    except _Cancelled:
        job.status = MrdnaStatus.stopped
        job.arbd_pid = None
        for st in job.stages:
            if st.status != "done":
                st.status = "failed"
        job.save(workspace_dir)
    except Exception as exc:  # noqa: BLE001
        logger.error("mrdna job %s failed: %s", job.job_id, exc, exc_info=True)
        # A killed ARBD child surfaces here as a generic error; if we asked to
        # cancel, treat it as a stop rather than a failure.
        if _cancelled():
            job.status = MrdnaStatus.stopped
        else:
            job.status = MrdnaStatus.failed
            job.error = str(exc)
        job.arbd_pid = None
        for st in job.stages:
            if st.status != "done":
                st.status = "failed"
        job.save(workspace_dir)
    finally:
        _RUNNING.pop(job.job_id, None)


def _restore_final_binding_topology(model) -> None:
    """Rebuild the deterministic final Fine CG topology after mrDNA's atomic tail."""
    model.clear_beads()
    model.generate_bead_model(1, 1, local_twist=True, escapable_twist=False)


class _Cancelled(Exception):
    pass


def _finalize_outputs(
    job: MrdnaJob,
    design: Design,
    workspace_dir: Path,
    sim_seconds: float | None = None,
) -> dict:
    """Extract/cache completed ARBD output and atomically publish completion.

    Shared by the normal runner and restart recovery: a dev-server reload can kill
    the Python thread after ARBD wrote its final DCD but before display extraction.
    """
    jd = job.job_dir(workspace_dir)
    payload = extract_mrdna_results(design, jd)
    (jd / "display.json").write_text(json.dumps({
        "version": _DISPLAY_VERSION, "positions": payload["positions"],
    }))
    (jd / "beads.json").write_text(json.dumps({
        "beads": payload["beads"], "edges": payload["edges"],
    }))
    try:
        from backend.core.mrdna_curvature import curvature_report

        (jd / "curvature.json").write_text(
            json.dumps(curvature_report(design, payload["positions"]))
        )
    except Exception:  # noqa: BLE001
        logger.warning("mrdna job %s: curvature report failed", job.job_id, exc_info=True)
    if sim_seconds is not None:
        job.sim_seconds = round(sim_seconds, 2)
    job.n_override = payload["n_override"]
    job.n_beads = payload["n_beads"]
    for st in job.stages:
        st.status = "done"
    job.status = MrdnaStatus.completed
    job.error = None
    job.arbd_pid = None
    job.save(workspace_dir)
    return payload


def start_job(job: MrdnaJob, workspace_dir: Path) -> None:
    """Launch _run_job in a background daemon thread. Idempotent if running."""
    if is_running(job.job_id):
        return
    # Model generation can be substantial for a Voltron-class design. Publish it
    # as preparation immediately instead of leaving an autostarted job "queued".
    job.status = MrdnaStatus.preparing
    job.save(workspace_dir)
    handle = _RunningHandle(
        thread=threading.Thread(
            target=_run_job,
            args=(job, workspace_dir),
            name=f"mrdna-runner-{job.job_id}",
            daemon=True,
        )
    )
    _RUNNING[job.job_id] = handle
    handle.thread.start()


def _pid_is_arbd(pid: int) -> bool:
    try:
        cmdline = (Path("/proc") / str(pid) / "cmdline").read_bytes().lower()
    except OSError:
        return False
    return b"arbd" in cmdline


def stop_job(job_id: str, workspace_dir: Path) -> bool:
    """Stop a running mrDNA job.  Sets the cancel flag and kills the detached ARBD
    child (found via /proc, self-verifying, or the persisted ``arbd_pid``) so the
    blocked ``simulate()`` unwinds and the thread marks the job stopped.  Returns
    True if a live job or orphan process was found."""
    handle = _RUNNING.get(job_id)
    live = handle is not None and handle.thread.is_alive()
    if handle is not None:
        handle.cancelled = True

    try:
        job = MrdnaJob.load(job_id, workspace_dir)
    except Exception:  # noqa: BLE001
        return live

    pid = _external_arbd_pid(job, workspace_dir)
    if pid is None and job.arbd_pid and _pid_is_arbd(job.arbd_pid):
        pid = job.arbd_pid
    if pid is not None:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
        live = True

    if not live and job.status == MrdnaStatus.running:
        # No live thread and no orphan process → just mark it stopped.
        job.status = MrdnaStatus.stopped
        job.arbd_pid = None
        job.save(workspace_dir)
    return live


def reconcile_mrdna_status(job: MrdnaJob, workspace_dir: Path) -> MrdnaJob:
    """Recover a detached job's status after the runner thread died (e.g. a
    ``uvicorn --reload`` restart mid-run).  If the cached ``display.json`` exists the
    run finished → ``completed``; if the ARBD child is gone and nothing was cached →
    ``stopped``.  No-op unless the job is an orphaned ``running`` one."""
    pid = _external_arbd_pid(job, workspace_dir)
    if is_running(job.job_id) or pid is not None:
        changed = False
        if pid is not None and job.arbd_pid != pid:
            job.arbd_pid = pid
            changed = True
        if pid is not None and job.status != MrdnaStatus.running:
            job.status = MrdnaStatus.running
            changed = True
        if changed:
            job.save(workspace_dir)
        return job
    jd = job.job_dir(workspace_dir)
    if (jd / "display.json").exists():
        job.status = MrdnaStatus.completed
        for st in job.stages:
            st.status = "done"
        job.save(workspace_dir)
        return job
    # Fine ARBD can finish just before a server reload kills the blocked Python
    # runner. Recover the complete raw three-phase output instead of leaving the
    # old (formerly mis-persisted) queued job stuck forever or rerunning it.
    actual = _multiresolution_progress(job, workspace_dir)
    if (job.fine_steps > 0 and actual and actual[0] >= 0.99):
        design = _load_snapshot_design(jd)
        if design is not None:
            try:
                _finalize_outputs(job, design, workspace_dir)
                logger.info("mrdna job %s finalized from completed orphan output", job.job_id)
                return job
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "mrdna job %s orphan-output finalization failed: %s",
                    job.job_id,
                    exc,
                    exc_info=True,
                )
    if job.status != MrdnaStatus.running:
        return job
    job.status = MrdnaStatus.stopped
    job.arbd_pid = None
    for st in job.stages:
        if st.status != "done":
            st.status = "failed"
    job.save(workspace_dir)
    return job
