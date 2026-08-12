"""Validation oracle for the oxDNA → atomistic DISPLAY reconstruction.

Every element the atomistic ball-and-stick / VDW representation draws under the
**oxDNA-display** toggle is measurable here so it can be queried + validated
programmatically, not just eyeballed:

  • each **bond** (a drawn stick, OR a stick the renderer HID because it was too
    long — both are reported, so a stretched bond you cannot see on screen is still
    queryable), and
  • each **atom** (a drawn sphere): clashes, NaN/stranded positions.

Read-only — builds the display model from a relaxed frame and measures geometry; it
NEVER mutates topology (Three-Layer Law: physical/display layer only).

The bonds + serial ordering come from ``build_atomistic_model`` exactly as the
renderer's rep-enable build does, so the audited bonds ARE the rendered bonds: a
bond flagged here is the bond drawn (or hidden) on screen for the same serial pair.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Optional

import numpy as np

# ── Reference thresholds (nm) ─────────────────────────────────────────────────
# Heavy-atom covalent bonds in DNA are ~0.13–0.16 nm.  These defaults are
# documented + overridable; the skill / route surface them so a DNA-origami user
# can recalibrate without code changes.
INTRA_RIGID_TOL_NM: float = (
    5e-3  # a PURE-rigid intra bond must equal the design template (stamp invariant)
)
COVALENT_MAX_NM: float = (
    0.20  # any covalent bond longer than this is over-stretched (real ones ≤ ~0.16)
)
BACKBONE_STRETCH_NM: float = (
    0.30  # an inter-residue O3'→P stick longer than this is over-stretched
)
RENDER_HIDE_NM: float = (
    1.0  # mirrors atomistic_renderer._MAX_BOND_NM — renderer HIDES longer bonds
)
CLASH_NM: float = 0.08  # two non-bonded heavy atoms closer than this clash
WC_COLLAPSE_NM: float = 0.70  # median WC-pair C1'-C1' below this = bases crushed onto partners (B-DNA ~1.05)

# Atoms the crossover / nick / skip / extra-base bridge MINIMISERS relocate
# (atomistic_minimisers: place O3'(src), P/O5'(dst), translate OP1/OP2 with P).  An
# intra bond touching one of these is a "linker" bond — at a junction the minimiser
# (not the rigid stamp) sets it, so deviation-from-template there is EXPECTED; it is
# judged by absolute length only.  An intra bond touching NONE of these is
# "rigid" — frame-invariant, so any deviation from the template is a STAMP BUG.
_MINIMISER_ATOMS = frozenset({"O3'", "P", "O5'", "OP1", "OP2"})


def _bond_class(a, b) -> str:
    """Classify a bond by what governs its geometry — the same partition the user
    sees on screen:
      ``rigid``    — intra-residue, no minimiser atom: locked to the template stamp.
      ``linker``   — intra-residue, touches a phosphate atom the bridge minimiser
                     may relocate (the C3'–O3' / P–O5' / O5'–C5' sticks at junctions).
      ``backbone`` — inter-residue O3'→P between consecutive nucleotides on a strand.
      ``bridge``   — inter-residue O3'→P that reaches across helices (crossover/nick).
    """
    if a.strand_id == b.strand_id and a.seq_num == b.seq_num:
        return (
            "linker"
            if (a.name in _MINIMISER_ATOMS or b.name in _MINIMISER_ATOMS)
            else "rigid"
        )
    if (
        a.helix_id == b.helix_id
        and a.direction == b.direction
        and abs(a.bp_index - b.bp_index) == 1
    ):
        return "backbone"
    return "bridge"


def _stats(vals: list[float]) -> dict:
    if not vals:
        return {"count": 0, "min": None, "max": None, "mean": None}
    arr = np.asarray(vals, float)
    return {
        "count": len(vals),
        "min": float(arr.min()),
        "max": float(arr.max()),
        "mean": float(arr.mean()),
    }


def audit_bonds(
    design,
    frame: Optional[dict] = None,
    *,
    intra_tol_nm: float = INTRA_RIGID_TOL_NM,
    covalent_max_nm: float = COVALENT_MAX_NM,
    backbone_stretch_nm: float = BACKBONE_STRETCH_NM,
    render_hide_nm: float = RENDER_HIDE_NM,
    clash_nm: float = CLASH_NM,
    wc_collapse_nm: float = WC_COLLAPSE_NM,
    max_report: int = 200,
) -> dict:
    """Measure every bond + atom of the atomistic model at ``frame`` (a relaxed
    oxDNA frame ``{key:{backbone_position(CM), a1, a3}}``; ``None`` audits the
    design's own ideal build).

    Returns a structured report:
      ``ok``                   — no stamp violations, no over-stretched/non-finite
                                 bonds, no clashes, no NaN/stranded atoms
      ``n_atoms`` / ``n_bonds``
      ``by_class``             — {rigid,linker,backbone,bridge}: length stats
      ``rigid_stamp_max_dev_nm`` — max |relaxed − design| over RIGID bonds (frame-
                                 invariant): ≈0 proves the rigid-frame stamp; any
                                 value > ``intra_tol_nm`` is a true RECONSTRUCTION
                                 BUG (NOT relaxation, NOT a junction)
      ``n_rigid_stamp_violations``
      ``invalid_bonds``        — flagged bonds (serials, names, sites, class,
                                 length_nm, reason): a rigid-stamp break, any
                                 covalent bond over ``covalent_max_nm`` /
                                 inter-residue bond over ``backbone_stretch_nm``
                                 (the over-stretched sticks the screenshot shows),
                                 or a non-finite position
      ``hidden_by_renderer``   — bonds longer than ``render_hide_nm`` (drawn as
                                 NOTHING on screen, but they exist — queryable here)
      ``clashes``              — non-bonded atom pairs closer than ``clash_nm``
      ``bad_atoms``            — atoms with a non-finite (NaN/inf) position.  (A
                                 nucleotide that got no frame is NOT "stranded" at
                                 the atom level — its intra bonds keep it internally
                                 whole; that failure shows up instead as
                                 over-stretched / hidden inter-residue bonds.)
    """
    from backend.core.atomistic import build_atomistic_model
    from backend.core.oxdna_health import build_display_model

    # Build EXACTLY what the display draws (build_display_model = the shared sink the
    # atomistic/surface routes use), so the audit measures the rendered geometry.
    model = (
        build_display_model(design, frame) if frame else build_atomistic_model(design)
    )
    # Design build = the template-integrity reference: identical serial/bond ordering,
    # so a per-index length comparison is exact (overrides change only positions).
    ref = build_atomistic_model(design)

    pos = np.array([[a.x, a.y, a.z] for a in model.atoms], float)
    n_atoms = len(model.atoms)
    finite = np.isfinite(pos).all(axis=1)

    ref_pos = np.array([[a.x, a.y, a.z] for a in ref.atoms], float)

    def _len(p, i, j):
        return float(np.linalg.norm(p[i] - p[j]))

    by_class: dict[str, list[float]] = {
        "rigid": [],
        "linker": [],
        "backbone": [],
        "bridge": [],
    }
    invalid: list[dict] = []
    hidden: list[dict] = []
    rigid_dev_max = 0.0
    n_stamp_viol = 0

    atoms = model.atoms
    for i, j in model.bonds:
        a, b = atoms[i], atoms[j]
        cls = _bond_class(a, b)
        if not (finite[i] and finite[j]):
            invalid.append(_bond_row(a, b, cls, float("nan"), "non-finite position"))
            continue
        L = _len(pos, i, j)
        by_class[cls].append(L)
        if cls == "rigid":
            dev = abs(L - _len(ref_pos, i, j))
            rigid_dev_max = max(rigid_dev_max, dev)
            if dev > intra_tol_nm:
                n_stamp_viol += 1
                invalid.append(
                    _bond_row(
                        a,
                        b,
                        cls,
                        L,
                        f"RIGID-STAMP VIOLATION (Δ={dev * 10:.3f} Å vs template — placer bug)",
                    )
                )
                continue
        is_inter = cls in ("backbone", "bridge")
        limit = backbone_stretch_nm if is_inter else covalent_max_nm
        if L > limit:
            invalid.append(
                _bond_row(
                    a,
                    b,
                    cls,
                    L,
                    f"{cls} bond over-stretched ({L * 10:.2f} Å > {limit * 10:.1f} Å)",
                )
            )
        if L > render_hide_nm:
            hidden.append(_bond_row(a, b, cls, L, "hidden by renderer (> cutoff)"))

    clashes = _find_clashes(pos, finite, model.bonds, clash_nm, max_report)
    bad_atoms = _find_bad_atoms(model, finite, max_report)
    hel_dir = {h.id: h.direction.value for h in design.helices}
    base_geom = _base_geometry(model, wc_collapse_nm=wc_collapse_nm, helix_dir=hel_dir)

    ok = (
        not invalid
        and not clashes
        and not bad_atoms
        and not base_geom["wc_collapsed"]
        and not base_geom["wc_helix_imbalanced"]
    )

    return {
        "ok": ok,
        "n_atoms": n_atoms,
        "n_bonds": len(model.bonds),
        "by_class": {k: _stats(v) for k, v in by_class.items()},
        "rigid_stamp_max_dev_nm": rigid_dev_max,
        "n_rigid_stamp_violations": n_stamp_viol,
        "invalid_bonds": invalid[:max_report],
        "n_invalid_bonds": len(invalid),
        "hidden_by_renderer": hidden[:max_report],
        "n_hidden_by_renderer": len(hidden),
        "clashes": clashes,
        "bad_atoms": bad_atoms,
        "base_geometry": base_geom,
        "thresholds": {
            "intra_rigid_tol_nm": intra_tol_nm,
            "covalent_max_nm": covalent_max_nm,
            "backbone_stretch_nm": backbone_stretch_nm,
            "render_hide_nm": render_hide_nm,
            "clash_nm": clash_nm,
            "wc_collapse_nm": wc_collapse_nm,
        },
    }


def _base_geometry(
    model,
    *,
    wc_collapse_nm: float,
    helix_dir: dict | None = None,
    imbalance_nm: float = 0.12,
) -> dict:
    """INTER-nucleotide geometry — whether bases are correctly POSITIONED relative to
    each other (a nucleotide can be internally rigid + backbone-connected yet
    mis-placed; bond-length checks alone are blind to it).  Measures, on the C1'
    atoms: WC-pair C1'-C1' (designed (h,bp) with both strands → B-DNA ~1.05 nm) and
    consecutive-base stacking C1'-C1' along a strand (~0.5-0.7 nm).  ``wc_collapsed``
    fires when the median WC C1'-C1' falls below ``wc_collapse_nm`` — bases crushed
    onto their partners.  ``wc_helix_imbalanced`` fires when the WC median differs by
    > ``imbalance_nm`` between FORWARD-lattice and REVERSE-lattice helices — the
    forward/reverse phase-mapping bug (oxDNA relaxes both helix types identically, so
    a per-lattice-direction split means the reconstruction mis-phased half of them)."""
    c1 = {
        (a.helix_id, a.bp_index, a.direction): np.array([a.x, a.y, a.z])
        for a in model.atoms
        if a.name == "C1'"
    }
    hd = helix_dir or {}
    wc, wc_fwd, wc_rev = [], [], []
    for h, bp, d in c1:
        if d == "FORWARD" and (h, bp, "REVERSE") in c1:
            v = float(np.linalg.norm(c1[(h, bp, "FORWARD")] - c1[(h, bp, "REVERSE")]))
            wc.append(v)
            (wc_fwd if hd.get(h) == "FORWARD" else wc_rev).append(v)
    stack = []
    for h, bp, d in c1:
        nxt = (h, bp + 1, d) if d == "FORWARD" else (h, bp - 1, d)
        if nxt in c1:
            stack.append(float(np.linalg.norm(c1[(h, bp, d)] - c1[nxt])))
    wc_med = float(np.median(wc)) if wc else None
    fwd_med = float(np.median(wc_fwd)) if wc_fwd else None
    rev_med = float(np.median(wc_rev)) if wc_rev else None
    imbalanced = bool(
        fwd_med is not None
        and rev_med is not None
        and abs(fwd_med - rev_med) > imbalance_nm
    )
    return {
        "wc_c1c1": _stats(wc) | {"median": wc_med},
        "wc_c1c1_forward_helix_median": fwd_med,
        "wc_c1c1_reverse_helix_median": rev_med,
        "stacking_c1c1": _stats(stack)
        | {"median": float(np.median(stack)) if stack else None},
        "wc_collapsed": bool(wc_med is not None and wc_med < wc_collapse_nm),
        "wc_helix_imbalanced": imbalanced,
    }


def _bond_row(a, b, cls, length_nm, reason) -> dict:
    return {
        "serials": [a.serial, b.serial],
        "atoms": [a.name, b.name],
        "residues": [a.residue, b.residue],
        "sites": [
            [a.helix_id, a.bp_index, a.direction],
            [b.helix_id, b.bp_index, b.direction],
        ],
        "strands": [a.strand_id, b.strand_id],
        "class": cls,
        "length_nm": None
        if (isinstance(length_nm, float) and math.isnan(length_nm))
        else round(length_nm, 4),
        "reason": reason,
    }


def _find_clashes(pos, finite, bonds, clash_nm, max_report) -> list[dict]:
    """Non-bonded heavy-atom pairs closer than ``clash_nm`` — overlapping spheres.
    Uniform spatial-hash so it scales to large structures."""
    bonded = set()
    for i, j in bonds:
        bonded.add((i, j) if i < j else (j, i))
    cell = clash_nm
    grid: dict[tuple, list[int]] = {}
    idx = np.where(finite)[0]
    for k in idx:
        c = tuple((pos[k] // cell).astype(int))
        grid.setdefault(c, []).append(int(k))
    out: list[dict] = []
    seen = set()
    for c, members in grid.items():
        neigh: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    neigh.extend(grid.get((c[0] + dx, c[1] + dy, c[2] + dz), ()))
        for a in members:
            for b in neigh:
                if b <= a:
                    continue
                key = (a, b)
                if key in seen or key in bonded:
                    continue
                seen.add(key)
                d = float(np.linalg.norm(pos[a] - pos[b]))
                if d < clash_nm:
                    out.append({"serials": [a, b], "distance_nm": round(d, 4)})
                    if len(out) >= max_report:
                        return out
    return out


def _find_bad_atoms(model, finite, max_report) -> list[dict]:
    """Atoms with a non-finite (NaN/inf) position — a degenerate frame (e.g. a1∥a3,
    or a non-finite CM) that would render as a missing / wild sphere."""
    out: list[dict] = []
    for k, a in enumerate(model.atoms):
        if not finite[k]:
            out.append(
                {
                    "serial": a.serial,
                    "name": a.name,
                    "site": [a.helix_id, a.bp_index, a.direction],
                    "reason": "non-finite position",
                }
            )
            if len(out) >= max_report:
                break
    return out


# ── Headless entry point: latest oxDNA job for a design ───────────────────────


def latest_job_for_design(design_source: str, workspace: Path) -> Optional[str]:
    """Return the job_id of the most recently-created oxDNA job whose
    ``design_source_path`` matches ``design_source`` (by file stem) AND that has at
    least one stage ``last_conf.dat`` to read.  ``None`` if there is no relaxed job."""
    from backend.core.oxdna_job import OxdnaJob

    stem = Path(design_source).stem
    best: tuple[float, str] | None = None
    # list_jobs is archive-aware, so a relaxed job seeded from this design is still
    # discoverable (and chainable) after its folder has been archived off-workspace.
    for job in OxdnaJob.list_jobs(workspace):
        if not job.design_source_path or Path(job.design_source_path).stem != stem:
            continue
        if not any(
            (job.stage_dir(workspace, st.name) / "last_conf.dat").exists()
            for st in job.stages
        ):
            continue
        if best is None or job.created_at > best[0]:
            best = (job.created_at, job.job_id)
    return best[1] if best else None


def relaxed_frame_for_job(
    design, job, workspace: Path, *, align: bool = True, copies: bool = True
) -> tuple[Optional[dict], Optional[str]]:
    """Load the latest relaxed frame of ``job`` as the per-nucleotide oxDNA frame
    dict the placer consumes (copy-aware), PBC-unwrapped + aligned to the design
    pose exactly like the display route.  Returns (frame, stage_name) or (None,None)
    when no stage has a ``last_conf.dat`` yet."""
    from backend.physics.oxdna_interface import (
        read_configuration_unwrapped,
        write_configuration,
    )

    conf_path = None
    stage_name = None
    for st in reversed(job.stages):
        cand = job.stage_dir(workspace, st.name) / "last_conf.dat"
        if cand.exists():
            conf_path, stage_name = cand, st.name
            break
    if conf_path is None:
        return (None, None)
    jd = job.job_dir(workspace)
    ref = jd / "design_ref.dat"
    if not ref.exists():
        from backend.api.crud import _geometry_for_design

        write_configuration(
            design, _geometry_for_design(design, compact_skips=True), ref
        )
    frame = read_configuration_unwrapped(
        conf_path, design, ref, align=align, copies=copies
    )
    return (frame, stage_name)


def audit_oxdna_job(design, job, workspace: Path, *, align: bool = True, **kw) -> dict:
    """Top-level oracle: audit the atomistic display of ``job``'s latest relaxed
    frame.  Adds ``ready``/``stage_name``/``job_id`` to the :func:`audit_bonds`
    report.  This is what the ``validate-atomistic`` skill runs against a design's
    latest oxDNA job."""
    frame, stage_name = relaxed_frame_for_job(design, job, workspace, align=align)
    if frame is None:
        return {
            "ready": False,
            "job_id": job.job_id,
            "reason": "no stage has a last_conf.dat",
        }
    report = audit_bonds(design, frame, **kw)
    report.update({"ready": True, "job_id": job.job_id, "stage_name": stage_name})
    return report


# ── Per-frame trajectory audit ────────────────────────────────────────────────
# The View-trajectory scrubber shows EVERY composite-trajectory frame through the
# same display reconstruction (build_display_model via _aligned_downsampled_frames),
# so the forward/reverse-phase + backbone-closure + identity invariants the single
# relaxed-display audit pins must hold on every frame — not just frame 0.  This
# audits a sampling of those frames programmatically so a per-frame regression is
# queryable, not eyeball-only.


def _sample_frame_indices(n: int, k: int) -> list[int]:
    """Evenly-spaced frame indices over [0, n-1] (always including the endpoints),
    deduped.  ``k>=n`` audits every frame; ``k<=1`` audits only frame 0."""
    if n <= 0:
        return []
    if k >= n:
        return list(range(n))
    if k <= 1:
        return [0]
    return sorted({round(i * (n - 1) / (k - 1)) for i in range(k)})


# A trajectory frame is INVARIANT-sound when the RECONSTRUCTION-CORRECTNESS signals
# hold — exactly the settled fixes that must survive on every scrubbed frame:
#   • the rigid stamp is exact (placer correct),
#   • the bases are not crushed onto their partners (wc_collapsed False),
#   • the forward/reverse phase is balanced (wc_helix_imbalanced False),
#   • the atom/bond identity matches the design build, and
#   • no atom is non-finite (a degenerate frame).
# Over-stretched bonds + clashes are deliberately NOT a gate: a raw (un-minimised) CG
# trajectory frame inherently carries 100s of mild 0.3–1.0 nm backbone over-stretches
# (the renderer hides the >1 nm ones; the single-frame relaxed audit shows the same)
# and a folded structure has sub-Å junction contacts.  These are surfaced as
# per-frame COUNTS (quality metrics) so an explosion is visible, but a frame is not
# failed for the inherent raw-CG roughness the user already validated visually.
def _frame_invariants_ok(rep: dict, ref_atoms: int, ref_bonds: int) -> bool:
    bg = rep["base_geometry"]
    return bool(
        rep["n_rigid_stamp_violations"] == 0
        and not rep["bad_atoms"]
        and not bg["wc_collapsed"]
        and not bg["wc_helix_imbalanced"]
        and rep["n_atoms"] == ref_atoms
        and rep["n_bonds"] == ref_bonds
    )


def _slim_frame_report(idx: int, rep: dict, ref_atoms: int, ref_bonds: int) -> dict:
    """Compact one full :func:`audit_bonds` report to the per-frame fields the
    trajectory audit asserts on (drop the bulky bond lists, keep a few examples)."""
    bg = rep["base_geometry"]
    return {
        "frame": idx,
        "invariants_ok": _frame_invariants_ok(rep, ref_atoms, ref_bonds),
        "ok": rep["ok"],
        "identity_ok": rep["n_atoms"] == ref_atoms and rep["n_bonds"] == ref_bonds,
        "n_atoms": rep["n_atoms"],
        "n_bonds": rep["n_bonds"],
        "n_rigid_stamp_violations": rep["n_rigid_stamp_violations"],
        "rigid_stamp_max_dev_nm": rep["rigid_stamp_max_dev_nm"],
        "wc_c1c1_median": bg["wc_c1c1"]["median"],
        "wc_c1c1_forward_helix_median": bg["wc_c1c1_forward_helix_median"],
        "wc_c1c1_reverse_helix_median": bg["wc_c1c1_reverse_helix_median"],
        "stacking_c1c1_median": bg["stacking_c1c1"]["median"],
        "wc_collapsed": bg["wc_collapsed"],
        "wc_helix_imbalanced": bg["wc_helix_imbalanced"],
        "n_invalid_bonds": rep["n_invalid_bonds"],
        "n_hidden_by_renderer": rep["n_hidden_by_renderer"],
        "n_clashes": len(rep["clashes"]),
        "n_bad_atoms": len(rep["bad_atoms"]),
        "invalid_bonds": rep["invalid_bonds"][:5],
    }


def _summarize_frames(frames: list[dict]) -> dict:
    wc = [f["wc_c1c1_median"] for f in frames if f["wc_c1c1_median"] is not None]
    return {
        "n_audited": len(frames),
        "all_invariants_ok": all(f["invariants_ok"] for f in frames),
        "identity_preserved": all(f["identity_ok"] for f in frames),
        "max_rigid_stamp_violations": max(
            (f["n_rigid_stamp_violations"] for f in frames), default=0
        ),
        "any_wc_collapsed": any(f["wc_collapsed"] for f in frames),
        "any_wc_helix_imbalanced": any(f["wc_helix_imbalanced"] for f in frames),
        "any_over_stretched": any(f["n_invalid_bonds"] > 0 for f in frames),
        "wc_c1c1_median_range": [min(wc), max(wc)] if wc else [None, None],
        "max_clashes": max((f["n_clashes"] for f in frames), default=0),
        "failed_frames": [f["frame"] for f in frames if not f["invariants_ok"]],
    }


def audit_trajectory_frames(
    design,
    stages,
    reference_conf_path,
    frame_indices: Optional[list[int]] = None,
    *,
    max_audit: int = 8,
    max_frames: int = 200,
    **kw,
) -> dict:
    """Audit a SAMPLING of composite-trajectory frames — the per-frame counterpart of
    :func:`audit_bonds`.  Reconstructs each requested frame through the SAME shared
    sink the View-trajectory scrubber uses (``_aligned_downsampled_frames`` →
    ``build_display_model``) and reports, per frame: rigid-stamp integrity, WC/stacking
    C1'-C1' geometry, forward/reverse phase balance, over-stretched/hidden bonds,
    clashes, and atom/bond identity vs the design build.

    ``stages`` is the same ``[(name, kind, traj_path[, marker])]`` list the trajectory
    routes assemble (whole lineage).  ``frame_indices=None`` evenly samples
    ``max_audit`` frames across the whole composite (endpoints included); an explicit
    list audits exactly those composite-frame indices (clamped to range).

    Returns ``{ready, n_frames, audited_frames, frames:[…per-frame…], summary}``.
    ``summary.all_invariants_ok`` is the assertable pass criterion: every audited
    frame has 0 stamp violations, balanced forward/reverse phase, un-collapsed bases,
    no non-finite atom, and preserved identity — proving the settled fixes hold on
    EVERY frame, not only the relaxed display frame.  (Over-stretch + clash counts are
    reported per frame as quality metrics, not a gate — see ``_frame_invariants_ok``.)"""
    from backend.core.atomistic import build_atomistic_model
    from backend.core.oxdna_health import _aligned_downsampled_frames

    _, ordered, _, _ = _aligned_downsampled_frames(
        design, stages, reference_conf_path, max_frames, copies=True
    )
    n = len(ordered)
    if n == 0:
        return {"ready": False, "reason": "no trajectory frames", "n_frames": 0}

    ref = build_atomistic_model(design)
    ref_atoms, ref_bonds = len(ref.atoms), len(ref.bonds)

    if frame_indices is None:
        idxs = _sample_frame_indices(n, max_audit)
    else:
        idxs = sorted({i for i in (int(x) for x in frame_indices) if 0 <= i < n})

    frames = [
        _slim_frame_report(
            idx, audit_bonds(design, ordered[idx], **kw), ref_atoms, ref_bonds
        )
        for idx in idxs
    ]
    summary = _summarize_frames(frames)
    return {
        "ready": True,
        "n_frames": n,
        "audited_frames": idxs,
        "frames": frames,
        "summary": summary,
        "ok": summary["all_invariants_ok"],
    }
