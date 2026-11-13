"""Read-only input discovery, bounded trajectory profiling, and candidate comparison.

Run with ``python -m experiments.namd_shell_calibration.workflow --help``.
No engine execution, managed-job writes, molecular authoring, or publication.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np

from backend.core.dcd_fast import read_layout, read_frame, cell_to_dimensions
from experiments.namd_shell_calibration.numerics import (
    box_coordinates,
    moments,
    register,
    scalar_update,
)

DNA = {"THY", "ADE", "CYT", "GUA", "DA", "DT", "DC", "DG"}


def read_json(path):
    return json.loads(Path(path).read_text())


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def psf_atoms(path):
    """Stream only NATOM; retain DNA identities, not the million-atom solvent."""
    atoms = []
    with Path(path).open() as stream:
        for line in stream:
            if "!NATOM" in line:
                count = int(line.split()[0])
                break
        else:
            raise ValueError("Missing NATOM")
        for i in range(count):
            row = next(stream).split()
            if int(row[0]) != i + 1:
                raise ValueError("Noncontiguous PSF atom indices")
            if row[3] in DNA:
                atoms.append(
                    dict(
                        index=i,
                        key=row[1:5],
                        atom_type=row[5],
                        charge=float(row[6]),
                        mass=float(row[7]),
                    )
                )
    keys = [tuple(a["key"]) for a in atoms]
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate DNA atom identity")
    return count, atoms


def pdb_selected(path, indices):
    wanted = {int(i): j for j, i in enumerate(indices)}
    result = np.full((len(indices), 3), np.nan)
    i = 0
    with Path(path).open() as stream:
        for line in stream:
            if line.startswith(("ATOM  ", "HETATM")):
                if i in wanted:
                    result[wanted[i]] = [float(line[k : k + 8]) for k in (30, 38, 46)]
                i += 1
    if not np.isfinite(result).all():
        raise ValueError("Missing PDB coordinates")
    return result


def retained_bonds(path, indices):
    """Read actual PSF bond connectivity, without reconstructing topology."""
    local = {int(v): i for i, v in enumerate(indices)}
    bonds = []
    with Path(path).open() as stream:
        for line in stream:
            if "!NBOND" in line:
                count = int(line.split()[0])
                break
        else:
            raise ValueError("Missing PSF bonds")
        pending = []
        for line in stream:
            pending.extend(map(int, line.split()))
            while len(pending) >= 2 and count:
                a, b = pending[:2]
                del pending[:2]
                count -= 1
                if a - 1 in local and b - 1 in local:
                    bonds.append([local[a - 1], local[b - 1]])
            if not count:
                break
        if count:
            raise ValueError("Truncated PSF bonds")
    return bonds


def check_images(x, dimensions, edges):
    """Refuse split local bonds/WC support; broad region extent alone is not a split.

    Current experiments use wrapAll off. No image repair or geometry modification
    is attempted. Triclinic trajectories require a dedicated image policy.
    """
    if dimensions is None:
        return
    if not np.allclose(dimensions[3:], 90):
        raise ValueError("Triclinic images require explicit unwrapping")
    edges = np.asarray(edges, int)
    delta = x[edges[:, 0]] - x[edges[:, 1]]
    if np.any(np.abs(delta) > dimensions[:3] / 2):
        raise ValueError("Split bonded/paired image; explicit unwrapping required")


def fresh(path):
    path = Path(path).resolve()
    if path.exists():
        raise ValueError(f"Output already exists: {path}")
    if any(p.name in {"workspace", "md_jobs", "nadoc_jobs"} for p in path.parents):
        raise ValueError("Use a separate experiment directory, not managed job storage")
    if shutil.disk_usage(path.parent).free < 256 * 1024**2:
        raise ValueError("Less than 256 MiB output headroom")
    path.mkdir()
    return path


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def prepare(control_job, reference_job, out):
    control_job, reference_job = (
        Path(control_job).resolve(),
        Path(reference_job).resolve(),
    )
    cj, rj = read_json(control_job / "job.json"), read_json(reference_job / "job.json")
    designs = [read_json(j / "design.json") for j in (control_job, reference_job)]
    strand_signatures = [
        [{k: s.get(k) for k in ("id", "domains", "sequence")} for s in d["strands"]]
        for d in designs
    ]
    crossover_signatures = [
        {
            x["id"]: {k: x.get(k) for k in ("half_a", "half_b", "extra_bases")}
            for x in d["crossovers"]
        }
        for d in designs
    ]
    if (
        strand_signatures[0] != strand_signatures[1]
        or crossover_signatures[0] != crossover_signatures[1]
    ):
        raise ValueError(
            "Reference/control strand order, sequence or crossover topology differs"
        )
    cp, rp = control_job / cj["package_subdir"], reference_job / rj["package_subdir"]
    stem, rstem = cj["name_stem"], rj["name_stem"]
    recipe_path = cp / "submodel.json"
    recipe = read_json(recipe_path)
    if recipe["version"] != 2 or recipe["shell_boundary"]["kind"] != "uniform":
        raise ValueError("Pilot requires the version-2 uniform-shell control")
    source_psf, source_pdb = (
        cp / "submodel_source/full.psf",
        cp / "submodel_source/full.pdb",
    )
    for path, field in [
        (source_psf, "source_psf_sha256"),
        (source_pdb, "source_pdb_sha256"),
    ]:
        if digest(path) != recipe[field]:
            raise ValueError(f"Source provenance mismatch: {path}")
    _, source = psf_atoms(source_psf)
    ref_count, ref = psf_atoms(rp / f"{rstem}.psf")
    control_count, ctrl = psf_atoms(cp / f"{stem}.psf")
    lookup = {tuple(a["key"]): a for a in ref}
    src = {a["index"]: a for a in source}
    kept = recipe["retained_source_indices"]
    atoms = [src[i] for i in kept]
    ctrl_by_index = {a["index"]: a for a in ctrl}
    mapping = []
    for j, a in enumerate(atoms):
        b = lookup.get(tuple(a["key"]))
        c = ctrl_by_index.get(j)
        if b is None or c is None or a["key"] != c["key"]:
            raise ValueError(f"Atom identity mismatch: {a['key']}")
        if any(
            a["atom_type"] != v["atom_type"] or abs(a["charge"] - v["charge"]) > 1e-6
            for v in (b, c)
        ):
            raise ValueError(f"Force-field identity mismatch: {a['key']}")
        mapping.append(b["index"])
    boundary = recipe["shell_boundary"]
    anchors = [i for i in boundary["fixed_output_indices"] if atoms[i]["key"][3] == "P"]
    reference = pdb_selected(source_pdb, kept)
    register(reference, reference, anchors)

    # Reuse the established topological mapper, without building atomic geometry.
    from experiments.exp46_xb_placement.xb_map import build_package_map, load_design

    pm = build_package_map(load_design(control_job / "design.json"), source_pdb)
    by_res = {}
    for i, a in enumerate(atoms):
        seg, resid, _, name = a["key"]
        by_res.setdefault((seg, int(resid)), {})[name] = i
    core = set(recipe["mobile_output_indices"])
    inserts = []
    for insert in pm.inserts:
        rows = by_res.get((insert.segid, insert.resid), {})
        if not core.intersection(rows.values()):
            continue
        ring = [rows[n] for n in ["N1", "C2", "N3", "C4", "C5", "C6"]]
        inserts.append(
            {**asdict(insert), "ring_indices": ring, "c1_index": rows["C1'"]}
        )
    if not inserts:
        raise ValueError("Control core contains no mapped extra bases")
    # Verify crossover topology against the reference snapshot, not UUID alone.
    reference_design = load_design(reference_job / "design.json")
    reference_xo = {
        x.id: x.model_dump(mode="json") for x in reference_design.crossovers
    }
    control_design = load_design(control_job / "design.json")
    for x in control_design.crossovers:
        if x.id in {i["crossover_id"] for i in inserts}:
            if reference_xo.get(x.id) != x.model_dump(mode="json"):
                raise ValueError("Reference/control crossover definitions differ")
    pairs, image_pairs = [], []
    wc_path = cp / f"{stem}_wc_pairs.json"
    for pair in read_json(wc_path)["pairs"]:
        a = by_res.get((pair["a"][0], int(pair["a"][1])), {}).get("C1'")
        b = by_res.get((pair["b"][0], int(pair["b"][1])), {}).get("C1'")
        if a is not None and b is not None:
            image_pairs.append([a, b])
            if a in core or b in core:
                pairs.append([a, b])
    bonds = retained_bonds(source_psf, kept)
    sources = [
        recipe_path,
        source_psf,
        source_pdb,
        control_job / "design.json",
        reference_job / "design.json",
        cp / "manifest.json",
        rp / "manifest.json",
        wc_path,
        rp / f"{rstem}.psf",
        cp / f"{stem}.psf",
    ]
    plan = dict(
        schema="nadoc.shell-calibration-plan.v1",
        control_job=str(control_job),
        reference_job=str(reference_job),
        control_package=str(cp),
        reference_package=str(rp),
        box=recipe["box"],
        atoms=atoms,
        reference_indices=mapping,
        control_indices=list(range(len(kept))),
        reference_natoms=ref_count,
        control_natoms=control_count,
        alignment_indices=anchors,
        shell_indices=boundary["restrained_output_indices"],
        fixed_indices=boundary["fixed_output_indices"],
        core_indices=sorted(core),
        baseline_k=boundary["coefficient_kcal_mol_A2"],
        inserts=inserts,
        wc_pairs=pairs,
        image_edges=bonds + image_pairs,
        alignment="Proper rigid fit of fixed outer-shell P atoms to control source pose",
        source_hashes={str(p): digest(p) for p in sources},
        limitations=[
            "Local frame removes rigid motion of shell relative to whole model.",
            "Control relaxation is not an equilibrium calibration ensemble.",
            "Full NPT and cropped NVT differ; assess density and salt separately.",
            "No native input changes or simulation execution.",
        ],
    )
    out = fresh(out)
    np.savez_compressed(out / "reference.npz", coordinates_A=reference)
    plan["reference_npz_sha256"] = digest(out / "reference.npz")
    write_json(out / "plan.json", plan)
    return {
        "plan": str(out / "plan.json"),
        "core_atoms": len(core),
        "shell_atoms": len(plan["shell_indices"]),
        "alignment_atoms": len(anchors),
        "inserts": inserts,
    }


def profile(
    plan_path, dcd, kind, out, start=0, stop=None, max_frames=32, trial_job=None
):
    plan_path, dcd = Path(plan_path), Path(dcd).resolve()
    p = read_json(plan_path)
    ref_path = plan_path.parent / "reference.npz"
    if digest(ref_path) != p["reference_npz_sha256"]:
        raise ValueError("Reference coordinate hash mismatch")
    if kind not in {"reference", "control"} or not 8 <= max_frames <= 512:
        raise ValueError("Require reference/control and 8–512 frames")
    package = Path(p[f"{kind}_package"])
    mapping = p[f"{kind}_indices"]
    expected_atoms = p[f"{kind}_natoms"]
    if trial_job is None:
        psfs = [
            Path(path)
            for path in p["source_hashes"]
            if Path(path).parent == package and Path(path).suffix == ".psf"
        ]
        if len(psfs) != 1 or digest(psfs[0]) != p["source_hashes"][str(psfs[0])]:
            raise ValueError("Planned PSF identity changed")
    if trial_job is not None:
        if kind != "control":
            raise ValueError("A trial job must use the control role")
        job = read_json(Path(trial_job) / "job.json")
        package = (Path(trial_job) / job["package_subdir"]).resolve()
        recipe = read_json(package / "submodel.json")
        if (
            recipe["box"] != p["box"]
            or recipe["retained_source_indices"] != [a["index"] for a in p["atoms"]]
            or recipe["shell_boundary"]["fixed_output_indices"] != p["fixed_indices"]
            or recipe["mobile_output_indices"] != p["core_indices"]
            or recipe["shell_boundary"]["restrained_output_indices"]
            != p["shell_indices"]
            or recipe["shell_boundary"]["kind"] != "uniform"
            or recipe["shell_boundary"]["coefficient_kcal_mol_A2"] != p["baseline_k"]
        ):
            raise ValueError("Trial boundary selection differs from the plan")
        expected_atoms, atoms = psf_atoms(package / f"{job['name_stem']}.psf")
        lookup = {tuple(a["key"]): a for a in atoms}
        mapping = []
        for source in p["atoms"]:
            atom = lookup.get(tuple(source["key"]))
            if (
                atom is None
                or atom["atom_type"] != source["atom_type"]
                or abs(atom["charge"] - source["charge"]) > 1e-6
            ):
                raise ValueError("Trial atom identity differs from the plan")
            mapping.append(atom["index"])
    layout = read_layout(dcd)
    if layout.n_atoms != expected_atoms:
        raise ValueError("DCD atom count does not match planned package")
    if not dcd.is_relative_to(package):
        raise ValueError("DCD must belong to the planned package")
    conf = package / (re.sub(r"\.cont\d+$", "", dcd.stem) + ".conf")
    if not conf.is_file() or not re.search(
        r"^\s*wrapAll\s+off\s*(?:#.*)?$", conf.read_text(), re.M | re.I
    ):
        raise ValueError("This pilot requires a matching config with wrapAll off")
    config_text = conf.read_text()
    native_options = {}
    for key in (
        "langevinTemp",
        "langevinDamping",
        "timestep",
        "langevinPiston",
        "constraints",
        "extraBondsFile",
    ):
        match = re.search(r"^\s*" + key + r"\s+([^\n#]+)", config_text, re.M | re.I)
        native_options[key] = match[1].strip() if match else None
    stop = layout.n_frames if stop is None else stop
    if not 0 <= start < stop <= layout.n_frames or stop - start < 8:
        raise ValueError("Need at least eight available frames in [start, stop)")
    frames = np.unique(
        np.linspace(start, stop - 1, min(max_frames, stop - start), dtype=int)
    )
    reference = np.load(ref_path)["coordinates_A"]
    if (
        len(frames) * layout.frame_bytes > 2 * 1024**3
        or len(frames) * len(mapping) * 3 * 8 > 128 * 1024**2
    ):
        raise ValueError(
            "Pilot exceeds 2 GiB reads or 128 MiB sampled-coordinate budget; reduce frames"
        )
    positions, residuals, times = [], [], []
    frame_hash = hashlib.sha256()
    stat_before = dcd.stat()
    for frame in frames:
        xyz, cell = read_frame(dcd, layout, int(frame))
        x = xyz[mapping].astype(float)
        frame_hash.update(x.tobytes())
        dims = cell_to_dimensions(cell)
        check_images(x, dims, p["image_edges"])
        aligned, residual = register(x, reference, p["alignment_indices"])
        positions.append(box_coordinates(aligned, p["box"]))
        residuals.append(residual)
        times.append(layout.first_ps + frame * layout.delta_ps)
    stat_after = dcd.stat()
    if (stat_before.st_size, stat_before.st_mtime_ns) != (
        stat_after.st_size,
        stat_after.st_mtime_ns,
    ):
        raise ValueError(
            "Trajectory changed during analysis; use stable downloaded results"
        )
    x = np.asarray(positions)
    mean, cov, drift = moments(x)
    split = len(x) // 2
    train_mean, train_cov, _ = moments(x[:split])
    hold_mean, hold_cov, _ = moments(x[split:])
    traces = {}
    for i, insert in enumerate(p["inserts"]):
        traces[f"insert_{i}_c1_box_A"] = x[:, insert["c1_index"]].tolist()
        traces[f"insert_{i}_ring_centroid_box_A"] = (
            x[:, insert["ring_indices"]].mean(1).tolist()
        )
    for i, (a, b) in enumerate(p["wc_pairs"]):
        traces[f"core_wc_{i}_C1_distance_A"] = np.linalg.norm(
            x[:, a] - x[:, b], axis=1
        ).tolist()
    # Intrinsic orientation/contact observables for every pair of core inserts.
    normals, centres = [], []
    for insert in p["inserts"]:
        rings = x[:, insert["ring_indices"]]
        centres.append(rings.mean(1))
        _, _, vectors = np.linalg.svd(
            rings - rings.mean(1)[:, None, :], full_matrices=False
        )
        normals.append(vectors[:, -1])
    for i in range(len(normals)):
        for j in range(i):
            traces[f"inserts_{j}_{i}_centroid_distance_A"] = np.linalg.norm(
                centres[i] - centres[j], axis=1
            ).tolist()
            traces[f"inserts_{j}_{i}_abs_normal_dot"] = np.abs(
                np.sum(normals[i] * normals[j], axis=1)
            ).tolist()
    shell = p["shell_indices"]
    report = dict(
        schema="nadoc.shell-calibration-profile.v1",
        kind=kind,
        plan_sha256=digest(plan_path),
        dcd=str(dcd),
        dcd_size=stat_before.st_size,
        config_sha256=digest(conf),
        native_options=native_options,
        trial_job=str(trial_job) if trial_job else None,
        dcd_mtime_ns=stat_before.st_mtime_ns,
        sampled_coordinate_sha256=frame_hash.hexdigest(),
        frames=frames.tolist(),
        times_ps=times,
        layout=asdict(layout),
        read_budget_bytes=len(frames) * layout.frame_bytes,
        alignment_rmsd_A=residuals,
        median_alignment_rmsd_A=float(np.median(residuals)),
        median_shell_rmsf_A=float(
            np.median(np.sqrt(np.trace(cov[shell], axis1=1, axis2=2)))
        ),
        median_shell_half_mean_shift_A=float(np.median(drift[shell])),
        median_shell_mean_offset_from_preparation_A=float(
            np.median(
                np.linalg.norm(
                    mean[shell] - box_coordinates(reference, p["box"])[shell], axis=1
                )
            )
        ),
        crossover_observables=traces,
        qualification="Exploratory statistics only; no stationarity or effective-sample-size qualification",
        limitations=p["limitations"],
    )
    out = fresh(out)
    np.savez_compressed(
        out / "statistics.npz",
        mean_A=mean,
        covariance_A2=cov,
        half_mean_shift_A=drift,
        train_mean_A=train_mean,
        train_covariance_A2=train_cov,
        holdout_mean_A=hold_mean,
        holdout_covariance_A2=hold_cov,
    )
    report["statistics_sha256"] = digest(out / "statistics.npz")
    write_json(out / "profile.json", report)
    return {
        k: report[k]
        for k in [
            "kind",
            "median_shell_rmsf_A",
            "median_shell_half_mean_shift_A",
            "qualification",
        ]
    }


def compare(plan_path, reference_profile, control_profile, temperature, out):
    p = read_json(plan_path)
    reports, arrays = [], []
    for path, kind in [(reference_profile, "reference"), (control_profile, "control")]:
        path = Path(path)
        report = read_json(path)
        if report["kind"] != kind or report["plan_sha256"] != digest(plan_path):
            raise ValueError("Profiles must share this plan and expected roles")
        stats = path.parent / "statistics.npz"
        if digest(stats) != report["statistics_sha256"]:
            raise ValueError("Statistics hash mismatch")
        reports.append(report)
        arrays.append(np.load(stats))
    if any(
        float(r["native_options"].get("langevinTemp") or "nan") != temperature
        for r in reports
    ):
        raise ValueError("Fit temperature must match both native thermostat settings")
    shell = p["shell_indices"]
    target, trial = [a["train_covariance_A2"][shell] for a in arrays]
    candidate, raw = scalar_update(target, trial, p["baseline_k"], temperature)
    hold_target, hold_trial = [
        np.trace(a["holdout_covariance_A2"][shell], axis1=1, axis2=2) for a in arrays
    ]
    if (
        np.any(hold_target <= 1e-8)
        or not np.isfinite(np.r_[hold_target, hold_trial]).all()
    ):
        raise ValueError("Invalid holdout variance")
    out = fresh(out)
    result = dict(
        schema="nadoc.shell-calibration-candidate.v1",
        plan_sha256=digest(plan_path),
        status="UNVALIDATED_PROPOSAL_NOT_NATIVE_INPUT",
        temperature_K=temperature,
        convention="NAMD U=k*r^2, kcal/mol/Angstrom^2",
        gain=0.25,
        bounds=[0, 0.5],
        current_k=p["baseline_k"],
        shell_indices=shell,
        proposed_k=candidate.tolist(),
        unclipped_k=raw.tolist(),
        clipped_count=int(np.count_nonzero(raw != candidate)),
        profile_hashes=[digest(reference_profile), digest(control_profile)],
        mean_shift_A=np.linalg.norm(
            arrays[0]["mean_A"][shell] - arrays[1]["mean_A"][shell], axis=1
        ).tolist(),
        holdout_rmsf_ratio=np.sqrt(hold_trial / hold_target).tolist(),
        required_before_trial=[
            "Equilibrium production samples, matched temperature and protocol audit",
            "Choose matched start/reference policy; mean shifts are not corrected here",
            "Remote-only native preparation and execution with original provenance",
            "Core extra-base distribution validation; shell RMSF alone is insufficient",
        ],
    )
    write_json(out / "candidate.json", result)
    return {"candidate": str(out / "candidate.json"), "status": result["status"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--control-job", type=Path, required=True)
    prep.add_argument("--reference-job", type=Path, required=True)
    prof = sub.add_parser("profile")
    prof.add_argument("--plan", dest="plan_path", type=Path, required=True)
    prof.add_argument("--dcd", type=Path, required=True)
    prof.add_argument("--kind", choices=["reference", "control"], required=True)
    prof.add_argument("--start", type=int, default=0)
    prof.add_argument("--stop", type=int)
    prof.add_argument("--max-frames", type=int, default=32)
    prof.add_argument(
        "--trial-job",
        type=Path,
        help="Optional child/trial job with the same verified boundary selection",
    )
    comp = sub.add_parser("compare")
    comp.add_argument("--plan", dest="plan_path", type=Path, required=True)
    comp.add_argument("--reference-profile", type=Path, required=True)
    comp.add_argument("--control-profile", type=Path, required=True)
    comp.add_argument("--temperature", type=float, required=True)
    for cmd in (prep, prof, comp):
        cmd.add_argument("--out", type=Path, required=True)
    args = vars(parser.parse_args())
    command = args.pop("command")
    print(
        json.dumps(
            {"prepare": prepare, "profile": profile, "compare": compare}[command](
                **args
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
