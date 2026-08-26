#!/usr/bin/env python3
"""Export Molecular-Placement-Audit-style views of representative 24hb trajectory pairs.

The four representatives are real stable DCD observations selected near 160, 121, 90,
and 60 degrees of directed slab-normal separation.  Each view contains the two insert
residues, five local base-pair levels on both helices, and directed template +Z arrows.
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.exp46_xb_placement.xb_map import (  # noqa: E402
    FrameJoiner, build_package_map, load_design,
)
from experiments.exp46_xb_placement.xb_observables import (  # noqa: E402
    INS_ATOMS, kabsch, template_atoms,
)

JOB = Path("/media/jojo/Archive/NADOC_archive/6950d3b79138")
PACKAGE = JOB / "package/24hb_1xT_namd_solvated"
PDB = PACKAGE / "24hb_1xT.pdb"
PSF = PACKAGE / "24hb_1xT_hmr.psf"
DCD = PACKAGE / "output/24hb_1xT_01_production_500ns_k0.dcd"
DESIGN = JOB / "design.json"
OUT = HERE / "data/pair_orientation_audit"
PLOTS = HERE / "plots"

SELECTIONS = (
    {
        "label": "Strongly opposed", "target_deg": 160.0, "sample": 464,
        "frame": 10208, "time_ns": 204.18,
        "lower": "103ece6f-67c3-4c86-b1e6-9b1fde77deaa",
        "upper": "8fdb431f-1974-48fc-943a-6f8ac39c0283",
    },
    {
        "label": "Ensemble-typical", "target_deg": 121.0, "sample": 321,
        "frame": 7062, "time_ns": 141.26,
        "lower": "85406cac-15d3-4f35-8315-f97221ca45d7",
        "upper": "38219493-cc31-44ba-9cb2-309e1d4a33bc",
    },
    {
        "label": "Near orthogonal", "target_deg": 90.0, "sample": 505,
        "frame": 11110, "time_ns": 222.22,
        "lower": "dbc17770-0f73-443d-a4cd-51b94aa7821a",
        "upper": "d085cfc1-9eb4-469a-a5f9-65f9e08ee4fd",
    },
    {
        "label": "Rare same hemisphere", "target_deg": 60.0, "sample": 484,
        "frame": 10648, "time_ns": 212.98,
        "lower": "3dad1467-f378-40a5-b1d3-3f9a893e5245",
        "upper": "b884c651-8b4f-475d-973f-6c16a2662004",
    },
)


def _unit(vector: np.ndarray) -> np.ndarray:
    return vector / np.linalg.norm(vector)


def _atom_rows(pm, segid: str, resid: int) -> list[int]:
    return sorted(row for (seg, res, _name), row in pm.rows.items()
                  if seg == segid and res == resid)


def _pose(pm, insert, xyz: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    names, local = template_atoms("DT")
    local_lookup = dict(zip(names, local))
    fit_names = [name for name in INS_ATOMS
                 if pm.row(insert.segid, insert.resid, name) is not None
                 and name in local_lookup]
    world = np.asarray([xyz[pm.row(insert.segid, insert.resid, name)] for name in fit_names])
    template = np.asarray([local_lookup[name] for name in fit_names])
    origin, rotation, rmsd = kabsch(template, world)
    ring = np.asarray([
        xyz[pm.row(insert.segid, insert.resid, name)]
        for name in ("N1", "C2", "N3", "C4", "C5", "C6")
    ])
    return ring.mean(axis=0), _unit(rotation[:, 2]), rmsd


def _view_basis(lower_center, upper_center, lower_normal, upper_normal) -> np.ndarray:
    x_axis = _unit(upper_center - lower_center)
    y_seed = lower_normal - upper_normal
    y_seed -= np.dot(y_seed, x_axis) * x_axis
    if np.linalg.norm(y_seed) < 1e-6:
        y_seed = lower_normal + upper_normal
        y_seed -= np.dot(y_seed, x_axis) * x_axis
    y_axis = _unit(y_seed)
    z_axis = _unit(np.cross(x_axis, y_axis))
    y_axis = _unit(np.cross(z_axis, x_axis))
    return np.column_stack((x_axis, y_axis, z_axis))


def _write_pdb(path: Path, rows: list[int], xyz: np.ndarray, atom_lines: list[str],
               chain: str) -> None:
    lines = []
    for serial, row in enumerate(rows, start=1):
        original = atom_lines[row]
        name = original[12:16]
        resname = original[17:20]
        resid = int(original[22:26])
        element = original[76:78].strip() or name.strip()[0]
        if element.upper() == "H" or name.strip().startswith("H"):
            continue
        x, y, z = xyz[row]
        lines.append(
            f"ATOM  {serial:5d} {name}{resname:>4s} {chain}{resid:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}{1.0:6.2f}{0.0:6.2f}          {element:>2s}"
        )
    path.write_text("\n".join(lines) + "\nEND\n")


def _write_bild(path: Path, lower_center: np.ndarray, upper_center: np.ndarray,
                lower_normal: np.ndarray, upper_normal: np.ndarray) -> None:
    def arrow(center, normal, color):
        end = center + 9.0 * normal
        return (
            f".color {color}\n"
            f".arrow {center[0]:.4f} {center[1]:.4f} {center[2]:.4f} "
            f"{end[0]:.4f} {end[1]:.4f} {end[2]:.4f} 0.34 0.72 0.90\n"
        )
    path.write_text(
        arrow(lower_center, lower_normal, "0.10 0.62 0.95")
        + arrow(upper_center, upper_normal, "1.00 0.38 0.12")
    )


def _render(panel_dir: Path, output: Path) -> None:
    commands = (
        f"open {panel_dir / 'context.pdb'}; "
        f"open {panel_dir / 'lower.pdb'}; open {panel_dir / 'upper.pdb'}; "
        f"open {panel_dir / 'normals.bild'}; "
        "hide cartoons; style #1-3 stick; "
        "color #1 #aeb8c2; color #2 #1597d4; color #3 #f26924; "
        "set bgColor white; lighting soft; graphics silhouettes true; "
        "view; zoom 1.18; "
        f"save {output} width 1500 height 1100 supersample 3 transparentBackground false; exit"
    )
    subprocess.run(
        ["chimerax", "--offscreen", "--nogui", "--exit", "--cmd", commands],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )


def main() -> int:
    import MDAnalysis as mda
    import matplotlib.pyplot as plt

    OUT.mkdir(parents=True, exist_ok=True)
    PLOTS.mkdir(parents=True, exist_ok=True)
    design = load_design(DESIGN)
    pm = build_package_map(design, PDB)
    inserts = {insert.crossover_id: insert for insert in pm.inserts}
    atom_lines = [line for line in PDB.read_text().splitlines()
                  if line.startswith(("ATOM", "HETATM"))]
    universe = mda.Universe(str(PSF), str(DCD))
    joiner = FrameJoiner(universe, pm, design, dna_selection="nucleic")
    if joiner.off != 0:
        raise ValueError(f"expected DNA rows to start at zero, got {joiner.off}")

    manifest = []
    panel_images = []
    for index, selection in enumerate(SELECTIONS, start=1):
        lower, upper = inserts[selection["lower"]], inserts[selection["upper"]]
        universe.trajectory[selection["frame"]]
        box = np.asarray(universe.dimensions[:3], dtype=float)
        xyz = joiner.positions(box)
        lower_center, lower_normal, lower_rmsd = _pose(pm, lower, xyz)
        upper_center, upper_normal, upper_rmsd = _pose(pm, upper, xyz)
        angle = float(np.degrees(np.arccos(np.clip(
            np.dot(lower_normal, upper_normal), -1.0, 1.0,
        ))))
        midpoint = 0.5 * (lower_center + upper_center)
        basis = _view_basis(lower_center, upper_center, lower_normal, upper_normal)
        xyz_view = (xyz - midpoint) @ basis
        lower_center = (lower_center - midpoint) @ basis
        upper_center = (upper_center - midpoint) @ basis
        lower_normal = lower_normal @ basis
        upper_normal = upper_normal @ basis

        local_residues = set()
        pair_bp = sorted((lower.src[1], upper.src[1]))
        for helix in {lower.src[0], lower.dst[0]}:
            for bp in range(pair_bp[0] - 2, pair_bp[1] + 3):
                for direction in ("FORWARD", "REVERSE"):
                    residue = pm.nt.get((helix, bp, direction))
                    if residue is not None:
                        local_residues.add(residue)
        lower_rows = _atom_rows(pm, lower.segid, lower.resid)
        upper_rows = _atom_rows(pm, upper.segid, upper.resid)
        context_rows = sorted({
            row for segid, resid in local_residues for row in _atom_rows(pm, segid, resid)
        } - set(lower_rows) - set(upper_rows))

        panel_dir = OUT / f"{index}_{selection['label'].lower().replace(' ', '_').replace('-', '_')}"
        panel_dir.mkdir(exist_ok=True)
        _write_pdb(panel_dir / "context.pdb", context_rows, xyz_view, atom_lines, "C")
        _write_pdb(panel_dir / "lower.pdb", lower_rows, xyz_view, atom_lines, "L")
        _write_pdb(panel_dir / "upper.pdb", upper_rows, xyz_view, atom_lines, "U")
        _write_bild(panel_dir / "normals.bild", lower_center, upper_center,
                    lower_normal, upper_normal)
        image_path = panel_dir / "render.png"
        _render(panel_dir, image_path)
        panel_images.append(image_path)
        manifest.append({
            **selection, "measured_angle_deg": angle,
            "lower_pose_rmsd_A": lower_rmsd, "upper_pose_rmsd_A": upper_rmsd,
            "lower_source": list(lower.src), "upper_source": list(upper.src),
            "local_context_residues": len(local_residues),
            "render": str(image_path.relative_to(HERE)),
        })

    (OUT / "manifest.json").write_text(json.dumps({
        "schema": "nadoc.exp55.pair-orientation-audit.v1",
        "source_job": str(JOB),
        "selection_note": (
            "Real stable observations chosen near four directed-normal separations; "
            "distinct crossover pairs, per-site resultant length >0.75, and both "
            "template-fit RMSDs <1 A."
        ),
        "colors": {"lower_bp": "blue", "higher_bp": "orange", "context": "gray"},
        "records": manifest,
    }, indent=2) + "\n")
    with (OUT / "manifest.csv").open("w", newline="") as handle:
        fields = ("label", "measured_angle_deg", "time_ns", "frame", "sample",
                  "lower", "upper", "lower_pose_rmsd_A", "upper_pose_rmsd_A", "render")
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in manifest:
            writer.writerow({key: row[key] for key in fields})

    fig, axes = plt.subplots(2, 2, figsize=(12.0, 8.8), constrained_layout=True)
    for ax, image_path, row in zip(axes.flat, panel_images, manifest):
        ax.imshow(plt.imread(image_path))
        ax.axis("off")
        ax.set_title(
            f"{row['label']}: {row['measured_angle_deg']:.1f}°\n"
            f"{row['time_ns']:.2f} ns · pair {row['lower'][:8]}/{row['upper'][:8]}",
            fontsize=11,
        )
    fig.suptitle(
        "24hb_1xT reciprocal extra-base pair orientations\n"
        "blue = lower-bp normal; orange = higher-bp normal",
        fontsize=15,
    )
    for suffix in ("png", "pdf"):
        fig.savefig(PLOTS / f"24hb_pair_orientation_audit.{suffix}",
                    dpi=300 if suffix == "png" else None)
    plt.close(fig)
    print(PLOTS / "24hb_pair_orientation_audit.png")
    print(OUT / "manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
