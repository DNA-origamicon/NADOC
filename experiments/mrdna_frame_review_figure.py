"""Render the isolated MRDNA qualification evidence as an offline A/B review.

Only reads prepared evidence. No design, production code, or golden is written.
The full atom feeds, exact detector identities and junction metrics remain linked.
"""

from __future__ import annotations

import argparse
import gzip
import html
import json
from pathlib import Path
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Line3DCollection
import numpy as np


def read_bundle(path):
    with gzip.open(path, "rt") as stream:
        return json.load(stream)


def positions(model):
    return np.array([[a["x"], a["y"], a["z"]] for a in model["atoms"]])


def junction_defects(model, diagnostics, endpoints):
    """Exact verdicts touching either endpoint residue; retain detector identities."""

    def residue(atom):
        return (
            atom.strand_id,
            atom.helix_id,
            atom.bp_index,
            atom.direction,
            atom.copy_k,
            atom.crossover_id,
            atom.extra_base_k,
        )

    keys = {residue(model.atoms[i]) for i in endpoints}
    serials = {a.serial for a in model.atoms if residue(a) in keys}
    return {
        "clashes": [
            hit
            for hit in diagnostics["clashes"]
            if serials.intersection(hit["serials"])
        ],
        "piercings": [
            hit
            for hit in diagnostics["piercing"]["pierced"]
            if serials.intersection([*hit["bond_serials"], *hit["ring_serials"]])
        ],
    }


def render_plate(bundle, destination):
    fig = plt.figure(figsize=(16, 12))
    fig.subplots_adjust(left=0.03, right=0.97, bottom=0.06, top=0.87,
                        wspace=0.06, hspace=0.18)
    points = {side: positions(bundle[side]) for side in ("current", "candidate")}
    colors = {"current": "#2375bd", "candidate": "#bf327f"}
    combined = np.concatenate(list(points.values()))
    center = (combined.min(0) + combined.max(0)) / 2
    radius = max(np.ptp(combined, axis=0)) * 0.55
    axes = [fig.add_subplot(2, 2, i + 1, projection="3d") for i in range(4)]

    def draw(ax, side, alpha=1, keep=None):
        xyz = points[side]
        bonds = np.asarray(bundle[side]["bonds"], dtype=int)
        if keep is not None:
            bonds = bonds[np.all(keep[bonds], axis=1)]
        ax.add_collection3d(
            Line3DCollection(
                xyz[bonds], colors=colors[side], linewidths=0.45, alpha=alpha
            )
        )
        selected = xyz if keep is None else xyz[keep]
        ax.scatter(*selected.T, s=2, color=colors[side], alpha=alpha, depthshade=False)

    for ax, side in zip(axes, ("current", "candidate")):
        draw(ax, side)
        d = bundle[side]["diagnostics"]
        ax.set_title(
            f"{side.title()}\n{d['n_clashes']} clashes; {d['piercing']['n_pierced']} piercings; "
            f"{d['bonds']['n_overstretched']} bond flags",
            fontsize=10,
        )
    draw(axes[2], "current", 0.25)
    draw(axes[2], "candidate", 0.5)
    vectors = bundle["displacement"]["vectors"]
    if vectors:
        axes[2].add_collection3d(
            Line3DCollection(
                [[v["from"], v["to"]] for v in vectors],
                colors="#cc9c00",
                linewidths=0.4,
            )
        )
    axes[2].set_title("Same-frame overlay; yellow = actual displacement", fontsize=10)
    focus = None
    focus_serials = []
    caption = "No detected defect; full context"
    # Show introduced defects first: an existing contact must not hide a
    # candidate regression in the close-up.
    current = bundle["current"]["diagnostics"]
    candidate = bundle["candidate"]["diagnostics"]
    introduced = {
        "piercing": {"pierced": [h for h in candidate["piercing"]["pierced"]
            if not any(h["bond_serials"] == c["bond_serials"]
                       and h["ring_serials"] == c["ring_serials"]
                       for c in current["piercing"]["pierced"])]},
        "clashes": [h for h in candidate["clashes"]
                    if h["serials"] not in [c["serials"] for c in current["clashes"]]],
        "bonds": {"overstretched": [h for h in candidate["bonds"]["overstretched"]
            if h["serials"] not in [c["serials"] for c in current["bonds"]["overstretched"]]]},
    }
    for side, d in (("candidate", introduced), ("current", current), ("candidate", candidate)):
        if d["piercing"]["pierced"]:
            hit = d["piercing"]["pierced"][0]
            focus_serials = hit["bond_serials"] + hit["ring_serials"]
            focus = points[side][hit["ring_serials"]].mean(0)
            caption = f"{side.title()}: bond {hit['bond_serials']} / pierced ring {hit['ring_serials']}"
            break
        if d["clashes"]:
            hit = d["clashes"][0]
            focus_serials = hit["serials"]
            focus = points[side][hit["serials"]].mean(0)
            caption = f"{side.title()}: clashing atom serials {hit['serials']}"
            break
        if d["bonds"]["overstretched"]:
            hit = d["bonds"]["overstretched"][0]
            focus_serials = hit["serials"]
            focus = points[side][hit["serials"]].mean(0)
            caption = f"{side.title()}: flagged bond serials {hit['serials']}"
            break
    focus = center if focus is None else focus

    def highlight_segment(segment, color, width):
        # Clip long stretched bonds to the close-up cube without hiding the
        # segment crossing a ring. Retain the full endpoints in the linked data.
        start, end = segment
        direction = end - start
        lower, upper = 0.0, 1.0
        for i in range(3):
            if abs(direction[i]) < 1e-14:
                if abs(start[i] - focus[i]) > 1.2:
                    return
                continue
            a, b = sorted(((focus[i] - 1.2 - start[i]) / direction[i],
                           (focus[i] + 1.2 - start[i]) / direction[i]))
            lower, upper = max(lower, a), min(upper, b)
            if lower > upper:
                return
        clipped = np.array([start + lower * direction, start + upper * direction])
        axes[3].plot(*clipped.T, color=color, linewidth=width)

    for side in ("current", "candidate"):
        xyz = points[side]
        draw(axes[3], side, 0.35, np.all(np.abs(xyz - focus) < 1.2, axis=1))
        d = bundle[side]["diagnostics"]
        for hit in [*d["clashes"], *d["bonds"]["overstretched"]]:
            seg = xyz[hit["serials"]]
            if np.linalg.norm(seg.mean(0) - focus) < 1.2:
                highlight_segment(seg, colors[side], 2)
        for hit in d["piercing"]["pierced"]:
            ring = xyz[hit["ring_serials"]]
            if np.linalg.norm(ring.mean(0) - focus) < 1.2:
                highlight_segment(xyz[hit["bond_serials"]], colors[side], 3)
                for a, b in zip(ring, np.roll(ring, -1, axis=0)):
                    highlight_segment(np.array([a, b]), colors[side], 2)
    if len(focus_serials) == 2:
        a, b = focus_serials
        distances = [np.linalg.norm(points[s][a] - points[s][b])
                     for s in ("current", "candidate")]
        axes[3].text2D(0, 0.96,
            f"{a}: {bundle['current']['atoms'][a]['name']} — "
            f"{b}: {bundle['current']['atoms'][b]['name']}\n"
            f"Current {distances[0]:.8f} nm; Candidate {distances[1]:.8f} nm",
            transform=axes[3].transAxes, fontsize=9,
            bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "none"})
        for side in ("current", "candidate"):
            axes[3].scatter(*points[side][focus_serials].T, s=25,
                            color=colors[side], depthshade=False)
    axes[3].set_title(textwrap.fill(caption, 72)
                     + "\nBlue = Current; magenta = Candidate; close-up clips long bonds", fontsize=9)
    for i, ax in enumerate(axes):
        at, span = (focus, 1.2) if i == 3 else (center, radius)
        ax.set(
            xlim=(at[0] - span, at[0] + span),
            ylim=(at[1] - span, at[1] + span),
            zlim=(at[2] - span, at[2] + span),
            xlabel="x (nm)",
            ylabel="y (nm)",
            zlabel="z (nm)",
        )
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=20, azim=-55)
    fig.suptitle(
        bundle.get(
            "figure_title",
            f"MRDNA zero-step reconstruction — phase {bundle['phase_deg']}°\n"
            "Current: production MD-seed reconstruction. Candidate: isolated native-frame transport. No dynamics.",
        ),
        fontsize=13,
    )
    fig.savefig(destination, dpi=150)
    plt.close(fig)


def build_review(directory):
    report = json.loads((directory / "frame-qualification.json").read_text())
    zero_rows = [r for r in report["rows"] if r["motion"] == "zero"]
    choices = [zero_rows[0]]
    for verdict in ("n_clashes", "n_pierced"):

        def count(row):
            d = row["candidate_diagnostics"]
            return d["piercing"][verdict] if verdict == "n_pierced" else d[verdict]

        for row in (min(zero_rows, key=count), max(zero_rows, key=count)):
            if row not in choices:
                choices.append(row)
    sections = []
    for row in choices:
        bundle = read_bundle(directory / row["zero_step_artifact"])
        name = f"review-phase-{row['phase_deg']:03d}.png"
        render_plate(bundle, directory / name)
        bonds = "".join(
            "<tr><td>"
            + "</td><td>".join(
                html.escape(str(x))
                for x in [
                    j["serials"],
                    *(
                        f"{j['length_nm'][s]:.6f}"
                        for s in ("reference", "current", "candidate")
                    ),
                    f"{j['max_endpoint_displacement_nm']:.6f}",
                    f"{j['length_nm']['candidate'] - j['length_nm']['current']:+.6f}",
                    *(
                        f"{len(j['defects']['current'][kind])} → {len(j['defects']['candidate'][kind])}"
                        for kind in ("clashes", "piercings")
                    ),
                ]
            )
            + "</td></tr>"
            for j in bundle["junctions"]
        )
        sections.append(
            f"<h2>Phase {row['phase_deg']}°</h2><img src='{name}' alt='Current, Candidate, displacement and exact defect views'>"
            f"<p><a href='{row['zero_step_artifact']}'>All atoms, bonds, detector identities and displacements</a></p>"
            "<table><tr><th>Bond serials</th><th>Native reference (nm)</th><th>Current (nm)</th><th>Candidate (nm)</th><th>Max endpoint displacement (nm)</th><th>Δ length (nm)</th><th>Clashes</th><th>Piercings</th></tr>"
            + bonds
            + "</table>"
        )
    first = read_bundle(directory / zero_rows[0]["zero_step_artifact"])
    construction = "".join(f"<li>{html.escape(s)}</li>" for s in first["construction"])
    limits = "".join(f"<li>{html.escape(s)}</li>" for s in report["limits"])
    metrics = []
    for mode in ("zero", "rigid", "local_twist"):
        rows = [r for r in report["rows"] if r["motion"] == mode]
        metrics.append(
            f"<tr><td>{mode}</td><td>{len(rows)}</td>"
            + "".join(
                f"<td>{max(r[k] for r in rows):.9f}</td>"
                for k in (
                    "point_max_error_nm",
                    "rigid_atom_max_error_nm",
                    "all_atom_max_error_nm",
                )
            )
            + "</tr>"
        )
    page = (
        "<!doctype html><meta charset='utf-8'><title>MRDNA isolated frame review</title>"
        "<style>body{font:16px system-ui;max-width:1500px;margin:2rem auto;padding:1rem}img{width:100%}td,th{padding:.4rem;border:1px solid #bbb}table{border-collapse:collapse}h1,h2{margin-top:2rem}</style>"
        "<h1>MRDNA: zero-step frame reconstruction</h1><p><strong>Isolated diagnostic. No production change is authorized by this artifact.</strong></p>"
        "<p>Current reads the initial fine particles through the production MD-seed reconstruction (default smoothing). Candidate transports the native atom frames through the measured particle motion. "
        "With zero dynamics, compare both structures to the native reference; inspect the exact local contacts and bond lengths below. No feature-log operation or native saved design is changed.</p>"
        f"<h2>Construction</h2><ol>{construction}</ol><h2>Prescribed-motion qualification</h2>"
        "<p>Rigid: 17°, −31°, 67° rotations and (2.1, −0.9, 3.4) nm translation. Local twist: independent O-particle rotation with DNA centers held fixed. "
        "No dynamics or physical sampling was run. Flexible linker error is included in the all-atom column.</p>"
        "<table><tr><th>Motion</th><th>Phases</th><th>Max point error (nm)</th><th>Max rigid atom error (nm)</th><th>Max all-atom error (nm)</th></tr>"
        + "".join(metrics)
        + "</table>"
        + sections[0]
        + "<details><summary>Engineering controls across the phase sweep</summary>"
        + "".join(sections[1:])
        + "</details>"
        + f"<h2>Limits</h2><ul>{limits}</ul><p><a href='frame-qualification.json'>Full phase and motion evidence</a></p>"
    )
    (directory / "review.html").write_text(page)
    return directory / "review.html"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    print(build_review(parser.parse_args().directory))
