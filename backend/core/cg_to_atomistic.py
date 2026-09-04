"""
CG-to-atomistic bridge: read a relaxed oxDNA configuration and produce
an AtomisticModel whose backbone positions are informed by the CG trajectory.

Two approaches are implemented:

Phase 3a — per-helix PCA axis refitting (build_atomistic_model_from_cg)
------------------------------------------------------------------------
Fits a PCA line through all CG backbone positions per helix and rebuilds
ideal B-DNA along those axes.  VALIDATED AS INSUFFICIENT: 9,656 EM steps
(CG path) vs 9,787 steps (ideal) — 1.3% difference, within run noise.
Root cause: PCA averages 420+ bp, diluting crossover signal; 0.05-0.10 nm
axis shifts don't change relative helix spacing at crossovers.  Kept for
reference; do NOT use for EM acceleration.

Phase 3b — per-domain Gaussian-smoothed position override (build_atomistic_model_from_cg_spline)
-------------------------------------------------------------------------------------------------
Uses CG backbone positions directly as per-nucleotide position overrides
(MrDNA methodology).  Gaussian smoothing (sigma=2 nt) removes MC positional
noise (~0.3-0.5 nm/nt) within each helix domain without crossing crossover
boundaries.  At crossover junctions, the CG equilibrium positions are used
directly — these are ~0.6-1.4 nm apart vs ~0.05 nm in ideal B-DNA,
eliminating the 10^13 kJ/mol LJ spike.

Phase 3c — paired-frame target + topology-safe projection (production NAMD seed)
--------------------------------------------------------------------------------
Maps intact Watson--Crick pairs with proper rigid transforms derived from oxDNA2
backbone/a1/a3 frames, rejects melted-pair frames, and projects the result toward a
known-valid atomistic structure until ring topology and bounded-bond gates pass.  The
subsequent NAMD handoff always uses the 1 fs no-RATTLE declash/minimisation ladder.

Pipeline
--------
1. Export oxDNA package from the current design.
2. Run oxDNA relaxation (``oxDNA input.txt`` → ``last_conf.dat``).
3. Call ``build_atomistic_model_from_cg_spline(design, last_conf.dat)`` which:
   a. Reads relaxed backbone positions from the .dat file.
   b. Groups nucleotides by strand domain (helix segment).
   c. Applies Gaussian smoothing within each domain (not across crossovers).
   d. Passes smoothed positions as nuc_pos_override to build_atomistic_model.
4. Pass the returned AtomisticModel to ``build_gromacs_package``.
"""

from __future__ import annotations

from pathlib import Path
from dataclasses import dataclass

import numpy as np
from scipy.ndimage import gaussian_filter1d

from backend.core.models import Design, Helix, Vec3
from backend.core.atomistic import AtomisticModel, build_atomistic_model
from backend.physics.oxdna_interface import (
    read_configuration,
    read_configuration_full_unwrapped,
    oxdna_backbone_site,
)
from backend.core.sequences import domain_bp_range


@dataclass(frozen=True)
class SeedProjectionReport:
    """Audit trail for the topology-safe projection of an oxDNA target."""

    iterations: int
    fully_mapped_units: int
    backed_off_units: int
    mean_target_fraction: float
    min_bond_ratio: float
    max_bond_ratio: float
    min_bond_nm: float
    max_bond_nm: float
    ring_piercings: int
    steric_clashes: int
    steric_cutoff_nm: float
    target_rmsd_nm: float
    target_p95_nm: float


# ── Phase 3b: per-domain smoothed position override ──────────────────────────


def _smooth_cg_positions_per_domain(
    design: Design,
    cg_positions: dict[tuple[str, int, str], np.ndarray],
    sigma: float = 2.0,
) -> dict[tuple[str, int, str], np.ndarray]:
    """
    Smooth CG backbone positions within each helix domain independently.

    Per-domain Gaussian smoothing (sigma nucleotides) removes MC positional
    noise (~0.3-0.5 nm/nt) while preserving crossover junction geometry.
    Smoothing is applied independently per domain so that positions from
    adjacent helices are never blended together at crossover boundaries.

    Parameters
    ----------
    design       : Design matching the CG configuration.
    cg_positions : Output of read_configuration — (helix_id, bp, dir) → pos nm.
    sigma        : Gaussian smoothing width in nucleotides.  2.0 is recommended:
                   smooths noise while keeping crossover positions close to CG.

    Returns
    -------
    dict mapping (helix_id, bp_index, direction_str) → smoothed position (nm),
    suitable for use as nuc_pos_override in build_atomistic_model.
    """
    smoothed: dict[tuple[str, int, str], np.ndarray] = {}

    for strand in design.strands:
        for domain in strand.domains:
            h_id = domain.helix_id
            dir_str = domain.direction.value  # "FORWARD" or "REVERSE"

            # Collect bp indices in 5'→3' order for this domain.
            bps = list(domain_bp_range(domain))
            keys = [(h_id, bp, dir_str) for bp in bps]

            # Gather the CG positions that exist for this domain.
            raw_pos: list[np.ndarray] = []
            valid_keys: list[tuple[str, int, str]] = []
            for key in keys:
                pos = cg_positions.get(key)
                if pos is not None:
                    raw_pos.append(pos)
                    valid_keys.append(key)

            if not valid_keys:
                continue

            if len(valid_keys) < 3 or sigma <= 0.0:
                # Too short to smooth meaningfully; use raw CG positions.
                for key, pos in zip(valid_keys, raw_pos):
                    smoothed[key] = pos.copy()
                continue

            pts = np.array(raw_pos)  # shape (N, 3)

            # Gaussian smooth each coordinate axis independently.
            # mode='nearest' avoids edge ringing by clamping boundary values.
            smoothed_pts = gaussian_filter1d(pts, sigma=sigma, axis=0, mode="nearest")

            for key, pos in zip(valid_keys, smoothed_pts):
                smoothed[key] = pos

    return smoothed


def deformed_helix_axes(
    design: Design,
    full_map: dict[tuple[str, int, str], dict],
    sigma: float = 2.0,
    base_orient: str = "design_axis",
) -> dict[tuple[str, int], tuple[np.ndarray, np.ndarray]]:
    """Per-(helix, bp) deformed centerline point + local tangent from a relaxed CG map.

    The atomistic placer derives each nucleotide's radial direction (hence its
    helical phase) from ``backbone - axis_point``, and uses the returned tangent as
    the base slab-face normal (``e_z``).  By default ``axis_point`` is the
    helix's IDEAL straight axis; once a helix has bent/shifted in the relaxed CG
    structure, that straight reference makes the global displacement swamp the true
    radial — the twist collapses and adjacent nucleotides pile up (the seed-clash
    bug).  This returns the BENT centerline so the radial is measured correctly.

    Centerline per bp = midpoint of the two paired strands' centres of mass (which
    straddle the helix axis); built only from base-paired bps (a single strand's CM
    sits off-axis), then linearly filled across the helix's bp span, Gaussian
    smoothed, and differentiated for the local tangent.  The tangent is sign-aligned
    to the helix's original axis direction so FORWARD/REVERSE polarity is preserved.
    Helices with fewer than two paired bps are omitted (fall back to the straight
    axis).  Physical-layer only — never written back into topology.

    ``base_orient`` selects the source of the returned TANGENT (the base stacking
    axis, ``e_z``); the centerline POINT is unchanged either way:
      - ``"design_axis"`` (default): tangent = d(centerline)/dbp.  The centerline is
        the midpoint of two backbone sites that spiral slightly off-axis (strands are
        ~208° apart, not 180°), so this tangent sits ~12° off the true helix axis even
        for a perfectly straight, unrelaxed duplex — a construction artifact that tilts
        every base ~5–6° past the correct B-form baseline (measured: 15.7° vs the
        validated ideal build's 10.0°) AND rotates WC pairs OPEN (primary H-bond 4.12 Å
        vs 2.89 Å).  The legacy default; no live caller uses it — both the display and
        the NAMD seed pass ``"oxdna_a3"``.
      - ``"oxdna_a3"``: tangent = the SHARED stacking axis of each WC pair,
        ``normalize(a3_fwd − a3_rev)`` (oxDNA's own base normals; on a straight ideal
        duplex a3 is exactly on-axis).  Restores the display base orientation to the
        ideal-build value while preserving WC pairing — a per-base a3 rigid stamp would
        instead collapse pairs (FWD/REV a3 are only ~157° apart, real propeller), so the
        SHARED axis is used, not each base's own.  Falls back to ``design_axis`` per
        helix when a3 is missing.
    """
    axis_dir = {}
    for h in design.helices:
        d = np.array(
            [
                h.axis_end.x - h.axis_start.x,
                h.axis_end.y - h.axis_start.y,
                h.axis_end.z - h.axis_start.z,
            ],
            dtype=float,
        )
        n = np.linalg.norm(d)
        axis_dir[h.id] = d / n if n > 1e-9 else np.array([0.0, 0.0, 1.0])

    by_helix: dict[str, dict[int, dict[str, dict]]] = {}
    for (h_id, bp, dr), rec in full_map.items():
        a3 = rec.get("a3")
        by_helix.setdefault(h_id, {}).setdefault(bp, {})[dr] = {
            "pt": np.asarray(rec["backbone_position"], dtype=float),
            "a3": None if a3 is None else np.asarray(a3, dtype=float),
        }

    out: dict[tuple[str, int], tuple[np.ndarray, np.ndarray]] = {}
    for h_id, bpmap in by_helix.items():
        adir = axis_dir.get(h_id)
        paired_bp: list[int] = []
        paired_pt: list[np.ndarray] = []
        paired_s: list[np.ndarray | None] = []  # per-pair shared a3 stacking axis
        for bp in sorted(bpmap):
            dd = bpmap[bp]
            if "FORWARD" in dd and "REVERSE" in dd:
                paired_bp.append(bp)
                paired_pt.append(0.5 * (dd["FORWARD"]["pt"] + dd["REVERSE"]["pt"]))
                a3f, a3r = dd["FORWARD"]["a3"], dd["REVERSE"]["a3"]
                if a3f is None or a3r is None:
                    paired_s.append(None)
                else:
                    # Shared stacking axis of the WC pair: FWD/REV a3 point ~antiparallel,
                    # so a3f − a3r is their common normal.  Sign-align to the helix axis up
                    # front (so opposite-signed rows never cancel when interpolated/smoothed).
                    s = a3f - a3r
                    n = float(np.linalg.norm(s))
                    s = (
                        s / n
                        if n > 1e-9
                        else (adir if adir is not None else np.array([0.0, 0.0, 1.0]))
                    )
                    if adir is not None and float(np.dot(s, adir)) < 0:
                        s = -s
                    paired_s.append(s)
        if len(paired_bp) < 2:
            continue
        kb = np.array(paired_bp)
        kp = np.array(paired_pt)
        core_bps = np.arange(paired_bp[0], paired_bp[-1] + 1)
        axis = np.stack([np.interp(core_bps, kb, kp[:, c]) for c in range(3)], axis=1)
        if sigma > 0 and len(core_bps) >= 3:
            axis = gaussian_filter1d(axis, sigma=sigma, axis=0, mode="nearest")

        use_a3 = base_orient == "oxdna_a3" and all(s is not None for s in paired_s)
        if use_a3:
            # Tangent (base stacking axis, e_z) from oxDNA's own a3 — interpolated +
            # smoothed across the bp span exactly like the centerline point, then
            # renormalised.  a3 is on-axis on an ideal duplex, so this removes the
            # ~12° off-axis tilt the d(centerline)/dbp tangent carries.
            ks = np.array(paired_s)
            s_axis = np.stack(
                [np.interp(core_bps, kb, ks[:, c]) for c in range(3)], axis=1
            )
            if sigma > 0 and len(core_bps) >= 3:
                s_axis = gaussian_filter1d(s_axis, sigma=sigma, axis=0, mode="nearest")
            sn = np.linalg.norm(s_axis, axis=1, keepdims=True)
            tang = s_axis / np.where(sn < 1e-9, 1.0, sn)
        else:
            tang = np.gradient(axis, axis=0)
            tn = np.linalg.norm(tang, axis=1, keepdims=True)
            tang = tang / np.where(tn < 1e-9, 1.0, tn)
        # Sign-align to the helix's original axis direction (no FWD/REV flip).
        if adir is not None and float(np.dot(tang.mean(axis=0), adir)) < 0:
            tang = -tang

        # Cover EVERY bp present on the helix — single-stranded overhang ends sit
        # OUTSIDE the paired range, and without an axis there they fall back to the
        # straight ideal axis and re-clash.  Extrapolate the smoothed centerline
        # straight along its end tangent (an overhang continues the helix), one
        # centerline-rise step per bp.
        step0 = axis[1] - axis[0]
        stepN = axis[-1] - axis[-2]
        lo = min(bpmap)
        hi = max(bpmap)
        for bp in range(lo, hi + 1):
            if bp < paired_bp[0]:
                pt, tg = axis[0] + (bp - paired_bp[0]) * step0, tang[0]
            elif bp > paired_bp[-1]:
                pt, tg = axis[-1] + (bp - paired_bp[-1]) * stepN, tang[-1]
            else:
                idx = bp - paired_bp[0]
                pt, tg = axis[idx], tang[idx]
            out[(h_id, int(bp))] = (pt, tg)
    return out


def build_atomistic_model_from_cg_spline(
    design: Design,
    conf_path: str | Path,
    sigma: float = 2.0,
) -> AtomisticModel:
    """
    Build an all-atom model using per-domain smoothed CG backbone positions
    as position overrides — the MrDNA-inspired Phase 3b approach.

    CG backbone positions at crossover junctions are ~0.6-1.4 nm apart
    (compared to ~0.05 nm in ideal B-DNA), eliminating the O5'/O1P LJ spike.
    Gaussian smoothing within each helix domain removes MC positional noise
    before the override so backbone bond lengths remain physically correct.

    The oxDNA ``.dat`` stores each nucleotide's CENTRE OF MASS, which sits
    ~0.34 units inward of the backbone.  Using the raw CM (as ``read_configuration``
    returns) makes the seeded atomistic duplex too THIN (paired backbones ~1.0 nm
    apart instead of ~1.6 nm) → backbone atoms of paired strands clash at NAMD
    startup — the very thing the relaxation is meant to prevent.  So we reconstruct
    the true backbone site (``oxdna_backbone_site``) from the CM + a1/a3 before
    smoothing.

    Parameters
    ----------
    design    : Design — must match the topology used to generate the conf.
    conf_path : Path to a relaxed oxDNA .dat file (e.g. ``last_conf.dat``).
    sigma     : Gaussian smoothing width in nucleotides (default 2.0).

    Returns
    -------
    AtomisticModel with CG-informed backbone positions.
    """
    # PBC make-whole: DEFENSIVE — an E-field/surface run can stream the structure
    # across a box face; a wrapped strand would make the backbone spline overshoot.
    # No-op for a structure already whole in [0,L) (the common case).
    # Keep the synthetic crossover-extra particles in the readback.  They occupy real
    # oxDNA particle rows but are not design nucleotide keys, so the default reader
    # deliberately drops them.  Dropping them here made the relaxed display follow the
    # simulated insert while the NAMD seed silently rebuilt that insert at its native
    # default pose.
    full_map = read_configuration_full_unwrapped(
        conf_path, design, include_extra_bases=True
    )
    # UNPAIRED ssDNA (overhangs / tails / unpaired scaffold loops) has no helix axis to
    # fit, so the axis-derived placement above collapses distinct ssDNA nucleotides —
    # 0.5-1.1 nm apart in the relaxed conf — onto near-coincident atoms.  NAMD then can't
    # distribute the bonded terms through those degenerate atoms and aborts at startup with
    # "Bad global angle count!" (VoltronCore: 962 ssDNA nt → 55 coincident atom pairs).
    # Stamp each unpaired nucleotide from its oxDNA a1/a3 RIGID frame instead — exactly the
    # fix the display path already uses (oxdna_health._ssdna_frame_override); the formed
    # duplex stays on the axis path (the rigid stamp collapses WC pairs, ssDNA has none).
    # Use the canonical relaxed-frame override builder shared with the display.  In
    # particular this converts each ``(__xb__, crossover_id, k)`` particle's simulated
    # CM+a1+a3 into the exact ``xb_pos_override`` contract consumed by the atomistic
    # placer.  Keeping this in one helper makes display and NAMD seed reconstruction
    # agree by construction.  The lazy import breaks the cg_to_atomistic <->
    # oxdna_health cycle (oxdna_health imports deformed_helix_axes from this module).
    from backend.core.oxdna_health import (
        _frame_atomistic_overrides,
        _ssdna_frame_override,
    )

    pos_override, axis_override, xb_pos_override, _ext_pos_override = (
        _frame_atomistic_overrides(
            design, full_map, base_orient="oxdna_a3", sigma=sigma
        )
    )
    ssdna_override = _ssdna_frame_override(design, full_map)
    # apply_design_geometry=False: the CG override already gives each nucleotide's FINAL
    # world position (deformed + cluster-transformed, then oxDNA-relaxed).  Letting
    # build_atomistic_model re-apply the design's deformations/cluster transforms on top
    # would DOUBLE them — the ~N× explosion when seeding copy-pasted, rotated clusters.
    # The seed is a pure function of the oxDNA positions; pre-oxDNA transforms don't apply.
    # relaxed_oxdna_phase=True: this is a RELAXED oxDNA structure, so a REVERSE helix has
    # no well-defined lattice direction for the REV-strand P azimuthal correction — apply
    # the FORWARD-convention (+58.2°) uniformly, matching the display reconstruction.
    # Without it, REVERSE helices keep the wrong correction and pairs stay open
    # (2.85 Å vs 3.08 Å primary H-bond on VoltronCore).
    model = build_atomistic_model(
        design,
        nuc_pos_override=pos_override,
        axis_override=axis_override,
        frame_override=ssdna_override,
        xb_pos_override=xb_pos_override,
        apply_design_geometry=False,
        relaxed_oxdna_phase=True,
    )

    # Safety net: the reconstruction must preserve the CG structure's extent.  If a
    # future seed still blows up (e.g. an unwrapped/torn conf), fail with an actionable
    # message rather than writing a corrupt PDB whose overflowing coordinates crash NAMD
    # downstream with a cryptic error.  (A correct reconstruction reconstructs at ~1×.)
    if model.atoms and full_map:
        cg = np.asarray([r["backbone_position"] for r in full_map.values()])
        at = np.asarray([[a.x, a.y, a.z] for a in model.atoms])
        cg_span = float(np.ptp(cg, axis=0).max())
        at_span = float(np.ptp(at, axis=0).max())
        if cg_span > 1.0 and at_span > 2.0 * cg_span:
            raise ValueError(
                f"oxDNA→atomistic reconstruction exploded the structure "
                f"({cg_span:.0f} nm CG → {at_span:.0f} nm all-atom, {at_span / cg_span:.1f}×). "
                f"The relaxed conf could not be reconstructed cleanly — re-run the oxDNA "
                f"relaxation, or seed from a conformation that fits within one box."
            )
    return model


def build_atomistic_model_from_cg_pair_frames(
    design: Design,
    conf_path: str | Path,
    sigma: float = 2.0,
    *,
    max_formed_pair_backbone_distance_nm: float = 2.5,
) -> AtomisticModel:
    """Topology-safe oxDNA backmap that moves each formed WC pair as a rigid unit.

    The legacy spline mapper independently places the two nucleotides of a pair from
    noisy backbone sites. On a relaxed origami this can fold neighbouring atomistic
    rings through one another. Here a chemically valid ideal atomistic model supplies
    every residue, and one proper rotation/translation maps each complete base pair
    onto the relaxed oxDNA pair frame. Thus internal sugar/base geometry, chirality and
    Watson--Crick separation cannot be damaged by the coarse-grained mapping itself.

    A designed pair is only treated as formed when its two oxDNA backbone sites remain
    within ``max_formed_pair_backbone_distance_nm``.  This distinction matters after a
    real relaxation: a frayed/melted designed pair has no meaningful duplex frame and
    must never drag an atomistic residue across the structure.  Unformed, unpaired and
    synthetic-insert residues deliberately remain in the valid ideal seed for now.
    """
    from backend.physics.oxdna_interface import oxdna_backbone_site

    full = read_configuration_full_unwrapped(
        conf_path, design, include_extra_bases=True
    )
    # Start from the known-valid atomistic topology/geometry. This is intentionally not
    # the old calibrated oxDNA rigid stamp.
    model = build_atomistic_model(design, apply_design_geometry=False)
    axes = deformed_helix_axes(design, full, sigma=sigma, base_orient="oxdna_a3")
    helix_z = {}
    for h in design.helices:
        z = np.asarray([h.axis_end.x-h.axis_start.x, h.axis_end.y-h.axis_start.y,
                        h.axis_end.z-h.axis_start.z], float)
        helix_z[h.id] = z / (np.linalg.norm(z) + 1e-14)

    groups = {}
    for atom in model.atoms:
        if atom.helix_id is not None and atom.bp_index is not None:
            groups.setdefault((atom.helix_id, atom.bp_index, atom.direction), []).append(atom)

    # Put the complete chemically valid seed into the relaxed conformation's global
    # frame before applying local pair frames.  Without this fit, residues that are
    # unpaired/frayed (and therefore intentionally not locally mapped) remain near the
    # design origin while their bonded neighbours move into oxDNA's translated/rotated
    # frame, creating enormous artificial bonds at the paired/unpaired boundary.
    source_centres, target_centres = [], []
    for h, bp in {(k[0], k[1]) for k in groups}:
        gf, gr = groups.get((h, bp, "FORWARD")), groups.get((h, bp, "REVERSE"))
        rf, rr = full.get((h, bp, "FORWARD")), full.get((h, bp, "REVERSE"))
        if not gf or not gr or rf is None or rr is None:
            continue
        sf = next((a for a in gf if a.name == "C1'"), None)
        sr = next((a for a in gr if a.name == "C1'"), None)
        if sf is None or sr is None:
            continue
        bf = oxdna_backbone_site(rf["backbone_position"], rf["a1"], rf["a3"])
        br = oxdna_backbone_site(rr["backbone_position"], rr["a1"], rr["a3"])
        if np.linalg.norm(bf - br) > max_formed_pair_backbone_distance_nm:
            continue
        source_centres.append(
            0.5
            * np.asarray(
                [[sf.x, sf.y, sf.z], [sr.x, sr.y, sr.z]], dtype=float
            ).sum(axis=0)
        )
        target_centres.append(0.5 * (bf + br))
    global_R = np.eye(3)
    if len(source_centres) >= 3:
        source_arr, target_arr = np.asarray(source_centres), np.asarray(target_centres)
        source_mean, target_mean = source_arr.mean(0), target_arr.mean(0)
        u, _, vt = np.linalg.svd((source_arr - source_mean).T @ (target_arr - target_mean))
        global_R = vt.T @ u.T
        if np.linalg.det(global_R) < 0:
            vt[-1] *= -1
            global_R = vt.T @ u.T
        for atom in model.atoms:
            p = target_mean + global_R @ (
                np.asarray([atom.x, atom.y, atom.z]) - source_mean
            )
            atom.x, atom.y, atom.z = p.tolist()
        helix_z = {h: global_R @ z for h, z in helix_z.items()}

    def basis(x, z):
        z = np.asarray(z, float)
        zn = float(np.linalg.norm(z))
        if zn < 1e-8:
            raise ValueError("oxDNA pair frame has a degenerate stacking axis")
        z /= zn
        x = np.asarray(x, float)
        x -= np.dot(x, z) * z
        xn = float(np.linalg.norm(x))
        if xn < 1e-8:
            raise ValueError("oxDNA pair frame has collinear pairing/stacking axes")
        x /= xn
        return np.column_stack([x, np.cross(z, x), z])

    for h, bp in {(k[0], k[1]) for k in groups}:
        kf, kr = (h, bp, "FORWARD"), (h, bp, "REVERSE")
        gf, gr = groups.get(kf), groups.get(kr)
        rf, rr = full.get(kf), full.get(kr)
        if not gf or not gr or rf is None or rr is None or (h, bp) not in axes:
            continue
        sf = next((a for a in gf if a.name == "C1'"), None)
        sr = next((a for a in gr if a.name == "C1'"), None)
        if sf is None or sr is None:
            continue
        psf = np.asarray([sf.x, sf.y, sf.z]); psr = np.asarray([sr.x, sr.y, sr.z])
        source_c = 0.5 * (psf + psr)
        source_B = basis(psf - psr, helix_z[h])

        bf = oxdna_backbone_site(rf["backbone_position"], rf["a1"], rf["a3"])
        br = oxdna_backbone_site(rr["backbone_position"], rr["a1"], rr["a3"])
        if np.linalg.norm(bf - br) > max_formed_pair_backbone_distance_nm:
            continue
        target_c = 0.5 * (bf + br)
        target_z = axes[(h, bp)][1]
        target_B = basis(bf - br, target_z)
        R = target_B @ source_B.T
        for atom in (*gf, *gr):
            p = np.asarray([atom.x, atom.y, atom.z])
            atom.x, atom.y, atom.z = (target_c + R @ (p - source_c)).tolist()
    return model


def build_topology_safe_oxdna_seed(
    design: Design,
    conf_path: str | Path,
    *,
    sigma: float = 2.0,
    min_bond_ratio: float = 0.5,
    max_bond_ratio: float = 6.0,
    min_interunit_heavy_nm: float = 0.12,
    max_iterations: int = 64,
) -> tuple[AtomisticModel, AtomisticModel, SeedProjectionReport]:
    """Return a safe MD start, the canonical oxDNA target, and an audit report.

    The canonical pair-frame backmap is returned verbatim as a diagnostic target.  It
    is *not* assumed to be a legal covalent starting structure.  A rigidly aligned ideal
    atomistic model supplies the known-valid end of a homotopy, and paired nucleotides
    are advanced toward the target as shared repair units.  Units implicated in an
    overstretched bond or ring piercing are deterministically backed off until both
    gates pass.  This never claims that minimisation can undo a topological defect.
    """
    from backend.core.ring_piercing import model_piercings

    safe = build_atomistic_model(design, apply_design_geometry=False)
    target = build_atomistic_model_from_cg_pair_frames(design, conf_path, sigma=sigma)
    if len(safe.atoms) != len(target.atoms):
        raise ValueError("oxDNA seed target does not match the atomistic topology")

    p0 = np.asarray([[a.x, a.y, a.z] for a in safe.atoms], dtype=float)
    p1 = np.asarray([[a.x, a.y, a.z] for a in target.atoms], dtype=float)
    c0, c1 = p0.mean(0), p1.mean(0)
    u, _, vt = np.linalg.svd((p0 - c0).T @ (p1 - c1))
    rigid = vt.T @ u.T
    if np.linalg.det(rigid) < 0:
        vt[-1] *= -1
        rigid = vt.T @ u.T
    p0 = (p0 - c0) @ rigid.T + c1

    # A complete designed pair is one repair unit, ensuring collision repair cannot
    # independently squash its two bases. Other residues remain individual units.
    present = {(a.helix_id, a.bp_index, a.direction) for a in safe.atoms}
    unit_for_atom = []
    for a in safe.atoms:
        opposite = "REVERSE" if a.direction == "FORWARD" else "FORWARD"
        if (a.helix_id, a.bp_index, opposite) in present and a.extra_base_k is None:
            unit_for_atom.append(("pair", a.helix_id, a.bp_index))
        else:
            unit_for_atom.append(("residue", a.chain_id, a.seq_num))
    units = sorted(set(unit_for_atom), key=repr)
    weight = {unit: 1.0 for unit in units}
    unit_indices = {
        unit: np.asarray([i for i, value in enumerate(unit_for_atom) if value == unit])
        for unit in units
    }
    # Store one proper rigid transform per repair unit. Interpolating Cartesian atom
    # coordinates directly is invalid: halfway between two opposed rotations collapses
    # a nucleotide through its own centre. Rotation-vector interpolation keeps every
    # sugar/base (and every paired duplex rung) chemically rigid at all repair weights.
    from scipy.spatial.transform import Rotation

    unit_transforms = {}
    for unit, indices in unit_indices.items():
        source, dest = p0[indices], p1[indices]
        source_c, dest_c = source.mean(0), dest.mean(0)
        u, _, vt = np.linalg.svd((source - source_c).T @ (dest - dest_c))
        rotation = vt.T @ u.T
        if np.linalg.det(rotation) < 0:
            vt[-1] *= -1
            rotation = vt.T @ u.T
        unit_transforms[unit] = (
            indices,
            source_c,
            dest_c,
            Rotation.from_matrix(rotation).as_rotvec(),
        )
    heavy_indices = np.asarray(
        [i for i, atom in enumerate(safe.atoms) if atom.element != "H"], dtype=int
    )
    bonded = {tuple(sorted(pair)) for pair in safe.bonds}

    baseline = np.asarray(
        [max(float(np.linalg.norm(p0[i] - p0[j])), 0.05) for i, j in safe.bonds]
    )

    final_min_ratio = 0.0
    final_max_ratio = float("inf")
    hits = []
    steric_pairs: list[tuple[int, int]] = []
    for iteration in range(1, max_iterations + 1):
        coords = p0.copy()
        for unit, (indices, source_c, dest_c, rotvec) in unit_transforms.items():
            fraction = weight[unit]
            rotation = Rotation.from_rotvec(fraction * rotvec).as_matrix()
            centre = source_c + fraction * (dest_c - source_c)
            coords[indices] = (p0[indices] - source_c) @ rotation.T + centre
        for atom, xyz in zip(safe.atoms, coords, strict=True):
            atom.x, atom.y, atom.z = xyz.tolist()
        lengths = np.asarray(
            [np.linalg.norm(coords[i] - coords[j]) for i, j in safe.bonds]
        )
        ratios = lengths / baseline
        final_min_ratio = float(ratios.min(initial=1.0))
        final_max_ratio = float(ratios.max(initial=1.0))
        bad_units = set()
        for bond_index in np.flatnonzero(
            (ratios < min_bond_ratio) | (ratios > max_bond_ratio)
        ):
            i, j = safe.bonds[int(bond_index)]
            bad_units.update((unit_for_atom[i], unit_for_atom[j]))
        # Ring/steric scans dominate large-origami validation. Resolve gross covalent
        # discontinuities first; their moving segments would only create transient,
        # uninformative ring intersections.
        steric_pairs = []
        if not bad_units and len(heavy_indices):
            from scipy.spatial import cKDTree

            local_pairs = cKDTree(coords[heavy_indices]).query_pairs(
                min_interunit_heavy_nm, output_type="ndarray"
            )
            for local_i, local_j in local_pairs:
                i, j = int(heavy_indices[local_i]), int(heavy_indices[local_j])
                if unit_for_atom[i] == unit_for_atom[j] or tuple(sorted((i, j))) in bonded:
                    continue
                # The ideal origami builder has known crossover-junction contacts that
                # the established no-ENM declash minimisation resolves. This projection
                # gate prevents the oxDNA handoff from introducing *new* overlaps; it
                # does not pretend to repair baseline construction contacts here.
                if np.linalg.norm(p0[i] - p0[j]) < min_interunit_heavy_nm:
                    continue
                steric_pairs.append((i, j))
                bad_units.update((unit_for_atom[i], unit_for_atom[j]))
        hits = [] if bad_units else model_piercings(safe)
        for hit in hits:
            bad_units.update(unit_for_atom[i] for i in hit["bond_serials"])
            bad_units.update(unit_for_atom[i] for i in hit["ring_serials"])
        if not bad_units:
            break
        for unit in bad_units:
            weight[unit] = 0.0 if weight[unit] <= 1 / 256 else weight[unit] * 0.5
    else:
        raise ValueError(
            "oxDNA topology-safe projection did not converge within "
            f"{max_iterations} iterations"
        )

    values = np.asarray(list(weight.values()), dtype=float)
    target_delta = np.linalg.norm(coords - p1, axis=1)
    report = SeedProjectionReport(
        iterations=iteration,
        fully_mapped_units=int(np.count_nonzero(values == 1.0)),
        backed_off_units=int(np.count_nonzero(values < 1.0)),
        mean_target_fraction=float(values.mean()),
        min_bond_ratio=final_min_ratio,
        max_bond_ratio=final_max_ratio,
        min_bond_nm=float(lengths.min(initial=np.inf)),
        max_bond_nm=float(lengths.max(initial=0.0)),
        ring_piercings=len(hits),
        steric_clashes=len(steric_pairs),
        steric_cutoff_nm=min_interunit_heavy_nm,
        target_rmsd_nm=float(np.sqrt(np.mean(target_delta**2))),
        target_p95_nm=float(np.quantile(target_delta, 0.95)),
    )
    return safe, target, report


def read_backbone_positions(
    conf_path: str | Path,
    design: Design,
) -> dict[tuple[str, int, str], np.ndarray]:
    """
    Read a relaxed oxDNA configuration and return the reconstructed true
    BACKBONE position per nucleotide (nm), not the raw centre of mass.

    oxDNA's ``.dat`` position is the centre of mass; the backbone phosphate sits
    ~0.34 units outward along a1/a2 (oxDNA2, ``model.h`` POS_MM_BACK1/2).  This
    helper applies ``oxdna_backbone_site`` per nucleotide so downstream
    atomistic seeding gets a ~1.6 nm cross-pair duplex (near B-DNA) instead of
    the ~1.0 nm CM-to-CM separation that causes startup clashes.

    Returns
    -------
    dict mapping (helix_id, bp_index, direction_str) → backbone position (nm).
    """
    full = read_configuration_full_unwrapped(conf_path, design)
    return {
        key: oxdna_backbone_site(rec["backbone_position"], rec["a1"], rec["a3"])
        for key, rec in full.items()
    }


# ── Phase 3a: per-helix PCA axis refitting (kept for reference) ───────────────


def _fit_helix_axis(
    positions: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Fit a line through a set of 3D points using PCA.

    Returns (centroid, unit_direction) where direction is the first principal
    component (longest variance axis).
    """
    centroid = positions.mean(axis=0)
    _, _, Vt = np.linalg.svd(positions - centroid, full_matrices=False)
    direction = Vt[0]  # first principal component
    direction /= np.linalg.norm(direction) + 1e-14
    return centroid, direction


def _project_onto_axis(
    point: np.ndarray,
    centroid: np.ndarray,
    direction: np.ndarray,
) -> float:
    """Scalar projection of point onto the axis defined by (centroid, direction)."""
    return float(np.dot(point - centroid, direction))


def _refit_helix_axes(
    design: Design,
    cg_positions: dict[tuple[str, int, str], np.ndarray],
) -> Design:
    """
    Return a copy of *design* with each helix's axis_start/axis_end replaced
    by the axis fitted to the CG backbone positions for that helix.

    For helices with no CG positions (none of their nucleotides appear in
    cg_positions), the original axis is kept.
    """
    # Group CG backbone positions by helix_id.
    helix_pts: dict[str, list[np.ndarray]] = {}
    for (h_id, bp, direction), pos in cg_positions.items():
        helix_pts.setdefault(h_id, []).append(pos)

    new_helices: list[Helix] = []
    for helix in design.helices:
        pts_list = helix_pts.get(helix.id)
        if pts_list is None or len(pts_list) < 2:
            new_helices.append(helix)
            continue

        pts = np.array(pts_list)
        centroid, fitted_dir = _fit_helix_axis(pts)

        # Ensure fitted direction points in the same half-space as the original
        # helix axis (avoid axis flip).
        orig_start = np.array(
            [helix.axis_start.x, helix.axis_start.y, helix.axis_start.z]
        )
        orig_end = np.array([helix.axis_end.x, helix.axis_end.y, helix.axis_end.z])
        orig_dir = orig_end - orig_start
        orig_dir /= np.linalg.norm(orig_dir) + 1e-14
        if np.dot(fitted_dir, orig_dir) < 0:
            fitted_dir = -fitted_dir

        # Project the original axis_start and axis_end onto the fitted line to
        # get new start/end that preserve the bp_start/bp_end mapping.
        new_start = (
            centroid + _project_onto_axis(orig_start, centroid, fitted_dir) * fitted_dir
        )
        new_end = (
            centroid + _project_onto_axis(orig_end, centroid, fitted_dir) * fitted_dir
        )

        new_helix = helix.model_copy(
            update={
                "axis_start": Vec3(
                    x=float(new_start[0]), y=float(new_start[1]), z=float(new_start[2])
                ),
                "axis_end": Vec3(
                    x=float(new_end[0]), y=float(new_end[1]), z=float(new_end[2])
                ),
            }
        )
        new_helices.append(new_helix)

    return design.model_copy(update={"helices": new_helices})


def build_atomistic_model_from_cg(
    design: Design,
    conf_path: str | Path,
) -> AtomisticModel:
    """
    Build an all-atom model using helix axes fitted to a relaxed oxDNA
    configuration (Phase 3a — per-helix PCA axis refitting).

    NOTE: Validated 2026-04-20 as providing no EM benefit vs ideal B-DNA
    (9,656 steps CG vs 9,787 steps ideal — 1.3% difference, within noise).
    Use build_atomistic_model_from_cg_spline (Phase 3b) instead.
    """
    cg_positions = read_configuration(conf_path, design)
    design_cg = _refit_helix_axes(design, cg_positions)
    return build_atomistic_model(design_cg)
