#!/usr/bin/env python3
"""Measure, from equilibrated free NAMD trajectories, where every atom of a
nucleotide actually sits relative to the base pair it belongs to.

Read this before touching atomistic placement
=============================================

How an atomistic base SHOULD be positioned
------------------------------------------
A nucleotide's atoms are not placed by a rule.  They are placed by the *molecule*,
and the only honest way to know where they go is to look at a converged simulation
of that molecule.  Everything below follows from taking that seriously.

Three claims are load-bearing, and each replaces something the old code assumed:

**1. The base pair is the only frame that means anything.**
A nucleotide has no absolute position; it has a position *relative to its base pair*
and its local helix axis.  So the measurement frame is built from the duplex itself:

    O    origin  — the point on the LOCAL helix axis closest to this base pair
                   (the axial position of the bp centre, i.e. the C1'–C1' midpoint
                   projected onto the axis).  This is exactly the ``axis_point``
                   NADOC's geometric layer already computes per bp.
    e_z  the local helix axis, signed along the FORWARD strand's 5'→3'.
    e_x  the outward radial from O to the FORWARD strand's phosphorus of this bp.
         This is a DEFINITION, not a measurement: it fixes the azimuthal origin.
         It is the same anchor the CG "new positioning" uses (forward backbone bead
         held at azimuth 0), so the coarse and atomistic layers cannot drift apart.
    e_y  e_z x e_x.  Right-handed, always.

Every atom of both strands is then reported as (x, y, z) in that one frame.  Nothing
else is needed and nothing else is assumed.

**2. FORWARD and REVERSE are measured independently — no mirror, no transform.**
The old templates derive the reverse strand from the forward one (``_DT_BASE_REV``
and friends are z-mirrored copies, and ``_atom_frame`` flips ``e_z`` by strand).  That
bakes in the pseudo-dyad as an exact symmetry.  It is not exact: the two strands of a
real duplex sit in different sequence contexts, different groove environments, and —
in an origami — different crossover topology.  So this script fills two completely
separate template sets, FORWARD and REVERSE, from their own samples.  How close they
come to being dyad images of each other is then a *result* (reported in the
diagnostics as ``dyad_rmsd_nm``), never an input.

**3. The average must be over a 21 bp span, and it must be a rigid-body average.**
21 bp is two full helical turns (NADOC's honeycomb repeat, 10.5 bp/turn).  Averaging
a nucleotide's placement over exactly one repeat cancels any residual helical-phase
bias, so the answer does not depend on *which* 21 bp you picked — the script proves
this by also reporting the spread between spans.

But a naive coordinate average of a fluctuating molecule is not a molecule: bond
lengths shrink toward the centroid, rings flatten, and stereocentres soften.  So the
average is taken in two separate pieces, which is the whole trick here:

    shape  — the nucleotide's internal geometry, averaged by iterative Kabsch
             superposition (proper rotations only, det = +1 enforced, so chirality
             can never be silently inverted).  This is a valid molecule.
    pose   — where that molecule sits in the base-pair frame: mean translation, and
             the mean rotation projected back onto SO(3).

The emitted template is the mean *shape* placed at the mean *pose*.  The diagnostics
report how far this is from the naive Cartesian mean (``shrinkage_nm``); that gap is
exactly the artefact this decomposition exists to avoid.

What this deliberately does NOT do
----------------------------------
It does not compute a "P–P separation" or a "groove angle".  Those numbers are
convention traps — the answer swings by a full 24 deg depending on which phosphate of
an antiparallel pair you call the partner — and the whole point of measuring atom
positions in a shared frame is that no such scalar is needed.  The reverse strand's
phosphorus lands where the trajectory puts it.

Provenance caveat that must travel with the numbers
---------------------------------------------------
Every trajectory in this repo was seeded from NADOC's own build.  Local geometry
(bond lengths, pucker, base placement in its own frame, radial positions) demonstrably
relaxes away from that seed within the free stage.  The slow, soft degree of freedom is
the *azimuthal registration between the two strands* — see
``memory/project_extra_base_spacing.md`` and ``experiments/exp52_groove_seed_sweep``.
The REVERSE template's azimuth inherits that caveat; its radii, internal shape and
axial placement do not.

Usage
-----
    uv run python scripts/measure_atomistic_template.py \
        --psf  /path/<stem>.psf \
        --dcd  /path/output/<stem>_04_300K_NPT_MGHH_only_p100.dcd \
        --label 18hb_free --frames 12 \
        --out backend/core/data/measured_atomistic_template.json

Free stages ONLY (``MGHH_only`` or a ``_k0`` production).  An ``ENM`` stage is
restrained to the built geometry and will hand NADOC's own constants straight back.
Pass ``--dcd`` more than once (with matching ``--psf``) to pool independent jobs; the
per-source templates are compared and the spread reported before pooling.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

# ── Chemistry tables ──────────────────────────────────────────────────────────

# CHARMM36 residue names → NADOC residue names.
RESNAME_MAP = {
    "ADE": "DA", "THY": "DT", "GUA": "DG", "CYT": "DC",
    "DA": "DA", "DT": "DT", "DG": "DG", "DC": "DC",
    "A": "DA", "T": "DT", "G": "DG", "C": "DC",
}

# CHARMM36 atom names → NADOC/PDB atom names.  Only these three differ.
ATOM_MAP = {"O1P": "OP1", "O2P": "OP2", "C5M": "C7"}

PURINES = {"DA", "DG"}

# The heavy atoms NADOC's atomistic layer draws, per residue.  Measuring exactly this
# set means the existing bond tables, element table and renderer need no changes.
SUGAR_ATOMS = ("P", "OP1", "OP2", "O5'", "C5'", "C4'", "O4'", "C3'", "O3'", "C2'", "C1'")
BASE_ATOMS = {
    "DA": ("N9", "C8", "N7", "C5", "C4", "N3", "C2", "N1", "C6", "N6"),
    "DG": ("N9", "C8", "N7", "C5", "C4", "N3", "C2", "N2", "N1", "C6", "O6"),
    "DT": ("N1", "C2", "O2", "N3", "C4", "O4", "C5", "C6", "C7"),
    "DC": ("N1", "C2", "O2", "N3", "C4", "N4", "C5", "C6"),
}

# The Watson-Crick donor/acceptor on the pseudo-dyad: purine N1 ↔ pyrimidine N3.
WC_ATOM = {"DA": "N1", "DG": "N1", "DT": "N3", "DC": "N3"}
COMPLEMENT = {"DA": "DT", "DT": "DA", "DG": "DC", "DC": "DG"}

# Ring atoms used for the base-plane normal and centroid diagnostics.
PURINE_RING = ("N9", "C8", "N7", "C5", "C6", "N1", "C2", "N3", "C4")
PYRIMIDINE_RING = ("N1", "C2", "N3", "C4", "C5", "C6")

ELEMENTS = {"P": "P", "O": "O", "N": "N", "C": "C"}

SPAN_BP = 21          # two full helical turns — the averaging window
MIN_RUN_BP = 12       # shortest duplex run worth measuring
EXCLUDE_TERMINAL = 2  # bp dropped at each end of a run (fraying / junction strain)


def element_of(name: str) -> str:
    return ELEMENTS.get(name[0], name[0])


def _norm(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


# ── Local helix axis ──────────────────────────────────────────────────────────


def fit_phosphate_cylinder(
    p_atoms: np.ndarray, u0: np.ndarray, c0: np.ndarray, iters: int = 8
) -> tuple[np.ndarray, np.ndarray, float]:
    """Fit the local helix axis as the axis of the cylinder the phosphates lie on.

    Returns ``(point_on_axis, unit_direction, rms_radial_residual)``.

    Why the phosphates and not the C1'–C1' midpoints: the midpoints sit only ~0.2 nm
    off the axis, so their radial signal is comparable to their thermal noise and the
    fitted line wanders — widening the window then drives the apparent cross-strand
    azimuth monotonically toward 180 deg, dissolving the very asymmetry being measured
    (see ``scripts/measure_cg_registration.py``, where this was established).  The
    phosphates sit at ~0.9 nm and sweep a full circle over a turn, so they pin both the
    axis position and its direction hard.

    Gauss-Newton on 4 parameters (two tilts off ``u0``, two in-plane offsets of ``c0``)
    with a numerical Jacobian.  Hand-rolled rather than ``scipy.least_squares`` purely
    for speed: this runs once per (span, frame) and there are tens of thousands of them.
    """
    seed = np.array([1.0, 0.0, 0.0]) if abs(u0[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    e1 = _norm(np.cross(u0, seed))
    e2 = np.cross(u0, e1)

    def unpack(q):
        u = _norm(u0 + q[0] * e1 + q[1] * e2)
        c = c0 + q[2] * e1 + q[3] * e2
        return u, c

    def resid(q):
        u, c = unpack(q)
        d = p_atoms - c
        d = d - np.outer(d @ u, u)
        r = np.linalg.norm(d, axis=1)
        return r - r.mean()

    q = np.zeros(4)
    r0 = resid(q)
    for _ in range(iters):
        J = np.empty((len(r0), 4))
        for i in range(4):
            dq = np.zeros(4)
            dq[i] = 1e-5
            J[:, i] = (resid(q + dq) - r0) / 1e-5
        try:
            step, *_ = np.linalg.lstsq(J, -r0, rcond=None)
        except np.linalg.LinAlgError:
            break
        q_new = q + step
        r_new = resid(q_new)
        if np.dot(r_new, r_new) >= np.dot(r0, r0):
            break
        q, r0 = q_new, r_new

    u, c = unpack(q)
    d = p_atoms - c
    d = d - np.outer(d @ u, u)
    radii = np.linalg.norm(d, axis=1)
    return c, u, float(np.sqrt(np.mean((radii - radii.mean()) ** 2)))


# ── Rigid-body averaging ──────────────────────────────────────────────────────


def kabsch(mobile: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Proper rotation ``R`` and translation ``t`` with ``mobile @ R.T + t ≈ target``.

    A reflection is never returned: the smallest singular direction is flipped instead.
    A nucleotide has four stereocentres and an improper fit would quietly racemise the
    template, which is the one failure mode that must be impossible here.
    """
    mc, tc = mobile.mean(axis=0), target.mean(axis=0)
    H = (mobile - mc).T @ (target - tc)
    U, _, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    return R, tc - mc @ R.T


def kabsch_batch(mobile: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Batched :func:`kabsch` — ``mobile`` ``(N,A,3)`` onto ``target`` ``(A,3)``.

    Same arithmetic, same reflection guard, done as stacked 3x3 SVDs so the ~200k
    superpositions an averaging run needs are a handful of array ops instead of a
    Python loop.  Returns ``R`` ``(N,3,3)`` and ``t`` ``(N,1,3)`` with
    ``mobile @ R.mT + t ≈ target``.
    """
    mc = mobile.mean(axis=1, keepdims=True)
    tc = target.mean(axis=-2, keepdims=True)
    X = mobile - mc
    Y = np.broadcast_to(target - tc, X.shape)
    H = X.transpose(0, 2, 1) @ Y
    U, _, Vt = np.linalg.svd(H)
    VtT, UT = Vt.transpose(0, 2, 1), U.transpose(0, 2, 1)
    d = np.sign(np.linalg.det(VtT @ UT))
    D = np.zeros((len(H), 3, 3))
    D[:, 0, 0] = D[:, 1, 1] = 1.0
    D[:, 2, 2] = d
    R = VtT @ D @ UT
    return R, np.broadcast_to(tc, mc.shape) - mc @ R.transpose(0, 2, 1)


def mean_shape(samples: np.ndarray, iters: int = 6) -> np.ndarray:
    """Iterative Kabsch mean of ``(N, A, 3)`` conformers — a valid mean molecule.

    Starting from the sample closest to the naive centroid, every conformer is
    superposed onto the running mean and the mean recomputed.  Converges in a handful
    of rounds for a nucleotide.  The result is defined only up to a rigid motion; the
    pose is measured separately by :func:`mean_pose`.
    """
    naive = samples.mean(axis=0)
    d = ((samples - naive) ** 2).sum(axis=(1, 2))
    ref = samples[int(np.argmin(d))].copy()
    for _ in range(iters):
        R, t = kabsch_batch(samples, ref)
        new = (samples @ R.transpose(0, 2, 1) + t).mean(axis=0)
        converged = np.sqrt(((new - ref) ** 2).sum(axis=1).mean()) < 1e-6
        ref = new
        if converged:
            break
    # Return it centred on its own centroid.  This is not cosmetic: :func:`mean_pose`
    # builds the placement as ``shape @ R.T + t`` with ``t`` derived from the shape's
    # centroid, and a mean rotation SHRINKS a vector (averaging rotations of a fixed
    # vector is not a rotation of it) while the projected mean rotation R preserves its
    # length.  Leaving the shape off-centre therefore leaks that difference into the
    # placement as a spurious outward push — measured, it inflated the phosphorus radius
    # from 0.93 nm to 1.06 nm.  With the centroid at the origin the term vanishes.
    return ref - ref.mean(axis=0)


def mean_pose(samples: np.ndarray, shape: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Mean rigid placement of ``shape`` that best represents ``samples``.

    Rotations are averaged as matrices and projected back onto SO(3) by SVD (the
    chordal L2 mean), with the determinant forced positive; translations are averaged
    directly.  Both are well-conditioned here because the frame already removes the
    bulk of the variation.
    """
    # Per-sample fit of the one fixed shape onto each conformer — the transpose of
    # kabsch_batch's "many mobiles onto one target", so it is spelled out here.
    mc = shape.mean(axis=0)
    X = shape - mc
    tcs = samples.mean(axis=1)
    H = np.einsum("ai,naj->nij", X, samples - tcs[:, None, :])
    U, _, Vt = np.linalg.svd(H)
    VtT, UT = Vt.transpose(0, 2, 1), U.transpose(0, 2, 1)
    d = np.sign(np.linalg.det(VtT @ UT))
    D = np.zeros((len(H), 3, 3))
    D[:, 0, 0] = D[:, 1, 1] = 1.0
    D[:, 2, 2] = d
    Rs = VtT @ D @ UT
    ts = tcs - mc @ Rs.transpose(0, 2, 1)
    U, _, Vt = np.linalg.svd(Rs.mean(axis=0))
    dd = np.sign(np.linalg.det(U @ Vt))
    return U @ np.diag([1.0, 1.0, dd]) @ Vt, ts.mean(axis=0)


# The nucleotide's genuinely rigid pieces.  A whole-nucleotide rigid average is NOT
# enough: the molecule has soft torsions (the BI/BII phosphate flip about P-O5'/C5'-O5',
# gamma about C4'-C5', chi about the glycosidic bond), and averaging across them pulls
# every atom toward its own rotation axis.  Measured on a 24hb: P-OP1 came out 0.124 nm
# against a real 0.148, i.e. the "average nucleotide" was not a nucleotide at all.
# Averaging each rigid group's SHAPE separately and then averaging its POSE keeps every
# intra-group bond and angle at its physical value, and lets the soft torsions show up
# where they belong — as the relative placement of the groups.
RIGID_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("phosphate", ("P", "OP1", "OP2", "O5'")),
    ("sugar", ("C5'", "C4'", "O4'", "C3'", "O3'", "C2'", "C1'")),
)


def _groups_for(resname: str) -> list[tuple[str, tuple[str, ...]]]:
    return list(RIGID_GROUPS) + [("base", BASE_ATOMS[resname])]


def template_from_samples(samples: np.ndarray, resname: str) -> tuple[np.ndarray, dict]:
    """Per-rigid-group mean shape, each placed at its own mean pose."""
    names = atom_names(resname)
    idx = {n: i for i, n in enumerate(names)}
    placed = np.zeros((len(names), 3))
    group_diag = {}
    for gname, gatoms in _groups_for(resname):
        cols = [idx[a] for a in gatoms]
        sub = samples[:, cols, :]
        shape = mean_shape(sub)
        R, t = mean_pose(sub, shape)
        placed[cols] = shape @ R.T + t
        # Internal flexibility of the group: RMSD of each conformer to the mean shape
        # AFTER superposition.  Small = the group really is rigid and the mean is valid.
        gR, gt = kabsch_batch(sub, shape)
        aligned = sub @ gR.transpose(0, 2, 1) + gt
        group_diag[gname] = round(float(np.sqrt(((aligned - shape) ** 2).sum(axis=2).mean())), 4)

    # Averaging each group's pose independently leaves the two bonds that JOIN the
    # groups free to drift — measured, O5'-C5' came out 0.162 nm against a real 0.144.
    # Restore each by sliding the dependent group bodily along that bond until its
    # length matches the trajectory's own mean.  A pure translation of a rigid group
    # changes no intra-group geometry and no group orientation, and the target is
    # measured from the same samples rather than assumed.
    bond_fix = {}
    for mobile, (a_fixed, a_mobile) in (
        ("phosphate", ("C5'", "O5'")),
        ("base", ("C1'", "N9" if resname in PURINES else "N1")),
    ):
        i_f, i_m = idx[a_fixed], idx[a_mobile]
        target = float(np.linalg.norm(samples[:, i_m, :] - samples[:, i_f, :], axis=1).mean())
        v = placed[i_m] - placed[i_f]
        n = float(np.linalg.norm(v))
        if n < 1e-9:
            continue
        cols = [idx[a] for a in dict(_groups_for(resname))[mobile]]
        placed[cols] += (v / n) * (target - n)
        bond_fix[f"{a_fixed}-{a_mobile}"] = [round(n, 4), round(target, 4)]

    naive = samples.mean(axis=0)
    rmsf = np.sqrt(((samples - naive) ** 2).sum(axis=2).mean(axis=0))
    diag = {
        "n_samples": int(len(samples)),
        "inter_group_bond_before_after_nm": bond_fix,
        # The trajectory's OWN mean bond lengths — the standard the template should be
        # judged against, ahead of any literature value.
        "measured_bonds_nm": {
            f"{a}-{b}": round(float(np.linalg.norm(
                samples[:, idx[b], :] - samples[:, idx[a], :], axis=1).mean()), 4)
            for (a, b) in BOND_TARGETS if a in idx and b in idx
        },
        "rmsf_nm": [round(float(v), 4) for v in rmsf],
        # How far the physically-valid template sits from the naive coordinate mean.
        # This gap IS the averaging artefact the group decomposition exists to avoid.
        "shrinkage_nm": round(float(np.abs(np.linalg.norm(placed - naive, axis=1)).max()), 4),
        "group_rmsd_nm": group_diag,
    }
    return placed, diag


# ── Topology ──────────────────────────────────────────────────────────────────


@dataclass
class Chain:
    """One physical strand: residue indices in 5'→3' order."""

    resindices: list[int]
    resnames: list[str]


@dataclass
class Span:
    """One 21 bp stretch of continuous duplex, both strands intact."""

    fwd: list[int]           # residue indices, 5'→3'
    rev: list[int]           # residue indices, partner of fwd[k] at rev[k]
    source: str = ""
    fields: dict = field(default_factory=dict)


def build_chains(segments: dict[str, list[int]], resname_of: dict[int, str],
                 name_index: dict[int, dict[str, int]],
                 positions: np.ndarray) -> list[Chain]:
    """Group nucleic residues into strands, ordered 5'→3'.

    Order is taken from the topology and then *verified* with the O3'(i)–P(i+1)
    phosphodiester distance on the reference frame, so a segment written 3'→5' is
    caught and flipped rather than silently producing a mirrored template.

    Takes the prebuilt ``name_index`` rather than calling ``select_atoms`` per residue:
    the selection parser is re-entered on every call, and at ~7k residues per system
    that alone dominated the run.
    """
    chains: list[Chain] = []
    for _seg, resindices in segments.items():
        if len(resindices) < MIN_RUN_BP:
            continue
        fwd_ok = rev_ok = 0
        for a, b in zip(resindices, resindices[1:]):
            ia, ib = name_index[a], name_index[b]
            if "O3'" in ia and "P" in ib:
                fwd_ok += np.linalg.norm(positions[ia["O3'"]] - positions[ib["P"]]) < 2.5
            if "O3'" in ib and "P" in ia:
                rev_ok += np.linalg.norm(positions[ib["O3'"]] - positions[ia["P"]]) < 2.5
        if rev_ok > fwd_ok:
            resindices = resindices[::-1]
        chains.append(Chain(
            resindices=list(resindices),
            resnames=[resname_of[r] for r in resindices],
        ))
    return chains


def pair_bases(positions: np.ndarray, wc_index: dict[int, int],
               resname_of: dict[int, str]) -> dict[int, int]:
    """Watson-Crick partner map, from WC-atom proximity on the current frame.

    Label-free: no reliance on chain naming, residue numbering, or the design.  A pair
    must be complementary, mutually nearest, within 3.4 A on the WC donor/acceptor.

    ``positions`` MUST be an already-materialised ``(n_atoms, 3)`` array, never
    ``universe.atoms.positions``: that is a property which builds a fresh full-system
    array on every access, so touching it inside a per-residue loop allocates tens of
    gigabytes and will take the machine down.
    """
    from scipy.spatial import cKDTree

    idx = sorted(wc_index)
    pos = positions[[wc_index[i] for i in idx]]
    tree = cKDTree(pos)
    pairs: dict[int, int] = {}
    best: dict[int, tuple[float, int]] = {}
    for a, b in tree.query_pairs(3.4):
        ra, rb = idx[a], idx[b]
        if COMPLEMENT[resname_of[ra]] != resname_of[rb]:
            continue
        d = float(np.linalg.norm(pos[a] - pos[b]))
        if d < best.get(ra, (1e9, -1))[0]:
            best[ra] = (d, rb)
        if d < best.get(rb, (1e9, -1))[0]:
            best[rb] = (d, ra)
    for ra, (_d, rb) in best.items():
        if best.get(rb, (0, -1))[1] == ra:
            pairs[ra] = rb
    return pairs


STACK_CUTOFF = 7.5   # A, C1'(k)–C1'(k+1) of two stacked neighbours


def duplex_spans(chains: list[Chain], pairs: dict[int, int], c1_index: dict[int, int],
                 positions: np.ndarray) -> list[Span]:
    """Cut the structure into disjoint 21 bp stretches of continuous stacked duplex.

    What continues a run is STACKING, not the backbone.  A nick — and in an origami
    every staple boundary is one — leaves the double helix completely intact, so
    requiring an unbroken phosphodiester on both strands would reject essentially the
    whole structure (measured: zero qualifying spans in a 24hb).  The test is instead
    that both the forward residue and its partner step to a neighbour that is still
    stacked on them (C1'–C1' within 7.5 A).  A crossover physically removes the strand
    to another helix, so that distance blows up and the run ends there, which is the
    break we do want.

    Roles alternate between accepted spans.  Every duplex region is measured exactly
    once (greedy, no residue reused), and whichever strand is called FORWARD flips from
    one span to the next — so the FORWARD and REVERSE templates are built from disjoint
    samples and their agreement is a result to be reported, not a symmetry assumed.
    """
    found: list[tuple[list[int], list[int]]] = []
    for ch in chains:
        run_f: list[int] = []
        run_r: list[int] = []
        for ri in ch.resindices:
            pj = pairs.get(ri)
            cont = pj is not None
            if cont and run_f:
                cont = (
                    np.linalg.norm(positions[c1_index[run_f[-1]]]
                                   - positions[c1_index[ri]]) < STACK_CUTOFF
                    and np.linalg.norm(positions[c1_index[run_r[-1]]]
                                       - positions[c1_index[pj]]) < STACK_CUTOFF
                )
            if cont:
                run_f.append(ri)
                run_r.append(pj)
                continue
            _emit_run(run_f, run_r, found)
            run_f, run_r = ([ri], [pj]) if pj is not None else ([], [])
        _emit_run(run_f, run_r, found)

    spans: list[Span] = []
    used: set[int] = set()
    for f, r in found:
        if used.isdisjoint(f) and used.isdisjoint(r):
            used.update(f)
            used.update(r)
            if len(spans) % 2:
                # Same duplex, opposite role assignment: walk it 5'→3' along the
                # other strand.  The frame follows, so this is an independent look.
                spans.append(Span(fwd=r[::-1], rev=f[::-1]))
            else:
                spans.append(Span(fwd=f, rev=r))
    return spans


def _emit_run(run_f: list[int], run_r: list[int],
              found: list[tuple[list[int], list[int]]]) -> None:
    if len(run_f) < SPAN_BP + 2 * EXCLUDE_TERMINAL:
        return
    f = run_f[EXCLUDE_TERMINAL: len(run_f) - EXCLUDE_TERMINAL]
    r = run_r[EXCLUDE_TERMINAL: len(run_r) - EXCLUDE_TERMINAL]
    for s in range(0, len(f) - SPAN_BP + 1, SPAN_BP):
        found.append((f[s:s + SPAN_BP], r[s:s + SPAN_BP]))


# ── Measurement ───────────────────────────────────────────────────────────────


class Accumulator:
    """Per (role, residue) reservoirs of nucleotide conformers in the bp frame."""

    def __init__(self, cap: int = 30000):
        self.cap = cap
        self.samples: dict[tuple[str, str], list] = defaultdict(list)
        self.by_span: dict[tuple[str, str], list] = defaultdict(list)
        self.seen: dict[tuple[str, str], int] = defaultdict(int)

    def add(self, role: str, resname: str, coords: np.ndarray, span_id: int) -> None:
        key = (role, resname)
        self.seen[key] += 1
        if len(self.samples[key]) < self.cap:
            self.samples[key].append(coords.astype(np.float32))
            self.by_span[key].append(span_id)

    def stacked(self, role: str, resname: str) -> np.ndarray:
        return np.asarray(self.samples[(role, resname)], dtype=float)


def atom_names(resname: str) -> tuple[str, ...]:
    return SUGAR_ATOMS + BASE_ATOMS[resname]


def measure_span(span: Span, positions: np.ndarray, name_index: dict[int, dict[str, int]],
                 resname_of: dict[int, str], acc: Accumulator, span_id: int,
                 stats: dict, terminal: set[int]) -> None:
    """Measure both nucleotides of every base pair in one 21 bp span, one frame.

    The span gets ONE local axis fit — the cylinder through its 42 phosphates — and
    every bp in the span is then referred to that axis.  That is what makes "the average
    over a 21 bp span" a well-posed quantity rather than a rolling smooth.
    """
    n = len(span.fwd)
    c1f = np.array([positions[name_index[i]["C1'"]] for i in span.fwd])
    c1r = np.array([positions[name_index[i]["C1'"]] for i in span.rev])
    mids = (c1f + c1r) / 2.0

    ps = [positions[name_index[i]["P"]] for i in span.fwd + span.rev
          if "P" in name_index[i]]
    if len(ps) < 2 * n - 4:
        stats["skip_no_p"] += 1
        return

    u0 = _norm(mids[-1] - mids[0])
    parr = np.array(ps)
    c_fit, e_z, resid = fit_phosphate_cylinder(parr, u0, mids.mean(axis=0))
    if np.dot(e_z, u0) < 0:
        e_z = -e_z
    d = parr - c_fit
    stats["fit_radius_sum"] += float(np.linalg.norm(d - np.outer(d @ e_z, e_z), axis=1).mean())
    stats["fit_resid_sum"] += resid
    stats["fit_n"] += 1
    # A curved or locally melted span cannot define an axis; drop it rather than
    # contribute a frame that is wrong in a way the average cannot undo.
    if resid > 0.12:          # nm, RMS radial scatter of the phosphates
        stats["skip_axis"] += 1
        return

    for k in range(n):
        origin = c_fit + np.dot(mids[k] - c_fit, e_z) * e_z
        # Azimuth zero is anchored on the base pair's own C1'->C1' vector, which is the
        # one choice that privileges NEITHER strand: swapping the two roles maps the
        # frame onto itself.  Anchoring on one strand's atom instead injects that atom's
        # thermal noise into everything on the other strand — measured on a 24hb,
        # anchoring on the forward phosphorus (the worst case, since the BI/BII flip
        # swings P through tens of degrees) inflated the partner strand's apparent RMSF
        # by ~1.8x, and anchoring on the forward C1' still left a visible asymmetry.
        # The C1'->C1' vector also has a ~1.07 nm lever arm, unlike the bp centre, which
        # sits ~0.2 nm off the axis and so has a badly-determined radial direction.
        # The emitted template is rotated afterwards so the forward P lands at azimuth
        # 0, which is the convention the rest of NADOC consumes.
        radial = c1f[k] - c1r[k]
        radial = radial - np.dot(radial, e_z) * e_z
        if np.linalg.norm(radial) < 1e-6:
            continue
        e_x = _norm(radial)
        e_y = np.cross(e_z, e_x)
        R = np.column_stack([e_x, e_y, e_z])       # world → frame is R.T

        for role, ri in (("FORWARD", span.fwd[k]), ("REVERSE", span.rev[k])):
            rn = resname_of[ri]
            names = atom_names(rn)
            ni = name_index[ri]
            # A nick does not break the duplex (so the span survives it), but the two
            # nucleotides flanking one have a free 5'/3' end and no through-backbone:
            # their own atoms are not representative, so they contribute no sample.
            if ri in terminal:
                stats["skip_terminal_nt"] += 1
                continue
            if not all(a in ni for a in names):
                stats["skip_incomplete"] += 1
                continue
            xyz = np.array([positions[ni[a]] for a in names])
            acc.add(role, rn, (xyz - origin) @ R, span_id)
        stats["bp"] += 1


def analyse_universe(psf: str, dcd: str, n_frames: int, acc: Accumulator,
                     label: str) -> dict:
    import MDAnalysis as mda

    u = mda.Universe(psf, dcd)
    total = len(u.trajectory)
    frames = np.unique(np.linspace(total // 3, total - 1, n_frames).astype(int))
    print(f"[{label}] {total} frames; analysing {len(frames)}: {list(frames)}")

    resname_of: dict[int, str] = {}
    name_index: dict[int, dict[str, int]] = {}
    wc_index: dict[int, int] = {}
    c1_index: dict[int, int] = {}
    segments: dict[str, list[int]] = defaultdict(list)

    dna = u.select_atoms("nucleic")
    for res in dna.residues:
        rn = RESNAME_MAP.get(res.resname.strip().upper())
        if rn is None:
            continue
        ri = res.resindex
        resname_of[ri] = rn
        m = {ATOM_MAP.get(at.name, at.name): at.index for at in res.atoms}
        name_index[ri] = m
        segments[res.segid].append(ri)
        if WC_ATOM[rn] in m:
            wc_index[ri] = m[WC_ATOM[rn]]
        if "C1'" in m:
            c1_index[ri] = m["C1'"]
    for seg in segments:
        segments[seg].sort(key=lambda ri: u.residues[ri].resid)

    u.trajectory[int(frames[0])]
    ref_pos = np.array(u.atoms.positions, dtype=float)
    chains = build_chains(segments, resname_of, name_index, ref_pos)
    terminal = {ri for ch in chains for ri in (ch.resindices[:1] + ch.resindices[-1:])}
    print(f"[{label}] {len(chains)} strands, {len(resname_of)} nucleotides, "
          f"{len(terminal)} chain-end nucleotides excluded")

    stats = defaultdict(int)
    span_id = 0
    n_spans_total = 0
    for fi in frames:
        u.trajectory[int(fi)]
        raw = np.array(u.atoms.positions, dtype=float)     # materialise ONCE per frame
        pos = raw * 0.1                                    # A → nm
        pairs = pair_bases(raw, wc_index, resname_of)
        spans = duplex_spans(chains, pairs, c1_index, raw)
        n_spans_total += len(spans)
        for sp in spans:
            measure_span(sp, pos, name_index, resname_of, acc, span_id, stats, terminal)
            span_id += 1
        print(f"  frame {fi}: {len(pairs)} bp paired, {len(spans)} spans, "
              f"{stats['bp']} bp measured so far")

    return {
        "label": label,
        "psf": psf,
        "dcd": dcd,
        "n_frames_total": total,
        "frames_used": [int(f) for f in frames],
        "n_chains": len(chains),
        "n_spans": n_spans_total,
        "bp_measured": int(stats["bp"]),
        "skipped": {k: int(v) for k, v in stats.items() if k.startswith("skip")},
        "axis_fit": {
            "n": int(stats["fit_n"]),
            "mean_phosphate_radius_nm": round(stats["fit_radius_sum"] / max(1, stats["fit_n"]), 4),
            "mean_residual_nm": round(stats["fit_resid_sum"] / max(1, stats["fit_n"]), 4),
        },
    }


# ── Validation ────────────────────────────────────────────────────────────────

BOND_TARGETS = {                     # nm, from small-molecule/B-DNA reference values
    ("P", "OP1"): 0.148, ("P", "OP2"): 0.148, ("P", "O5'"): 0.160,
    ("O5'", "C5'"): 0.144, ("C5'", "C4'"): 0.151, ("C4'", "O4'"): 0.145,
    ("C4'", "C3'"): 0.152, ("O4'", "C1'"): 0.142, ("C3'", "O3'"): 0.143,
    ("C3'", "C2'"): 0.152, ("C2'", "C1'"): 0.152,
}

# Signed volume of (b-a, c-a, d-a) at each sugar stereocentre.  Sign, not magnitude, is
# the invariant: it is what distinguishes D-deoxyribose from its enantiomer.
STEREO = {
    "C1'": ("C1'", "O4'", "C2'", "N-glyco"),
    "C3'": ("C3'", "C4'", "C2'", "O3'"),
    "C4'": ("C4'", "O4'", "C5'", "C3'"),
}


def validate(template: dict, diagnostics: dict) -> dict:
    """Check the emitted template is a real B-DNA nucleotide, not an average artefact."""
    out: dict = {}
    for role in ("FORWARD", "REVERSE"):
        for rn in ("DA", "DT", "DG", "DC"):
            key = f"{role}/{rn}"
            entry = template[role][rn]
            pos = {a["name"]: np.array(a["xyz"]) for a in entry}
            bonds = {}
            for (a, b), tgt in BOND_TARGETS.items():
                if a in pos and b in pos:
                    bonds[f"{a}-{b}"] = round(float(np.linalg.norm(pos[a] - pos[b])), 4)
            worst = max((abs(bonds[f"{a}-{b}"] - t) for (a, b), t in BOND_TARGETS.items()
                         if f"{a}-{b}" in bonds), default=0.0)

            glyco = "N9" if rn in PURINES else "N1"
            stereo = {}
            for centre, (a, b, c, d) in STEREO.items():
                d = glyco if d == "N-glyco" else d
                if all(x in pos for x in (a, b, c, d)):
                    stereo[centre] = round(float(np.dot(
                        np.cross(pos[b] - pos[a], pos[c] - pos[a]), pos[d] - pos[a])), 5)

            ring = PURINE_RING if rn in PURINES else PYRIMIDINE_RING
            pts = np.array([pos[a] for a in ring if a in pos])
            _, sv, _ = np.linalg.svd(pts - pts.mean(axis=0))
            out[key] = {
                "bond_max_dev_nm": round(float(worst), 4),
                "bonds_nm": bonds,
                "stereo_signed_volume_nm3": stereo,
                "ring_planarity_nm": round(float(sv[2] / math.sqrt(len(pts))), 5),
                "glycosidic_nm": round(float(np.linalg.norm(pos["C1'"] - pos[glyco])), 4),
                "r_P_nm": round(float(math.hypot(pos["P"][0], pos["P"][1])), 4),
                "r_C1_nm": round(float(math.hypot(pos["C1'"][0], pos["C1'"][1])), 4),
                "azimuth_P_deg": round(math.degrees(math.atan2(pos["P"][1], pos["P"][0])), 2),
                "z_P_nm": round(float(pos["P"][2]), 4),
                "n_samples": diagnostics[key]["n_samples"],
                "max_rmsf_nm": round(float(max(diagnostics[key]["rmsf_nm"])), 4),
                "shrinkage_nm": diagnostics[key]["shrinkage_nm"],
            }

    # Watson-Crick geometry between the two independently measured strands — the
    # sharpest single test that FORWARD and REVERSE were measured consistently.
    wc = {}
    for rn in ("DA", "DT", "DG", "DC"):
        f = {a["name"]: np.array(a["xyz"]) for a in template["FORWARD"][rn]}
        r = {a["name"]: np.array(a["xyz"]) for a in template["REVERSE"][COMPLEMENT[rn]]}
        wc[f"{rn}-{COMPLEMENT[rn]}"] = {
            "wc_N_nm": round(float(np.linalg.norm(f[WC_ATOM[rn]] - r[WC_ATOM[COMPLEMENT[rn]]])), 4),
            "c1_c1_nm": round(float(np.linalg.norm(f["C1'"] - r["C1'"])), 4),
        }
    out["watson_crick"] = wc
    return out


def dyad_comparison(template: dict) -> dict:
    """How close is REVERSE to being the dyad image of FORWARD?

    A result, never an assumption.  The pseudo-dyad of a base pair is the axis through
    the pair perpendicular to the helix axis, so the test is: rotate the FORWARD
    template 180 deg about e_x and see how far it lands from the measured REVERSE
    template of the complementary base.  Reported as a per-atom RMSD.
    """
    out = {}
    for rn in ("DA", "DT", "DG", "DC"):
        f = {a["name"]: np.array(a["xyz"]) for a in template["FORWARD"][rn]}
        r = {a["name"]: np.array(a["xyz"]) for a in template["REVERSE"][rn]}
        common = [n for n in f if n in r]
        A = np.array([f[n] for n in common])
        B = np.array([r[n] for n in common])

        # (1) Are the two independently-measured nucleotides the same MOLECULE?
        # Optimal proper superposition; residual is pure internal-shape disagreement.
        R, t = kabsch(A, B)
        shape_rmsd = float(np.sqrt((((A @ R.T + t) - B) ** 2).sum(axis=1).mean()))

        # (2) Is the rigid motion relating them the pseudo-dyad — a 180 deg turn about
        # an axis perpendicular to the helix axis?  Read the angle and axis off R
        # rather than assuming either.
        angle = math.degrees(math.acos(max(-1.0, min(1.0, (np.trace(R) - 1.0) / 2.0))))
        w, V = np.linalg.eig(R)
        axis = np.real(V[:, int(np.argmin(np.abs(w - 1.0)))])
        axis = axis / np.linalg.norm(axis)
        out[rn] = {
            "shape_rmsd_nm": round(shape_rmsd, 4),
            "rotation_deg": round(angle, 2),
            "axis_tilt_from_perpendicular_deg": round(
                abs(90.0 - math.degrees(math.acos(min(1.0, abs(axis[2]))))), 2),
            "axis_azimuth_deg": round(math.degrees(math.atan2(axis[1], axis[0])) % 180.0, 2),
        }
    return out


def span_spread(acc: Accumulator) -> dict:
    """Between-span spread of the template — does "any given 21 bp span" agree?

    Groups each reservoir by its span id, builds an independent template per span from
    spans with a full complement of samples, and reports how far those per-span answers
    scatter about the pooled one.
    """
    out = {}
    for (role, rn), samples in acc.samples.items():
        arr = np.asarray(samples, dtype=float)
        sid = np.asarray(acc.by_span[(role, rn)])
        pooled = mean_shape(arr) if len(arr) else None
        if pooled is None:
            continue
        per_span = []
        for s in np.unique(sid)[:400]:
            sub = arr[sid == s]
            if len(sub) < 4:
                continue
            shape = mean_shape(sub, iters=3)
            R, t = mean_pose(sub, shape)
            per_span.append(shape @ R.T + t)
        if len(per_span) < 3:
            continue
        stack = np.asarray(per_span)
        grand = stack.mean(axis=0)
        dev = np.sqrt(((stack - grand) ** 2).sum(axis=2))     # (spans, atoms)
        out[f"{role}/{rn}"] = {
            "n_spans": int(len(per_span)),
            "rms_span_deviation_nm": round(float(np.sqrt((dev ** 2).mean())), 4),
            "max_span_deviation_nm": round(float(dev.max()), 4),
            "sem_nm": round(float(np.sqrt((dev ** 2).mean()) / math.sqrt(len(per_span))), 5),
        }
    return out


# ── Main ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--psf", action="append", required=True)
    ap.add_argument("--dcd", action="append", required=True)
    ap.add_argument("--label", action="append", default=None)
    ap.add_argument("--frames", type=int, default=12,
                    help="frames sampled per trajectory, from the last 2/3")
    ap.add_argument("--cap", type=int, default=30000, help="max conformers per bucket")
    ap.add_argument("--out", default="backend/core/data/measured_atomistic_template.json")
    ap.add_argument("--report", default=None, help="write the diagnostics JSON here too")
    args = ap.parse_args(argv)

    if len(args.psf) != len(args.dcd):
        ap.error("--psf and --dcd must be given the same number of times")
    labels = args.label or [Path(d).stem for d in args.dcd]

    # One accumulator per trajectory, pooled afterwards.  Keeping them apart is what
    # makes the cross-system check possible: an independently-built template per job,
    # each compared against the pooled answer, so a single anomalous system cannot hide
    # inside the average.
    per_source: dict[str, Accumulator] = {}
    sources = []
    for psf, dcd, label in zip(args.psf, args.dcd, labels):
        sub = Accumulator(cap=args.cap)
        sources.append(analyse_universe(psf, dcd, args.frames, sub, label))
        per_source[label] = sub

    acc = Accumulator(cap=args.cap * max(1, len(per_source)))
    for sub in per_source.values():
        for key, rows in sub.samples.items():
            acc.samples[key].extend(rows)
            acc.by_span[key].extend(sub.by_span[key])

    raw: dict = {"FORWARD": {}, "REVERSE": {}}
    diagnostics: dict = {}
    for role in ("FORWARD", "REVERSE"):
        for rn in ("DA", "DT", "DG", "DC"):
            arr = acc.stacked(role, rn)
            if len(arr) < 50:
                print(f"!! too few samples for {role}/{rn}: {len(arr)}", file=sys.stderr)
                return 2
            placed, diag = template_from_samples(arr, rn)
            raw[role][rn] = placed
            diagnostics[f"{role}/{rn}"] = diag
            print(f"  {role}/{rn}: {len(arr)} conformers, "
                  f"max RMSF {max(diag['rmsf_nm']):.3f} nm, "
                  f"shrinkage {diag['shrinkage_nm']:.4f} nm, "
                  f"groups {diag['group_rmsd_nm']}")

    # Re-zero the azimuth on the FORWARD phosphorus.  Measurement anchored on C1' for
    # noise reasons; NADOC's consumers expect azimuth 0 to be the forward backbone
    # position, so rotate the WHOLE template — both strands, all four bases — about the
    # helix axis as one rigid body.  A single common rotation cannot change any
    # measured relationship, only the arbitrary zero of the angle.
    p_idx = atom_names("DA").index("P")
    phis = [math.atan2(raw["FORWARD"][rn][p_idx][1], raw["FORWARD"][rn][p_idx][0])
            for rn in ("DA", "DT", "DG", "DC")]
    phi0 = math.atan2(float(np.mean([math.sin(p) for p in phis])),
                      float(np.mean([math.cos(p) for p in phis])))
    c, s = math.cos(-phi0), math.sin(-phi0)
    Rz = np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])
    print(f"  azimuth re-zero: rotating template by {math.degrees(-phi0):+.2f} deg "
          f"about the helix axis (forward P spread "
          f"{math.degrees(max(phis) - min(phis)):.2f} deg)")

    template: dict = {"FORWARD": {}, "REVERSE": {}}
    for role in ("FORWARD", "REVERSE"):
        for rn in ("DA", "DT", "DG", "DC"):
            placed = raw[role][rn] @ Rz.T
            template[role][rn] = [
                {"name": n, "element": element_of(n),
                 "xyz": [round(float(v), 5) for v in placed[i]]}
                for i, n in enumerate(atom_names(rn))
            ]

    # Cross-system agreement: rebuild the template from each trajectory alone and see
    # how far it lands from the pooled one.  Systems differ in bundle geometry, insert
    # count and sequence, so agreement here is the evidence that what is being measured
    # is B-DNA and not one design's quirk.
    cross: dict = {}
    if len(per_source) > 1:
        for label, sub in per_source.items():
            worst = 0.0
            rms: list[float] = []
            for role in ("FORWARD", "REVERSE"):
                for rn in ("DA", "DT", "DG", "DC"):
                    arr = sub.stacked(role, rn)
                    if len(arr) < 50:
                        continue
                    own, _ = template_from_samples(arr, rn)
                    own = own @ Rz.T
                    ref = np.array([a["xyz"] for a in template[role][rn]])
                    dev = np.linalg.norm(own - ref, axis=1)
                    worst = max(worst, float(dev.max()))
                    rms.append(float(np.sqrt((dev ** 2).mean())))
            cross[label] = {
                "rms_deviation_from_pooled_nm": round(float(np.mean(rms)), 4) if rms else None,
                "max_deviation_from_pooled_nm": round(worst, 4),
            }

    report = {
        "sources": sources,
        "cross_system": cross,
        "span_bp": SPAN_BP,
        "exclude_terminal_bp": EXCLUDE_TERMINAL,
        "per_bucket": diagnostics,
        "validation": validate(template, diagnostics),
        "dyad": dyad_comparison(template),
        "span_spread": span_spread(acc),
    }

    payload = {
        "format": "nadoc.measured_atomistic_template",
        "version": 1,
        "units": "nm",
        "frame": {
            "origin": "local helix axis point nearest the base pair (C1'-C1' midpoint projected onto the axis)",
            "e_x": "outward radial from the origin to the FORWARD strand phosphorus of this base pair",
            "e_y": "e_z x e_x",
            "e_z": "local helix axis, signed along the FORWARD strand 5'->3'",
        },
        "template": template,
        "report": report,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=1))
    print(f"\nwrote {out}")
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=1))
    print(json.dumps(report["validation"], indent=1)[:4000])
    print(json.dumps(report["dyad"], indent=1))
    print(json.dumps(report["span_spread"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
