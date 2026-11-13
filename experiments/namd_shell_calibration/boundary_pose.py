"""Analyze existing trajectory poses; never author or publish a molecular model.

Choose an observed medoid from an explicit sample. Quantify why moving boundary
atoms alone is different from retaining a coherent frame. Mixed-frame endpoint
bond distances are arithmetic diagnostics, never an exported candidate structure.
"""

import argparse
from pathlib import Path
import numpy as np
from backend.core.dcd_fast import read_layout, read_frame, cell_to_dimensions
from .workflow import read_json, write_json, fresh, digest, check_images, retained_bonds
from .numerics import register, box_coordinates


def analyze(plan_path, recipe_path, out):
    p = read_json(plan_path)
    recipe = read_json(recipe_path)
    for path, expected in p["source_hashes"].items():
        if digest(path) != expected:
            raise ValueError("Plan input changed")
    refpath = Path(plan_path).parent / "reference.npz"
    if digest(refpath) != p["reference_npz_sha256"]:
        raise ValueError("Reference coordinates changed")
    ref = np.load(refpath)["coordinates_A"]
    group = next(g for g in recipe["groups"] if g["name"] == "reference_late_sparse")
    control_group = next(
        g for g in recipe["groups"] if g["name"] == "control_final_dense"
    )
    b = control_group["blocks"][-1]
    sources = [("control", b["dcd"], b["frames"][-1], b["times_ps"][-1])]
    sources += [
        ("reference", b["dcd"], i, t)
        for b in group["blocks"]
        for i, t in zip(b["frames"], b["times_ps"])
    ]
    layouts = {path: read_layout(path) for _, path, _, _ in sources}
    read_bytes = sum(layouts[path].frame_bytes for _, path, _, _ in sources)
    if read_bytes > 2 * 1024**3 or len(sources) * len(ref) * 24 > 128 * 1024**2:
        raise ValueError("Read/memory budget exceeded")
    stamps = {
        path: (Path(path).stat().st_size, Path(path).stat().st_mtime_ns)
        for path in layouts
    }
    xs = []
    for kind, path, frame, _ in sources:
        if layouts[path].n_atoms != p[kind + "_natoms"]:
            raise ValueError("Wrong topology")
        xyz, cell = read_frame(path, layouts[path], frame)
        x = xyz[p[kind + "_indices"]].astype(float)
        check_images(x, cell_to_dimensions(cell), p["image_edges"])
        aligned, _ = register(x, ref, p["alignment_indices"])
        xs.append(box_coordinates(aligned, p["box"]))
    for path, stamp in stamps.items():
        if stamp != (Path(path).stat().st_size, Path(path).stat().st_mtime_ns):
            raise ValueError("Trajectory changed")
    current = xs[0]
    sample = np.array(xs[1:])
    anchors = sample[:, p["alignment_indices"]]
    distances = np.array(
        [
            [np.sqrt(np.mean(np.sum((a - b) ** 2, axis=1))) for b in anchors]
            for a in anchors
        ]
    )
    chosen = int(np.argmin(distances.mean(1)))
    observed = sample[chosen]
    edges = np.asarray(
        retained_bonds(
            Path(p["control_package"]) / "submodel_source/full.psf",
            [a["index"] for a in p["atoms"]],
        )
    )
    current_lengths = np.linalg.norm(
        current[edges[:, 0]] - current[edges[:, 1]], axis=1
    )
    observed_lengths = np.linalg.norm(
        observed[edges[:, 0]] - observed[edges[:, 1]], axis=1
    )
    tests = {}
    for name, ids in [
        ("fixed_only", p["fixed_indices"]),
        ("all_noncore", sorted(set(range(len(ref))) - set(p["core_indices"]))),
    ]:
        mask = np.zeros(len(ref), bool)
        mask[ids] = True
        crossing = mask[edges[:, 0]] != mask[edges[:, 1]]
        e = edges[crossing]
        # Compare endpoints from their original trajectories; do not construct a hybrid molecule.
        lengths = np.linalg.norm(
            np.where(mask[e[:, 0], None], observed[e[:, 0]], current[e[:, 0]])
            - np.where(mask[e[:, 1], None], observed[e[:, 1]], current[e[:, 1]]),
            axis=1,
        )
        rank = np.argsort(lengths)[::-1][:10]
        tests[name] = dict(
            crossing_bonds=len(e),
            max_mixed_endpoint_distance_A=float(lengths.max()),
            count_over_2A=int(np.sum(lengths > 2)),
            current_max_A=float(current_lengths[crossing].max()),
            observed_max_A=float(observed_lengths[crossing].max()),
            longest_current_bond=dict(
                atoms=[
                    p["atoms"][int(a)]["key"]
                    for a in e[int(np.argmax(current_lengths[crossing]))]
                ],
                current_A=float(current_lengths[crossing].max()),
                observed_A=float(
                    observed_lengths[crossing][
                        int(np.argmax(current_lengths[crossing]))
                    ]
                ),
            ),
            worst=[
                dict(
                    atoms=[p["atoms"][int(a)]["key"] for a in e[i]],
                    mixed_A=float(lengths[i]),
                    current_A=float(current_lengths[crossing][i]),
                    observed_A=float(observed_lengths[crossing][i]),
                )
                for i in rank
            ],
        )
    junctions = []
    for junction in sorted(set(i["crossover_id"] for i in p["inserts"])):
        ins = [i for i in p["inserts"] if i["crossover_id"] == junction]
        ids = [
            a
            for a, record in enumerate(p["atoms"])
            if any(
                record["key"][0] == i["segid"]
                and abs(int(record["key"][1]) - i["resid"]) <= 1
                for i in ins
            )
        ]
        local = np.isin(edges[:, 0], ids) & np.isin(edges[:, 1], ids)
        centroid = lambda x, i: x[i["ring_indices"]].mean(0)
        junctions.append(
            dict(
                crossover_id=junction,
                residues=[f"{i['segid']}:{i['resid']}" for i in ins],
                retained_atom_rms_displacement_A=float(
                    np.sqrt(
                        np.mean(np.sum((observed[ids] - current[ids]) ** 2, axis=1))
                    )
                ),
                current_max_bond_A=float(current_lengths[local].max()),
                observed_max_bond_A=float(observed_lengths[local].max()),
                current_insert_distance_A=float(
                    np.linalg.norm(
                        centroid(current, ins[0]) - centroid(current, ins[1])
                    )
                ),
                observed_insert_distance_A=float(
                    np.linalg.norm(
                        centroid(observed, ins[0]) - centroid(observed, ins[1])
                    )
                ),
            )
        )
    out = fresh(out)
    report = dict(
        status="OBSERVED_TRAJECTORY_COMPARISON_NOT_AUTHORED_CANDIDATE",
        plan_sha256=digest(plan_path),
        recipe_sha256=digest(recipe_path),
        code_sha256=digest(__file__),
        read_bytes=read_bytes,
        source_stamps=stamps,
        current_source=sources[0],
        observed_source=sources[chosen + 1],
        selection="Observed medoid minimizing average outer-P RMSD within the fixed-outer-P aligned late sparse sample; no averaging of molecular coordinates.",
        sampled_frames=len(sample),
        medoid_mean_distance_A=float(distances.mean(1)[chosen]),
        outer_P_pose_rmsd_A=float(
            np.sqrt(
                np.mean(
                    np.sum(
                        (
                            current[p["alignment_indices"]]
                            - observed[p["alignment_indices"]]
                        )
                        ** 2,
                        axis=1,
                    )
                )
            )
        ),
        endpoint_diagnostics=tests,
        junctions=junctions,
        recommendation="Investigate coherent whole-frame initialization of all retained atoms and restraint references; do not transplant outer-shell coordinates alone.",
        limitations=[
            "No candidate package, changed NADOC structure, or simulation was produced.",
            "Medoid is representative only of these sampled frames, not proof of equilibrium.",
            "No clash/piercing acceptance claim; molecular promotion needs its separate authoring/review path.",
        ],
    )
    write_json(out / "assessment.json", report)
    draw(current, observed, p, edges, out / "observed-poses.png")
    write_json(
        out / "outputs.json", {f.name: digest(f) for f in out.iterdir() if f.is_file()}
    )
    return report


def draw(current, observed, p, edges, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(12, 9), constrained_layout=True)
    for col, (x, label) in enumerate(
        [
            (current, "Current submodel: final 205 ps frame"),
            (observed, "Observed full-model medoid: no geometry edits"),
        ]
    ):
        for row, (a, b) in enumerate([(0, 1), (0, 2)]):
            ax = axes[row, col]
            ids = p["alignment_indices"]
            ax.scatter(
                x[ids, a],
                x[ids, b],
                s=9,
                color="gray",
                alpha=0.5,
                label="Fixed-layer P identities",
            )
            for n, insert in enumerate(p["inserts"]):
                ids = [
                    i
                    for i, atom in enumerate(p["atoms"])
                    if atom["key"][0] == insert["segid"]
                    and int(atom["key"][1]) == insert["resid"]
                ]
                ring = insert["ring_indices"]
                color = ["tab:blue", "tab:orange", "tab:green", "tab:red"][n]
                ax.scatter(x[ids, a], x[ids, b], s=10, alpha=0.7, color=color)
                ax.scatter(
                    x[ring, a],
                    x[ring, b],
                    s=22,
                    color=color,
                    label=f"{insert['segid']}:{insert['resid']} ring",
                )
                for i, j in edges[
                    np.isin(edges[:, 0], ids) & np.isin(edges[:, 1], ids)
                ]:
                    ax.plot(
                        x[[i, j], a], x[[i, j], b], color="black", lw=0.5, alpha=0.5
                    )
            ax.set(
                title=label,
                xlabel="Box X (Å)",
                ylabel="Box " + ("Y" if b == 1 else "Z") + " (Å)",
                xlim=(-65, 65),
                ylim=(-65, 65),
                aspect="equal",
            )
            if row == 0:
                ax.legend(fontsize=7)
    fig.suptitle(
        "Existing trajectories in one rigid outer-P frame; orthographic projections"
    )
    fig.savefig(path, dpi=130)
    fig.savefig(path.with_suffix(".svg"))
    plt.close(fig)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--recipe", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(analyze(args.plan, args.recipe, args.out))
