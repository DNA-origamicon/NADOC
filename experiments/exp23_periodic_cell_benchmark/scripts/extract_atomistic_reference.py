"""Attach MD-derived all-atom coordinates to a NADOC design.

The ordinary NADOC atomistic path rebuilds heavy atoms from local templates.
For MD troubleshooting, that is exactly the wrong provenance: we want CAD to
show/export the actual coordinates from a relaxed frame, while keeping the
NADOC topology and atom metadata.

This script copies atom identity/bonds from ``build_atomistic_model(design)``
and replaces coordinates with a frame from a NAMD/GROMACS trajectory whose DNA
atoms are in the same order as the NADOC export.  The result is a .nadoc file
with ``design.atomistic_reference`` populated.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from backend.core.atomistic import (
    atomistic_model_from_reference,
    atomistic_reference_topology_hash,
    build_atomistic_model,
)
from backend.core.models import AtomisticReference, AtomisticReferenceAtom, Design
from backend.core.pdb_export import export_pdb
from backend.core.periodic_cell import _detect_periodic_start, _slice_to_bp_range
from backend.core.sequences import assign_consensus_sequence


def _load_design(path: Path) -> Design:
    return Design.model_validate(json.load(path.open()))


def _periodic_slice(design: Design, periods: int, bp_start: int | None) -> Design:
    if bp_start is None:
        bp_start = _detect_periodic_start(design, periods)
    bp_count = periods * 21
    sliced = _slice_to_bp_range(design, bp_start, bp_start + bp_count)
    sliced, _ = assign_consensus_sequence(design, sliced, bp_start, bp_count)
    return sliced


def _positions_from_trajectory(topology: Path, trajectory: Path, frame: int) -> np.ndarray:
    try:
        import MDAnalysis as mda
    except ImportError as exc:
        raise SystemExit(
            "MDAnalysis is required to read trajectories. Install MDAnalysis or "
            "provide --coordinate-pdb instead."
        ) from exc

    u = mda.Universe(str(topology), str(trajectory))
    if frame < 0:
        frame = len(u.trajectory) + frame
    u.trajectory[frame]
    return np.asarray(u.atoms.positions, dtype=float) / 10.0


def _box_from_pdb_cryst1(path: Path | None) -> np.ndarray | None:
    if path is None or path.suffix.lower() != ".pdb" or not path.exists():
        return None
    with path.open(errors="replace") as fh:
        for line in fh:
            if line.startswith("CRYST1") and len(line) >= 33:
                try:
                    return np.array([
                        float(line[6:15]) / 10.0,
                        float(line[15:24]) / 10.0,
                        float(line[24:33]) / 10.0,
                    ])
                except ValueError:
                    return None
    return None


def _positions_from_pdb(path: Path) -> np.ndarray:
    coords: list[list[float]] = []
    with path.open(errors="replace") as fh:
        for line in fh:
            if line.startswith(("ATOM  ", "HETATM")) and len(line) >= 54:
                coords.append([
                    float(line[30:38]) / 10.0,
                    float(line[38:46]) / 10.0,
                    float(line[46:54]) / 10.0,
                ])
    return np.asarray(coords, dtype=float)


def _resolve_box_nm(explicit: list[float] | None, *pdb_paths: Path | None) -> np.ndarray | None:
    if explicit:
        return np.array(explicit, dtype=float)
    for path in pdb_paths:
        box = _box_from_pdb_cryst1(path)
        if box is not None:
            return box
    return None


def _rigid_align(mobile: np.ndarray, target: np.ndarray) -> np.ndarray:
    """Kabsch-align mobile coordinates onto target coordinates."""
    mob_centroid = mobile.mean(axis=0)
    tgt_centroid = target.mean(axis=0)
    mob0 = mobile - mob_centroid
    tgt0 = target - tgt_centroid
    cov = mob0.T @ tgt0
    u, _, vt = np.linalg.svd(cov)
    rot = vt.T @ u.T
    if np.linalg.det(rot) < 0:
        vt[-1, :] *= -1.0
        rot = vt.T @ u.T
    return mob0 @ rot + tgt_centroid


def _align_coords(
    md_coords: np.ndarray,
    template_coords: np.ndarray,
    mode: str,
    box_nm: np.ndarray | None,
) -> np.ndarray:
    if mode == "none":
        aligned = md_coords.copy()
    elif mode == "translate":
        aligned = md_coords + (template_coords.mean(axis=0) - md_coords.mean(axis=0))
    elif mode == "rigid":
        aligned = _rigid_align(md_coords, template_coords)
    else:
        raise ValueError(f"Unknown alignment mode: {mode}")

    if box_nm is not None:
        for axis, length in enumerate(box_nm):
            if length > 1e-6:
                delta = aligned[:, axis] - template_coords[:, axis]
                aligned[:, axis] -= np.round(delta / length) * length
    return aligned


def _build_reference(
    design: Design,
    coords_nm: np.ndarray,
    source: str,
    notes: str,
    align: str,
    box_nm: np.ndarray | None,
) -> tuple[Design, dict]:
    base_design = design.model_copy(update={"atomistic_reference": None})
    base_model = build_atomistic_model(base_design)
    n_atoms = len(base_model.atoms)
    if len(coords_nm) < n_atoms:
        raise SystemExit(
            f"Coordinate source has {len(coords_nm)} atoms, but design needs {n_atoms}."
        )

    template_coords = np.array([[a.x, a.y, a.z] for a in base_model.atoms], dtype=float)
    raw_coords = coords_nm[:n_atoms]
    md_coords = _align_coords(raw_coords, template_coords, align, box_nm)
    disp = md_coords - template_coords
    rmsd = math.sqrt(float(np.mean(np.sum(disp * disp, axis=1))))
    mean_disp = float(np.mean(np.linalg.norm(disp, axis=1)))
    max_disp = float(np.max(np.linalg.norm(disp, axis=1)))

    ref_atoms: list[AtomisticReferenceAtom] = []
    for atom, pos in zip(base_model.atoms, md_coords, strict=True):
        ref_atoms.append(AtomisticReferenceAtom(
            serial=atom.serial,
            name=atom.name,
            element=atom.element,
            residue=atom.residue,
            chain_id=atom.chain_id,
            seq_num=atom.seq_num,
            x=float(pos[0]),
            y=float(pos[1]),
            z=float(pos[2]),
            strand_id=atom.strand_id,
            helix_id=atom.helix_id,
            bp_index=atom.bp_index,
            direction=atom.direction,
            is_modified=atom.is_modified,
            aux_helix_id=atom.aux_helix_id,
            aux_t=atom.aux_t,
        ))

    ref = AtomisticReference(
        source=source,
        notes=notes,
        topology_hash=atomistic_reference_topology_hash(base_design),
        atoms=ref_atoms,
        bonds=list(base_model.bonds),
    )
    out_design = base_design.model_copy(update={"atomistic_reference": ref})
    report = {
        "source": source,
        "notes": notes,
        "topology_hash": ref.topology_hash,
        "design_atoms": n_atoms,
        "coordinate_atoms": int(len(coords_nm)),
        "used_coordinate_atoms": n_atoms,
        "alignment": align,
        "minimum_image_box_nm": box_nm.tolist() if box_nm is not None else None,
        "template_vs_reference_rmsd_nm": rmsd,
        "template_vs_reference_mean_displacement_nm": mean_disp,
        "template_vs_reference_max_displacement_nm": max_disp,
        "bonds": len(base_model.bonds),
    }
    return out_design, report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--design", type=Path, required=True)
    ap.add_argument("--out-nadoc", type=Path, required=True)
    ap.add_argument("--out-pdb", type=Path)
    ap.add_argument("--report", type=Path)
    ap.add_argument("--topology", type=Path, help="PSF/PDB/GRO topology for --trajectory")
    ap.add_argument("--trajectory", type=Path, help="DCD/XTC/TRR trajectory")
    ap.add_argument("--frame", type=int, default=-1, help="Trajectory frame index; -1 means final")
    ap.add_argument("--coordinate-pdb", type=Path, help="Single-frame PDB coordinate source")
    ap.add_argument("--periodic-periods", type=int, default=0, help="Slice design to this many 21 bp periods first")
    ap.add_argument("--periodic-bp-start", type=int, default=None)
    ap.add_argument("--source", default="")
    ap.add_argument("--notes", default="")
    ap.add_argument(
        "--box-nm",
        nargs=3,
        type=float,
        metavar=("X", "Y", "Z"),
        help="Periodic box lengths for nearest-image placement; defaults to CRYST1 when available.",
    )
    ap.add_argument("--box-pdb", type=Path, help="PDB whose CRYST1 record supplies the periodic box")
    ap.add_argument(
        "--align",
        choices=("translate", "rigid", "none"),
        default="none",
        help="Optional whole-structure alignment before nearest-image placement.",
    )
    args = ap.parse_args()

    if bool(args.coordinate_pdb) == bool(args.trajectory):
        raise SystemExit("Provide exactly one of --coordinate-pdb or --trajectory.")
    if args.trajectory and not args.topology:
        raise SystemExit("--trajectory requires --topology.")

    design = _load_design(args.design)
    if args.periodic_periods:
        design = _periodic_slice(design, args.periodic_periods, args.periodic_bp_start)

    if args.coordinate_pdb:
        coords = _positions_from_pdb(args.coordinate_pdb)
        source = args.source or str(args.coordinate_pdb)
        box_nm = _resolve_box_nm(args.box_nm, args.box_pdb, args.coordinate_pdb)
    else:
        coords = _positions_from_trajectory(args.topology, args.trajectory, args.frame)
        source = args.source or f"{args.trajectory} frame {args.frame}"
        box_nm = _resolve_box_nm(args.box_nm, args.box_pdb, args.topology)

    out_design, report = _build_reference(design, coords, source, args.notes, args.align, box_nm)
    args.out_nadoc.parent.mkdir(parents=True, exist_ok=True)
    args.out_nadoc.write_text(out_design.model_dump_json(indent=2))

    if args.out_pdb:
        ref_model = atomistic_model_from_reference(out_design)
        if ref_model is None:
            raise SystemExit("Internal error: atomistic reference was not created.")
        args.out_pdb.parent.mkdir(parents=True, exist_ok=True)
        args.out_pdb.write_text(export_pdb(out_design, model=ref_model))

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2))

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
