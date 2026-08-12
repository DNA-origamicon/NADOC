#!/usr/bin/env python3
"""Search direction-local poses for reciprocal 2xT inserts in an isolated audit.

The search works directly in atom coordinates so thousands of objective evaluations do
not rebuild the design.  Every accepted result is subsequently rebuilt and measured by
the Molecular Placement Audit before it can be used as a proposal.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.optimize import differential_evolution, minimize
from scipy.spatial.transform import Rotation

from backend.core.atomistic import build_atomistic_model
from backend.core.atomistic_validation import (
    BACKBONE_STRETCH_NM,
    CLASH_NM,
    COVALENT_MAX_NM,
    _bond_class,
)
from backend.core.models import Design
from backend.core.molecular_placement_audit import _midpoint_constraint_planes
from backend.core.ring_piercing import _scan, residue_key, ring_names_for


PLANE_MARGIN_NM = 0.002
CLASH_MARGIN_NM = 0.002


def positions(model) -> np.ndarray:
    return np.asarray([[a.x, a.y, a.z] for a in model.atoms], dtype=float)


def pair_data(design: Design, *, fast_bridges: bool = True):
    records: list[dict] = []
    model = build_atomistic_model(
        design,
        fast_bridges=fast_bridges,
        measured_positioning=True,
        _extra_base_placement_sink=records,
        _two_base_default=False,
    )
    planes = _midpoint_constraint_planes(records)
    by_xid: dict[str, list[dict]] = {}
    for row in records:
        by_xid.setdefault(row["crossover_id"], []).append(row)
    frames = {}
    for xid, rows in by_xid.items():
        chain = np.mean([np.asarray(r["source_chain_tangent"]) for r in rows], axis=0)
        chain /= np.linalg.norm(chain)
        bow = np.mean([np.asarray(r["bow"]) for r in rows], axis=0)
        bow -= chain * float(np.dot(bow, chain))
        bow /= np.linalg.norm(bow)
        axial = np.cross(chain, bow)
        axial /= np.linalg.norm(axial)
        frames[xid] = np.column_stack([bow, axial, chain])
    return model, positions(model), planes, by_xid, frames


class PairProblem:
    """Twelve variables: a direction-local rigid delta for base k=0 and k=1.

    The same two deltas are mapped through both reciprocal strands' own chemical
    3'->5' frames.  This is exact directional symmetry, not a world-space mirror.
    """

    def __init__(self, model, base_pos, plane, frames):
        self.model = model
        self.base = base_pos
        self.plane = plane
        self.xids = tuple(plane["crossover_ids"])
        self.enforce_plane = bool(plane.get("enforce_plane", True))
        self.frames = frames
        self.groups = {}
        moved = []
        for xid in self.xids:
            for k in (0, 1):
                serials = np.asarray([
                    i for i, atom in enumerate(model.atoms)
                    if atom.crossover_id == xid and atom.extra_base_k == k
                ], dtype=int)
                if not len(serials):
                    raise ValueError(f"missing atoms for {xid} base {k}")
                self.groups[(xid, k)] = serials
                moved.extend(serials.tolist())
        self.moved = np.asarray(sorted(moved), dtype=int)
        self.moved_set = set(self.moved.tolist())
        self.pivots = {
            key: self.base[serials].mean(axis=0)
            for key, serials in self.groups.items()
        }

        origin = np.asarray(plane["origin"], dtype=float)
        normal = np.asarray(plane["normal"], dtype=float)
        normal /= np.linalg.norm(normal)
        self.origin = origin
        self.normal = normal
        self.side = {}
        if self.enforce_plane:
            for xid in self.xids:
                serials = np.concatenate([self.groups[(xid, 0)], self.groups[(xid, 1)]])
                signed = float(np.mean((self.base[serials] - origin) @ normal))
                self.side[xid] = 1.0 if signed >= 0 else -1.0

        bonded = {tuple(sorted(b)) for b in model.bonds}
        self.bonds = []
        for i, j in model.bonds:
            if i not in self.moved_set and j not in self.moved_set:
                continue
            cls = _bond_class(model.atoms[i], model.atoms[j])
            limit = BACKBONE_STRETCH_NM if cls in {"backbone", "bridge"} else COVALENT_MAX_NM
            self.bonds.append((i, j, limit, cls))

        lo = self.base[self.moved].min(axis=0) - 1.3
        hi = self.base[self.moved].max(axis=0) + 1.3
        near = np.where(((self.base >= lo) & (self.base <= hi)).all(axis=1))[0]
        pairs = set()
        for i in self.moved:
            for j in near:
                i, j = int(i), int(j)
                if i == j:
                    continue
                a, b = sorted((i, j))
                if (a, b) in bonded:
                    continue
                xa, xb = model.atoms[a].crossover_id, model.atoms[b].crossover_id
                if xa is not None and xa == xb:
                    continue
                pairs.add((a, b))
        self.clash_pairs = np.asarray(sorted(pairs), dtype=int)

        residues: dict[tuple, dict[str, int]] = {}
        for i in near:
            atom = model.atoms[int(i)]
            if atom.name.startswith("H"):
                continue
            residues.setdefault(residue_key(atom), {})[atom.name] = int(i)
        rings = []
        for key, names in residues.items():
            for kind, ring_names in ring_names_for(names):
                rings.append((key, kind, [names[n] for n in ring_names]))
        near_set = set(map(int, near))
        ring_serials = {s for _, _, serials in rings for s in serials}
        scan_bonds = [
            (i, j) for i, j in model.bonds
            if i in near_set and j in near_set
            and not model.atoms[i].name.startswith("H")
            and not model.atoms[j].name.startswith("H")
        ]
        # Retain rings and bonds that can participate in a moved-residue defect.
        self.rings = rings
        self.scan_bonds = scan_bonds
        self.moved_ring_serials = ring_serials & self.moved_set

    def apply(self, x: np.ndarray) -> np.ndarray:
        q = self.base.copy()
        for xid in self.xids:
            frame = self.frames[xid]
            for k in (0, 1):
                p = x[k * 6:(k + 1) * 6]
                translation = frame @ p[:3]
                rotation = frame @ Rotation.from_rotvec(np.radians(p[3:])).as_matrix() @ frame.T
                serials = self.groups[(xid, k)]
                pivot = self.pivots[(xid, k)]
                q[serials] = (self.base[serials] - pivot) @ rotation.T + pivot + translation
        return q

    def piercing_hits(self, q):
        raw = _scan(q, self.scan_bonds, self.rings, max_report=100)
        return [
            hit for hit in raw
            if set(hit["bond_serials"]) & self.moved_set
            or set(hit["ring_serials"]) & self.moved_set
        ]

    def metrics(self, x, *, include_piercing=True):
        q = self.apply(np.asarray(x, dtype=float))
        plane_deficits = []
        if self.enforce_plane:
            for xid in self.xids:
                serials = np.concatenate([self.groups[(xid, 0)], self.groups[(xid, 1)]])
                signed = self.side[xid] * ((q[serials] - self.origin) @ self.normal)
                plane_deficits.extend(np.maximum(0.0, PLANE_MARGIN_NM - signed))
        clash_d = np.linalg.norm(
            q[self.clash_pairs[:, 0]] - q[self.clash_pairs[:, 1]], axis=1
        )
        clash_deficits = np.maximum(0.0, CLASH_NM + CLASH_MARGIN_NM - clash_d)
        bond_lengths = np.asarray([np.linalg.norm(q[i] - q[j]) for i, j, _, _ in self.bonds])
        bond_limits = np.asarray([limit for _, _, limit, _ in self.bonds])
        bond_deficits = np.maximum(0.0, bond_lengths - (bond_limits - 0.002))
        piercings = self.piercing_hits(q) if include_piercing else []
        return {
            "q": q,
            "plane": np.asarray(plane_deficits),
            "clash": clash_deficits,
            "bond": bond_deficits,
            "piercings": piercings,
            "max_bond_nm": float(bond_lengths.max(initial=0.0)),
        }

    def objective(self, x, *, with_piercing=True):
        m = self.metrics(x, include_piercing=with_piercing)
        defect = (
            5.0e6 * float(np.dot(m["plane"], m["plane"]))
            + 5.0e6 * float(np.dot(m["clash"], m["clash"]))
            + 5.0e6 * float(np.dot(m["bond"], m["bond"]))
        )
        if with_piercing:
            defect += 1000.0 * len(m["piercings"])
        x = np.asarray(x)
        regularizer = 0.02 * float(np.dot(x[:3], x[:3]) + np.dot(x[6:9], x[6:9]))
        regularizer += 2e-6 * float(np.dot(x[3:6], x[3:6]) + np.dot(x[9:12], x[9:12]))
        return defect + regularizer

    @staticmethod
    def summary(m):
        return {
            "plane_crossings": int(np.count_nonzero(m["plane"] > 0)),
            "clashes": int(np.count_nonzero(m["clash"] > CLASH_MARGIN_NM - 1e-9)),
            "clash_margin_failures": int(np.count_nonzero(m["clash"] > 1e-9)),
            "overstretched": int(np.count_nonzero(m["bond"] > 0.002 - 1e-9)),
            "bond_margin_failures": int(np.count_nonzero(m["bond"] > 1e-9)),
            "piercings": len(m["piercings"]),
            "max_bond_nm": round(m["max_bond_nm"], 6),
        }


def solve(problem: PairProblem, seed: int, restarts: int, max_rotation_deg: float):
    bounds = [(-0.55, 0.55)] * 3 + [(-max_rotation_deg, max_rotation_deg)] * 3
    bounds *= 2
    rng = np.random.default_rng(seed)
    candidates = [np.zeros(12)]
    # Global exploration once; polishing without discontinuous piercing finds the
    # feasible corridors, and exact piercing decides among them.
    de = differential_evolution(
        lambda x: problem.objective(x, with_piercing=False),
        bounds,
        seed=seed,
        popsize=7,
        maxiter=120,
        tol=1e-7,
        polish=False,
        updating="immediate",
        workers=1,
    )
    candidates.append(de.x)
    for _ in range(restarts):
        candidates.append(de.x + rng.normal(0.0, [0.08] * 3 + [8.0] * 3 + [0.08] * 3 + [8.0] * 3))
    best = None
    best_key = None
    for start in candidates:
        start = np.clip(start, [a for a, _ in bounds], [b for _, b in bounds])
        res = minimize(
            lambda x: problem.objective(x, with_piercing=False),
            start,
            method="Powell",
            bounds=bounds,
            options={"maxiter": 1800, "xtol": 2e-6, "ftol": 1e-10},
        )
        m = problem.metrics(res.x)
        s = problem.summary(m)
        key = (
            s["plane_crossings"] + s["clashes"] + s["overstretched"] + s["piercings"],
            s["piercings"],
            problem.objective(res.x, with_piercing=False),
        )
        if best_key is None or key < best_key:
            best_key = key
            best = (res.x, s)
        if key[0] == 0:
            break
    return best


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("design", type=Path)
    parser.add_argument("--seed", type=int, default=731)
    parser.add_argument("--restarts", type=int, default=10)
    parser.add_argument("--pair", type=int, action="append")
    parser.add_argument("--isolated", action="store_true")
    parser.add_argument("--max-rotation-deg", type=float, default=45.0)
    args = parser.parse_args()

    design = Design.from_json(args.design.read_text())
    model, base, planes, _, frames = pair_data(design)
    selected = set(args.pair if args.pair is not None else range(len(planes)))
    result = {}
    for index, plane in enumerate(planes):
        if index not in selected:
            continue
        problem = PairProblem(model, base, plane, frames)
        x, summary = solve(
            problem, args.seed + index * 1009, args.restarts, args.max_rotation_deg
        )
        key = "|".join(problem.xids)
        result[key] = {"params": np.asarray(x).round(10).tolist(), "metrics": summary}
        print(f"PAIR {index} {key} {json.dumps(summary, sort_keys=True)}", flush=True)
    if args.isolated:
        paired = {xid for plane in planes for xid in plane["crossover_ids"]}
        all_two = {
            atom.crossover_id for atom in model.atoms
            if atom.crossover_id and atom.extra_base_k in (0, 1)
        }
        for offset, xid in enumerate(sorted(all_two - paired)):
            fake_plane = {
                "crossover_ids": [xid],
                "origin": [0.0, 0.0, 0.0],
                "normal": [0.0, 0.0, 1.0],
                "enforce_plane": False,
            }
            problem = PairProblem(model, base, fake_plane, frames)
            x, summary = solve(
                problem, args.seed + 50000 + offset * 1009, args.restarts,
                args.max_rotation_deg,
            )
            result[xid] = {"params": np.asarray(x).round(10).tolist(), "metrics": summary}
            print(f"ISOLATED {xid} {json.dumps(summary, sort_keys=True)}", flush=True)
    print("RESULT=" + json.dumps(result, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
