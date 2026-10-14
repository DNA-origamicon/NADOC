"""Bounded, read-only screen of one existing exp59 unwelded production job.

Usage: .venv/bin/python experiments/cpd_isomer_formation/run.py --job JOB_ID --out NEW_DIRECTORY
No fitting, bond formation, MD, external services, or calibrated photorates.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from experiments.cpd_isomer_formation.geometry import NAMES, catalog, eligible, features, local_image, planar_reactant_audit


def pin(path):
    p = Path(path)
    return {"path": str(p.resolve()), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def summarize_grids(f, w, plan):
    """Keep cached replays and trajectory extraction on the same scoring path."""
    grids = []
    for distance in plan["distance_cutoffs_ang"]:
        for angle in plan["twist_cutoffs_deg"]:
            for margin in plan["face_margin_cutoffs"]:
                mask = eligible(f, distance, angle, margin)
                multiplicity = mask.sum(axis=-1)
                unique = mask & (multiplicity[..., None] == 1)
                grids.append({
                    "distance_ang": distance, "twist_deg": angle, "face_margin": margin,
                    "compatible_fraction_by_pair_isomer": np.average(mask, axis=0, weights=w).tolist(),
                    "unique_fraction_by_pair_isomer": np.average(unique, axis=0, weights=w).tolist(),
                    "ambiguous_fraction_by_pair": np.average(multiplicity > 1, axis=0, weights=w).tolist(),
                    "any_compatible_fraction_by_pair": np.average(multiplicity > 0, axis=0, weights=w).tolist(),
                    "compatible_sample_counts_by_isomer": mask.sum(axis=(0, 1)).tolist(),
                })
    return grids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--frames-per-file", type=int, default=200)
    parser.add_argument("--scope", choices=("designed", "all-tt"), default="all-tt")
    parser.add_argument("--diagnostic-only", action="store_true",
                        help="retain unqualified diagnostic geometry despite a failed mapping preflight; never a formation ranking")
    args = parser.parse_args()
    if not 2 <= args.frames_per_file <= 500:
        parser.error("frames-per-file must be 2..500")
    import MDAnalysis as mda
    from backend.core.kimmdy_analysis import (
        _valid_box, _scan_all_tt_candidates, _designed_candidate_map,
        topology_thymine_sites, THYMINE_RESNAMES,
    )
    from backend.core.models import Design

    started = time.monotonic()
    inventory_path = ROOT / "experiments/exp59_kimmdy_extra_base_matrix/inventory.json"
    inventory = json.loads(inventory_path.read_text())
    job = next(j for j in inventory["selected_analysis_jobs"] if j["job_id"] == args.job)
    summary_path = inventory_path.parent / "results/jobs" / args.job / "summary.json.gz"
    previous = json.loads(gzip.decompress(summary_path.read_bytes()))
    pairs = previous["pairs"]
    if not pairs or not all(p["intended_weld"] for p in pairs):
        raise ValueError("Expected a nonempty designed-weld pair cohort")
    products = catalog()
    approach_audit = planar_reactant_audit(products)
    if not approach_audit["passed"] and not args.diagnostic_only:
        raise ValueError("Suprafacial reactant mapping preflight failed. Anti zero counts are not rarity evidence. See the 2026-10-10 mapping audit; only --diagnostic-only permits unqualified geometry extraction.")
    args.out.mkdir(parents=True, exist_ok=False)
    plan = {
        "created_at": datetime.now(timezone.utc).isoformat(), "job_id": args.job,
        "lineage_id": job["lineage_id"], "name_stem": job["name_stem"],
        "scope": "Experimental geometry occupancy; no photorate or yield calibration",
        "pair_scope": args.scope,
        "reactant_mapping_audit": approach_audit,
        "formation_ranking_qualified": False,
        "diagnostic_only": args.diagnostic_only,
        "candidate_screen": "For all-tt, union of all intra/interstrand TT pairs within 6 A midpoint distance in sampled frames, plus every intended pair; fail rather than truncate at 20000 candidates.",
        "inventory": pin(inventory_path), "prior_summary": pin(summary_path),
        "scripts": [pin(Path(__file__)), pin(Path(__file__).with_name("geometry.py"))],
        "topology": pin(job["topology"]), "design": pin(job["design_path"]),
        "products": products, "frames_per_file_cap": args.frames_per_file,
        "distance_cutoffs_ang": [3.6, 4.0, 4.5], "twist_cutoffs_deg": [30.0, 45.0, 60.0],
        "face_margin_cutoffs": [0.1, 0.25, 0.5], "minimum_forming_distance_ang": 2.5,
        "classification_assumption": "Suprafacial addition with retained substituent ordering; no excited-state rearrangement",
        "atom_aliases": {"C7": "C7 or CHARMM thymine C5M; exactly one required"},
        "threshold_authority": "Exploratory sensitivity grid, not a fitted or literature-validated all-isomer reaction window",
        "source_qualification": "Unrestrained production selection inherited from exp59; no pairing/fraying gate imposed",
        "pair_order": "Canonical (segment ID, residue number) order in all-tt; saved summary order in designed mode. I/II labels depend on this order.",
    }
    (args.out / "plan.json").write_text(json.dumps(plan, indent=2)+"\n")
    raw, weights, locators, file_records = [], [], [], []
    try:
        if args.scope == "all-tt":
            design = Design.model_validate_json(Path(job["design_path"]).read_text())
            union = {}
            screens = []
            for trajectory in job["production_dcds"]:
                u = mda.Universe(job["topology"], trajectory)
                sites = topology_thymine_sites(u, design)
                designed, excluded = _designed_candidate_map(design, sites)
                if excluded:
                    raise ValueError("Unresolved intended sites in topology")
                n = len(u.trajectory)
                selected = np.unique(np.linspace(0, n-1, min(n, args.frames_per_file), dtype=int)).tolist()
                candidates, screen = _scan_all_tt_candidates(
                    u, sites, selected, cutoff_ang=6.0, pair_scope="all",
                    always_include=designed, max_candidates=20000, progress=None,
                )
                # The scanner records truncation; reject any incomplete candidate set.
                if screen.get("truncated") or screen.get("n_dropped", 0):
                    raise ValueError("Candidate screen truncated")
                union.update({p["id"]:p for p in candidates})
                screens.append(screen)
                u.trajectory.close()
                print(f"{args.job}: screened {len(selected)} frames, {len(candidates)} pairs", flush=True)
            if len(union) >= 20000:
                raise ValueError("Candidate limit reached")
            pairs = [union[k] for k in sorted(union)]
            plan["screen_audits"] = screens
            plan["selected_pair_count"] = len(pairs)
            (args.out / "plan.json").write_text(json.dumps(plan, indent=2)+"\n")
        for file_index, trajectory in enumerate(job["production_dcds"]):
            u = mda.Universe(job["topology"], trajectory)
            indices = []
            for pair in pairs:
                pair_indices = []
                for side in ("site_a", "site_b"):
                    site = pair[side]
                    residue = u.residues[site["resindex"]]
                    if (residue.segid != site["segid"] or int(residue.resid) != site["resid"]
                            or residue.resname not in THYMINE_RESNAMES):
                        raise ValueError(f"Nonunique/non-thymine site: {site['site_id']}")
                    for name in NAMES:
                        atoms = residue.atoms.select_atoms("name C7 C5M" if name == "C7" else f"name {name}")
                        if len(atoms) != 1:
                            raise ValueError(f"Missing/ambiguous {site['site_id']}:{name}")
                        pair_indices.append(int(atoms[0].index))
                    for name, serial_key in (("C5", "c5_serial"), ("C6", "c6_serial")):
                        if int(residue.atoms.select_atoms(f"name {name}")[0].index) != site[serial_key]:
                            raise ValueError("Prior candidate atom order does not match topology")
                indices.append(pair_indices)
            indices = np.asarray(indices)
            bond_set = {tuple(sorted(map(int, b))) for b in u.bonds.indices}
            for row in indices:
                if any(tuple(sorted((int(row[a]), int(row[b])))) in bond_set
                       for a in (1, 2) for b in (7, 8)):
                    raise ValueError("Already formed CPD encountered; not a reactant ensemble")
            n = len(u.trajectory)
            selected = np.unique(np.linspace(0, n-1, min(n, args.frames_per_file), dtype=int))
            dt = float(u.trajectory.dt)
            if not np.isfinite(dt) or dt <= 0:
                raise ValueError("Missing positive sampling interval")
            path = Path(trajectory)
            stat = path.stat()
            file_records.append({"path": str(path.resolve()), "bytes": stat.st_size,
                                 "mtime_ns": stat.st_mtime_ns, "total_frames": n,
                                 "dt_ps": dt, "sampled_frames": len(selected),
                                 "identity_scope": "Size/mtime plus exact cached local coordinates; no full multi-GB DCD hash"})
            for local_frame in selected:
                ts = u.trajectory[int(local_frame)]
                box = _valid_box(ts.dimensions)
                if box is None:
                    raise ValueError("Invalid/missing periodic cell")
                raw.append(local_image(u.atoms.positions[indices], box))
                # Equal stratified samples estimate the time distribution within each file.
                weights.append(n*dt/len(selected))
                locators.append([file_index, int(local_frame), float(ts.time)])
            if path.stat().st_size != stat.st_size or path.stat().st_mtime_ns != stat.st_mtime_ns:
                raise ValueError("Trajectory changed during analysis")
            u.trajectory.close()
            print(f"{args.job}: {file_index+1}/{len(job['production_dcds'])} files, {len(raw)} samples", flush=True)
        x = np.asarray(raw)
        w = np.asarray(weights)
        if not np.all(np.isfinite(x)):
            raise ValueError("Nonfinite sampled coordinates")
        f = features(x, products)
        grids = summarize_grids(f, w, plan)
        series = args.out / "geometry.npz"
        np.savez_compressed(series, coordinates_ang=x, time_weights_ps=w,
                            locators=np.asarray(locators), atom_indices=indices,
                            **f)
        def pair_class(p):
            if p["intended_weld"]:
                return "intended_weld"
            n_extra = sum((p[s].get("design_identity") or {}).get("kind") == "crossover_insert"
                          for s in ("site_a", "site_b"))
            location = ("intrastrand_adjacent" if p["same_strand"] and p["sequence_separation"] == 1
                        else "intrastrand_nonadjacent" if p["same_strand"] else "interstrand")
            return f"{location}:" + ("native_native" if n_extra == 0 else "extra_native" if n_extra == 1 else "extra_extra")

        result = {
            "schema": "nadoc.cpd-isomer-formation-pilot.v1", "status": "analysis_complete",
            "formation_ranking_qualified": False,
            "reactant_mapping_passed": approach_audit["passed"],
            "plan": pin(args.out / "plan.json"), "cached_geometry": pin(series),
            "trajectory_files": file_records, "pair_ids": [p["id"] for p in pairs],
            "pairs": [{**{k:p[k] for k in ("id", "site_a", "site_b", "intended_weld_identity")},
                       "class":pair_class(p)} for p in pairs],
            "isomer_ids": [p["id"] for p in products], "sample_count": len(raw),
            "represented_time_ns": float(w.sum()/1000), "grids": grids,
            "elapsed_seconds": time.monotonic()-started,
            "limits": ["One production job; lineage-level uncertainty not established.",
                       "Correlated snapshots and sparse sampling; no event count or encounter lifetime inferred.",
                       "Approach-face geometry assumes suprafacial addition without electronic rearrangement.",
                       "Thresholds are exploratory; compatible channels are not calibrated reaction probabilities.",
                       "Multiple compatible channels remain ambiguous; their fractions must not be summed as exclusive outcomes.",
                       "No absorption, wavelength, quantum yield, competition/depletion, or UV damage model.",
                       "No minimum-population detection bound inferred from zero observations."],
        }
        (args.out / "summary.json").write_text(json.dumps(result, indent=2)+"\n")
        primary = next(g for g in grids if (g['distance_ang'],g['twist_deg'],g['face_margin']) == (4.0,45.0,0.25))
        print(json.dumps({"job":args.job,"samples":len(raw),"pairs":len(pairs),
                          "primary_counts":dict(zip(result['isomer_ids'],primary['compatible_sample_counts_by_isomer'])),
                          "elapsed_seconds":result['elapsed_seconds']},indent=2))
    except Exception as exc:
        (args.out / "failure.json").write_text(json.dumps({"error":repr(exc),"elapsed_seconds":time.monotonic()-started},indent=2)+"\n")
        raise


if __name__ == "__main__":
    main()
