"""Atom/bond/ring evidence for isolated local-predictor candidates."""

from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree
from backend.core.ring_piercing import ring_names_for, segment_pierces_ring
from backend.core.exp_local import psf_block


def piercings(x, bonds, rings):
    """Exact ring fan tests; conservative variable-radius broad phase for long bonds."""
    if not rings:
        return []
    centers = np.array([x[r].mean(0) for _, _, r in rings])
    radius = max(
        np.linalg.norm(x[r] - c, axis=1).max() for (_, _, r), c in zip(rings, centers)
    )
    mid = x[bonds].mean(1)
    half = np.linalg.norm(x[bonds[:, 0]] - x[bonds[:, 1]], axis=1) / 2
    near = cKDTree(centers).query_ball_point(mid, half + radius + 1e-6)
    candidates = [
        (int(i), int(j))
        for i, js in enumerate(near)
        for j in js
        if not set(bonds[i]).intersection(rings[j][2])
    ]
    hits = []
    # Batch the same Moller-Trumbore fan as the independent production oracle.
    for size in sorted({len(r) for _, _, r in rings}):
        eligible = [(i, j) for i, j in candidates if len(rings[j][2]) == size]
        for start in range(0, len(eligible), 4096):
            pairs = eligible[start : start + 4096]
            if not pairs:
                continue
            bi = np.array([p[0] for p in pairs])
            rj = np.array([p[1] for p in pairs])
            polygon = x[np.array([rings[j][2] for j in rj])]
            v0 = polygon.mean(1)[:, None, :]
            e1 = polygon - v0
            e2 = np.roll(polygon, -1, axis=1) - v0
            p0 = x[bonds[bi, 0]][:, None, :]
            d = (x[bonds[bi, 1]] - x[bonds[bi, 0]])[:, None, :]
            h = np.cross(d, e2)
            a = np.einsum("nki,nki->nk", e1, h)
            ok = np.abs(a) > 1e-14
            f = np.zeros_like(a)
            f[ok] = 1 / a[ok]
            s = p0 - v0
            u = f * np.einsum("nki,nki->nk", s, h)
            q = np.cross(s, e1)
            v = f * np.einsum("nki,nki->nk", d, q)
            t = f * np.einsum("nki,nki->nk", e2, q)
            ok &= (
                (u >= 0)
                & (u <= 1)
                & (v >= 0)
                & (u + v <= 1)
                & (t > 1e-9)
                & (t < 1 - 1e-9)
            )
            for k in np.flatnonzero(ok.any(1)):
                i, j = pairs[k]
                bond = bonds[i].tolist()
                res, kind, serials = rings[j]
                # Verify every reported positive with the existing scalar oracle.
                assert segment_pierces_ring(x[bond[0]], x[bond[1]], x[serials])[0]
                hits.append(dict(bond=bond, ring=serials, residue=res, kind=kind))
    return hits


def angle_audit(psf, residue_index, native, candidate):
    lines = psf.splitlines()
    start = next(i for i, line in enumerate(lines) if "!NATOM" in line)
    count = int(lines[start].split()[0])
    types = [line.split()[5] for line in lines[start + 1 : start + 1 + count]]
    angle = psf_block(psf, "!NTHETA", 3)
    r = residue_index[angle]
    angle = angle[(r[:, 0] != r[:, 1]) | (r[:, 1] != r[:, 2])]
    parameters = {}
    active = False
    for line in (
        Path("backend/data/forcefield/par_all36_na.prm").read_text().splitlines()
    ):
        fields = line.split("!")[0].split()
        if fields == ["ANGLES"]:
            active = True
            continue
        if fields == ["DIHEDRALS"]:
            break
        if active and len(fields) >= 5:
            parameters[tuple(fields[:3])] = float(fields[4])
            parameters[tuple(reversed(fields[:3]))] = float(fields[4])
    target = np.array([parameters[tuple(types[i] for i in row)] for row in angle])
    result = {}
    for label, x in [("native", native), ("local", candidate)]:
        a = x[angle[:, 0]] - x[angle[:, 1]]
        b = x[angle[:, 2]] - x[angle[:, 1]]
        cosine = np.einsum("ij,ij->i", a, b) / (
            np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)
        ).clip(1e-10)
        values = np.degrees(np.arccos(np.clip(cosine, -1, 1)))
        error = np.abs(values - target)
        result[label] = dict(
            count=len(values),
            median_absolute_error_deg=float(np.median(error)),
            max_absolute_error_deg=float(error.max()),
            errors_over_30_deg=int((error > 30).sum()),
        )
    return result


def audit(root, prediction_file="local.npz", suffix=""):
    summaries = {}
    for name in ["6hb_0xT", "24hb_0xT", "platform"]:
        out = root / name
        native = np.load(out / "native.npz")
        local = np.load(out / prediction_file)
        ri = native["residue_index"]
        names = native["names"]
        bonds = native["bonds"]
        x = native["positions_nm"]
        y = local["positions_nm"]
        keys = json.loads(str(native["keys_json"]))
        byres = [{} for _ in keys]
        for i, (r, n) in enumerate(zip(ri, names)):
            byres[r][str(n)] = i
        rings = [
            (i, kind, [lookup[n] for n in ns])
            for i, lookup in enumerate(byres)
            for kind, ns in ring_names_for(lookup)
        ]
        heavy = np.char.startswith(names.astype(str), "H") == 0
        hb = bonds[heavy[bonds].all(1)]
        scans = {
            key: piercings(z, hb, rings) for key, z in [("native", x), ("local", y)]
        }
        excluded = {tuple(sorted(p)) for p in bonds.tolist()}
        adjacency = [set() for _ in names]
        for a, b in bonds:
            adjacency[a].add(b)
            adjacency[b].add(a)
        for neighbors in adjacency:
            for a in neighbors:
                for b in neighbors:
                    if a != b:
                        excluded.add(tuple(sorted((a, b))))
        heavyi = np.flatnonzero(heavy)
        clashes = {}
        for key, z in [("native", x), ("local", y)]:
            pairs = heavyi[cKDTree(z[heavyi]).query_pairs(0.18, output_type="ndarray")]
            clashes[key] = [
                p.tolist()
                for p in pairs
                if ri[p[0]] != ri[p[1]] and tuple(sorted(p)) not in excluded
            ]
        displacement = np.zeros(len(keys))
        np.maximum.at(displacement, ri, np.linalg.norm(y - x, axis=1))
        rows = []
        for a, b in bonds:
            if ri[a] == ri[b]:
                continue
            r, s = int(ri[a]), int(ri[b])
            involved = {r, s}
            hits = {
                key: [
                    h
                    for h in scans[key]
                    if involved.intersection(
                        [int(ri[h["bond"][0]]), int(ri[h["bond"][1]]), h["residue"]]
                    )
                ]
                for key in scans
            }
            counts = {
                key: sum(
                    bool(involved.intersection([int(ri[i]), int(ri[j])]))
                    for i, j in pairs
                )
                for key, pairs in clashes.items()
            }
            row = dict(
                atom_indices=[int(a), int(b)],
                atom_names=[str(names[a]), str(names[b])],
                nt_keys=[keys[r], keys[s]],
                native_bond_nm=float(np.linalg.norm(x[a] - x[b])),
                candidate_bond_nm=float(np.linalg.norm(y[a] - y[b])),
                max_atom_displacement_nm=float(max(displacement[r], displacement[s])),
                cross_helix=keys[r][0] != keys[s][0],
                clashes_under_018_nm=counts,
                piercings={key: len(v) for key, v in hits.items()},
            )
            rows.append(row)
        # Inspectable neighborhoods: largest bond error, a piercing, a clash,
        # and an ordinary junction. Coordinates share the input frame.
        chosen = sorted(
            rows, key=lambda r: abs(r["candidate_bond_nm"] - 0.16), reverse=True
        )[:3]
        chosen += [r for r in rows if r["piercings"]["local"]][:2]
        chosen += [r for r in rows if r["clashes_under_018_nm"]["local"]][:2]
        chosen += [min(rows, key=lambda r: abs(r["candidate_bond_nm"] - 0.16))]
        examples = []
        for row in chosen:
            a, b = row["atom_indices"]
            focus = (x[a] + x[b]) / 2
            indices = np.flatnonzero(
                heavy
                & (
                    (np.linalg.norm(x - focus, axis=1) < 0.9)
                    | (np.linalg.norm(y - (y[a] + y[b]) / 2, axis=1) < 0.9)
                )
            )
            indices = np.unique(np.r_[indices, [a, b]])
            keep = set(indices.tolist())
            localb = [p.tolist() for p in hb if set(p).issubset(keep)]
            examples.append(
                dict(
                    junction=row,
                    indices=indices.tolist(),
                    names=names[indices].tolist(),
                    native=x[indices].tolist(),
                    candidate=y[indices].tolist(),
                    bonds=localb,
                    clash_pairs={
                        key: [p for p in pairs if set(p).issubset(keep)]
                        for key, pairs in clashes.items()
                    },
                    ring_hits={
                        key: [
                            h for h in scan if set(h["bond"] + h["ring"]).issubset(keep)
                        ]
                        for key, scan in scans.items()
                    },
                )
            )
        psf_path = (
            out / "native.psf"
            if name == "platform"
            else Path(".development-artifacts/exp_atoms_20261007") / f"{name}.psf"
        )
        angles = angle_audit(psf_path.read_text(), ri, x, y)
        result = dict(
            angles=angles,
            junctions=rows,
            ring_piercings=scans,
            clashes_under_018_nm=clashes,
            examples=examples,
        )
        (out / f"geometry_audit{suffix}.json").write_text(json.dumps(result))
        summary = dict(
            angles=angles,
            ring_piercings={k: len(v) for k, v in scans.items()},
            clashes_under_018_nm={k: len(v) for k, v in clashes.items()},
            inter_residue_links=len(rows),
            inter_links_outside_014_018_nm={
                k: sum(not 0.14 <= r[field] <= 0.18 for r in rows)
                for k, field in [
                    ("native", "native_bond_nm"),
                    ("local", "candidate_bond_nm"),
                ]
            },
        )
        summaries[name] = summary
        (root / f"geometry_summary{suffix}.json").write_text(
            json.dumps(summaries, indent=2)
        )
        print(name, json.dumps(summary), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit(args.output)
