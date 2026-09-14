#!/usr/bin/env python3
"""Inventory and extra-base-only KIMMDY analysis for the stored NAMD matrix."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
RESULTS = HERE / "results"
JOBS_OUT = RESULTS / "jobs"
INVENTORY = HERE / "inventory.json"
CROSSOVER_CSV = HERE / "crossover_summary.csv"
LINEAGE_CSV = HERE / "lineage_summary.csv"
REPORT = HERE / "REPORT.md"
CROSSOVER_UNGATED_CSV = HERE / "crossover_summary_ungated.csv"
LINEAGE_UNGATED_CSV = HERE / "lineage_summary_ungated.csv"
REPORT_UNGATED = HERE / "REPORT_UNGATED.md"
SCAN_ROOTS = (ROOT, Path("/media/jojo/Archive"))


def _find(*args: str) -> list[Path]:
    cmd = [
        "find", *map(str, SCAN_ROOTS),
        "(", "-type", "d", "(",
        "-name", ".git", "-o", "-name", ".venv", "-o", "-name", "node_modules",
        "-o", "-name", "site-packages", "-o", "-name", "cpdenv", "-o", "-name", "cpdEnv",
        "-o", "-name", "lost+found",
        ")", "-prune", ")", "-o", *args,
    ]
    run = subprocess.run(cmd, text=True, capture_output=True, check=True)
    return [Path(line) for line in run.stdout.splitlines() if line]


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _location(path: Path) -> str:
    return "archive" if str(path).startswith("/media/jojo/Archive/") else "local"


def _dcd_metadata(path: Path) -> dict[str, Any]:
    row: dict[str, Any] = {"path": str(path.resolve()), "bytes": path.stat().st_size}
    try:
        from MDAnalysis.coordinates.DCD import DCDReader

        reader = DCDReader(str(path))
        row.update(n_atoms=int(reader.n_atoms), n_frames=int(len(reader)), dt_ps=float(reader.dt))
        if len(reader):
            row["first_time_ps"] = float(reader[0].time)
            row["last_time_ps"] = float(reader[-1].time)
        reader.close()
    except Exception as exc:  # inventory must retain malformed/incomplete files
        row["reader_error"] = f"{type(exc).__name__}: {exc}"
    return row


def _piece_key(path: Path) -> tuple[str, int, str]:
    match = re.search(r"\.cont(\d+)\.dcd$", path.name)
    base = re.sub(r"\.cont\d+\.dcd$", ".dcd", path.name)
    return base, 0 if match is None else int(match.group(1)) + 1, path.name


def _arrangement(design: Any) -> dict[str, Any]:
    from backend.core import junction_topology as jt

    connectors = jt.crossover_connectors(design)
    by_id = {row.crossover_id: row for row in connectors}
    pairs = jt.reciprocal_pairs(connectors)
    lengths: list[tuple[int, int]] = []
    for i, j in pairs:
        a = by_id[connectors[i].crossover_id]
        b = by_id[connectors[j].crossover_id]
        xa = next((x for x in design.crossovers if x.id == a.crossover_id), None)
        xb = next((x for x in design.crossovers if x.id == b.crossover_id), None)
        lengths.append((len((xa.extra_bases if xa else "") or ""), len((xb.extra_bases if xb else "") or "")))
    nonzero = [tuple(sorted(pair)) for pair in lengths if pair != (0, 0)]
    counts = Counter(f"{a}-{b}" for a, b in nonzero)
    label = "+".join(sorted(counts)) or "0-0"
    return {"reciprocal_insert_arrangements": dict(counts), "arrangement_label": label}


def _resolve_design(job: dict[str, Any], jobs_by_id: dict[str, list[dict[str, Any]]]) -> tuple[Path | None, str]:
    own = Path(job["job_dir"]) / "design.json"
    if own.is_file():
        return own, "immutable_job_snapshot"
    seen = {job["job_id"]}
    parent = job.get("parent_job_id")
    while parent and parent not in seen:
        seen.add(parent)
        choices = jobs_by_id.get(parent, [])
        # Prefer the same storage tree, then any exact-ID match.
        choices = sorted(choices, key=lambda x: _location(Path(x["job_dir"])) != job["location"])
        if not choices:
            break
        candidate = choices[0]
        path = Path(candidate["job_dir"]) / "design.json"
        if path.is_file():
            return path, "ancestor_job_snapshot"
        parent = candidate.get("parent_job_id")
    return None, "missing"


def inventory() -> dict[str, Any]:
    from backend.core.cpd_metrics import designed_weld_pairs
    from backend.core.models import Design

    dcd_paths = _find("-type", "f", "-iname", "*.dcd", "-print")
    job_paths = _find("-type", "f", "-name", "job.json", "-print")
    all_dcds = []
    for path in dcd_paths:
        try:
            all_dcds.append({"path": str(path.resolve()), "bytes": path.stat().st_size, "location": _location(path)})
        except OSError:
            continue

    managed: list[dict[str, Any]] = []
    for path in job_paths:
        if "site-packages" in path.parts:
            continue
        meta = _read_json(path)
        if not meta:
            continue
        package_subdir = meta.get("package_subdir")
        if not package_subdir or "namd" not in str(package_subdir).lower():
            continue
        job_dir = path.parent.resolve()
        package = (job_dir / package_subdir).resolve()
        output = package / "output"
        dcds = sorted(output.glob("*.dcd"), key=_piece_key) if output.is_dir() else []
        managed.append({
            "job_id": str(meta.get("job_id") or job_dir.name),
            "job_dir": str(job_dir),
            "location": _location(job_dir),
            "name_stem": meta.get("name_stem"),
            "status": meta.get("status"),
            "run_kind": meta.get("run_kind"),
            "parent_job_id": meta.get("parent_job_id"),
            "package": str(package),
            "all_output_dcds": [str(p.resolve()) for p in dcds],
        })

    jobs_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for job in managed:
        jobs_by_id[job["job_id"]].append(job)

    selected: list[dict[str, Any]] = []
    relevant_jobs: list[dict[str, Any]] = []
    metadata_cache: dict[str, dict[str, Any]] = {}
    for job in managed:
        production = [Path(p) for p in job["all_output_dcds"] if "production" in Path(p).name.lower()]
        design_path, design_source = _resolve_design(job, jobs_by_id)
        design = None
        design_error = None
        if design_path:
            try:
                design = Design.model_validate_json(design_path.read_text())
            except Exception as exc:
                design_error = f"{type(exc).__name__}: {exc}"
        if design is None:
            # Keep named extra-base production jobs visible even if no exact snapshot survived.
            if production and re.search(r"(?:\d+xT|\d+-\d+xT)", str(job.get("name_stem")), re.I):
                relevant_jobs.append({**job, "design_source": design_source, "design_error": design_error,
                                      "production_dcds": [str(p) for p in production],
                                      "eligibility": "missing exact design-to-residue mapping"})
            continue
        inserts = [x for x in design.crossovers if x.extra_bases]
        n_insert_bases = sum(len(x.extra_bases or "") for x in inserts)
        if not inserts and not production:
            continue
        welds = designed_weld_pairs(design)
        row = {
            **job,
            "design_path": str(design_path.resolve()),
            "design_source": design_source,
            "n_helices": len(design.helices),
            "size_class": "2hb" if len(design.helices) == 2 else "larger_origami",
            "n_insert_crossovers": len(inserts),
            "n_insert_bases": n_insert_bases,
            "insert_sequences": dict(Counter(x.extra_bases for x in inserts)),
            "n_designed_extra_tt_pairs": len(welds),
            **_arrangement(design),
            "production_dcds": [str(p.resolve()) for p in production],
        }
        if design_error:
            row["design_error"] = design_error
        dcd_meta = []
        for path in production:
            key = str(path.resolve())
            metadata_cache.setdefault(key, _dcd_metadata(path))
            dcd_meta.append(metadata_cache[key])
        row["production_metadata"] = dcd_meta
        total_frames = sum(int(x.get("n_frames", 0)) for x in dcd_meta)
        if not production:
            row["eligibility"] = "no unrestrained production DCD"
        elif not welds:
            row["eligibility"] = "no reciprocal extra-T partner; KIMMDY pair undefined"
        elif total_frames < 2:
            row["eligibility"] = "incomplete production DCD (<2 frames)"
        elif any("reader_error" in x for x in dcd_meta):
            row["eligibility"] = "unreadable production DCD"
        else:
            stem = str(job["name_stem"])
            top_choices = [Path(job["package"]) / f"{stem}_hmr.psf", Path(job["package"]) / f"{stem}.psf"]
            topology = next((p for p in top_choices if p.is_file()), None)
            if topology is None:
                row["eligibility"] = "missing PSF topology"
            else:
                row["topology"] = str(topology.resolve())
                row["eligibility"] = "analyse"
                selected.append(row)
        relevant_jobs.append(row)

    # Earliest production ancestor defines a continuous continuation lineage; siblings remain replicas.
    by_id_one = {key: values[0] for key, values in jobs_by_id.items()}
    selected_ids = {row["job_id"] for row in selected}
    for row in selected:
        lineage = row["job_id"]
        parent = row.get("parent_job_id")
        while parent in selected_ids:
            lineage = parent
            parent = by_id_one.get(parent, {}).get("parent_job_id")
        row["lineage_id"] = lineage

    selected_lookup = {row["job_id"]: row for row in selected}
    for row in relevant_jobs:
        if row["job_id"] in selected_lookup:
            row["lineage_id"] = selected_lookup[row["job_id"]]["lineage_id"]

    legacy = []
    for label, path in (
        ("legacy_CPD_1xT", Path("/media/jojo/Archive/NAMD/CPD_1xT")),
        ("legacy_CPD_2xT", Path("/media/jojo/Archive/NAMD/CPD_2xT")),
    ):
        files = [x for x in all_dcds if x["path"].startswith(str(path) + "/")]
        legacy.append({"label": label, "path": str(path), "n_dcds": len(files),
                       "dcd_bytes": sum(x["bytes"] for x in files),
                       "eligibility": "not primary: no NADOC design snapshot or audited insert residue map"})

    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for row in relevant_jobs:
        if "size_class" not in row:
            continue
        key = (row["size_class"], row["arrangement_label"])
        group = groups.setdefault(key, {"size_class": key[0], "arrangement": key[1],
                                        "jobs": 0, "production_jobs": 0, "analysable_jobs": 0,
                                        "production_frames": 0, "production_bytes": 0})
        group["jobs"] += 1
        if row.get("production_dcds"):
            group["production_jobs"] += 1
        if row.get("eligibility") == "analyse":
            group["analysable_jobs"] += 1
        for meta in row.get("production_metadata", []):
            group["production_frames"] += int(meta.get("n_frames", 0))
            group["production_bytes"] += int(meta.get("bytes", 0))

    payload = {
        "schema": "nadoc.exp59.inventory.v1",
        "scan_roots": [str(path) for path in SCAN_ROOTS],
        "scan_summary": {
            "n_dcds": len(all_dcds),
            "dcd_bytes": sum(x["bytes"] for x in all_dcds),
            "by_location": {
                location: {"n_dcds": sum(x["location"] == location for x in all_dcds),
                           "dcd_bytes": sum(x["bytes"] for x in all_dcds if x["location"] == location)}
                for location in ("local", "archive")
            },
            "n_managed_namd_jobs": len(managed),
            "n_extra_base_relevant_jobs": len(relevant_jobs),
            "n_selected_analysis_jobs": len(selected),
        },
        "matrix": sorted(groups.values(), key=lambda x: (x["size_class"], x["arrangement"])),
        "relevant_managed_jobs": relevant_jobs,
        "selected_analysis_jobs": selected,
        "legacy_collections": legacy,
        "all_dcds": all_dcds,
    }
    INVENTORY.write_text(json.dumps(payload, indent=2) + "\n")
    print(INVENTORY)
    return payload


def analyse(max_frames: int, force: bool = False) -> None:
    from backend.core.kimmdy_analysis import analyze_kimmdy_trajectory, write_kimmdy_outputs
    from backend.core.models import Design

    inv = _read_json(INVENTORY) or inventory()
    JOBS_OUT.mkdir(parents=True, exist_ok=True)
    for index, job in enumerate(inv["selected_analysis_jobs"], start=1):
        out = JOBS_OUT / job["job_id"]
        summary = out / "summary.json"
        if summary.is_file() and not force:
            print(f"[{index}/{len(inv['selected_analysis_jobs'])}] {job['job_id']} cached", flush=True)
            continue
        print(f"[{index}/{len(inv['selected_analysis_jobs'])}] {job['job_id']} {job['name_stem']}", flush=True)
        design = Design.model_validate_json(Path(job["design_path"]).read_text())

        def progress(stage: str, done: int, total: int) -> None:
            if done == 1 or done == total or done % 100 == 0:
                print(f"  {stage} {done}/{total}", flush=True)

        report, series = analyze_kimmdy_trajectory(
            Path(job["topology"]), [Path(p) for p in job["production_dcds"]], design,
            pair_mode="designed", pair_scope="interstrand", max_frames=max_frames,
            rate_model="periodic", progress=progress,
        )
        report["exp59"] = {
            "job_id": job["job_id"], "lineage_id": job["lineage_id"],
            "name_stem": job["name_stem"], "size_class": job["size_class"],
            "arrangement_label": job["arrangement_label"], "design_source": job["design_source"],
        }
        write_kimmdy_outputs(report, series, out)


def quality(force: bool = False) -> None:
    """Apply duplex/local-pair/backbone integrity gates to the sampled KIMMDY frames."""
    import MDAnalysis as mda

    from backend.core.kimmdy_analysis import _design_residue_map, _mic, _valid_box
    from backend.core.models import Design

    inv = _read_json(INVENTORY)
    if not inv:
        raise FileNotFoundError(f"run inventory first: {INVENTORY}")
    jobs = inv["selected_analysis_jobs"]
    for job_no, job in enumerate(jobs, start=1):
        out = JOBS_OUT / job["job_id"]
        target = out / "quality.npz"
        report = _read_json(out / "summary.json")
        if report is None:
            continue
        if target.is_file() and not force:
            print(f"[{job_no}/{len(jobs)}] {job['job_id']} quality cached", flush=True)
            continue
        print(f"[{job_no}/{len(jobs)}] {job['job_id']} structural quality", flush=True)
        design = Design.model_validate_json(Path(job["design_path"]).read_text())
        paths = job["production_dcds"]
        universe = mda.Universe(job["topology"], paths if len(paths) > 1 else paths[0])
        design_map = _design_residue_map(design)
        residue_lookup = {(str(res.segid), int(res.resid)): res for res in universe.residues
                          if (str(res.segid), int(res.resid)) in design_map}
        atom_lookup: dict[tuple[str, int], dict[str, int]] = {}
        for key, residue in residue_lookup.items():
            atom_lookup[key] = {str(atom.name): int(atom.index) for atom in residue.atoms
                                if str(atom.name) in {"C1'", "O3'", "P"}}

        normal_by_identity = {}
        insert_keys = []
        for residue_key, identity in design_map.items():
            if identity.get("kind") == "base":
                normal_by_identity[(identity["helix_id"], identity["bp_index"], identity["direction"])] = residue_key
            elif identity.get("kind") == "crossover_insert" and residue_key in atom_lookup:
                insert_keys.append(residue_key)
        insert_keys.sort()

        bp_atoms = []
        for (helix, bp, direction), key_a in normal_by_identity.items():
            if direction != "FORWARD":
                continue
            key_b = normal_by_identity.get((helix, bp, "REVERSE"))
            if key_b and "C1'" in atom_lookup.get(key_a, {}) and "C1'" in atom_lookup.get(key_b, {}):
                bp_atoms.append((atom_lookup[key_a]["C1'"], atom_lookup[key_b]["C1'"]))
        bp_atoms_array = np.asarray(bp_atoms, dtype=int)

        site_checks = []
        for site in insert_keys:
            segid, resid = site
            before = (segid, resid - 1)
            after = (segid, resid + 1)
            src = before
            while design_map.get(src, {}).get("kind") == "crossover_insert":
                src = (segid, src[1] - 1)
            dst = after
            while design_map.get(dst, {}).get("kind") == "crossover_insert":
                dst = (segid, dst[1] + 1)
            local_pairs = []
            for flank in (src, dst):
                identity = design_map.get(flank, {})
                if identity.get("kind") != "base":
                    continue
                opposite = "REVERSE" if identity["direction"] == "FORWARD" else "FORWARD"
                partner = normal_by_identity.get((identity["helix_id"], identity["bp_index"], opposite))
                if partner and "C1'" in atom_lookup.get(flank, {}) and "C1'" in atom_lookup.get(partner, {}):
                    local_pairs.append((atom_lookup[flank]["C1'"], atom_lookup[partner]["C1'"]))
            bonds = []
            if "O3'" in atom_lookup.get(before, {}) and "P" in atom_lookup.get(site, {}):
                bonds.append((atom_lookup[before]["O3'"], atom_lookup[site]["P"]))
            if "O3'" in atom_lookup.get(site, {}) and "P" in atom_lookup.get(after, {}):
                bonds.append((atom_lookup[site]["O3'"], atom_lookup[after]["P"]))
            site_checks.append((site, local_pairs, bonds))

        frame_indices = [int(value) for value in report["frame_indices"]]
        n_frames = len(frame_indices)
        global_paired = np.full(n_frames, np.nan)
        site_valid = np.zeros((len(site_checks), n_frames), dtype=bool)
        for frame_no, frame_index in enumerate(frame_indices):
            ts = universe.trajectory[frame_index]
            positions = universe.atoms.positions
            box = _valid_box(ts.dimensions)
            if len(bp_atoms_array):
                bp_d = np.linalg.norm(_mic(positions[bp_atoms_array[:, 1]] - positions[bp_atoms_array[:, 0]], box), axis=1)
                global_paired[frame_no] = np.mean((bp_d >= 8.0) & (bp_d <= 13.0))
            for site_no, (_site, local_pairs, bonds) in enumerate(site_checks):
                local_ok = len(local_pairs) == 2
                if local_ok:
                    pairs = np.asarray(local_pairs, dtype=int)
                    local_d = np.linalg.norm(_mic(positions[pairs[:, 1]] - positions[pairs[:, 0]], box), axis=1)
                    local_ok = bool(np.all((local_d >= 8.0) & (local_d <= 13.0)))
                bond_ok = len(bonds) == 2
                if bond_ok:
                    bond_array = np.asarray(bonds, dtype=int)
                    bond_d = np.linalg.norm(_mic(positions[bond_array[:, 1]] - positions[bond_array[:, 0]], box), axis=1)
                    bond_ok = bool(np.all((bond_d >= 1.2) & (bond_d <= 2.2)))
                site_valid[site_no, frame_no] = local_ok and bond_ok and global_paired[frame_no] >= 0.90
            if frame_no == 0 or (frame_no + 1) % 100 == 0 or frame_no + 1 == n_frames:
                print(f"  quality {frame_no + 1}/{n_frames}", flush=True)

        site_index = {f"{segid}:{resid}": i for i, (segid, resid) in enumerate(insert_keys)}
        pair_valid = np.zeros((len(report["pairs"]), n_frames), dtype=bool)
        for pair_no, pair in enumerate(report["pairs"]):
            ia = site_index.get(pair["site_a"]["site_id"])
            ib = site_index.get(pair["site_b"]["site_id"])
            if ia is not None and ib is not None:
                pair_valid[pair_no] = site_valid[ia] & site_valid[ib]
        np.savez_compressed(
            target,
            frame_indices=np.asarray(frame_indices, dtype=np.int64),
            global_paired_fraction=global_paired,
            insert_site_ids=np.asarray([f"{a}:{b}" for a, b in insert_keys]),
            insert_site_valid=site_valid,
            pair_ids=np.asarray([pair["id"] for pair in report["pairs"]]),
            pair_valid=pair_valid,
        )


def _crossover_rows(inv: dict[str, Any], use_structural_gates: bool = True) -> list[dict[str, Any]]:
    from backend.core.cpd_metrics import REACTIVE_D_NM, REACTIVE_ETA_DEG, angular_separation_deg

    jobs = {row["job_id"]: row for row in inv["selected_analysis_jobs"]}
    rows = []
    for job_id, job in jobs.items():
        out = JOBS_OUT / job_id
        report = _read_json(out / "summary.json")
        if not report or not (out / "timeseries.npz").is_file():
            continue
        series = np.load(out / "timeseries.npz")
        quality_path = out / "quality.npz"
        quality_data = (np.load(quality_path)
                        if use_structural_gates and quality_path.is_file() else None)
        pair_index = {str(value): i for i, value in enumerate(series["pair_ids"])}
        quality_pair_index = ({str(value): i for i, value in enumerate(quality_data["pair_ids"])}
                              if quality_data is not None else {})
        groups: dict[tuple[str, str], list[int]] = defaultdict(list)
        for pair in report["pairs"]:
            weld = pair.get("intended_weld_identity") or {}
            key = tuple(sorted((str(weld.get("crossover_a")), str(weld.get("crossover_b")))))
            groups[key].append(pair_index[pair["id"]])
        for key, indices in groups.items():
            k = np.asarray(series["periodic_propensity"])[indices]
            d = np.asarray(series["d_mid_nm"])[indices]
            eta = np.asarray(series["eta_deg"])[indices]
            best = np.nanmax(k, axis=0)
            reactive = np.any((d < REACTIVE_D_NM) & (angular_separation_deg(eta) < REACTIVE_ETA_DEG), axis=0)
            if quality_data is not None:
                valid_by_pair = np.asarray([quality_data["pair_valid"][quality_pair_index[report["pairs"][i]["id"]]]
                                            for i in indices])
                valid_frame = np.any(valid_by_pair, axis=0)
                filtered_best = np.max(np.where(valid_by_pair, k, -np.inf), axis=0)
                filtered_best[~valid_frame] = np.nan
                filtered_reactive = np.any(valid_by_pair & (d < REACTIVE_D_NM)
                                           & (angular_separation_deg(eta) < REACTIVE_ETA_DEG), axis=0)
                good = valid_frame & np.isfinite(filtered_best)
            else:
                filtered_best = best
                filtered_reactive = reactive
                good = np.isfinite(filtered_best)
            duration_ps = sum(max(0, int(meta.get("n_frames", 0)) - 1) * float(meta.get("dt_ps", 0.0))
                              for meta in job.get("production_metadata", []))
            rows.append({
                "job_id": job_id, "lineage_id": job["lineage_id"], "name_stem": job["name_stem"],
                "size_class": job["size_class"], "arrangement": job["arrangement_label"],
                "crossover_a": key[0], "crossover_b": key[1], "n_pair_combinations": len(indices),
                "duration_ps": duration_ps, "n_frames": len(best),
                "structural_gates_applied": use_structural_gates,
                "valid_frames": int(np.sum(good)), "pct_frames_structurally_valid": float(100 * np.mean(good)),
                "raw_mean_best_periodic_propensity": float(np.mean(best)),
                "raw_pct_any_reactive_corner": float(100 * np.mean(reactive)),
                "mean_best_periodic_propensity": float(np.mean(filtered_best[good])) if np.any(good) else math.nan,
                "median_best_periodic_propensity": float(np.median(filtered_best[good])) if np.any(good) else math.nan,
                "p95_best_periodic_propensity": float(np.percentile(filtered_best[good], 95)) if np.any(good) else math.nan,
                "pct_any_reactive_corner": float(100 * np.mean(filtered_reactive[good])) if np.any(good) else math.nan,
            })
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _bootstrap_ci(values: list[float], seed: int = 59) -> tuple[float, float]:
    if not values:
        return math.nan, math.nan
    rng = np.random.default_rng(seed)
    array = np.asarray(values, dtype=float)
    means = np.mean(rng.choice(array, size=(20000, len(array)), replace=True), axis=1)
    return tuple(float(x) for x in np.percentile(means, [2.5, 97.5]))


def _aggregate_crossovers(crossovers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Reduce jobs to independent lineages, then build size/arrangement summaries."""
    lineage_groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in crossovers:
        lineage_groups[(row["lineage_id"], row["size_class"], row["arrangement"],
                        row["crossover_a"], row["crossover_b"])].append(row)
    lineage_crossovers = []
    for key, members in lineage_groups.items():
        weights = np.asarray([max(float(x["duration_ps"]), 1.0) for x in members])
        props = np.asarray([x["mean_best_periodic_propensity"] for x in members])
        reactive = np.asarray([x["pct_any_reactive_corner"] for x in members])
        valid = np.isfinite(props) & np.isfinite(reactive)
        if not np.any(valid):
            continue
        lineage_crossovers.append({
            "lineage_id": key[0], "size_class": key[1], "arrangement": key[2],
            "crossover_a": key[3], "crossover_b": key[4],
            "jobs": len({x["job_id"] for x in members}),
            "crossovers": 1,
            "mean_best_periodic_propensity": float(np.average(props[valid], weights=weights[valid])),
            "mean_pct_any_reactive_corner": float(np.average(reactive[valid], weights=weights[valid])),
            "mean_frames_included_pct": float(np.average(
                [x["pct_frames_structurally_valid"] for x in members], weights=weights)),
        })

    lineage_groups2: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in lineage_crossovers:
        lineage_groups2[(row["lineage_id"], row["size_class"], row["arrangement"])].append(row)
    lineages = []
    for (lineage, size_class, arrangement), members in sorted(lineage_groups2.items()):
        lineages.append({
            "lineage_id": lineage, "size_class": size_class, "arrangement": arrangement,
            "jobs": max(x["jobs"] for x in members),
            "crossovers": len(members),
            "mean_best_periodic_propensity": float(np.mean(
                [x["mean_best_periodic_propensity"] for x in members])),
            "mean_pct_any_reactive_corner": float(np.mean(
                [x["mean_pct_any_reactive_corner"] for x in members])),
            "mean_frames_included_pct": float(np.mean(
                [x["mean_frames_included_pct"] for x in members])),
        })

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in lineages:
        grouped[(row["size_class"], row["arrangement"])].append(row)
    table = []
    for key, members in sorted(grouped.items()):
        props = [x["mean_best_periodic_propensity"] for x in members]
        reactive = [x["mean_pct_any_reactive_corner"] for x in members]
        p_lo, p_hi = _bootstrap_ci(props)
        r_lo, r_hi = _bootstrap_ci(reactive, seed=60)
        table.append({
            "size_class": key[0], "arrangement": key[1], "n_lineages": len(members),
            "mean_best_k": float(np.mean(props)), "best_k_ci": [p_lo, p_hi],
            "mean_reactive_pct": float(np.mean(reactive)), "reactive_ci": [r_lo, r_hi],
            "mean_frames_included_pct": float(np.mean(
                [x["mean_frames_included_pct"] for x in members])),
        })
    return lineages, table


def summarize() -> None:
    inv = _read_json(INVENTORY)
    if not inv:
        raise FileNotFoundError(f"run inventory first: {INVENTORY}")
    crossovers = _crossover_rows(inv)
    _write_csv(CROSSOVER_CSV, crossovers)

    # Each continuous production lineage is one independent simulation unit.  Within a
    # larger origami, crossover means are averaged before lineages are compared.
    lineage_groups: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in crossovers:
        lineage_groups[(row["lineage_id"], row["size_class"], row["arrangement"],
                        row["crossover_a"], row["crossover_b"])].append(row)
    lineage_crossovers = []
    for key, members in lineage_groups.items():
        weights = np.asarray([max(float(x["duration_ps"]), 1.0) for x in members])
        props = np.asarray([x["mean_best_periodic_propensity"] for x in members])
        reactive = np.asarray([x["pct_any_reactive_corner"] for x in members])
        valid = np.isfinite(props) & np.isfinite(reactive)
        if not np.any(valid):
            continue
        lineage_crossovers.append({
            "lineage_id": key[0], "size_class": key[1], "arrangement": key[2],
            "crossover_a": key[3], "crossover_b": key[4],
            "jobs": len({x["job_id"] for x in members}),
            "mean_best_periodic_propensity": float(np.average(props[valid], weights=weights[valid])),
            "mean_pct_any_reactive_corner": float(np.average(reactive[valid], weights=weights[valid])),
            "mean_structurally_valid_pct": float(np.average(
                [x["pct_frames_structurally_valid"] for x in members], weights=weights)),
        })
    lineage_groups2: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in lineage_crossovers:
        lineage_groups2[(row["lineage_id"], row["size_class"], row["arrangement"])].append(row)
    lineages = []
    for (lineage, size_class, arrangement), members in sorted(lineage_groups2.items()):
        lineages.append({
            "lineage_id": lineage, "size_class": size_class, "arrangement": arrangement,
            "jobs": max(x["jobs"] for x in members),
            "crossovers": len(members),
            "mean_best_periodic_propensity": float(np.mean([x["mean_best_periodic_propensity"] for x in members])),
            "mean_pct_any_reactive_corner": float(np.mean([x["mean_pct_any_reactive_corner"] for x in members])),
            "mean_structurally_valid_pct": float(np.mean([x["mean_structurally_valid_pct"] for x in members])),
        })
    _write_csv(LINEAGE_CSV, lineages)

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in lineages:
        grouped[(row["size_class"], row["arrangement"])].append(row)
    table = []
    for key, members in sorted(grouped.items()):
        props = [x["mean_best_periodic_propensity"] for x in members]
        reactive = [x["mean_pct_any_reactive_corner"] for x in members]
        p_lo, p_hi = _bootstrap_ci(props)
        r_lo, r_hi = _bootstrap_ci(reactive, seed=60)
        table.append({"size_class": key[0], "arrangement": key[1], "n_lineages": len(members),
                      "mean_best_k": float(np.mean(props)), "best_k_ci": [p_lo, p_hi],
                      "mean_reactive_pct": float(np.mean(reactive)), "reactive_ci": [r_lo, r_hi],
                      "mean_valid_pct": float(np.mean([x["mean_structurally_valid_pct"] for x in members]))})

    scan = inv["scan_summary"]
    sampled_frames = 0
    for job in inv["selected_analysis_jobs"]:
        job_report = _read_json(JOBS_OUT / job["job_id"] / "summary.json")
        if job_report:
            sampled_frames += int(job_report.get("n_sampled_frames", 0))
    lines = [
        "# exp59 report — extra-base KIMMDY matrix",
        "",
        "> This is the original canonical-geometry-gated sensitivity analysis. `REPORT_UNGATED.md` is the primary analysis after review established that the gates reject deliberately single-stranded and visually intact 2hb conformations.",
        "",
        "## Inventory",
        "",
        f"The scan found **{scan['n_dcds']} DCD files** ({scan['dcd_bytes']/2**40:.3f} TiB): "
        f"{scan['by_location']['local']['n_dcds']} local ({scan['by_location']['local']['dcd_bytes']/2**30:.2f} GiB) and "
        f"{scan['by_location']['archive']['n_dcds']} on Archive ({scan['by_location']['archive']['dcd_bytes']/2**40:.3f} TiB). "
        f"There are {scan['n_managed_namd_jobs']} managed NAMD jobs, {scan['n_extra_base_relevant_jobs']} extra-base-relevant job records, "
        f"and {scan['n_selected_analysis_jobs']} production jobs with at least two frames, a PSF, an exact design mapping, and one or more reciprocal extra-T pairs.",
        "",
        "The legacy `Archive/NAMD/CPD_1xT` (23 DCDs, 54.16 GiB) and `CPD_2xT` (16 DCDs, 317.17 GiB) replicas are inventoried but excluded from the primary matrix because no NADOC design snapshot or audited mapping from topology residues to crossover inserts survives. Restrained, SMD/umbrella, vacuum/probe, and incomplete trajectories are likewise audit-only.",
        "",
        "### Managed production matrix",
        "",
        "| size | inserts per reciprocal side | production jobs | analyzable jobs | stored production frames |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in inv["matrix"]:
        lines.append(
            f"| {row['size_class']} | {row['arrangement']} | {row['production_jobs']} | "
            f"{row['analysable_jobs']} | {row['production_frames']:,} |"
        )
    lines += [
        "",
        f"KIMMDY was run on every eligible production job above ({sampled_frames:,} frames total, with at most 500 frames spread across each job). The frame cap represents every trajectory while keeping the multi-terabyte scan tractable; it is not an every-stored-frame calculation.",
        "",
        "## Claim being tested",
        "",
        "Gerling, Kube, Kick, and Dietz ([Science Advances 2018](https://doi.org/10.1126/sciadv.aau1157)) demonstrated that placing unpaired thymidines at DNA-origami crossover positions can create UV-induced covalent bonds; their experiments used 310 nm irradiation. The paper establishes feasibility, but it does not report a controlled comparison of one versus two inserts on each reciprocal strand and does not establish that two total thymidines (the 1+1 arrangement here) are globally optimal. Consequently, this analysis tests the later *optimality extrapolation*, not whether the published crosslinking experiment occurred.",
        "",
        "## Lineage-level KIMMDY comparison",
        "",
        "The metric is the per-frame maximum corrected periodic KIMMDY propensity among all extra-T pair combinations at one reciprocal crossover. Frames must retain at least 90% global duplex pairing, both flanking C1′ pairs at 8–13 Å, and both backbone links for each insert at 1.2–2.2 Å. `Reactive %` is the fraction of structurally valid frames meeting both the midpoint-distance and dihedral criteria. CIs bootstrap independent production lineages; they are descriptive when lineage counts are small.",
        "",
        "| size | reciprocal inserts per side | lineages | structurally valid % | mean best k (95% CI) | reactive % (95% CI) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in table:
        lines.append(f"| {row['size_class']} | {row['arrangement']} | {row['n_lineages']} | {row['mean_valid_pct']:.1f} | {row['mean_best_k']:.4f} ({row['best_k_ci'][0]:.4f}–{row['best_k_ci'][1]:.4f}) | {row['mean_reactive_pct']:.3f} ({row['reactive_ci'][0]:.3f}–{row['reactive_ci'][1]:.3f}) |")

    lines += ["", "## Interpretation", ""]
    by_key = {(x["size_class"], x["arrangement"]): x for x in table}
    one = by_key.get(("2hb", "1-1"))
    two = by_key.get(("2hb", "2-2"))
    large_one = by_key.get(("larger_origami", "1-1"))
    large_two = by_key.get(("larger_origami", "2-2"))
    if one and two:
        ratio = one["mean_best_k"] / two["mean_best_k"] if two["mean_best_k"] else math.inf
        lines.append(f"In the controlled 2hb runs, the Dietz-style 1+1 arrangement has mean best propensity {one['mean_best_k']:.4f}, versus {two['mean_best_k']:.4f} for 2+2 ({ratio:.2f}×; equivalently 2+2 is {1/ratio:.2f}× higher). Reactive-corner occupancy is {one['mean_reactive_pct']:.3f}% versus {two['mean_reactive_pct']:.3f}%. These values are retained only to quantify sensitivity to the canonical-geometry gate; low gate passage is not evidence that the structures are unstable.")
    if one and large_one:
        difference = 100 * (large_one["mean_best_k"] / one["mean_best_k"] - 1) if one["mean_best_k"] else math.nan
        lines.append(f"Across all mapped 1+1 runs, mean best propensity is {one['mean_best_k']:.4f} in 2hb and {large_one['mean_best_k']:.4f} in larger origami ({difference:+.1f}%). The larger-origami mean combines one long 24hb lineage with three 0.5 ns 6hbx100 replicas, so this is not strong evidence of a size effect.")
    if two and large_two:
        difference = 100 * (large_two["mean_best_k"] / two["mean_best_k"] - 1) if two["mean_best_k"] else math.nan
        lines.append(f"For 2+2, the corresponding 2hb versus larger-origami values are {two['mean_best_k']:.4f} and {large_two['mean_best_k']:.4f} ({difference:+.1f}%). Both size comparisons point in the same direction but remain confounded by trajectory length, construct geometry, and small lineage counts.")
    long_24hb = {
        row["arrangement"]: row
        for row in lineages
        if row["size_class"] == "larger_origami" and row["crossovers"] == 159
    }
    if "1-1" in long_24hb and "2-2" in long_24hb:
        one_24 = long_24hb["1-1"]
        two_24 = long_24hb["2-2"]
        lines.append(
            f"Restricting the comparison to the two mature 24hb lineages gives the same qualitative result: "
            f"1+1 has mean best propensity {one_24['mean_best_periodic_propensity']:.4f} and reactive occupancy "
            f"{one_24['mean_pct_any_reactive_corner']:.3f}%, whereas 2+2 has {two_24['mean_best_periodic_propensity']:.4f} "
            f"and {two_24['mean_pct_any_reactive_corner']:.3f}%. This removes the short 6hb runs but still leaves only one long "
            "lineage per condition."
        )
    lines += [
        "",
        "## Position and orientation context",
        "",
        "The independent exp55 orientation analysis reinforces the context dependence seen here. The two long 2hb 1+1 lineages occupied markedly different coupled basins: their reciprocal face-normal separations were 72.3 ± 16.8° and 146.7 ± 27.4°. In 24hb, individual sites were usually concentrated (median resultant lengths 0.876 and 0.883 for the two reciprocal sides), yet different crossovers selected different basins; the traversal-aligned population means were separated by 61.7°. Thus a minimal 2hb system is mechanistically useful but not a reliable stand-in for the full distribution of origami environments. See [`../exp55_2hb_extra_base_orientation/REPORT.md`](../exp55_2hb_extra_base_orientation/REPORT.md).",
        "",
        "The canonical-geometry gate-pass difference is large: the mapped 2hb groups pass only 35.5–64.1% of frames, compared with 96.9–97.1% in larger origami. Because the 2hb designs contain deliberately single-stranded bases and exhibit expected terminal fraying, this difference must not be interpreted as structural instability. The ungated analysis is therefore primary.",
        "",
        "## Scientific conclusion",
        "",
        "This gated sensitivity analysis is not used for the primary scientific conclusion. Refer to `REPORT_UNGATED.md`, which includes every finite sampled frame and avoids treating expected single-stranded behavior or terminal fraying as a disqualifying event.",
    ]
    lines += [
        "",
        "## Matrix gaps",
        "",
        "The 2hb set covers 0+1 (both polarities), 1+1, 1+2 (both polarities), and 2+2. It lacks unrestrained 0+0 and 0+2/2+0 production controls. The larger-origami set contains only symmetric 1+1 and 2+2 designs; asymmetric controls are absent. Only one long 24hb production lineage exists for each symmetric condition, while the 6hb/6hbx100 data are short bring-up runs.",
        "",
    ]
    lines += [
        "",
        "Asymmetric 0+1 and 1+0 constructs contain only one crossover-insert thymine and therefore have zero possible interstrand extra-T pair by definition. They are structural controls, not zero-valued KIMMDY observations.",
        "",
        "A favorable classical-MD geometry is necessary but not sufficient for a 305 nm CPD. The score is dimensionless, the reactive corner is a screening threshold, and neither supplies absorption, excited-state dynamics, quantum yield, or an absolute crosslink probability. The [KIMMDY method paper](https://doi.org/10.1038/s41467-026-71955-2) likewise describes its distance/angle photodimerization model as heuristic and cautions that heuristic models have limited predictive power. Accordingly, these simulations can challenge a universal geometric-optimality claim but cannot by themselves refute the reported experimental crosslinking result.",
        "",
        "## Outputs",
        "",
        "- `inventory.json`: every DCD plus managed-job eligibility and matrix coverage",
        "- `crossover_summary.csv`: one row per reciprocal crossover per production job",
        "- `lineage_summary.csv`: independent-lineage statistical units",
        "- `results/jobs/<job_id>/`: KIMMDY summary, pair table, and sampled time series",
        "",
    ]
    REPORT.write_text("\n".join(lines))
    print(CROSSOVER_CSV)
    print(LINEAGE_CSV)
    print(REPORT)


def summarize_ungated() -> None:
    """Primary summary using all finite sampled frames, without canonical-geometry gates."""
    inv = _read_json(INVENTORY)
    if not inv:
        raise FileNotFoundError(f"run inventory first: {INVENTORY}")

    crossovers = _crossover_rows(inv, use_structural_gates=False)
    lineages, table = _aggregate_crossovers(crossovers)
    _write_csv(CROSSOVER_UNGATED_CSV, crossovers)
    _write_csv(LINEAGE_UNGATED_CSV, lineages)

    gated_crossovers = _crossover_rows(inv, use_structural_gates=True)
    _gated_lineages, gated_table = _aggregate_crossovers(gated_crossovers)
    ungated_by_key = {(x["size_class"], x["arrangement"]): x for x in table}
    gated_by_key = {(x["size_class"], x["arrangement"]): x for x in gated_table}
    total_sampled = sum(int(row["n_frames"]) for row in crossovers)

    lines = [
        "# exp59 report — ungated extra-base KIMMDY matrix",
        "",
        "## Primary analysis decision",
        "",
        "All finite sampled KIMMDY frames are included. No global duplex-pairing, local flanking-C1′, or insert-backbone gate is applied. Those checks systematically reject expected conformations in these designs: deliberately single-stranded bases and terminal fraying in a small 2hb construct are not evidence that the modeled crossover or whole structure is unusable. The former gated output is retained in `REPORT.md` only as a sensitivity analysis.",
        "",
        f"The analysis contains {total_sampled:,} crossover-frame observations from the same 20 eligible production jobs and 18 independent lineages. The KIMMDY calculation itself is unchanged: only reciprocal designed extra-thymidine pairs are evaluated, and the per-frame statistic is the maximum corrected periodic propensity among pair combinations at a crossover.",
        "",
        "## Ungated lineage-level comparison",
        "",
        "| size | inserts per reciprocal side | lineages | frames included % | mean best k (95% CI) | reactive % (95% CI) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in table:
        lines.append(
            f"| {row['size_class']} | {row['arrangement']} | {row['n_lineages']} | "
            f"{row['mean_frames_included_pct']:.1f} | {row['mean_best_k']:.4f} "
            f"({row['best_k_ci'][0]:.4f}–{row['best_k_ci'][1]:.4f}) | "
            f"{row['mean_reactive_pct']:.3f} ({row['reactive_ci'][0]:.3f}–{row['reactive_ci'][1]:.3f}) |"
        )

    lines += [
        "",
        "## Change caused by removing the gates",
        "",
        "| size | inserts/side | gated k | ungated k | k change | gated reactive % | ungated reactive % |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for key, ungated in ungated_by_key.items():
        gated = gated_by_key.get(key)
        if not gated:
            continue
        k_change = 100 * (ungated["mean_best_k"] / gated["mean_best_k"] - 1)
        lines.append(
            f"| {key[0]} | {key[1]} | {gated['mean_best_k']:.4f} | "
            f"{ungated['mean_best_k']:.4f} | {k_change:+.1f}% | "
            f"{gated['mean_reactive_pct']:.3f} | {ungated['mean_reactive_pct']:.3f} |"
        )

    one = ungated_by_key.get(("2hb", "1-1"))
    mixed = ungated_by_key.get(("2hb", "1-2"))
    two = ungated_by_key.get(("2hb", "2-2"))
    large_one = ungated_by_key.get(("larger_origami", "1-1"))
    large_two = ungated_by_key.get(("larger_origami", "2-2"))
    lines += ["", "## Interpretation", ""]
    if one and mixed and two:
        lines.append(
            f"In 2hb, removing the gates changes the absolute values and yields a monotonic arrangement ordering: "
            f"1+1 = {one['mean_best_k']:.4f}, 1+2 = {mixed['mean_best_k']:.4f}, and 2+2 = "
            f"{two['mean_best_k']:.4f}. The 2+2 best-pair score is {two['mean_best_k']/one['mean_best_k']:.2f}× "
            f"the 1+1 score; reactive occupancy is {one['mean_reactive_pct']:.3f}% versus "
            f"{two['mean_reactive_pct']:.3f}%."
        )
    if one and large_one and two and large_two:
        one_delta = 100 * (large_one["mean_best_k"] / one["mean_best_k"] - 1)
        two_delta = 100 * (large_two["mean_best_k"] / two["mean_best_k"] - 1)
        lines.append(
            f"The apparent size effect is now arrangement-dependent: larger-origami 1+1 is {one_delta:+.1f}% "
            f"relative to 2hb 1+1, while larger-origami 2+2 is {two_delta:+.1f}% relative to 2hb 2+2. "
            "This is more informative than the gate-pass contrast, but it remains confounded by construct geometry, "
            "trajectory length, and limited independent long-run replication."
        )

    long_24hb = {
        row["arrangement"]: row
        for row in lineages
        if row["size_class"] == "larger_origami" and row["crossovers"] == 159
    }
    if "1-1" in long_24hb and "2-2" in long_24hb:
        one_24 = long_24hb["1-1"]
        two_24 = long_24hb["2-2"]
        lines.append(
            f"In the mature 24hb lineages alone, 1+1 gives k = "
            f"{one_24['mean_best_periodic_propensity']:.4f} and {one_24['mean_pct_any_reactive_corner']:.3f}% "
            f"reactive occupancy; 2+2 gives k = {two_24['mean_best_periodic_propensity']:.4f} and "
            f"{two_24['mean_pct_any_reactive_corner']:.3f}%. There is still only one long lineage per condition."
        )

    lines += [
        "",
        "## Revised conclusion",
        "",
        "Removing the inappropriate structural filters does not rescue a unique 1+1 optimum. The qualitative result remains that 2+2 offers more frequent favorable extra-T geometry than 1+1 in both 2hb and mature 24hb. The magnitude changes, however, so the gated percentages must not be described as structural survival or stability.",
        "",
        "This remains evidence about the probability that *any* reciprocal extra-T pairing reaches favorable ground-state geometry. Because 2+2 supplies four pair combinations while 1+1 supplies one, it does not establish higher intrinsic reactivity per thymine pair or higher experimental quantum yield. Small lineage counts and the absence of a balanced large-origami arrangement matrix still preclude a definitive optimal-design claim.",
        "",
        "## Outputs",
        "",
        "- `crossover_summary_ungated.csv`: ungated job/crossover observations",
        "- `lineage_summary_ungated.csv`: ungated independent-lineage units",
        "- `REPORT.md`: former gated analysis, retained as sensitivity only",
        "- `inventory.json` and `results/jobs/`: unchanged inventory and raw KIMMDY outputs",
        "",
    ]
    REPORT_UNGATED.write_text("\n".join(lines))
    print(CROSSOVER_UNGATED_CSV)
    print(LINEAGE_UNGATED_CSV)
    print(REPORT_UNGATED)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=(
        "inventory", "analyse", "quality", "summarize", "summarize-ungated", "all",
    ))
    parser.add_argument("--max-frames", type=int, default=500)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    if args.command in {"inventory", "all"}:
        inventory()
    if args.command in {"analyse", "all"}:
        analyse(args.max_frames, args.force)
    if args.command in {"quality", "all"}:
        quality(args.force)
    if args.command in {"summarize", "all"}:
        summarize()
    if args.command in {"summarize-ungated", "all"}:
        summarize_ungated()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
