#!/usr/bin/env python3
"""Measure where a crossover extra base ACTUALLY sits, in the same parameterisation
NADOC uses to place it.

NADOC's builder (``atomistic._build_extra_base_atoms``) puts insert ``i`` of ``n`` at

    t_i    = i / (n + 1)                      along a quadratic Bezier
    p0     = C3' of the 3'-exit (src) nucleotide
    p1     = C5' of the 5'-entry (dst) nucleotide
    ctrl   = midpoint + bow_dir * (_BOW_FRAC_3D=0.3) * |p1 - p0|
    bow_dir= normalise(cross(halfA -> halfB, avg helix axis))

so at n=1 the sugar-template ORIGIN lands at ``mid + 0.15*L*bow_dir`` with ZERO offset
along the helix axis.  The L-BFGS-B joint solve then moves the whole insert.  This script
rebuilds that frame from any coordinate source (built model, package PDB, MD frame) and
reports the insert's (t, bow, axial) coordinates -> the numbers the builder should use.

Frame (right-handed, per crossover, per frame):
    u    = unit(p1 - p0)                       chord, src->dst
    b_p  = bow_dir made perpendicular to u     (builder convention, halfA -> halfB)
    a    = cross(u, b_p)                       third axis (~ +/- helix axis)
Position of an insert atom x:
    t    = dot(x - p0, u) / L                  (pure arc pose: ~0.5)
    bow  = dot(x - p0, b_p) / L                (pure arc pose: ~0.15)
    ax   = dot(x - p0, a)   / L                (pure arc pose: ~0)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from xb_map import FrameJoiner, build_package_map, load_design, pdb_coords  # noqa: E402

RING_NAMES = ["N1", "C2", "N3", "C4", "C5", "C6"]
INS_ATOMS = ("C1'", "C3'", "C5'", "C4'", "O4'", "P", "O3'",
             "N1", "C2", "N3", "C4", "C5", "C6")


def _unit(v):
    n = float(np.linalg.norm(v))
    return v / (n if n > 1e-12 else 1.0)


# ── the builder's own nucleotide template, for a rigid-pose (Kabsch) readout ───
def template_atoms(residue: str = "DT"):
    """(names, local coords in Angstrom) of the template the builder rigid-transforms."""
    from backend.core.atomistic import BASE_TEMPLATES, _SUGAR
    names, xyz = [], []
    for nm, _el, a, b, c in _SUGAR:
        names.append(nm)
        xyz.append((a, b, c))
    for nm, _el, a, b, c in BASE_TEMPLATES[residue][0]:
        if nm in names:
            continue
        names.append(nm)
        xyz.append((a, b, c))
    return names, np.asarray(xyz, dtype=float) * 10.0


def kabsch(local, world):
    """Rigid fit world ~= origin + R @ local.  Returns (origin, R, rmsd)."""
    lc, wc = local.mean(axis=0), world.mean(axis=0)
    H = (local - lc).T @ (world - wc)
    U, _S, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    R = Vt.T @ np.diag([1.0, 1.0, d]) @ U.T
    o = wc - R @ lc
    res = world - (local @ R.T + o)
    return o, R, float(np.sqrt((res ** 2).sum() / len(local)))


def mean_rotation(mats):
    """Chordal-L2 mean of rotation matrices (SVD projection of the arithmetic mean)."""
    M = np.mean(np.asarray(mats), axis=0)
    U, _S, Vt = np.linalg.svd(M)
    d = np.sign(np.linalg.det(U @ Vt))
    return U @ np.diag([1.0, 1.0, d]) @ Vt


# ── coordinate sources ────────────────────────────────────────────────────────
class PackageSource:
    """Coordinates from a package-PDB-ordered array (PDB, .coor, DCD frame)."""

    def __init__(self, pm, X, box=None, ref_row=None):
        self.pm, self.X = pm, X
        self.box = box
        self.ref = None if ref_row is None else X[ref_row]

    def _mi(self, x):
        if self.box is None or self.ref is None:
            return x
        return x - np.round((x - self.ref) / self.box) * self.box

    def nt(self, key, name):
        r = self.pm.nt_row(key, name)
        return None if r is None else self._mi(self.X[r])

    def ins(self, insert, name):
        r = self.pm.row(insert.segid, insert.resid, name)
        return None if r is None else self._mi(self.X[r])

    def raw(self, row):
        return self._mi(self.X[row])


class ModelSource:
    """Coordinates from a freshly built AtomisticModel (nm -> Angstrom)."""

    def __init__(self, model, scale=10.0):
        self.nt_idx, self.ins_idx = {}, {}
        for a in model.atoms:
            xid = getattr(a, "crossover_id", None)
            if xid is not None:
                self.ins_idx[(xid, getattr(a, "extra_base_k", 0), a.name)] = a
            else:
                self.nt_idx[(a.helix_id, a.bp_index, a.direction, a.name)] = a
        self.scale = scale

    @staticmethod
    def _p(a, s):
        return np.array([a.x, a.y, a.z]) * s

    def nt(self, key, name):
        a = self.nt_idx.get((key[0], key[1], key[2], name))
        return None if a is None else self._p(a, self.scale)

    def ins(self, insert, name):
        a = self.ins_idx.get((insert.crossover_id, insert.k, name))
        return None if a is None else self._p(a, self.scale)


# ── the probe ─────────────────────────────────────────────────────────────────
class JunctionProbe:
    def __init__(self, pm, ins, half_a_helix, axis_window=6):
        self.ins = ins
        siblings = sorted(
            (other for other in pm.inserts if other.crossover_id == ins.crossover_id),
            key=lambda other: other.k,
        )
        self.prev_insert = siblings[ins.k - 1] if ins.k > 0 else None
        self.next_insert = siblings[ins.k + 1] if ins.k + 1 < len(siblings) else None
        self.half_a_helix = half_a_helix
        self.hel_src, self.bp_src, self.dir_src = ins.src
        self.hel_dst, self.bp_dst, self.dir_dst = ins.dst
        self.axis_keys = {}
        for hel, bp0 in ((self.hel_src, self.bp_src), (self.hel_dst, self.bp_dst)):
            self.axis_keys[hel] = [
                ((hel, bp, "FORWARD"), (hel, bp, "REVERSE"))
                for bp in range(bp0 - axis_window, bp0 + axis_window + 1)]
        self.neigh_keys = []
        for hel, bp0 in ((self.hel_src, self.bp_src), (self.hel_dst, self.bp_dst)):
            for bp in (bp0 - 1, bp0, bp0 + 1):
                for d in ("FORWARD", "REVERSE"):
                    self.neigh_keys.append((hel, bp, d))
        self.ref_row = None
        _res = {"T": "DT", "A": "DA", "G": "DG", "C": "DC"}.get(
            (ins.base or "T").upper(), "DT")
        self.template = template_atoms(_res)

        # the partner crossover of the reciprocal pair: same two helices, crossover bp
        # within 2, opposite hop direction
        self.partner_rows: list[int] = []
        bb = ("P", "O5'", "C5'", "C4'", "C3'", "O3'", "C1'")
        for other in pm.inserts:
            if other.crossover_id == ins.crossover_id:
                continue
            if {other.src[0], other.dst[0]} != {ins.src[0], ins.dst[0]}:
                continue
            if abs(other.src[1] - ins.src[1]) > 2:
                continue
            if other.src[0] == ins.src[0]:
                continue                          # same hop direction: not reciprocal
            for nm in bb:
                r = pm.row(other.segid, other.resid, nm)
                if r is not None:
                    self.partner_rows.append(r)
            for key in (other.src, other.dst):
                for nm in bb:
                    r = pm.nt_row(key, nm)
                    if r is not None:
                        self.partner_rows.append(r)
        self.partner_rows = sorted(set(self.partner_rows))

    def rows(self, pm):
        """Every package row this probe touches (for a minimum-image reference)."""
        out = []
        for name in ("C3'", "C5'", "C1'"):
            for key in (self.ins.src, self.ins.dst):
                r = pm.nt_row(key, name)
                if r is not None:
                    out.append(r)
        for name in INS_ATOMS:
            r = pm.row(self.ins.segid, self.ins.resid, name)
            if r is not None:
                out.append(r)
        for keys in self.axis_keys.values():
            for kf, kr in keys:
                for k in (kf, kr):
                    r = pm.nt_row(k, "C1'")
                    if r is not None:
                        out.append(r)
        for key in self.neigh_keys:
            for name in RING_NAMES:
                r = pm.nt_row(key, name)
                if r is not None:
                    out.append(r)
        return sorted(set(out))

    def measure(self, src) -> dict:
        p0 = src.nt(self.ins.src, "C3'")
        p1 = src.nt(self.ins.dst, "C5'")
        chord = p1 - p0
        L = float(np.linalg.norm(chord))
        u = chord / L

        axes, centres = {}, {}
        for hel, keys in self.axis_keys.items():
            mids, bps = [], []
            for i, (kf, kr) in enumerate(keys):
                f, r = src.nt(kf, "C1'"), src.nt(kr, "C1'")
                if f is not None and r is not None:
                    mids.append((f + r) * 0.5)
                    bps.append(i)
            mids = np.asarray(mids)
            c = mids.mean(axis=0)
            w, V = np.linalg.eigh(np.cov((mids - c).T))
            ax = V[:, int(np.argmax(w))]
            if np.dot(mids[-1] - mids[0], ax) < 0:
                ax = -ax                                  # along increasing bp
            axes[hel], centres[hel] = ax, c

        hel_b = self.hel_dst if self.hel_src == self.half_a_helix else self.hel_src
        avg_axis = _unit(axes[self.half_a_helix] + axes[hel_b])
        pa = src.nt(self.ins.src if self.hel_src == self.half_a_helix else self.ins.dst, "C1'")
        pb = src.nt(self.ins.dst if self.hel_src == self.half_a_helix else self.ins.src, "C1'")
        bow = _unit(np.cross(_unit(pb - pa), avg_axis))
        b_p = _unit(bow - float(np.dot(bow, u)) * u)
        a3 = np.cross(u, b_p)

        def coords(x):
            d = x - p0
            return (float(np.dot(d, u)) / L, float(np.dot(d, b_p)) / L,
                    float(np.dot(d, a3)) / L)

        out = {"L": L}
        c1 = src.ins(self.ins, "C1'")
        out["t_c1"], out["bow_c1"], out["ax_c1"] = coords(c1)
        for nm in ("C3'", "C5'", "C4'", "P"):
            x = src.ins(self.ins, nm)
            if x is not None:
                out[f"t_{nm}"], out[f"bow_{nm}"], out[f"ax_{nm}"] = coords(x)

        ring = np.array([src.ins(self.ins, n) for n in RING_NAMES])
        cen = ring.mean(axis=0)
        out["t_base"], out["bow_base"], out["ax_base"] = coords(cen)
        w, V = np.linalg.eigh(np.cov((ring - cen).T))
        nrm = V[:, int(np.argmin(w))]

        gly = _unit(src.ins(self.ins, "N1") - c1)
        out["gly_dot_axis"] = float(np.dot(gly, avg_axis))
        out["gly_dot_bow"] = float(np.dot(gly, b_p))
        out["gly_dot_chord"] = float(np.dot(gly, u))
        out["norm_dot_chord"] = abs(float(np.dot(nrm, u)))
        out["norm_dot_axis"] = abs(float(np.dot(nrm, avg_axis)))
        out["norm_dot_bow"] = abs(float(np.dot(nrm, b_p)))

        ci, cj = centres[self.hel_src], centres[self.hel_dst]
        out["interhelix"] = float(np.linalg.norm(cj - ci))
        out["axis_angle_deg"] = float(np.degrees(np.arccos(np.clip(
            abs(float(np.dot(axes[self.hel_src], axes[self.hel_dst]))), -1, 1))))
        # C3'(src) -> C5'(dst) chord orientation relative to the helix axis
        out["chord_dot_axis"] = float(np.dot(u, avg_axis))

        # ── integrity: the two phosphodiester links this insert bridges, and the
        # base-pair status of the flanking bp on each helix.  A junction whose backbone
        # or flanking pairs have come apart is not reporting an equilibrium pose.
        o3 = (src.ins(self.prev_insert, "O3'") if self.prev_insert is not None
              else src.nt(self.ins.src, "O3'"))
        pi = src.ins(self.ins, "P")
        out["bond_src"] = (float(np.linalg.norm(pi - o3))
                           if o3 is not None and pi is not None else float("nan"))
        o3i = src.ins(self.ins, "O3'")
        pd = (src.ins(self.next_insert, "P") if self.next_insert is not None
              else src.nt(self.ins.dst, "P"))
        out["bond_dst"] = (float(np.linalg.norm(pd - o3i))
                           if o3i is not None and pd is not None else float("nan"))
        for tag, key in (("src", self.ins.src), ("dst", self.ins.dst)):
            opp = "REVERSE" if key[2] == "FORWARD" else "FORWARD"
            a = src.nt(key, "C1'")
            b = src.nt((key[0], key[1], opp), "C1'")
            out[f"bp_{tag}"] = (float(np.linalg.norm(b - a))
                                if a is not None and b is not None else float("nan"))

        best = (1e9, "", 0.0)
        for key in self.neigh_keys:
            rows = [src.nt(key, n) for n in RING_NAMES]
            if any(r is None for r in rows):
                continue
            nb = np.asarray(rows)
            nc = nb.mean(axis=0)
            d = float(np.linalg.norm(nc - cen))
            if d < best[0]:
                w2, V2 = np.linalg.eigh(np.cov((nb - nc).T))
                ang = float(np.degrees(np.arccos(np.clip(
                    abs(float(np.dot(nrm, V2[:, int(np.argmin(w2))]))), -1, 1))))
                best = (d, "%s:%d:%s" % key, ang)
        out["stack_d"], out["stack_key"], out["stack_ang"] = best

        # ── the same bow, but referenced to the CHEMICAL 3'->5' hop direction
        # (src -> dst) instead of the Crossover record's arbitrary half_a -> half_b.
        p_src = src.nt(self.ins.src, "C1'")
        p_dst = src.nt(self.ins.dst, "C1'")
        bow_sd = _unit(np.cross(_unit(p_dst - p_src), avg_axis))
        bow_sd = _unit(bow_sd - float(np.dot(bow_sd, u)) * u)
        out["bow_sd_c1"] = float(np.dot(c1 - p0, bow_sd)) / L
        out["bow_sd_base"] = float(np.dot(cen - p0, bow_sd)) / L

        # ── global junction frame, identical for every crossover of this junction:
        # e_ih  helix(min id) -> helix(max id);  e_ax  avg axis;  e_perp = e_ih x e_ax
        h_lo, h_hi = sorted((self.hel_src, self.hel_dst))
        e_ih = _unit(centres[h_hi] - centres[h_lo])
        e_ax = _unit(avg_axis - float(np.dot(avg_axis, e_ih)) * e_ih)
        e_pp = np.cross(e_ih, e_ax)
        jc = (centres[h_lo] + centres[h_hi]) * 0.5
        for tag, x in (("c1", c1), ("base", cen)):
            d = x - jc
            out[f"g_ih_{tag}"] = float(np.dot(d, e_ih))
            out[f"g_ax_{tag}"] = float(np.dot(d, e_ax))
            out[f"g_pp_{tag}"] = float(np.dot(d, e_pp))

        # ── the SAME hop-referenced axes, but with a FIXED axial reference instead of
        # the chord tangent: e1 = hop (src helix -> dst helix), e2 = helix axis,
        # e3 = e1 x e2.  Origin p0, lengths in units of L.  The chord tangent tilts a
        # lot between the two crossovers of a pair, so this frame is the fair test of
        # whether one set of constants describes both.
        e1 = _unit(centres[self.hel_dst] - centres[self.hel_src])
        e2 = _unit(avg_axis - float(np.dot(avg_axis, e1)) * e1)
        e3 = np.cross(e1, e2)
        for tag, x in (("c1", c1), ("base", cen), ("p1", p1)):
            dd = x - p0
            out[f"h1_{tag}"] = float(np.dot(dd, e1)) / L
            out[f"h2_{tag}"] = float(np.dot(dd, e2)) / L
            out[f"h3_{tag}"] = float(np.dot(dd, e3)) / L
        for nm in ("P", "C3'", "C5'"):
            x = src.ins(self.ins, nm)
            if x is None:
                continue
            dd = x - p0
            out[f"h1_{nm}"] = float(np.dot(dd, e1)) / L
            out[f"h2_{nm}"] = float(np.dot(dd, e2)) / L
            out[f"h3_{nm}"] = float(np.dot(dd, e3)) / L

        # ── clearance to the PARTNER crossover of the reciprocal pair
        if self.partner_rows and hasattr(src, "raw"):
            mine = np.array([v for v in (src.ins(self.ins, n) for n in INS_ATOMS)
                             if v is not None])
            theirs = np.array([src.raw(r) for r in self.partner_rows])
            dmat = np.linalg.norm(mine[:, None, :] - theirs[None, :, :], axis=-1)
            out["partner_min_d"] = float(dmat.min())

        # ── rigid pose of the whole insert nucleotide in the builder's local frame
        names, loc = self.template
        world, lset = [], []
        for i, nm in enumerate(names):
            x = src.ins(self.ins, nm)
            if x is not None:
                world.append(x)
                lset.append(loc[i])
        if len(world) >= 6:
            o, R, rms = kabsch(np.asarray(lset), np.asarray(world))
            B = np.column_stack([u, b_p, a3])
            d = o - p0
            out["pose_t"] = float(np.dot(d, u)) / L
            out["pose_bow"] = float(np.dot(d, b_p)) / L
            out["pose_ax"] = float(np.dot(d, a3)) / L
            out["pose_bow_sd"] = float(np.dot(d, bow_sd)) / L
            out["pose_rmsd"] = rms
            out["pose_M"] = (B.T @ R).ravel().tolist()
        return out


# ── driver ────────────────────────────────────────────────────────────────────
def _fmt(tag, ins, m):
    return (f"  {tag:<10s} {ins.crossover_id[:8]} k{ins.k}  "
            f"t={m['t_c1']:+.3f} bow={m['bow_c1']:+.3f} ax={m['ax_c1']:+.3f}  "
            f"L={m['L']:5.2f}  base(t,bow,ax)=({m['t_base']:+.2f},{m['bow_base']:+.2f},"
            f"{m['ax_base']:+.2f})  stack={m['stack_d']:5.2f}@{m['stack_key']}")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True, type=Path)
    ap.add_argument("--stem", default=None)
    ap.add_argument("--dcd", nargs="+", default=None,
                    help="one or more chronological production DCD pieces")
    ap.add_argument("--stride", type=int, default=20)
    ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--static-only", action="store_true",
                    help="measure built model + package seed, skip the trajectory")
    ap.add_argument("--build", action="store_true",
                    help="also rebuild the design (arc pose + solved pose)")
    args = ap.parse_args(argv)

    job = args.job
    design = load_design(job / "design.json")
    stem = args.stem or json.loads((job / "job.json").read_text())["name_stem"]
    pkg = job / "package" / f"{stem}_namd_solvated"
    pdb = pkg / f"{stem}.pdb"
    pm = build_package_map(design, pdb)
    half_a = {xo.id: xo.half_a.helix_id for xo in design.crossovers}
    for fl in design.forced_ligations:
        half_a[fl.id] = fl.three_prime_helix_id

    probes = [(ins, JunctionProbe(pm, ins, half_a[ins.crossover_id])) for ins in pm.inserts]
    print(f"{len(probes)} insert(s) in {stem}")

    static = {}
    if args.build:
        from backend.core.atomistic import build_atomistic_model
        for tag, kw in (("arc", {"fast_bridges": True}), ("built", {})):
            model = build_atomistic_model(design, **kw)
            s = ModelSource(model)
            static[tag] = {}
            for ins, pr in probes:
                m = pr.measure(s)
                static[tag][ins.crossover_id] = m
                print(_fmt(tag, ins, m))

    X0 = pdb_coords(pdb)
    static["seed"] = {}
    for ins, pr in probes:
        m = pr.measure(PackageSource(pm, X0))
        static["seed"][ins.crossover_id] = m
        print(_fmt("seed", ins, m))

    eq = pkg / "output" / f"{stem}_00_reseed.coor"
    if eq.exists():
        # Moved out of junction_topology when shell re-preparation became the
        # canonical NAMD binary-coordinate owner.  Keep exp46 usable as the shared
        # extractor for later archived trajectories (exp53).
        from backend.core.md_shell_reprep import read_namd_coor
        Xe = read_namd_coor(eq)
        static["reseed"] = {}
        for ins, pr in probes:
            m = pr.measure(PackageSource(pm, Xe, box=None))
            static["reseed"][ins.crossover_id] = m
            print(_fmt("reseed", ins, m))

    if args.static_only:
        return 0

    import MDAnalysis as mda
    dcd = args.dcd or [str(sorted((pkg / "output").glob("*production*.dcd"))[-1])]
    uni = mda.Universe(str(pkg / f"{stem}_hmr.psf"), *dcd)
    n = len(uni.trajectory)
    idx = list(range(args.start, n, args.stride))
    dcd_label = ", ".join(Path(p).name for p in dcd)
    print(f"DCD {dcd_label}: {n} frames, stride {args.stride} -> {len(idx)} samples")

    joiner = FrameJoiner(uni, pm, design)
    print(f"  DNA fragments: {[len(f) for f in joiner.frags]}  "
          f"join plan: {[(fi, len(p)) for fi, p in joiner.plan]}")

    # every designed base pair, for a global melt metric
    bp_pairs = []
    for (hel, bp, d) in pm.nt:
        if d != "FORWARD":
            continue
        a = pm.nt_row((hel, bp, "FORWARD"), "C1'")
        b = pm.nt_row((hel, bp, "REVERSE"), "C1'")
        if a is not None and b is not None:
            bp_pairs.append((a, b))
    bp_pairs = np.asarray(bp_pairs)
    print(f"  {len(bp_pairs)} designed base pairs tracked")

    # A crossover can carry multiple inserts.  Keying only by crossover_id silently
    # interleaves k0/k1 measurements and doubles the apparent time series for 2xT.
    recs = {(ins.crossover_id, ins.k): [] for ins, _ in probes}
    frames, paired, boxes = [], [], []
    for ts in uni.trajectory[args.start::args.stride]:
        box = ts.dimensions[:3].astype(float)
        X = joiner.positions(box)
        frames.append(int(ts.frame))
        boxes.append([float(v) for v in box])
        dd = np.linalg.norm(X[bp_pairs[:, 0]] - X[bp_pairs[:, 1]], axis=1)
        paired.append(float(np.mean((dd > 8.0) & (dd < 13.0))))
        s = PackageSource(pm, X)
        for ins, pr in probes:
            recs[(ins.crossover_id, ins.k)].append(pr.measure(s))

    out = {"stem": stem, "job": str(job), "dcd": dcd, "n_frames": n,
           "stride": args.stride, "start": args.start, "frames": frames,
           "paired_fraction": paired, "boxes": boxes, "n_bp": len(bp_pairs),
           "static": static,
           "inserts": [{"crossover_id": ins.crossover_id, "k": ins.k, "base": ins.base,
                        "src": list(ins.src), "dst": list(ins.dst),
                        "segid": ins.segid, "resid": ins.resid,
                        "samples": recs[(ins.crossover_id, ins.k)]} for ins, _ in probes]}
    path = args.out or (Path(__file__).parent / f"{stem}_xb_traj.json")
    path.write_text(json.dumps(out))
    print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
