"""Repeatable, bounded offline comparisons; never runs an engine or changes inputs.

Create a sampling recipe with ``recipe`` and reprocess it with ``run`` into a
fresh output directory. Explicit frame indices keep repeated analyses comparable.
"""

import argparse
import csv
import hashlib
from pathlib import Path
import re

import numpy as np

from backend.core.dcd_fast import read_layout, read_frame, cell_to_dimensions
from .numerics import register, box_coordinates
from .workflow import read_json, write_json, digest, fresh, check_images


def options(path):
    result = {}
    for line in Path(path).read_text().splitlines():
        row = line.split("#")[0].split(None, 1)
        if len(row) == 2:
            result.setdefault(row[0].lower(), []).append(row[1].strip())
    return result


def one(opts, key):
    values = opts.get(key.lower(), [])
    if len(values) != 1:
        raise ValueError(f"Require one literal {key}, got {values}")
    return values[0]


def stage_times(layout, opts, elapsed):
    """Use executed config, not stale manifest steps; refuse ambiguous clocks."""
    dt = float(one(opts, "timestep")) / 1000
    steps = int(one(opts, "run"))
    first = int(opts.get("firsttimestep", ["0"])[0])
    local = (layout.istart + np.arange(layout.n_frames) * layout.nsavc - first) * dt
    if not np.isclose(layout.delta_ps, layout.nsavc * dt, rtol=1e-5):
        raise ValueError("DCD/config timestep mismatch")
    if local[0] < 0 or local[-1] > steps * dt + 1e-5:
        raise ValueError("DCD frames exceed actual stage duration")
    return elapsed + local, elapsed + steps * dt


def make_recipe(plan_path, reference_dcd):
    p = read_json(plan_path)
    package = Path(p["control_package"])
    elapsed, blocks = 0.0, []
    for stage in read_json(package / "manifest.json")["segments"]:
        name = stage["name"]
        conf = package / (name + ".conf")
        opts = options(conf)
        if "run" not in opts:
            continue
        dcd = package / "output" / (name + ".dcd")
        layout = read_layout(dcd)
        times, elapsed = stage_times(layout, opts, elapsed)
        if "_04_" in name and "MGHH_only" in name:
            if one(opts, "extraBondsFile") != "mgh_extrabonds.txt":
                raise ValueError("Final stage still has DNA extra bonds")
            blocks.append(
                dict(
                    dcd=str(dcd),
                    frames=list(range(layout.n_frames)),
                    times_ps=times.tolist(),
                )
            )
    if not blocks:
        raise ValueError("No final DNA-ENM-free stages")
    layout = read_layout(reference_dcd)
    if not np.isclose(layout.delta_ps, 10, rtol=1e-5) or layout.n_frames < 100:
        raise ValueError("Default recipe needs >=100 reference frames at 10 ps cadence")

    def ref_block(indices):
        return dict(
            dcd=str(Path(reference_dcd).resolve()),
            frames=list(map(int, indices)),
            times_ps=[float(layout.first_ps + i * layout.delta_ps) for i in indices],
        )

    groups = [
        dict(name="control_final_dense", kind="control", blocks=blocks),
        dict(
            name="control_final_10ps",
            kind="control",
            blocks=[
                dict(b, frames=[b["frames"][-1]], times_ps=[b["times_ps"][-1]])
                for b in blocks
            ],
        ),
        dict(
            name="reference_early_50ps", kind="reference", blocks=[ref_block(range(5))]
        ),
    ]
    for i, start in enumerate(
        np.linspace(layout.n_frames // 2, layout.n_frames - 5, 8, dtype=int)
    ):
        groups.append(
            dict(
                name=f"reference_late_50ps_{i}",
                kind="reference",
                blocks=[ref_block(range(start, start + 5))],
            )
        )
    groups.append(
        dict(
            name="reference_late_sparse",
            kind="reference",
            blocks=[
                ref_block(
                    np.linspace(
                        layout.n_frames // 2, layout.n_frames - 1, 24, dtype=int
                    )
                )
            ],
        )
    )
    return dict(
        schema="nadoc.submodel-comparison-recipe.v1",
        plan=str(Path(plan_path).resolve()),
        groups=groups,
        notes=[
            "50 ps acquisition windows have five saved frames spanning 40 ps at 10 ps cadence.",
            "Control dense window is relaxation, not an equilibrated ensemble.",
            "Late sparse reference measures long-timescale heterogeneity, not matched-window kinetics.",
        ],
    )


def statistics(x, reference, p):
    mean = x.mean(0)
    rmsf = np.sqrt(np.var(x, axis=0, ddof=1).sum(1))
    groups = {
        "core_heavy": [
            i for i in p["core_indices"] if not p["atoms"][i]["key"][3].startswith("H")
        ],
        "shell_heavy": p["shell_indices"],
        "outer_P": p["alignment_indices"],
    }
    metrics = {}
    for name, indices in groups.items():
        delta = mean[indices] - reference[indices]
        metrics[name] = dict(
            median_rmsf_A=float(np.median(rmsf[indices])),
            mean_pose_rmsd_A=float(np.sqrt(np.mean(np.sum(delta**2, axis=1)))),
            half_mean_shift_rms_A=float(
                np.sqrt(
                    np.mean(
                        np.sum(
                            (
                                x[: len(x) // 2, indices].mean(0)
                                - x[len(x) // 2 :, indices].mean(0)
                            )
                            ** 2,
                            axis=1,
                        )
                    )
                )
            ),
        )
    anchors = mean[p["alignment_indices"]]
    metrics["outer_P"]["principal_radii_A"] = np.sqrt(
        np.linalg.eigvalsh(
            (anchors - anchors.mean(0)).T @ (anchors - anchors.mean(0)) / len(anchors)
        )
    ).tolist()
    centres, normals, traces = [], [], {}
    for insert in p["inserts"]:
        rings = x[:, insert["ring_indices"]]
        centres.append(rings.mean(1))
        normals.append(
            np.linalg.svd(rings - rings.mean(1)[:, None], full_matrices=False)[2][:, -1]
        )
    for i in range(len(centres)):
        for j in range(i):
            delta = centres[i] - centres[j]
            traces[f"insert_{j}_{i}_distance_A"] = np.linalg.norm(
                delta, axis=1
            ).tolist()
            traces[f"insert_{j}_{i}_abs_normal_dot"] = np.abs(
                np.sum(normals[i] * normals[j], axis=1)
            ).tolist()
    for i, (a, b) in enumerate(p["wc_pairs"]):
        traces[f"wc_{i}_C1_distance_A"] = np.linalg.norm(
            x[:, a] - x[:, b], axis=1
        ).tolist()
    return metrics, traces, mean, rmsf


def sampling_budget(requests, layouts, n_atoms):
    byte_count = sum(
        len(frames) * layouts[path].frame_bytes for path, frames in requests.items()
    )
    coord_bytes = sum(map(len, requests.values())) * n_atoms * 3 * 8
    if byte_count > 2 * 1024**3 or coord_bytes > 128 * 1024**2:
        raise ValueError(
            "Sampling exceeds global 2 GiB read / 128 MiB selected-coordinate budget"
        )
    return byte_count


def run(recipe_path, out):
    recipe = read_json(recipe_path)
    names = [g["name"] for g in recipe["groups"]]
    if len(set(names)) != len(names) or not {
        "control_final_10ps",
        "reference_late_sparse",
    } <= set(names):
        raise ValueError(
            "Need distinct group names and control/reference summary groups"
        )
    plan_path = Path(recipe["plan"])
    p = read_json(plan_path)
    for path, expected in p["source_hashes"].items():
        if digest(path) != expected:
            raise ValueError(f"Plan input changed: {path}; prepare a new plan")
    refpath = plan_path.parent / "reference.npz"
    if digest(refpath) != p["reference_npz_sha256"]:
        raise ValueError("Reference coordinates changed")
    reference = np.load(refpath)["coordinates_A"]
    boxref = box_coordinates(reference, p["box"])
    requests, roles, layouts, configs, stamps = {}, {}, {}, {}, {}
    dependencies = {}
    for group in recipe["groups"]:
        kind = group["kind"]
        if kind not in ("reference", "control"):
            raise ValueError("Unknown group role")
        for block in group["blocks"]:
            path = str(Path(block["dcd"]).resolve())
            if path in roles and roles[path] != kind:
                raise ValueError("Conflicting DCD roles")
            package = Path(p[f"{kind}_package"])
            if not Path(path).is_relative_to(package):
                raise ValueError("DCD outside planned package")
            roles[path] = kind
            layout = layouts.setdefault(path, read_layout(path))
            if layout.n_atoms != p[f"{kind}_natoms"]:
                raise ValueError("DCD/PSF atom count mismatch")
            if len(block["frames"]) != len(block["times_ps"]):
                raise ValueError("Frame/time count mismatch")
            if any(
                type(i) is not int or not 0 <= i < layout.n_frames
                for i in block["frames"]
            ):
                raise ValueError("Invalid frame index")
            requests.setdefault(path, set()).update(block["frames"])
            conf = package / (re.sub(r"\.cont\d+$", "", Path(path).stem) + ".conf")
            opts = options(conf)
            if one(opts, "wrapAll").lower() != "off":
                raise ValueError("Requires wrapAll off")
            configs[str(conf)] = dict(sha256=digest(conf), options=opts)
            for key in (
                "structure",
                "parameters",
                "extrabondsfile",
                "consref",
                "conskfile",
                "fixedatomsfile",
            ):
                for value in opts.get(key, []):
                    dependency = (package / value).resolve()
                    if (
                        not dependency.is_relative_to(package)
                        or not dependency.is_file()
                    ):
                        raise ValueError(f"Unresolved native dependency: {value}")
                    if str(dependency) not in dependencies:
                        dependencies[str(dependency)] = digest(dependency)
            stat = Path(path).stat()
            stamps[path] = dict(size=stat.st_size, mtime_ns=stat.st_mtime_ns)
    read_bytes = sampling_budget(requests, layouts, len(reference))
    out = fresh(out)
    cache, residuals, sample_hashes = {}, {}, {}
    for path, indices in requests.items():
        h = hashlib.sha256()
        mapping = p[f"{roles[path]}_indices"]
        for i in sorted(indices):
            xyz, cell = read_frame(path, layouts[path], i)
            selected = xyz[mapping].astype(float)
            h.update(selected.tobytes())
            check_images(selected, cell_to_dimensions(cell), p["image_edges"])
            aligned, residual = register(selected, reference, p["alignment_indices"])
            cache[path, i] = box_coordinates(aligned, p["box"])
            residuals[path, i] = residual
        sample_hashes[path] = h.hexdigest()
        print(f"Read {len(indices)} frames: {Path(path).name}", flush=True)
    results, means = {}, {}
    with (out / "residue_metrics.csv").open("w") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "group",
                "segid",
                "resid",
                "resname",
                "heavy_atoms",
                "median_rmsf_A",
                "mean_pose_rmsd_A",
            ]
        )
        residues = {}
        for i, atom in enumerate(p["atoms"]):
            if not atom["key"][3].startswith("H"):
                residues.setdefault(tuple(atom["key"][:3]), []).append(i)
        for group in recipe["groups"]:
            keys = [
                (str(Path(b["dcd"]).resolve()), i)
                for b in group["blocks"]
                for i in b["frames"]
            ]
            if len(keys) < 4 or len(set(keys)) != len(keys):
                raise ValueError("Groups need >=4 distinct frames")
            times = [t for b in group["blocks"] for t in b["times_ps"]]
            if not np.all(np.diff(times) > 0):
                raise ValueError("Group clock must be strictly increasing")
            x = np.array([cache[k] for k in keys])
            metrics, traces, mean, rmsf = statistics(x, boxref, p)
            name = group["name"]
            results[name] = dict(
                frames=len(x),
                times_ps=times,
                metrics=metrics,
                traces=traces,
                median_anchor_fit_rmsd_A=float(np.median([residuals[k] for k in keys])),
            )
            means[name] = mean
            for key, ids in residues.items():
                writer.writerow(
                    [
                        name,
                        *key,
                        len(ids),
                        float(np.median(rmsf[ids])),
                        float(
                            np.sqrt(
                                np.mean(np.sum((mean[ids] - boxref[ids]) ** 2, axis=1))
                            )
                        ),
                    ]
                )
    for path, stamp in stamps.items():
        stat = Path(path).stat()
        if stamp != dict(size=stat.st_size, mtime_ns=stat.st_mtime_ns):
            raise ValueError("Trajectory changed during processing")
    offsets = {}
    for name, mean in means.items():
        offsets[name] = {
            label: float(
                np.sqrt(
                    np.mean(
                        np.sum(
                            (mean[indices] - means["control_final_10ps"][indices]) ** 2,
                            axis=1,
                        )
                    )
                )
            )
            for label, indices in [
                ("core", p["core_indices"]),
                ("shell", p["shell_indices"]),
                ("outer_P", p["alignment_indices"]),
            ]
        }
    report = dict(
        schema="nadoc.submodel-comparison.v1",
        recipe=recipe,
        recipe_sha256=digest(recipe_path),
        plan_sha256=digest(plan_path),
        code_hashes={
            str(Path(__file__).with_name(f)): digest(Path(__file__).with_name(f))
            for f in ("comparison.py", "workflow.py", "numerics.py")
        },
        read_bytes=read_bytes,
        trajectories=stamps,
        sampled_coordinate_hashes=sample_hashes,
        configs=configs,
        inserts=p["inserts"],
        groups=results,
        mean_offsets_from_control_A=offsets,
        limitations=p["limitations"]
        + recipe["notes"]
        + [
            "Five-frame windows do not establish convergence; no effective sample size or confidence intervals.",
            "No restraint coefficient correction is inferred from unequal-duration or relaxation variances.",
        ],
    )
    report["native_dependency_hashes"] = dependencies
    write_json(out / "comparison.json", report)
    with (out / "observable_summary.csv").open("w") as stream:
        writer = csv.writer(stream)
        writer.writerow(
            ["group", "observable", "mean", "sample_sd", "min", "max", "samples"]
        )
        for name, group in results.items():
            for observable, values in group["traces"].items():
                writer.writerow(
                    [
                        name,
                        observable,
                        np.mean(values),
                        np.std(values, ddof=1),
                        min(values),
                        max(values),
                        len(values),
                    ]
                )
    write_json(out / "recipe.json", recipe)
    plot(report, out / "comparison.svg")
    write_json(
        out / "outputs.json", {f.name: digest(f) for f in out.iterdir() if f.is_file()}
    )
    return dict(output=str(out), read_bytes=read_bytes, groups=len(results))


def plot(report, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    groups = report["groups"]
    short = [v for k, v in groups.items() if k.startswith("reference_late_50ps_")]
    labels = ["core_heavy", "shell_heavy", "outer_P"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for i, label in enumerate(labels):
        vals = [v["metrics"][label]["median_rmsf_A"] for v in short]
        axes[0].plot([i] * len(vals), vals, "o", color="tab:blue", alpha=0.5)
    axes[0].plot(
        range(3),
        [groups["control_final_10ps"]["metrics"][k]["median_rmsf_A"] for k in labels],
        "s-",
        color="tab:orange",
        label="Submodel final 50 ps",
    )
    axes[0].plot(
        [], [], "o", color="tab:blue", label="Full model: 8 late 50 ps windows"
    )
    axes[0].set(
        xticks=range(3),
        xticklabels=["Core heavy", "Shell heavy", "Outer P"],
        ylabel="Median atomic RMSF (Å)",
        title="Matched cadence: 5 samples per window",
    )
    axes[0].legend(fontsize=8)
    names = [
        k
        for k in groups["control_final_10ps"]["traces"]
        if k.startswith("insert_") and k.endswith("_distance_A")
    ]
    for kind, color, offset, label in [
        ("control_final_10ps", "tab:orange", -0.12, "Submodel final 50 ps"),
        ("reference_late_sparse", "tab:blue", 0.12, "Full model late 107.8 ns"),
    ]:
        for i, name in enumerate(names):
            vals = np.array(groups[kind]["traces"][name])
            axes[1].errorbar(
                i + offset,
                vals.mean(),
                yerr=[[vals.mean() - vals.min()], [vals.max() - vals.mean()]],
                fmt="o",
                color=color,
                label=label if i == 0 else None,
            )
    axes[1].set(
        xticks=range(len(names)),
        xticklabels=[
            k.replace("insert_", "").replace("_distance_A", "").replace("_", "–")
            for k in names
        ],
        ylabel="Ring-centroid separation (Å)",
        title="Means and sampled ranges (unequal durations)",
    )
    axes[1].legend(fontsize=8)
    fig.savefig(path)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    create = subs.add_parser("recipe")
    create.add_argument("--plan", required=True)
    create.add_argument("--reference-dcd", required=True)
    create.add_argument("--out", required=True)
    process = subs.add_parser("run")
    process.add_argument("--recipe", required=True)
    process.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "recipe":
        if Path(args.out).exists():
            raise ValueError("Recipe already exists")
        write_json(args.out, make_recipe(args.plan, args.reference_dcd))
    else:
        print(run(args.recipe, args.out))


if __name__ == "__main__":
    main()
